import os
import re
import ssl
import json
import time
import copy
import asyncio
import logging
import requests
import urllib3
import yaml
import random
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as config

import tiktoken
from dotenv import load_dotenv
from openai import OpenAI  # 引入 OpenAI SDK 以兼容 Qwen

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    import PyPDF2 

# 1. Network & Environment Config
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['CURL_CA_BUNDLE'] = ''

# 彻底清理代理，防止连接错误
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(k, None)

# 2. API Config
load_dotenv()
# 直接写入您提供的 API Key
CHATGPT_API_KEY = "sk-d16851ac97ed487ca44cfbe19dd0232f"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# --- Universal Fallback Object ---
class UniversalFallback(dict):
    """防止解析失败导致 crash 的安全字典"""
    def __init__(self):
        super().__init__()
        self['toc_detected'] = 'no'
        self['page_index_given_in_toc'] = 'no'
        self['completed'] = 'no'
        self['answer'] = 'no'
    def extend(self, other): pass 
    def __iter__(self): return iter([])
    def __len__(self): return 0
    def get(self, key, default=None): return super().get(key, default)

def get_qwen_client():
    """初始化并返回 Qwen (OpenAI兼容) 客户端"""
    return OpenAI(
        api_key=CHATGPT_API_KEY,
        base_url=DASHSCOPE_BASE_URL
    )

def request_api_stream_sync(model, messages, timeout=600): 
    """
    使用 OpenAI SDK 调用 Qwen 模型。
    修复 404 错误：强制将请求映射到可用的模型名。
    """
    # 强制修正模型名称，避免 qwen2.5-vl-72b 等不存在的模型导致 404
    # 建议使用 'qwen-plus' (兼顾速度与能力) 或 'qwen-max'
    target_model = "qwen-plus" 
    
    client = get_qwen_client()

    try:
        response = client.chat.completions.create(
            model=target_model,
            messages=messages,
            stream=True,
            temperature=0.1,
            timeout=timeout
        )

        full_content = ""
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content_str = chunk.choices[0].delta.content
                full_content += content_str
                print(f"{content_str}", end="", flush=True)
        
        print("\n") 
        return full_content

    except Exception as e:
        # 如果是 404 错误，给出明确提示
        if "404" in str(e):
            logging.error(f"❌ 模型名错误或无权限: {target_model}。请检查百炼控制台模型开通状态。")
        else:
            logging.error(f"❌ Qwen API 请求失败: {str(e)}")
        return "Error"

def clean_deepseek_content(content):
    if not content or not isinstance(content, str): return ""
    # 移除 DeepSeek 风格的思维链标签
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
    return content.strip()

def ChatGPT_API_with_finish_reason(model, prompt, api_key=None, chat_history=None):
    messages = chat_history + [{"role": "user", "content": prompt}] if chat_history else [{"role": "user", "content": prompt}]
    
    max_retries = 5
    for i in range(max_retries):
        raw = request_api_stream_sync(model, messages)
        if raw != "Error" and raw.strip():
            return clean_deepseek_content(raw), "finished"
        
        wait_time = 3 * (2 ** i)
        print(f'************* API 正在重试 ({i+1}/{max_retries}) - 等待 {wait_time}s *************')
        time.sleep(wait_time)
        
    return "Error", "failed"

def ChatGPT_API(model, prompt, api_key=None, chat_history=None):
    res, _ = ChatGPT_API_with_finish_reason(model, prompt, api_key, chat_history)
    return res

async def ChatGPT_API_async(model, prompt, api_key=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, ChatGPT_API, model, prompt)

def get_json_content(content):
    if not content: return ""
    match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
    if match: return match.group(1)
    return content

def extract_json(content):
    if content == "Error" or not content: 
        return UniversalFallback()
    try:
        content = clean_deepseek_content(content)
        json_str = ""
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            json_str = json_match.group(1)
        else:
            start_idx = content.find('{')
            end_idx = content.rfind('}')
            list_start = content.find('[')
            list_end = content.rfind(']')
            if start_idx != -1 and (list_start == -1 or start_idx < list_start):
                 if end_idx != -1: json_str = content[start_idx : end_idx + 1]
            elif list_start != -1:
                 if list_end != -1: json_str = content[list_start : list_end + 1]
            else:
                 json_str = content
        if not json_str: return UniversalFallback()
        json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
        return json.loads(json_str)
    except Exception as e:
        logging.error(f"JSON 解析错误: {e}")
        return UniversalFallback()

def count_tokens(text, model=None):
    return len(text) // 2

def write_node_id(data, node_id=0):
    if isinstance(data, dict):
        data['node_id'] = str(node_id).zfill(4); node_id += 1
        for k in list(data.keys()):
            if 'nodes' in k: node_id = write_node_id(data[k], node_id)
    elif isinstance(data, list):
        for i in range(len(data)): node_id = write_node_id(data[i], node_id)
    return node_id

def get_nodes(structure):
    if isinstance(structure, dict):
        sn = copy.deepcopy(structure); sn.pop('nodes', None)
        nodes = [sn]
        for k in list(structure.keys()):
            if 'nodes' in k: nodes.extend(get_nodes(structure[k]))
        return nodes
    elif isinstance(structure, list):
        res = []
        for i in structure: res.extend(get_nodes(i))
        return res

def get_pdf_name(pdf_path):
    if hasattr(pdf_path, 'name'): return pdf_path.name
    return os.path.basename(pdf_path)

class JsonLogger:
    def __init__(self, file_path):
        name = get_pdf_name(file_path)
        self.filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        os.makedirs("./logs", exist_ok=True); self.log_data = []
    def log(self, level, message, **kwargs):
        entry = {'message': str(message), 'level': level, 'timestamp': datetime.now().isoformat()}
        self.log_data.append(entry)
        try:
            with open(os.path.join("logs", self.filename), "w", encoding="utf-8-sig") as f:
                json.dump(self.log_data, f, indent=2, ensure_ascii=False)
        except Exception: pass
    def info(self, m): self.log("INFO", m)
    def error(self, m): self.log("ERROR", m)

def get_page_tokens(pdf_path, model=None):
    page_list = []
    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text() or "" 
                    t = t.replace('\x00', '')
                    page_list.append((t, len(t)))
            return page_list
        except: pass
    return page_list

def get_text_of_pages(pdf_path, start, end, tag=True):
    text = ""
    start = max(1, start)
    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                loop_end = min(end, total_pages)
                for i in range(start-1, loop_end):
                    t = pdf.pages[i].extract_text() or ""
                    text += f"<start_index_{i+1}>\n{t}\n<end_index_{i+1}>\n" if tag else t
            return text
        except: pass
    return text

def list_to_tree(data):
    nodes, roots = {}, []
    for item in data:
        c = item.get('structure')
        try:
            s_idx = int(item.get('start_index', 0))
            e_idx = int(item.get('end_index', 0))
        except: s_idx, e_idx = 0, 0
        node = {'title': item.get('title', 'Untitled'), 'start_index': s_idx, 'end_index': e_idx, 'nodes': []}
        key = str(c) if c else str(item.get('title')) + str(s_idx)
        nodes[key] = node
        p_c = '.'.join(str(c).split('.')[:-1]) if c and '.' in str(c) else None
        if p_c and p_c in nodes: nodes[p_c]['nodes'].append(node)
        else: roots.append(node)
    return roots

def post_processing(structure, end_idx):
    if not structure: return []
    for i, item in enumerate(structure):
        try:
            curr_idx = int(item.get('physical_index', 0))
            if i < len(structure) - 1:
                next_idx_val = int(structure[i+1]['physical_index'])
                item['end_index'] = next_idx_val if next_idx_val > curr_idx else curr_idx
            else:
                item['end_index'] = end_idx
            item['start_index'] = curr_idx
        except: continue
    return list_to_tree(structure)

def reorder_dict(data, key_order):
    return {k: data[k] for k in key_order if k in data}

def format_structure(structure, order=None):
    if isinstance(structure, dict):
        if 'nodes' in structure: structure['nodes'] = format_structure(structure['nodes'], order)
        return reorder_dict(structure, order) if order else structure
    elif isinstance(structure, list):
        return [format_structure(i, order) for i in structure]
    return structure

class ConfigLoader:
    def __init__(self, default_path=None):
        if default_path is None: default_path = Path(__file__).parent / "config.yaml"
        if not os.path.exists(default_path): self._default_dict = {}
        else:
            with open(default_path, "r", encoding="utf-8") as f: self._default_dict = yaml.safe_load(f) or {}
    def load(self, user_opt=None) -> config:
        u_dict = vars(user_opt) if isinstance(user_opt, config) else (user_opt or {})
        return config(**{**self._default_dict, **u_dict})

def convert_physical_index_to_int(data):
    if isinstance(data, list):
        for i in range(len(data)):
            if 'physical_index' in data[i]:
                try:
                    val = str(data[i]['physical_index'])
                    m = re.search(r'(\d+)', val)
                    data[i]['physical_index'] = int(m.group(1)) if m else None
                except: data[i]['physical_index'] = None
    return data

def add_preface_if_needed(toc_list):
    if not toc_list or not isinstance(toc_list, list): return toc_list
    try:
        first_item = toc_list[0]
        start_index = first_item.get('start_index') or first_item.get('physical_index')
        start_val = int(re.findall(r'\d+', str(start_index))[0]) if start_index else 1
        if start_val > 1:
            toc_list.insert(0, {'title': 'Preface / Abstract', 'structure': '0', 'start_index': 1, 'end_index': start_val, 'physical_index': 1, 'level': 1})
    except: pass
    return toc_list

def convert_page_to_int(toc_list):
    if not isinstance(toc_list, list): return toc_list
    for item in toc_list:
        if isinstance(item, dict) and 'page' in item:
            try:
                nums = re.findall(r'\d+', str(item['page']))
                item['page'] = int(nums[0]) if nums else 1
            except: item['page'] = 1
        if isinstance(item, dict) and 'nodes' in item:
            convert_page_to_int(item['nodes'])
    return toc_list

def add_node_text(structure, page_list):
    if isinstance(structure, list):
        for node in structure: add_node_text(node, page_list)
    elif isinstance(structure, dict):
        try:
            start = int(structure.get('start_index') or 1)
            end = int(structure.get('end_index') or start)
            text_content = ""
            for i in range(max(0, start - 1), min(len(page_list), end)):
                text_content += page_list[i][0] + "\n"
            structure['text'] = text_content
            if 'nodes' in structure: add_node_text(structure['nodes'], page_list)
        except: pass

async def generate_summaries_for_structure(structure, model=None):
    nodes = get_nodes(structure)
    tasks = []
    async def summarize_node(node):
        text_content = node.get('text', '')
        if not text_content: 
            node['summary'] = ""
            return
        prompt = f"请简要总结以下文本（一句话）：\n\n{text_content[:3000]}"
        summary = await ChatGPT_API_async(model, prompt)
        node['summary'] = summary.strip()
    for node in nodes: tasks.append(summarize_node(node))
    if tasks: await asyncio.gather(*tasks)
    return structure

def clean_page_numbers(data):
    if isinstance(data, dict):
        for k in ['page_number', 'page', 'physical_index', 'start_index', 'end_index']:
            if k in data:
                try:
                    v = data[k]
                    digits = ''.join(filter(str.isdigit, str(v)))
                    data[k] = int(digits) if digits else 0
                except: pass
        for v in data.values(): clean_page_numbers(v)
    elif isinstance(data, list):
        for item in data: clean_page_numbers(item)
    return data

def remove_structure_text(structure):
    if isinstance(structure, dict):
        structure.pop('text', None)
        if 'nodes' in structure: remove_structure_text(structure['nodes'])
    elif isinstance(structure, list):
        for item in structure: remove_structure_text(item)
