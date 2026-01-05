import sys
import os
import json
import sqlite3
import requests
import urllib3
import time
import numpy as np
import re
import hashlib
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, 
                             QMessageBox, QSplitter, QFrame)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QSettings

# ================= 配置与环境 =================
# 禁用 HTTPS 警告 (Win7/内网适配)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.environ['CURL_CA_BUNDLE'] = ''

# API 配置
# Embedding API
EMBEDDING_API_URL = "https://www.bge.com/v1/embeddings" 
API_KEY = "your api key"
EMBEDDING_MODEL_NAME = "bge-m3"

# Rerank API
RERANK_API_URL = "https://www.bge.com/v1/rerank" 
RERANK_MODEL_NAME = "bge-reranker-v2-m3"

# ================= 样式表 (Dark Mode) =================
STYLESHEET = """
QMainWindow { background-color: #2b2b2b; color: #e0e0e0; font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; }
QLabel { color: #aaaaaa; font-weight: bold; font-size: 13px; }
QLineEdit { background-color: #3c3c3c; color: #ffffff; border: 1px solid #555555; padding: 6px; border-radius: 4px; }
QTextEdit { background-color: #1e1e1e; color: #e0e0e0; border: 1px solid #444444; font-family: Consolas, monospace; font-size: 12px; }
QPushButton { background-color: #007acc; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold; font-size: 14px; }
QPushButton:hover { background-color: #005f9e; }
QPushButton:pressed { background-color: #004a80; }
QPushButton:disabled { background-color: #444444; color: #888888; }
QFrame#Divider { border: 1px solid #444444; }
"""

# ================= 核心工具：相似度计算 =================
def cosine_similarity(vec1, vec2):
    try:
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return np.dot(vec1, vec2) / (norm1 * norm2)
    except Exception:
        return 0.0

# ================= 核心工具：内容哈希去重 =================
def get_text_hash(text):
    """生成文本的 SHA256 哈希，用于严格去重"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

# ================= 新增模块：PageIndex Loader =================
class PageIndexLoader:
    def __init__(self):
        self.index = {}          
        self.ordered_ids = []    
        self.is_loaded = False

    def load_json(self, json_path):
        if not json_path or not os.path.exists(json_path):
            return False, "文件不存在"
        
        try:
            with open(json_path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            
            self.index = {}
            self.ordered_ids = []
            
            root_structure = data.get("structure", []) if isinstance(data, dict) else data
            
            for item in root_structure:
                self._traverse(item, parent_path=[])
            
            self.is_loaded = True
            return True, f"成功加载 PageIndex，包含 {len(self.index)} 个节点"
        except Exception as e:
            return False, f"加载异常: {str(e)}"

    def _traverse(self, node, parent_path):
        current_title = node.get("title", "")
        node_id = str(node.get("node_id", "")) 
        current_path = parent_path + [current_title]
        
        if node_id:
            self.index[node_id] = {
                "title": current_title,
                "text": node.get("text", ""),
                "summary": node.get("summary", ""),
                "path": current_path,
                "raw_node": node 
            }
            self.ordered_ids.append(node_id)
        
        if "nodes" in node and isinstance(node["nodes"], list):
            for child in node["nodes"]:
                self._traverse(child, current_path)

    def get_node(self, node_id):
        return self.index.get(str(node_id))

    def get_siblings(self, node_id):
        if str(node_id) not in self.ordered_ids:
            return []
        
        idx = self.ordered_ids.index(str(node_id))
        siblings = []
        if idx > 0:
            siblings.append(self.index[self.ordered_ids[idx - 1]])
        if idx < len(self.ordered_ids) - 1:
            siblings.append(self.index[self.ordered_ids[idx + 1]])
        return siblings

# ================= 工作线程：工业级鲁棒召回任务 =================
class RecallWorker(QThread):
    log_signal = pyqtSignal(str)          
    result_signal = pyqtSignal(list)      
    finish_signal = pyqtSignal(bool)      

    def __init__(self, query_text, db_path, json_path):
        super().__init__()
        self.query_text = query_text
        self.db_path = db_path
        self.json_path = json_path
        self.page_index = PageIndexLoader()

    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.log_signal.emit(f"[{timestamp}] {msg}")

    # --- Step 1: Embedding ---
    def get_remote_embedding(self, text):
        self.log(f"正在发送 Query 到 BGE-M3: {text[:20]}...")
        headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}' }
        payload = { "model": EMBEDDING_MODEL_NAME, "input": [text] }
        
        try:
            response = requests.post(EMBEDDING_API_URL, headers=headers, json=payload, verify=False, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and len(data['data']) > 0:
                    return data['data'][0]['embedding']
        except Exception as e:
            self.log(f"❌ Embedding 网络异常: {str(e)}")
        return None

    # --- Step 2: Rerank API ---
    def rerank_with_bge(self, query, candidates_text_list):
        self.log(f"📡 Reranker ({RERANK_MODEL_NAME}) 正在处理 {len(candidates_text_list)} 条去重后的数据...")
        headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}' }
        
        # 工业级优化：这里不包含 System Prompt (因为模型是 Encoder)，
        # 而是将“规则”内化在 input text 的构造和后续的 python 逻辑中。
        payload = {
            "model": RERANK_MODEL_NAME,
            "query": query,
            "documents": candidates_text_list # List of strings
        }

        try:
            start_time = time.time()
            response = requests.post(RERANK_API_URL, headers=headers, json=payload, verify=False, timeout=30)
            cost_time = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                scores = [0.0] * len(candidates_text_list)
                
                # 兼容不同的 API 返回格式 (List[float] 或 List[Object])
                if "results" in data:
                    for res in data["results"]:
                        idx = res.get("index")
                        score = res.get("relevance_score", 0.0)
                        if idx is not None and 0 <= idx < len(scores):
                            scores[idx] = score
                elif isinstance(data, list):
                     # 部分 API 直接返回 float 列表
                     scores = data
                else:
                    self.log("⚠️ Reranker 返回格式未知，降级处理。")
                    return None

                self.log(f"✅ Reranker 完成，耗时: {cost_time:.2f}s")
                return scores
            else:
                self.log(f"⚠️ Reranker 请求失败: {response.status_code}")
                return None
        except Exception as e:
            self.log(f"⚠️ Reranker 调用异常: {str(e)}")
            return None

    # --- Step 3: 工业级规则裁决 (Rule-Based Adjudication) ---
    def apply_industrial_rules(self, query, path_str, original_score):
        """
        根据附件中的 System Prompt 逻辑，在 Python 层面实施“硬约束”。
        解决 Reranker 对 'model train' 和 'background' 区分不清的问题。
        """
        q_lower = query.lower()
        p_lower = path_str.lower()
        final_adj_score = original_score

        # 规则 1: 意图解析与负向抑制
        # 如果 Query 明确是在问技术细节 (train, optimizer, loss, architecture)
        technical_terms = ["train", "optimi", "loss", "layer", "struct", "arch"]
        if any(t in q_lower for t in technical_terms):
            
            # 严重惩罚：Introduction, Background, Motivation, Why, Preface
            # 这些章节通常包含大量关键词复述，但没有干货，是 Reranker 的主要误判源
            negative_sections = ["introduction", "background", "preface", "motivation", "overview", "why", "related work"]
            
            for neg in negative_sections:
                if neg in p_lower:
                    # "必须显著降权" -> 暴力扣分
                    final_adj_score -= 3.0 
                    # self.log(f"  -> 触发规则惩罚: 路径包含 '{neg}'")
                    break
            
            # 正向激励：Query 里的词出现在 Path 里
            # "优先匹配 Section 标题与 Query 的语义一致性"
            if "train" in q_lower and "train" in p_lower:
                final_adj_score += 1.0
        
        return final_adj_score

    def run(self):
        try:
            # 0. 加载 PageIndex
            has_pageindex = False
            if self.json_path:
                self.log(f"加载 PageIndex: {os.path.basename(self.json_path)}...")
                success, msg = self.page_index.load_json(self.json_path)
                if success:
                    has_pageindex = True
                else:
                    self.log(f"⚠️ PageIndex 加载失败: {msg}")

            # 1. Query Vector
            query_vec_list = self.get_remote_embedding(self.query_text)
            if not query_vec_list:
                self.finish_signal.emit(False)
                return
            query_vec_np = np.array(query_vec_list, dtype=np.float32)

            # 2. SQLite Vector Search
            if not os.path.exists(self.db_path):
                self.log("❌ 数据库不存在")
                self.finish_signal.emit(False)
                return

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, embedding, section_id FROM vectors")
            rows = cursor.fetchall()
            
            # 向量初筛 Top-30 (扩大范围给去重留空间)
            raw_candidates = []
            for row in rows:
                doc_id, emb_json, sec_id_db = row
                try:
                    doc_vec = np.array(json.loads(emb_json), dtype=np.float32)
                    score = cosine_similarity(query_vec_np, doc_vec)
                    raw_candidates.append({"id": doc_id, "vec_score": score, "section_id": str(sec_id_db)})
                except: continue

            raw_candidates.sort(key=lambda x: x["vec_score"], reverse=True)
            top_candidates_raw = raw_candidates[:30] 

            # 3. 数据准备 & 严格去重 (Deduplication)
            # "多个 Top 结果 Original Text 完全相同" -> 必须去重
            rerank_input_texts = [] # 送给模型的
            processed_candidates = [] # 用于后续处理的
            seen_content_hashes = set()

            for item in top_candidates_raw:
                sec_id = item["section_id"]
                node_info = self.page_index.get_node(sec_id) if has_pageindex else None
                
                # 获取原始内容
                raw_text = ""
                path_str = ""
                summary_text = ""

                if node_info:
                    raw_text = node_info['text']
                    path_str = " > ".join(node_info['path'])
                    summary_text = node_info.get('summary', '')
                else:
                    cursor.execute("SELECT original_snippet, section_path FROM documents WHERE id=?", (item['id'],))
                    db_row = cursor.fetchone()
                    if db_row:
                        raw_text = db_row[0]
                        path_str = str(db_row[1])

                # >>> 关键优化：去重 <<<
                content_hash = get_text_hash(raw_text)
                if content_hash in seen_content_hashes:
                    continue # 跳过重复内容
                seen_content_hashes.add(content_hash)

                # >>> 关键优化：构造 Reranker 输入 (Structure Injection) <<<
                # 将 Path 拼接到 Text 前面，让 Reranker 感知结构
                # 格式: "Section: Training > Optimizer \n Content: ... text ..."
                context_aware_input = f"Section Path: {path_str}\nContent: {raw_text}"
                rerank_input_texts.append(context_aware_input)

                # 构造展示内容
                display_content = f"[Summary]\n{summary_text}\n\n[Text]\n{raw_text}" if summary_text else raw_text
                
                processed_candidates.append({
                    "id": item["id"],
                    "vec_score": item["vec_score"],
                    "path": path_str,
                    "content": display_content,
                    "final_score": 0.0 # 待填
                })
                
                if len(processed_candidates) >= 15: # 限制送入 Reranker 的数量，提高速度
                    break

            conn.close()

            # 4. 执行 Rerank
            rerank_scores = self.rerank_with_bge(self.query_text, rerank_input_texts)
            
            # 5. 分数融合与规则修正
            if rerank_scores and len(rerank_scores) == len(processed_candidates):
                for idx, candidate in enumerate(processed_candidates):
                    raw_rerank_score = rerank_scores[idx]
                    
                    # [Step 3] 应用工业级规则修正
                    # 这里把“系统提示词”里的逻辑变成了代码逻辑
                    adjusted_rerank_score = self.apply_industrial_rules(
                        self.query_text, 
                        candidate['path'], 
                        raw_rerank_score
                    )
                    
                    # 混合公式: 0.2 * Vec + 0.8 * Rerank (增加 Rerank 权重，因为我们已经做了规则修正)
                    candidate['final_score'] = 0.2 * candidate['vec_score'] + 0.8 * adjusted_rerank_score
                    candidate['debug_score'] = f"R:{adjusted_rerank_score:.2f} (Orig:{raw_rerank_score:.2f})"
                
                processed_candidates.sort(key=lambda x: x["final_score"], reverse=True)
                self.log("✅ Rerank 排序完成 (含规则修正)")
            else:
                self.log("⚠️ 降级：仅使用向量分排序")
                for candidate in processed_candidates:
                    candidate['final_score'] = candidate['vec_score']
                    candidate['debug_score'] = "VecOnly"

            # 6. Top-10
            final_top_10 = processed_candidates[:10]
            for idx, res in enumerate(final_top_10):
                res['rank'] = idx + 1

            self.result_signal.emit(final_top_10)
            self.finish_signal.emit(True)

        except Exception as e:
            self.log(f"❌ 严重错误: {str(e)}")
            import traceback
            self.log(traceback.format_exc())
            self.finish_signal.emit(False)

# ================= 主界面 (无修改，保持原样) =================
class RAGRecallApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RAG 工业级召回测试 (Structure-aware + Rules)")
        self.resize(1200, 850)
        self.setStyleSheet(STYLESHEET)
        
        self.settings = QSettings("MyCorp", "RAGRecall_V3")
        self.init_ui()
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(10)
        
        # Left
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # DB
        db_layout = QHBoxLayout()
        self.db_path_edit = QLineEdit()
        self.db_path_edit.setText(self.settings.value("last_db_path", ""))
        btn_db = QPushButton("📂 向量库")
        btn_db.clicked.connect(self.browse_db)
        db_layout.addWidget(QLabel("Vector DB:"))
        db_layout.addWidget(self.db_path_edit)
        db_layout.addWidget(btn_db)
        left_layout.addLayout(db_layout)
        
        # JSON
        json_layout = QHBoxLayout()
        self.json_path_edit = QLineEdit()
        self.json_path_edit.setText(self.settings.value("last_json_path", ""))
        btn_json = QPushButton("📄 PageIndex")
        btn_json.clicked.connect(self.browse_json)
        json_layout.addWidget(QLabel("Structure JSON:"))
        json_layout.addWidget(self.json_path_edit)
        json_layout.addWidget(btn_json)
        left_layout.addLayout(json_layout)
        
        # Query
        left_layout.addWidget(QLabel("用户查询 (Query):"))
        self.query_input = QTextEdit()
        self.query_input.setPlaceholderText("请输入问题，例如：Transformer 架构的训练细节？")
        self.query_input.setMaximumHeight(80)
        left_layout.addWidget(self.query_input)
        
        # Button
        self.btn_search = QPushButton("🚀 执行优化版召回 (Rule-Enhanced)")
        self.btn_search.setFixedHeight(50)
        self.btn_search.setStyleSheet("background-color: #2da44e; font-size: 15px;")
        self.btn_search.clicked.connect(self.start_recall)
        left_layout.addWidget(self.btn_search)
        
        # Result
        left_layout.addWidget(QLabel("RAG Context Pack (Top-10):"))
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        self.result_display.setStyleSheet("font-family: Consolas; font-size: 13px; color: #aaddff;")
        left_layout.addWidget(self.result_display)
        
        # Right Console
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.addWidget(QLabel("📟 System Console"))
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setStyleSheet("background-color: #111; color: #0f0; font-family: Consolas;")
        right_layout.addWidget(self.console_output)
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([800, 400])
        main_layout.addWidget(splitter)

    def browse_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择数据库", "", "SQLite DB (*.db);;All Files (*.*)")
        if path:
            self.db_path_edit.setText(path)
            self.settings.setValue("last_db_path", path)

    def browse_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 JSON", "", "JSON Files (*.json);;All Files (*.*)")
        if path:
            self.json_path_edit.setText(path)
            self.settings.setValue("last_json_path", path)

    def log(self, msg):
        self.console_output.append(msg)
        cursor = self.console_output.textCursor()
        cursor.movePosition(cursor.End)
        self.console_output.setTextCursor(cursor)

    def start_recall(self):
        db_path = self.db_path_edit.text().strip()
        json_path = self.json_path_edit.text().strip()
        query = self.query_input.toPlainText().strip()
        
        if not db_path or not os.path.exists(db_path):
            QMessageBox.warning(self, "Error", "无效的数据库路径")
            return
        if not query:
            return
        
        self.btn_search.setEnabled(False)
        self.result_display.clear()
        self.console_output.clear()
        self.log("🚀 初始化召回任务...")
        
        self.worker = RecallWorker(query, db_path, json_path)
        self.worker.log_signal.connect(self.log)
        self.worker.result_signal.connect(self.display_results)
        self.worker.finish_signal.connect(self.on_finished)
        self.worker.start()

    def display_results(self, results):
        html = ""
        for item in results:
            score_text = f"{item['final_score']:.4f}"
            debug_info = item.get('debug_score', '')
            color = "#00ff00" if item['final_score'] > 0 else "#ffaa00"
            
            html += f"""
            <div style='border-bottom: 1px solid #555; padding: 12px; margin-bottom: 8px;'>
                <span style='color: #888; font-weight:bold;'>Rank #{item['rank']}</span> | 
                <span style='color: {color}; font-weight: bold;'>Final: {score_text}</span> 
                <span style='color: #aaa; font-size:11px;'>[{debug_info}]</span><br>
                
                <div style='margin-top:5px; color: #ffcc00;'><b>[Section Path]</b> {item['path']}</div>
                
                <div style='margin-top:5px; background-color: #222; padding: 8px; border-left: 3px solid #2da44e; white-space: pre-wrap;'>
{item['content'][:300]}... (Display truncated)
                </div>
            </div>
            """
        self.result_display.setHtml(html)

    def on_finished(self, success):
        self.btn_search.setEnabled(True)
        if success:
            self.log("✅ 流程结束")
        else:
            self.log("❌ 流程失败")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = RAGRecallApp()
    window.show()
    sys.exit(app.exec_())