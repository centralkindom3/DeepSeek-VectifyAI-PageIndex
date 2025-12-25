import sys
import json
import os
import subprocess
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, 
                             QFileDialog, QMessageBox, QFrame)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QPalette, QFont

# 引入我们刚才创建的视觉窗口
from ai_visual_window import AIVisualWindow

CONFIG_FILE = "gui_configs.json"

# === Cyberpunk Style Sheet ===
STYLESHEET = """
QMainWindow {
    background-color: #0d1117;
}
QLabel {
    color: #00ffcc;
    font-family: 'Segoe UI', sans-serif;
    font-weight: bold;
}
QLineEdit {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #c9d1d9;
    padding: 5px;
    font-family: 'Consolas';
}
QLineEdit:focus {
    border: 1px solid #00ffcc;
    background-color: #0d1117;
}
QPushButton {
    background-color: #238636;
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: bold;
    font-size: 14px;
}
QPushButton:hover {
    background-color: #2ea043;
}
QPushButton:pressed {
    background-color: #1a6329;
}
/* 特殊按钮样式：视觉开关 */
QPushButton#VisualBtn {
    background-color: #1f6feb;
    border: 1px solid #1f6feb;
}
QPushButton#VisualBtn:hover {
    background-color: #388bfd;
}
QTextEdit {
    background-color: #0d1117;
    border: 1px solid #30363d;
    color: #00ff99; /* Matrix Green */
    font-family: 'Consolas', monospace;
    font-size: 12px;
}
QComboBox {
    background-color: #161b22;
    color: #c9d1d9;
    border: 1px solid #30363d;
    padding: 5px;
}
QComboBox::drop-down {
    border: none;
}
"""

class WorkerThread(QThread):
    log_signal = pyqtSignal(str)      # 发送普通日志到主控制台
    stream_signal = pyqtSignal(str)   # 发送 AI 字符到视觉窗口

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        # 必须使用 bufsize=0 和 binary mode 读取，或者 text mode 下 flush
        # 这里使用 text=True 但手动处理读取循环
        process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # 将 stderr 合并到 stdout
            shell=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=0 # 无缓冲，关键！
        )

        while True:
            # 逐个字符读取，实现极致的流式体验
            char = process.stdout.read(1)
            
            if not char and process.poll() is not None:
                break
                
            if char:
                # 简单缓冲区处理，检测 DEBUG 标记
                # 注意：逐字符读取时，匹配长字符串需要累积缓冲
                self.process_char(char)
        
        process.wait()

    def process_char(self, char):
        # 这是一个简化的处理逻辑。
        # 为了性能和简化，我们在这里做一个假设：
        # 如果 utils.py 输出的是一行，我们按行处理可能会有延迟，但更安全。
        # 如果想按字符处理，需要一个状态机。
        # 这里的折中方案：累积字符，遇到换行符处理。
        
        if not hasattr(self, 'line_buffer'):
            self.line_buffer = ""
        
        self.line_buffer += char
        
        if char == "\n":
            line = self.line_buffer.strip()
            # 检查是否是我们在 utils.py 里埋下的钩子
            if line.startswith("DEBUG_AI_CHAR:"):
                # 提取纯内容
                content = line.split("DEBUG_AI_CHAR:", 1)[1]
                # 发送给视觉窗口
                self.stream_signal.emit(content)
                # 不发送给主控制台，保持主控制台清洁
            else:
                # 普通日志，发送给主控制台
                self.log_signal.emit(line)
            
            self.line_buffer = ""

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageIndex Pro - Neural Interface")
        self.resize(1100, 850)
        
        # 初始化视觉窗口（隐藏状态）
        self.visual_window = AIVisualWindow()
        
        self.configs = self.load_configs()
        self.init_ui()
        self.apply_styles()

    def apply_styles(self):
        self.setStyleSheet(STYLESHEET)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # === Header Area ===
        header_layout = QHBoxLayout()
        title_label = QLabel("PAGEINDEX PRO")
        title_label.setStyleSheet("font-size: 24px; color: #00ffcc; letter-spacing: 2px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # === Config Section ===
        cfg_frame = QFrame()
        cfg_frame.setStyleSheet("background-color: #161b22; border-radius: 8px; padding: 10px;")
        cfg_layout = QHBoxLayout(cfg_frame)
        
        self.cb_configs = QComboBox()
        self.cb_configs.addItems(self.configs.keys())
        self.cb_configs.currentTextChanged.connect(self.load_selected_config)
        
        btn_save = QPushButton("💾 SAVE CONFIG")
        btn_save.clicked.connect(self.save_config)
        btn_save.setStyleSheet("background-color: #21262d; border: 1px solid #30363d;")

        cfg_layout.addWidget(QLabel("CONFIGURATION:"))
        cfg_layout.addWidget(self.cb_configs, 1)
        cfg_layout.addWidget(btn_save)
        layout.addWidget(cfg_frame)

        # === Input Section ===
        input_layout = QVBoxLayout()
        
        # PDF Selection
        file_layout = QHBoxLayout()
        self.edit_pdf = QLineEdit()
        self.edit_pdf.setPlaceholderText("Select PDF document path...")
        btn_file = QPushButton("📂 BROWSE")
        btn_file.clicked.connect(self.get_file)
        file_layout.addWidget(QLabel("DOCUMENT:"))
        file_layout.addWidget(self.edit_pdf, 1)
        file_layout.addWidget(btn_file)
        input_layout.addLayout(file_layout)
        
        # Model Selection
        model_layout = QHBoxLayout()
        self.edit_model = QLineEdit("DeepSeek-V3")
        model_layout.addWidget(QLabel("AI MODEL:"))
        model_layout.addWidget(self.edit_model, 1)
        input_layout.addLayout(model_layout)
        
        layout.addLayout(input_layout)

        # === Action Buttons ===
        btn_layout = QHBoxLayout()
        
        self.btn_run = QPushButton("🚀 INITIALIZE INDEXING")
        self.btn_run.setFixedHeight(45)
        self.btn_run.clicked.connect(self.start_task)
        
        self.btn_visual = QPushButton("👁 VISUALIZER: OFF")
        self.btn_visual.setObjectName("VisualBtn")
        self.btn_visual.setCheckable(True)
        self.btn_visual.setFixedHeight(45)
        self.btn_visual.clicked.connect(self.toggle_visual_window)
        
        btn_layout.addWidget(self.btn_run, 2)
        btn_layout.addWidget(self.btn_visual, 1)
        layout.addLayout(btn_layout)

        # === Console Output ===
        layout.addWidget(QLabel("SYSTEM LOGS:"))
        self.txt_console = QTextEdit()
        self.txt_console.setReadOnly(True)
        layout.addWidget(self.txt_console)

    def toggle_visual_window(self):
        if self.btn_visual.isChecked():
            self.visual_window.show()
            self.btn_visual.setText("👁 VISUALIZER: ON")
            # 移动到主窗口右侧
            geo = self.geometry()
            self.visual_window.move(geo.x() + geo.width() + 10, geo.y())
        else:
            self.visual_window.hide()
            self.btn_visual.setText("👁 VISUALIZER: OFF")

    def load_configs(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        return {"Default": {"pdf": "", "model": "DeepSeek-V3", "pages": "3"}}

    def save_config(self):
        name = self.cb_configs.currentText() or "NewConfig"
        self.configs[name] = {"pdf": self.edit_pdf.text(), "model": self.edit_model.text(), "pages": "3"}
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(self.configs, f)
        QMessageBox.information(self, "System", "Configuration Saved Successfully.")

    def load_selected_config(self, name):
        if name in self.configs:
            c = self.configs[name]
            self.edit_pdf.setText(c.get('pdf',''))
            self.edit_model.setText(c.get('model','DeepSeek-V3'))

    def get_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "*.pdf")
        if f: self.edit_pdf.setText(f)

    def start_task(self):
        pdf_path = self.edit_pdf.text()
        if not pdf_path:
            QMessageBox.warning(self, "Error", "Please select a PDF file first.")
            return

        py_exe = sys.executable
        # -u 参数非常重要，强制 stdout 不缓冲
        cmd = f'"{py_exe}" -u run_pageindex.py --pdf_path "{pdf_path}" --model "{self.edit_model.text()}" --toc-check-pages 3'
        
        self.txt_console.clear()
        self.txt_console.append(f"<span style='color:#FFFF00'>[SYSTEM] Initializing subprocess: {cmd}</span>")
        
        self.worker = WorkerThread(cmd)
        self.worker.log_signal.connect(self.txt_console.append)
        
        # 将 Worker 的流信号连接到视觉窗口
        self.worker.stream_signal.connect(self.visual_window.add_stream_char)
        
        # 自动打开视觉窗口
        if not self.btn_visual.isChecked():
            self.btn_visual.click()
            
        self.worker.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion') # 使用 Fusion 风格作为基底，便于 CSS 覆盖
    main = MainWindow()
    main.show()
    sys.exit(app.exec_())