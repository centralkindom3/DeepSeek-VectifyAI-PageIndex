import sys
import json
import os
import subprocess
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox, 
                             QFileDialog, QMessageBox, QFrame)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor

# Import the visual window
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
/* Special Button Style: Visual Switch */
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
    border-radius: 4px;
}
QComboBox::drop-down {
    border: none;
}
QComboBox QAbstractItemView {
    background-color: #161b22;
    color: #c9d1d9;
    selection-background-color: #238636;
}
"""

# 模型列表及默认值
AVAILABLE_MODELS = [
    "qwen2.5-vl-72b",
    "DeepSeek-V3",
    "DeepSeek-R1",
    "qwq-32b",
    "Qwen2.5-32B"
]
DEFAULT_MODEL = "qwen2.5-vl-72b"

class WorkerThread(QThread):
    log_signal = pyqtSignal(str)      # Send normal logs to main console
    stream_signal = pyqtSignal(str)   # Send AI chars to visual window

    def __init__(self, command):
        super().__init__()
        self.command = command
        self.line_buffer = ""

    def run(self):
        process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=0
        )

        while True:
            char = process.stdout.read(1)
            if not char and process.poll() is not None:
                break
            if char:
                self.process_char(char)
        
        self.flush_buffer()
        process.wait()

    def flush_buffer(self):
        if self.line_buffer:
            line = self.line_buffer.strip()
            if line:
                self.emit_log_line(line)
            self.line_buffer = ""

    def process_char(self, char):
        self.line_buffer += char
        if char == "\n":
            line = self.line_buffer.strip()
            if line: 
                if line.startswith("DEBUG_AI_CHAR:"):
                    try:
                        content = line.split("DEBUG_AI_CHAR:", 1)[1]
                        self.stream_signal.emit(content)
                    except: pass
                else:
                    self.emit_log_line(line)
            self.line_buffer = ""

    def emit_log_line(self, line):
        if "[SUCCESS]" in line:
            formatted_line = f"<span style='color:#00FF00; font-weight:bold; font-size:13px;'>{line}</span>"
        elif "[ERROR]" in line or "Exception" in line or "Traceback" in line or "Error" in line:
            formatted_line = f"<span style='color:#FF3333; font-weight:bold;'>{line}</span>"
        elif "[INFO]" in line:
            formatted_line = f"<span style='color:#33CCFF;'>{line}</span>"
        elif "[Warning]" in line:
            formatted_line = f"<span style='color:#FFFF00;'>{line}</span>"
        else:
            formatted_line = line
        self.log_signal.emit(formatted_line)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageIndex Pro - Neural Interface")
        self.resize(1100, 850)
        
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
        
        # Model Selection - 改为下拉列表
        model_layout = QHBoxLayout()
        self.combo_model = QComboBox()
        self.combo_model.addItems(AVAILABLE_MODELS)
        # 设置默认模型
        default_index = AVAILABLE_MODELS.index(DEFAULT_MODEL) if DEFAULT_MODEL in AVAILABLE_MODELS else 0
        self.combo_model.setCurrentIndex(default_index)
        
        model_layout.addWidget(QLabel("AI MODEL:"))
        model_layout.addWidget(self.combo_model, 1)
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
            geo = self.geometry()
            self.visual_window.move(geo.x() + geo.width() + 10, geo.y())
        else:
            self.visual_window.hide()
            self.btn_visual.setText("👁 VISUALIZER: OFF")

    def load_configs(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        # 默认配置使用新默认模型
        return {"Default": {"pdf": "", "model": DEFAULT_MODEL, "pages": "3"}}

    def save_config(self):
        name = self.cb_configs.currentText() or "NewConfig"
        current_model = self.combo_model.currentText()
        self.configs[name] = {
            "pdf": self.edit_pdf.text(),
            "model": current_model,
            "pages": "3"
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.configs, f)
        QMessageBox.information(self, "System", "Configuration Saved Successfully.")

    def load_selected_config(self, name):
        if name and name in self.configs:
            c = self.configs[name]
            self.edit_pdf.setText(c.get('pdf', ''))
            model_name = c.get('model', DEFAULT_MODEL)
            # 如果配置中的模型不在列表中，fallback 到默认
            if model_name in AVAILABLE_MODELS:
                self.combo_model.setCurrentText(model_name)
            else:
                self.combo_model.setCurrentIndex(0)

    def get_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "*.pdf")
        if f:
            self.edit_pdf.setText(f)

    def append_log(self, text):
        self.txt_console.append(text)
        cursor = self.txt_console.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.txt_console.setTextCursor(cursor)

    def start_task(self):
        pdf_path = self.edit_pdf.text()
        if not pdf_path:
            QMessageBox.warning(self, "Error", "Please select a PDF file first.")
            return

        py_exe = sys.executable
        current_model = self.combo_model.currentText()
        cmd = f'"{py_exe}" -u run_pageindex.py --pdf_path "{pdf_path}" --model "{current_model}" --toc-check-pages 3'
        
        self.txt_console.clear()
        self.txt_console.append(f"<span style='color:#FFFF00'>[SYSTEM] Initializing subprocess...</span>")
        
        self.worker = WorkerThread(cmd)
        self.worker.log_signal.connect(self.append_log)
        self.worker.stream_signal.connect(self.visual_window.add_stream_char)
        
        if not self.btn_visual.isChecked():
            self.btn_visual.click()
            
        self.worker.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    main = MainWindow()
    main.show()
    sys.exit(app.exec_())
