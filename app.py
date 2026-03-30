import sys
import subprocess
import threading
import os
import json
import time
import re
import tempfile
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QMessageBox,
    QProgressBar, QListWidget, QDialog, QGroupBox, QSplitter,
    QCheckBox, QPlainTextEdit
)
from PyQt5.QtCore import pyqtSignal, QObject, Qt
from PyQt5.QtGui import QFont, QPalette, QColor


def get_default_downloads_folder():
    if sys.platform == 'win32':
        import ctypes.wintypes
        CSIDL_PROFILE = 0x28
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PROFILE, None, 0, buf)
        profile = buf.value
        downloads = os.path.join(profile, 'Downloads')
    else:
        downloads = os.path.join(str(Path.home()), 'Downloads')
    os.makedirs(downloads, exist_ok=True)
    return downloads


def get_python_command():
    candidates = ['py', 'python', 'python3', sys.executable]
    for cmd in candidates:
        try:
            result = subprocess.run([cmd, '-m', 'gallery_dl', '--version'],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return cmd
        except:
            continue
    return sys.executable


class WorkerSignals(QObject):
    output = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal()
    error = pyqtSignal(str)


class GalleryDLWorker(threading.Thread):
    def __init__(self, urls, directory, signals, stop_flag, debug=False):
        super().__init__()
        self.urls = urls
        self.directory = directory
        self.signals = signals
        self.stop_flag = stop_flag
        self.process = None
        self.debug = debug
        self.python_cmd = get_python_command()
        self.temp_config_files = []

    def create_erome_config(self):
        config = {"extractor": {"erome": {"directory": ["{title}"]}}}
        fd, path = tempfile.mkstemp(suffix='.json', prefix='gallerydl_', text=True)
        with os.fdopen(fd, 'w') as f:
            json.dump(config, f, indent=2)
        self.temp_config_files.append(path)
        return path

    def run(self):
        try:
            check = subprocess.run([self.python_cmd, '-m', 'gallery_dl', '--version'],
                                   capture_output=True, text=True)
            if check.returncode != 0:
                self.signals.error.emit(f"gallery-dl not found. Install: {self.python_cmd} -m pip install gallery-dl")
                return

            for url in self.urls:
                if self.stop_flag.is_set():
                    break

                self.signals.output.emit(f"\n[INFO] Processing: {url}\n")

                # Download command
                cmd = [self.python_cmd, "-m", "gallery_dl", "-d", self.directory]
                temp_config = None
                if "erome.com" in url.lower():
                    temp_config = self.create_erome_config()
                    cmd.extend(["-c", temp_config])
                    self.signals.output.emit("[INFO] Create New Folder\n")

                cmd.append(url)

                if self.debug:
                    self.signals.output.emit(f"[DEBUG] Running: {' '.join(cmd)}\n")

                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                    bufsize=1
                )

                downloaded_files = 0
                seen_files = set()
                file_saved_pattern = re.compile(
                    r'^([A-Za-z]:[\\/]|/).+\.(jpg|jpeg|png|gif|mp4|webm|mov|avi|mkv|m4v|wmv|flv|bmp|tiff|webp)$',
                    re.IGNORECASE
                )

                for line in self.process.stdout:
                    if self.stop_flag.is_set():
                        self.process.terminate()
                        break

                    if self.debug:
                        self.signals.output.emit(f"[RAW] {line}")

                    line_stripped = line.strip()
                    if file_saved_pattern.match(line_stripped):
                        downloaded_files += 1
                        seen_files.add(line_stripped)
                        total = len(seen_files)
                        self.signals.progress.emit(downloaded_files, total)
                        self.signals.output.emit(f"[PROGRESS] {downloaded_files}/{total} files\n")

                    if not self.debug:
                        self.signals.output.emit(line)

                if self.process:
                    self.process.wait()

                if temp_config and os.path.exists(temp_config):
                    try:
                        os.remove(temp_config)
                    except:
                        pass

            if not self.stop_flag.is_set():
                self.signals.finished.emit()
            else:
                self.signals.output.emit("\n[INFO] Download stopped by user.\n")

        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            for cfg in self.temp_config_files:
                if os.path.exists(cfg):
                    try:
                        os.remove(cfg)
                    except:
                        pass

    def stop(self):
        if self.process:
            self.process.terminate()


class HistoryDialog(QDialog):
    def __init__(self, history, history_file, parent=None):
        super().__init__(parent)
        self.history = history
        self.history_file = history_file
        self.parent = parent
        self.setWindowTitle("📖 Download History")
        self.setMinimumSize(500, 400)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        for url in self.history:
            self.list_widget.addItem(url)
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        redownload_btn = QPushButton("🔃 Re-download Selected")
        redownload_btn.clicked.connect(self.redownload)
        remove_btn = QPushButton("♻️ Remove Selected")
        remove_btn.clicked.connect(self.remove_selected)
        clear_btn = QPushButton("♻️ Clear All History")
        clear_btn.clicked.connect(self.clear_all)

        for btn in (redownload_btn, remove_btn, clear_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2c2c2c;
                    color: #f0f0f0;
                    border: 1px solid #3a3a3a;
                    border-radius: 8px;
                    padding: 8px 16px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #3a3a3a; }
            """)
            btn_layout.addWidget(btn)

        layout.addLayout(btn_layout)

        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #f0f0f0; }
            QListWidget {
                background-color: #2d2d30;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                font-family: monospace;
                padding: 5px;
            }
            QListWidget::item:selected { background-color: #0e639c; color: white; }
        """)

    def redownload(self):
        current = self.list_widget.currentItem()
        if current:
            self.parent.url_entry.setPlainText(current.text())
            self.accept()
            self.parent.start_download()

    def remove_selected(self):
        current = self.list_widget.currentRow()
        if current >= 0:
            self.list_widget.takeItem(current)
            self.history.pop(current)
            self.save_history()

    def clear_all(self):
        confirm = QMessageBox.question(self, "Confirm Clear", "Clear all history?",
                                       QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.history.clear()
            self.list_widget.clear()
            self.save_history()

    def save_history(self):
        with open(self.history_file, "w") as f:
            json.dump(self.history, f, indent=2)


class GalleryDLGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("❤ EroMe Media Downloader")
        self.setMinimumSize(1100, 700)

        self.download_dir = ""
        self.history_file = "download_history.json"
        self.stop_flag = threading.Event()
        self.worker = None
        self.signals = None
        self.debug_mode = False

        self.load_history()
        self.setup_ui()
        self.apply_modern_stylesheet()

        default_dir = get_default_downloads_folder()
        self.download_dir = default_dir
        self.dir_path.setText(self.download_dir)
        self.open_dir_btn.setEnabled(True)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(2)
        main_splitter.setStyleSheet("QSplitter::handle { background-color: #2d2d30; }")

        # LEFT PANEL
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(15, 15, 15, 15)

        url_group = QGroupBox("🔗 Download URLs")
        url_layout = QVBoxLayout()
        self.url_entry = QPlainTextEdit()
        self.url_entry.setPlaceholderText(
            "Enter one URL per line\n Example:\nhttps://erome.com/a/example1"
        )
        self.url_entry.setMaximumHeight(100)
        self.url_entry.setStyleSheet("font-size: 12px; padding: 6px;")
        url_layout.addWidget(self.url_entry)
        url_group.setLayout(url_layout)
        left_layout.addWidget(url_group)

        dir_group = QGroupBox("📁 Download Directory")
        dir_layout = QVBoxLayout()
        self.dir_path = QLineEdit()
        self.dir_path.setReadOnly(True)
        self.dir_path.setPlaceholderText("No directory selected")
        dir_btn_layout = QHBoxLayout()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.select_directory)
        self.open_dir_btn = QPushButton("📂 Open Folder")
        self.open_dir_btn.clicked.connect(self.open_directory)
        self.open_dir_btn.setEnabled(False)
        dir_btn_layout.addWidget(browse_btn)
        dir_btn_layout.addWidget(self.open_dir_btn)
        dir_layout.addWidget(self.dir_path)
        dir_layout.addLayout(dir_btn_layout)
        dir_group.setLayout(dir_layout)
        left_layout.addWidget(dir_group)

        # PROGRESS BAR - redesigned
        progress_group = QGroupBox("📊 Progress")
        progress_layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v/%m files")
        progress_layout.addWidget(self.progress_bar)
        self.progress_details = QLabel("Ready")
        self.progress_details.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(self.progress_details)
        progress_group.setLayout(progress_layout)
        left_layout.addWidget(progress_group)

        btn_layout = QVBoxLayout()
        self.download_btn = QPushButton("📥 Start Download")
        self.download_btn.clicked.connect(self.start_download)
        self.stop_btn = QPushButton("⬜ Stop Download")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_download)
        self.clear_output_btn = QPushButton("❌ Clear Log")
        self.clear_output_btn.clicked.connect(self.clear_output)
        self.history_btn = QPushButton("📜 History")
        self.history_btn.clicked.connect(self.show_history)

        for btn in (self.download_btn, self.stop_btn, self.clear_output_btn, self.history_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn_layout.addWidget(btn)

        self.debug_checkbox = QCheckBox("🐞 Debug Mode")
        self.debug_checkbox.stateChanged.connect(self.toggle_debug)
        btn_layout.addWidget(self.debug_checkbox)

        left_layout.addLayout(btn_layout)
        left_layout.addStretch()

        # RIGHT PANEL
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 15, 15, 15)
        log_group = QGroupBox("📄 Live Log")
        log_layout = QVBoxLayout()
        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setFont(QFont("Courier New", 10))
        log_layout.addWidget(self.output_area)
        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group)

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([400, 700])

        # Main vertical layout for central widget
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_splitter)

        # Bottom bar with status on left and credit on right
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(10, 5, 10, 5)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("padding: 4px; background-color: #252526; color: #4ec0e9;")
        bottom_layout.addWidget(self.status_label, 1)

        # Credit label (bottom right) - RED AND BOLD
        self.credit_label = QLabel("Dev | By RJ")
        self.credit_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.credit_label.setStyleSheet("""
            QLabel {
                color: #ff4d4d;
                font-weight: bold;
                font-size: 10px;
                padding-right: 5px;
            }
        """)
        self.credit_label.setToolTip("Developed by RJ")
        bottom_layout.addWidget(self.credit_label)

        main_layout.addLayout(bottom_layout)

    def apply_modern_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #2d2d30;
                border-radius: 10px;
                margin-top: 12px;
                background-color: #252526;
                color: #f0f0f0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
                background-color: #252526;
                color: #4ec0e9;
            }
            QLineEdit, QPlainTextEdit, QTextEdit {
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                background-color: #2d2d30;
                color: #f0f0f0;
                selection-background-color: #0e639c;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
                border: 1px solid #0e639c;
            }
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1177bb; }
            QPushButton:pressed { background-color: #0a4d73; }
            QPushButton:disabled { background-color: #3a3a3a; color: #8a8a8a; }
            QProgressBar {
                border: none;
                border-radius: 6px;
                background-color: #2d2d30;
                height: 16px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                                  stop:0 #0e639c, stop:1 #4ec0e9);
                border-radius: 6px;
            }
            QCheckBox {
                color: #f0f0f0;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #3a3a3a;
                background-color: #2d2d30;
            }
            QCheckBox::indicator:checked {
                background-color: #0e639c;
                border: 1px solid #0e639c;
            }
            QScrollBar:vertical {
                background-color: #2d2d30;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #5a5a5a;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #6a6a6a;
            }
        """)

    def toggle_debug(self, state):
        self.debug_mode = (state == Qt.Checked)
        self.append_output(f"[INFO] Debug mode {'ON' if self.debug_mode else 'OFF'}\n")

    def select_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if folder:
            downloads_subfolder = os.path.join(folder, "Downloads")
            os.makedirs(downloads_subfolder, exist_ok=True)
            self.download_dir = downloads_subfolder
            self.dir_path.setText(self.download_dir)
            self.open_dir_btn.setEnabled(True)
            self.append_output(f"[INFO] Download directory set to: {self.download_dir}\n")

    def open_directory(self):
        if self.download_dir and os.path.exists(self.download_dir):
            if sys.platform == 'win32':
                os.startfile(self.download_dir)
            else:
                os.system(f'open "{self.download_dir}"')

    def start_download(self):
        urls_text = self.url_entry.toPlainText().strip()
        if not urls_text:
            QMessageBox.warning(self, "Error", "Please enter at least one URL.")
            return

        urls = [url.strip() for url in urls_text.splitlines() if url.strip()]
        if not urls:
            QMessageBox.warning(self, "Error", "No valid URLs found.")
            return

        if not self.download_dir:
            QMessageBox.warning(self, "Error", "No download directory selected.")
            return

        os.makedirs(self.download_dir, exist_ok=True)

        for url in urls:
            self.add_history(url)

        self.download_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.clear_output_btn.setEnabled(False)
        self.output_area.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(0)
        self.progress_details.setText("Starting download...")
        self.stop_flag.clear()

        self.signals = WorkerSignals()
        self.signals.output.connect(self.append_output)
        self.signals.progress.connect(self.update_progress)
        self.signals.finished.connect(self.download_finished)
        self.signals.error.connect(self.show_error)

        self.worker = GalleryDLWorker(urls, self.download_dir, self.signals, self.stop_flag, self.debug_mode)
        self.worker.start()
        self.status_label.setText("Downloading...")

    def stop_download(self):
        if self.worker and self.worker.is_alive():
            self.stop_flag.set()
            self.worker.stop()
            self.append_output("\n[INFO] Stopping download...\n")
            self.status_label.setText("Stopping...")
        else:
            self.download_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def append_output(self, text):
        self.output_area.moveCursor(self.output_area.textCursor().End)
        self.output_area.insertPlainText(text)
        self.output_area.moveCursor(self.output_area.textCursor().End)
        scrollbar = self.output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_progress(self, completed, total):
        # total is dynamic (number of unique saved files)
        if total == 0:
            self.progress_bar.setMaximum(0)
            self.progress_bar.setFormat("0/0 files")
            self.progress_details.setText("Waiting for first file...")
        else:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(completed)
            self.progress_bar.setFormat(f"{completed}/{total} files")
            self.progress_details.setText(f"Downloaded {completed} of {total} files")
            if completed == total:
                self.progress_bar.setFormat("100% - Complete")

    def download_finished(self):
        self.append_output("\n[SUCCESS] All downloads completed. ✔\n")
        self.download_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.clear_output_btn.setEnabled(True)
        self.status_label.setText("✔ Completed")
        self.progress_details.setText("✔ Download completed!")
        QMessageBox.information(self, "Complete", "All files downloaded.")

    def clear_output(self):
        self.output_area.clear()
        self.status_label.setText("Output cleared")

    def show_history(self):
        dialog = HistoryDialog(self.history, self.history_file, self)
        dialog.exec_()

    def load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r") as f:
                    self.history = json.load(f)
            except:
                self.history = []
        else:
            self.history = []

    def add_history(self, url):
        if url not in self.history:
            self.history.insert(0, url)
            if len(self.history) > 100:
                self.history = self.history[:100]
            with open(self.history_file, "w") as f:
                json.dump(self.history, f, indent=2)

    def show_error(self, msg):
        QMessageBox.critical(self, "Error", msg)
        self.download_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.clear_output_btn.setEnabled(True)
        self.status_label.setText("Error occurred")
        self.progress_bar.setValue(0)
        self.progress_details.setText("Error occurred")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, QColor(240, 240, 240))
    palette.setColor(QPalette.Base, QColor(45, 45, 48))
    palette.setColor(QPalette.AlternateBase, QColor(37, 37, 38))
    palette.setColor(QPalette.ToolTipBase, QColor(240, 240, 240))
    palette.setColor(QPalette.ToolTipText, QColor(240, 240, 240))
    palette.setColor(QPalette.Text, QColor(240, 240, 240))
    palette.setColor(QPalette.Button, QColor(45, 45, 48))
    palette.setColor(QPalette.ButtonText, QColor(240, 240, 240))
    palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.Highlight, QColor(14, 99, 156))
    palette.setColor(QPalette.HighlightedText, QColor(240, 240, 240))
    app.setPalette(palette)

    window = GalleryDLGUI()
    window.show()
    sys.exit(app.exec_())