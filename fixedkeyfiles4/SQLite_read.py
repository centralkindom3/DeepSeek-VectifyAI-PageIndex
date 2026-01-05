import sys
import sqlite3
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QFileDialog, QLineEdit, QTextEdit, QLabel, QHBoxLayout
)
from PyQt5.QtCore import Qt

class SQLiteReader(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SQLite 数据库读取器 (第一行预览)")
        self.setMinimumSize(800, 600)

        # 布局
        main_layout = QVBoxLayout()

        # 文件选择部分
        file_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("尚未选择数据库文件")
        browse_btn = QPushButton("选择 .db 文件")
        browse_btn.clicked.connect(self.browse_file)
        file_layout.addWidget(self.path_edit)
        file_layout.addWidget(browse_btn)

        # 读取按钮
        self.read_btn = QPushButton("读取数据库（显示每个表的第一行数据，不含标题）")
        self.read_btn.clicked.connect(self.read_db)
        self.read_btn.setEnabled(False)  # 初始禁用，直到选择文件

        # 结果显示区（可复制粘贴）
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(False)  # 允许用户选中复制
        self.result_text.setPlaceholderText("读取结果将显示在这里（使用 Tab 分隔，便于复制到 Excel）")

        # 添加到主布局
        main_layout.addWidget(QLabel("选择的 SQLite 数据库文件:"))
        main_layout.addLayout(file_layout)
        main_layout.addWidget(self.read_btn)
        main_layout.addWidget(QLabel("数据预览（每个表的第一行数据，完整显示，不含列标题）:"))
        main_layout.addWidget(self.result_text)

        self.setLayout(main_layout)

        self.db_path = None

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 SQLite 数据库文件",
            "",
            "SQLite Files (*.db *.sqlite *.sqlite3);;All Files (*)"
        )
        if file_path:
            self.db_path = file_path
            self.path_edit.setText(file_path)
            self.read_btn.setEnabled(True)
            self.result_text.clear()
            self.result_text.setPlaceholderText("已选择文件，点击“读取”按钮查看第一行数据")

    def read_db(self):
        if not self.db_path:
            self.result_text.setText("错误：请先选择一个数据库文件！")
            return

        self.result_text.clear()
        self.result_text.append("正在读取数据库，请稍等...\n")

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 获取所有表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()

            if not tables:
                self.result_text.append("数据库中没有找到任何表。")
                conn.close()
                return

            output_lines = []
            for table_tuple in tables:
                table_name = table_tuple[0]
                output_lines.append(f"===== 表: {table_name} =====\n")

                # 前1行数据（不查询列标题）
                cursor.execute(f"SELECT * FROM \"{table_name}\" LIMIT 1;")
                row = cursor.fetchone()  # 只取第一行

                if row is None:
                    output_lines.append("(此表为空，没有数据)\n\n")
                    continue

                # 将每一列转换为字符串，None 显示为空，完整保留所有内容
                row_str = "\t".join("" if cell is None else str(cell) for cell in row)
                output_lines.append(row_str + "\n\n")  # 表之间空行分隔

            # 一次性写入结果
            full_output = "".join(output_lines)
            if full_output.strip():
                self.result_text.setPlainText(full_output.rstrip())
            else:
                self.result_text.setPlainText("所有表均为空。")

            conn.close()

        except sqlite3.Error as e:
            self.result_text.setPlainText(f"SQLite 错误: {str(e)}")
        except Exception as e:
            self.result_text.setPlainText(f"发生未知错误: {str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SQLiteReader()
    window.show()
    sys.exit(app.exec_())