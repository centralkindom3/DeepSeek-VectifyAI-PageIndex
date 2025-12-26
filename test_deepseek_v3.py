import requests
import json
import urllib3
import sys

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_KEY = ""
URL = ""
MODEL_NAME = "DeepSeek-V3"

def test_v3_diagnostic():
    print(f"--- 诊断模式: {MODEL_NAME} ---")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    data = {
        "model": MODEL_NAME, 
        "messages": [{"role": "user", "content": "你好，请回复'测试成功'"}], 
        "stream": True,
        "temperature": 0.1 # 调低温度增加稳定性
    }
    
    try:
        response = requests.post(URL, headers=headers, json=data, timeout=30, verify=False, stream=True)
        print(f"HTTP状态码: {response.status_code}")
        
        if response.status_code != 200:
            print(f"错误内容: {response.text}")
            return

        print("--- 原始数据流开始 ---")
        content_received = False
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8').strip()
                print(f"RAW: {line_str}") # 打印每一行原始数据
                
                if line_str.startswith("data:"):
                    raw_json = line_str[5:].strip()
                    if raw_json == "[DONE]": break
                    try:
                        j = json.loads(raw_json)
                        txt = j['choices'][0].get('delta', {}).get('content', '')
                        if txt:
                            content_received = True
                            print(f">>> 解析到文字: {txt}")
                    except:
                        pass
        
        if not content_received:
            print("--- 警告：连接成功但未解析到任何文字内容 ---")
            
    except Exception as e:
        print(f"请求异常: {e}")

if __name__ == "__main__":

    test_v3_diagnostic()
