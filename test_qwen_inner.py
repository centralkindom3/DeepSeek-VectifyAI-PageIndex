import requests
import json
import urllib3
import os

# 1. 禁用 SSL 警告（针对 Win7 环境访问 HTTPS 特别重要）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 2. 配置内网信息
API_KEY = "sk-fXM4W0CdcKnNp3NVDfF85f2b90284b11AfDdF9F5627f627b"
# 使用内网建议的完整路径
URL = "https://aiplus.airchina.com.cn:18080/v1/chat/completions"
MODEL_NAME = "Qwen2.5-32B"

def test_qwen_inner_network():
    print(f"--- 开始测试 Qwen2.5-32B 内网接口 ---")
    print(f"请求地址: {URL}")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    # 3. 构造请求数据，严格遵守内网要求的 stream: true
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "你好，请回答‘内网连接成功’并写一段话。"}
        ],
        "stream": True,  # 必须开启
        "temperature": 0.6
    }

    try:
        # 发起流式请求
        print("正在发送请求并等待响应流...")
        response = requests.post(
            URL, 
            headers=headers, 
            json=payload, 
            timeout=60, 
            verify=False, 
            stream=True
        )

        if response.status_code != 200:
            print(f"❌ 请求失败，状态码: {response.status_code}")
            print(f"错误详情: {response.text}")
            return

        print("✅ 连接成功，正在接收流式内容:\n" + "-"*40)

        full_content = ""
        # 4. 解析流式返回的 SSE 数据
        for line in response.iter_lines():
            if not line:
                continue
            
            # 解码每一行
            line_str = line.decode('utf-8')
            
            # 过滤掉 SSE 的 data: 前缀
            if line_str.startswith("data: "):
                data_json_str = line_str[6:]
                
                # 检查结束标志
                if data_json_str.strip() == "[DONE]":
                    break
                
                try:
                    chunk = json.loads(data_json_str)
                    # 提取消息碎片
                    delta = chunk['choices'][0].get('delta', {})
                    if 'content' in delta:
                        content_piece = delta['content']
                        full_content += content_piece
                        # 实时打印，模拟打字机效果
                        print(content_piece, end='', flush=True)
                except Exception:
                    continue

        print("\n" + "-"*40)
        print(f"测试完成，总字符数: {len(full_content)}")

    except Exception as e:
        print(f"❌ 发生网络或代码异常: {e}")

if __name__ == "__main__":
    test_qwen_inner_network()