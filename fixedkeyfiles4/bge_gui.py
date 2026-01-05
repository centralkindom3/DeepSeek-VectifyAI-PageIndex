import sys
import os
import json
import sqlite3
import hashlib
import requests
import urllib3
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QMessageBox, QProgressBar)
from PyQt5.QtCore import QThread, pyqtSignal, QSettings, Qt

# 禁用 HTTPS 警告（适配Win7旧环境）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= 配置常量 =================
# API 配置 (根据提供的代码写死)
API_URL = "https://www.bge.com/v1/embeddings" # 注意：BGE是embedding模型，通常端点是 /embeddings 而不是 chat/completions
API_KEY = "your api key"
MODEL_NAME = "bge-m3"
BATCH_SIZE = 8  # 批处理大小，避免一次请求过大

# ================= 样式表 (Dark Mode) =================
STYLESHEET = """
QMainWindow { background-color: #2b2b2b; color: #ffffff; }
QLabel { color: #cccccc; font-size: 14px; font-weight: bold; }
QLineEdit { background-color: #3b3b3b; color: #ffffff; border: 1px solid #555555; padding: 5px; border-radius: 3px; }
QPushButton { background-color: #007acc; color: white; border: none; padding: 8px 15px; border-radius: 4px; font-weight: bold; }
QPushButton:hover { background-color: #005f9e; }
QPushButton:pressed { background-color: #004a80; }
QPushButton:disabled { background-color: #444444; color: #888888; }
QTextEdit { background-color: #1e1e1e; color: #00ff00; border: 1px solid #555555; font-family: Consolas, monospace; font-size: 12px; }
QProgressBar { border: 1px solid #555555; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background-color: #007acc; width: 20px; }
"""

# ================= 工作线程：执行耗时任务 =================
class VectorWorker(QThread):
    log_signal = pyqtSignal(str)       # 发送日志信号
    finish_signal = pyqtSignal(bool, str) # 完成信号
    progress_signal = pyqtSignal(int)  # 进度信号

    def __init__(self, input_path):
        super().__init__()
        self.input_path = input_path
        self.output_json_path = input_path.replace(".json", "_embedded.json")
        self.output_db_path = input_path.replace(".json", "_rag.db")

    def generate_stable_id(self, metadata):
        """生成稳定的 ID (doc_title + section_id 的 MD5)"""
        raw_str = f"{metadata.get('doc_title', '')}_{metadata.get('section_id', '')}"
        return hashlib.md5(raw_str.encode('utf-8')).hexdigest()

    def init_db(self):
        """初始化 SQLite 表结构 (符合 Prompt 要求)"""
        self.log_signal.emit(f"正在初始化数据库: {self.output_db_path}")
        conn = sqlite3.connect(self.output_db_path)
        cursor = conn.cursor()
        
        # 1. Vectors 表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vectors (
                id TEXT PRIMARY KEY,
                embedding TEXT,
                dim INTEGER,
                doc_title TEXT,
                section_id TEXT
            )
        ''')
        
        # 2. Documents 表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                embedding_text TEXT,
                section_hint TEXT,
                original_snippet TEXT,
                section_path TEXT,
                depth INTEGER,
                original_length INTEGER
            )
        ''')
        conn.commit()
        return conn

    def call_bge_api(self, text_batch):
        """调用远程 BGE-M3 接口"""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {API_KEY}'
        }
        payload = {
            "model": MODEL_NAME,
            "input": text_batch
        }
        
        try:
            # 使用 verify=False 跳过 SSL 验证 (Win7/内网常见问题)
            response = requests.post(API_URL, headers=headers, json=payload, verify=False, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                # 兼容 OpenAI 格式返回
                if "data" in result:
                    return [item["embedding"] for item in result["data"]]
                else:
                    self.log_signal.emit(f"[API Error] 响应格式异常: {result}")
                    return None
            else:
                self.log_signal.emit(f"[API Error] Status: {response.status_code}, Msg: {response.text}")
                return None
        except Exception as e:
            self.log_signal.emit(f"[Network Error] {str(e)}")
            return None

    def run(self):
        try:
            # 1. 读取 JSON
            self.log_signal.emit(f"正在读取文件: {self.input_path}")
            with open(self.input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                self.finish_signal.emit(False, "输入 JSON 格式错误，根节点必须是列表。")
                return

            total_items = len(data)
            self.log_signal.emit(f"共加载 {total_items} 条数据，准备开始向量化...")
            
            # 2. 初始化数据库
            conn = self.init_db()
            cursor = conn.cursor()

            processed_results = [] # 用于保存最终 JSON
            
            # 3. 批处理循环
            for i in range(0, total_items, BATCH_SIZE):
                batch_items = data[i : i + BATCH_SIZE]
                batch_texts = [item.get('embedding_text', '') for item in batch_items]
                
                # 过滤空文本
                valid_indices = [idx for idx, txt in enumerate(batch_texts) if txt.strip()]
                valid_texts = [batch_texts[idx] for idx in valid_indices]
                
                if not valid_texts:
                    continue

                self.log_signal.emit(f"正在处理批次: {i+1} - {min(i+BATCH_SIZE, total_items)} / {total_items}")
                
                # 发送请求
                embeddings = self.call_bge_api(valid_texts)
                
                if embeddings and len(embeddings) == len(valid_texts):
                    # 4. 数据组装与存储
                    for idx_in_batch, vector in zip(valid_indices, embeddings):
                        item = batch_items[idx_in_batch]
                        metadata = item.get('metadata', {})
                        
                        stable_id = self.generate_stable_id(metadata)
                        
                        # 构建完整的存储对象
                        record = {
                            "id": stable_id,
                            "embedding": vector,
                            "embedding_text": item.get('embedding_text', ''),
                            "section_hint": item.get('section_hint', ''),
                            "metadata": metadata,
                            "original_snippet": item.get('original_snippet', '')
                        }
                        
                        processed_results.append(record)
                        
                        # --- 写入 SQLite (事务内) ---
                        # 表 1: Vectors
                        cursor.execute('''
                            INSERT OR REPLACE INTO vectors (id, embedding, dim, doc_title, section_id)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (
                            stable_id,
                            json.dumps(vector), # SQLite存数组通常转为JSON字符串或BLOB
                            len(vector),
                            metadata.get('doc_title', ''),
                            metadata.get('section_id', '')
                        ))
                        
                        # 表 2: Documents
                        cursor.execute('''
                            INSERT OR REPLACE INTO documents (id, embedding_text, section_hint, original_snippet, section_path, depth, original_length)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            stable_id,
                            item.get('embedding_text', ''),
                            item.get('section_hint', ''),
                            item.get('original_snippet', ''),
                            json.dumps(metadata.get('section_path', [])), # 路径转JSON存
                            metadata.get('depth', 0),
                            metadata.get('original_length', 0)
                        ))
                    
                    conn.commit() # 提交当前批次
                else:
                    self.log_signal.emit("❌ 当前批次向量化失败，已跳过。")

                self.progress_signal.emit(int((min(i+BATCH_SIZE, total_items) / total_items) * 100))
                time.sleep(0.5) # 稍微暂停防止速率限制

            conn.close()
            
            # 5. 保存 JSON 结果文件
            self.log_signal.emit(f"正在保存 JSON 结果: {self.output_json_path}")
            with open(self.output_json_path, 'w', encoding='utf-8') as f:
                json.dump(processed_results, f, ensure_ascii=False, indent=2)

            self.finish_signal.emit(True, f"处理完成！\n数据库: {self.output_db_path}\nJSON: {self.output_json_path}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finish_signal.emit(False, str(e))

# ================= 主窗体 UI =================
class VectorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BGE-M3 Vectorizer Client (Win7 Compatible)")
        self.resize(800, 600)
        self.setStyleSheet(STYLESHEET)
        
        # 配置文件路径
        self.settings = QSettings("MyCorp", "BGEClient")
        
        self.initUI()
        self.worker = None

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 1. 标题
        title = QLabel("JSON to BGE-M3 向量化工具")
        title.setStyleSheet("font-size: 18px; color: #007acc;")
        main_layout.addWidget(title)

        # 2. 文件选择区域
        file_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("请选择 Optimized Vector JSON 文件...")
        self.path_input.setReadOnly(True)
        
        btn_browse = QPushButton("📂 选择文件")
        btn_browse.clicked.connect(self.select_file)
        
        file_layout.addWidget(self.path_input)
        file_layout.addWidget(btn_browse)
        main_layout.addLayout(file_layout)

        # 3. 操作按钮
        self.btn_run = QPushButton("🚀 开始发送 BGE 向量化")
        self.btn_run.setFixedHeight(45)
        self.btn_run.setStyleSheet("font-size: 14px;")
        self.btn_run.clicked.connect(self.run_vectorization)
        main_layout.addWidget(self.btn_run)
        
        # 4. 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # 5. 控制台日志
        main_layout.addWidget(QLabel("系统控制台:"))
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        main_layout.addWidget(self.console)
        
        # 底部状态
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("font-size: 12px; color: #888888;")
        main_layout.addWidget(self.status_label)

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.console.append(f"[{timestamp}] {message}")
        # 滚动到底部
        cursor = self.console.textCursor()
        cursor.movePosition(cursor.End)
        self.console.setTextCursor(cursor)

    def select_file(self):
        # 获取上次保存的目录，默认为桌面
        last_dir = self.settings.value("last_dir", os.path.expanduser("~/Desktop"))
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "选择 JSON 文件", 
            last_dir, 
            "JSON Files (*.json)"
        )
        
        if file_path:
            self.path_input.setText(file_path)
            # 保存当前选择的目录
            current_dir = os.path.dirname(file_path)
            self.settings.setValue("last_dir", current_dir)
            self.log(f"已加载文件: {file_path}")

    def run_vectorization(self):
        json_path = self.path_input.text()
        if not json_path or not os.path.exists(json_path):
            QMessageBox.warning(self, "错误", "请先选择有效的 JSON 文件！")
            return
        
        self.btn_run.setEnabled(False)
        self.progress_bar.setValue(0)
        self.console.clear()
        self.log("正在启动向量化任务线程...")
        
        # 启动线程
        self.worker = VectorWorker(json_path)
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.finish_signal.connect(self.on_task_finished)
        self.worker.start()

    def on_task_finished(self, success, message):
        self.btn_run.setEnabled(True)
        if success:
            QMessageBox.information(self, "完成", message)
            self.log("✅ 任务全部完成")
            self.status_label.setText("任务完成")
        else:
            QMessageBox.critical(self, "失败", f"任务出错: {message}")
            self.log("❌ 任务失败")
            self.status_label.setText("任务失败")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VectorApp()
    window.show()

    sys.exit(app.exec_())
