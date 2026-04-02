import sys
import subprocess
import threading
import os
import json
import re
import tempfile
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QMessageBox,
    QProgressBar, QListWidget, QDialog, QGroupBox, QSplitter,
    QCheckBox, QPlainTextEdit, QTabWidget
)
from PyQt5.QtCore import pyqtSignal, QObject, Qt
from PyQt5.QtGui import QFont, QPalette, QColor, QIcon, QPixmap


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
    IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp']
    VIDEO_EXTENSIONS = ['mp4', 'webm', 'mov', 'avi', 'mkv', 'm4v', 'wmv', 'flv']
    ALL_EXTENSIONS = IMAGE_EXTENSIONS + VIDEO_EXTENSIONS

    def __init__(self, urls, directory, signals, stop_flag, media_type='all', debug=False):
        super().__init__()
        self.urls = urls
        self.directory = directory
        self.signals = signals
        self.stop_flag = stop_flag
        self.media_type = media_type
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

    def _build_filter_expr(self):
        if self.media_type == 'images':
            exts = self.IMAGE_EXTENSIONS
        elif self.media_type == 'videos':
            exts = self.VIDEO_EXTENSIONS
        else:
            return None
        ext_tuple = ', '.join(f"'{ext}'" for ext in exts)
        return f"extension in ({ext_tuple})"

    def run(self):
        try:
            check = subprocess.run([self.python_cmd, '-m', 'gallery_dl', '--version'],
                                   capture_output=True, text=True)
            if check.returncode != 0:
                self.signals.error.emit(f"gallery-dl not found. Install: {self.python_cmd} -m pip install gallery-dl")
                return

            pattern = r'\.(' + '|'.join(self.ALL_EXTENSIONS) + r')$'
            file_saved_pattern = re.compile(
                r'^([A-Za-z]:[\\/]|/).+' + pattern,
                re.IGNORECASE
            )

            for url in self.urls:
                if self.stop_flag.is_set():
                    break

                self.signals.output.emit(f"\n[INFO] Processing: {url}\n")

                cmd = [self.python_cmd, "-m", "gallery_dl", "-d", self.directory]

                temp_config = None
                if "erome.com" in url.lower():
                    temp_config = self.create_erome_config()
                    cmd.extend(["-c", temp_config])
                    self.signals.output.emit("[INFO] Create New Folder\n")

                filter_expr = self._build_filter_expr()
                if filter_expr:
                    cmd.extend(["--filter", filter_expr])
                    if self.debug:
                        self.signals.output.emit(f"[DEBUG] Filter: {filter_expr}\n")

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
            self.parent.set_urls_from_tab(current.text())
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
    THEMES = {
        'images': {
            'bg_main': '#1e1e2f', 'bg_panel': '#25253a', 'bg_entry': '#2d2d40',
            'text': '#f0f0f0', 'border': '#3a3a4a', 'highlight': '#0e639c',
            'highlight_hover': '#1177bb', 'highlight_pressed': '#0a4d73',
            'disabled_text': '#8a8a8a', 'progress_start': '#0e639c', 'progress_end': '#4ec0e9',
            'scrollbar_bg': '#2d2d40', 'scrollbar_handle': '#5a5a6a', 'scrollbar_handle_hover': '#6a6a7a',
            'credit_color': '#ff4d4d', 'status_color': '#4ec0e9',
        },
        'videos': {
            'bg_main': '#2f1e1e', 'bg_panel': '#3a2525', 'bg_entry': '#402d2d',
            'text': '#f0f0f0', 'border': '#4a3a3a', 'highlight': '#9c3e0e',
            'highlight_hover': '#b84e1a', 'highlight_pressed': '#7a2e0a',
            'disabled_text': '#8a8a8a', 'progress_start': '#9c3e0e', 'progress_end': '#e06c3e',
            'scrollbar_bg': '#402d2d', 'scrollbar_handle': '#6a4a4a', 'scrollbar_handle_hover': '#7a5a5a',
            'credit_color': '#ff4d4d', 'status_color': '#e06c3e',
        },
        'all': {
            'bg_main': '#1e2f1e', 'bg_panel': '#253a25', 'bg_entry': '#2d402d',
            'text': '#f0f0f0', 'border': '#3a4a3a', 'highlight': '#0e9c6b',
            'highlight_hover': '#1ab87a', 'highlight_pressed': '#0a7a52',
            'disabled_text': '#8a8a8a', 'progress_start': '#0e9c6b', 'progress_end': '#4ec08e',
            'scrollbar_bg': '#2d402d', 'scrollbar_handle': '#5a6a5a', 'scrollbar_handle_hover': '#6a7a6a',
            'credit_color': '#ff4d4d', 'status_color': '#4ec08e',
        }
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EroMe Media Downloader")
        self.setMinimumSize(1100, 700)

        self.download_dir = ""
        self.history_file = "download_history.json"
        self.stop_flag = threading.Event()
        self.worker = None
        self.signals = None
        self.debug_mode = False

        self.load_history()
        self.setup_ui()
        self.apply_theme('images')
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        default_dir = get_default_downloads_folder()
        self.download_dir = default_dir
        self.dir_path.setText(self.download_dir)
        self.open_dir_btn.setEnabled(True)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(2)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(15, 15, 15, 15)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #3a3a3a; background-color: #252526; border-radius: 8px; }
            QTabBar::tab { background-color: #2d2d30; color: #f0f0f0; padding: 8px 20px; margin-right: 2px;
                           border-top-left-radius: 6px; border-top-right-radius: 6px; }
            QTabBar::tab:selected { background-color: #0e639c; color: white; }
            QTabBar::tab:hover:!selected { background-color: #3a3a3a; }
        """)

        # Tab 1: Images
        self.images_tab = QWidget()
        images_layout = QVBoxLayout(self.images_tab)
        self.images_url_entry = QPlainTextEdit()
        self.images_url_entry.setPlaceholderText(
            "Enter one URL per line\nExample:\nhttps://erome.com/a/example1"
        )
        self.images_url_entry.setMaximumHeight(100)
        images_layout.addWidget(self.images_url_entry)
        self.tab_widget.addTab(self.images_tab, "📷 Images")

        # Tab 2: Videos
        self.videos_tab = QWidget()
        videos_layout = QVBoxLayout(self.videos_tab)
        self.videos_url_entry = QPlainTextEdit()
        self.videos_url_entry.setPlaceholderText(
            "Enter one URL per line\nExample:\nhttps://erome.com/a/example1"
        )
        self.videos_url_entry.setMaximumHeight(100)
        videos_layout.addWidget(self.videos_url_entry)
        self.tab_widget.addTab(self.videos_tab, "🎥 Videos")

        # Tab 3: All Medias
        self.all_tab = QWidget()
        all_layout = QVBoxLayout(self.all_tab)
        self.all_url_entry = QPlainTextEdit()
        self.all_url_entry.setPlaceholderText(
            "Enter one URL per line\nExample:\nhttps://erome.com/a/example1"
        )
        self.all_url_entry.setMaximumHeight(100)
        all_layout.addWidget(self.all_url_entry)
        self.tab_widget.addTab(self.all_tab, "📁 All Medias")

        left_layout.addWidget(self.tab_widget)

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

        # --- Progress group: now only a text label (no progress bar) ---
        progress_group = QGroupBox("📊 Progress")
        progress_layout = QVBoxLayout()
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

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_splitter)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(10, 5, 10, 5)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status_label")
        bottom_layout.addWidget(self.status_label, 1)

        self.credit_label = QLabel("Dev | By RJ")
        self.credit_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.credit_label.setObjectName("credit_label")
        self.credit_label.setToolTip("Developed by RJ")
        bottom_layout.addWidget(self.credit_label)

        main_layout.addLayout(bottom_layout)

    def generate_stylesheet(self, theme):
        return f"""
            QMainWindow {{ background-color: {theme['bg_main']}; }}
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {theme['border']};
                border-radius: 10px;
                margin-top: 12px;
                background-color: {theme['bg_panel']};
                color: {theme['text']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
                background-color: {theme['bg_panel']};
                color: {theme['status_color']};
            }}
            QLineEdit, QPlainTextEdit, QTextEdit {{
                border: 1px solid {theme['border']};
                border-radius: 6px;
                background-color: {theme['bg_entry']};
                color: {theme['text']};
                selection-background-color: {theme['highlight']};
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
                border: 1px solid {theme['highlight']};
            }}
            QPushButton {{
                background-color: {theme['highlight']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {theme['highlight_hover']}; }}
            QPushButton:pressed {{ background-color: {theme['highlight_pressed']}; }}
            QPushButton:disabled {{ background-color: {theme['border']}; color: {theme['disabled_text']}; }}
            QProgressBar {{
                border: none;
                border-radius: 6px;
                background-color: {theme['bg_entry']};
                height: 16px;
                text-align: center;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                                  stop:0 {theme['progress_start']}, stop:1 {theme['progress_end']});
                border-radius: 6px;
            }}
            QCheckBox {{
                color: {theme['text']};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid {theme['border']};
                background-color: {theme['bg_entry']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {theme['highlight']};
                border: 1px solid {theme['highlight']};
            }}
            QScrollBar:vertical {{
                background-color: {theme['scrollbar_bg']};
                width: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {theme['scrollbar_handle']};
                border-radius: 5px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {theme['scrollbar_handle_hover']};
            }}
            QTabWidget::pane {{
                border: 1px solid {theme['border']};
                background-color: {theme['bg_panel']};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background-color: {theme['bg_entry']};
                color: {theme['text']};
                padding: 8px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
            QTabBar::tab:selected {{
                background-color: {theme['highlight']};
                color: white;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {theme['border']};
            }}
            QSplitter::handle {{
                background-color: {theme['border']};
            }}
            QListWidget {{
                background-color: {theme['bg_entry']};
                color: {theme['text']};
                border: 1px solid {theme['border']};
                border-radius: 8px;
                font-family: monospace;
                padding: 5px;
            }}
            QListWidget::item:selected {{
                background-color: {theme['highlight']};
                color: white;
            }}
            QDialog {{
                background-color: {theme['bg_main']};
                color: {theme['text']};
            }}
            QLabel#status_label {{
                background-color: {theme['bg_panel']};
                color: {theme['status_color']};
                padding: 4px;
            }}
            QLabel#credit_label {{
                color: {theme['credit_color']};
            }}
        """

    def apply_theme(self, theme_name):
        theme = self.THEMES.get(theme_name, self.THEMES['images'])
        stylesheet = self.generate_stylesheet(theme)
        self.setStyleSheet(stylesheet)

        # Update application palette
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(theme['bg_main']))
        palette.setColor(QPalette.WindowText, QColor(theme['text']))
        palette.setColor(QPalette.Base, QColor(theme['bg_entry']))
        palette.setColor(QPalette.AlternateBase, QColor(theme['bg_panel']))
        palette.setColor(QPalette.ToolTipBase, QColor(theme['text']))
        palette.setColor(QPalette.ToolTipText, QColor(theme['text']))
        palette.setColor(QPalette.Text, QColor(theme['text']))
        palette.setColor(QPalette.Button, QColor(theme['bg_panel']))
        palette.setColor(QPalette.ButtonText, QColor(theme['text']))
        palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.Highlight, QColor(theme['highlight']))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        QApplication.instance().setPalette(palette)

    def on_tab_changed(self, index):
        if index == 0:
            self.apply_theme('images')
        elif index == 1:
            self.apply_theme('videos')
        elif index == 2:
            self.apply_theme('all')

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

    def get_urls_from_active_tab(self):
        current_index = self.tab_widget.currentIndex()
        if current_index == 0:
            text = self.images_url_entry.toPlainText()
        elif current_index == 1:
            text = self.videos_url_entry.toPlainText()
        else:
            text = self.all_url_entry.toPlainText()
        return [url.strip() for url in text.splitlines() if url.strip()]

    def set_urls_to_active_tab(self, urls_text):
        current_index = self.tab_widget.currentIndex()
        if current_index == 0:
            self.images_url_entry.setPlainText(urls_text)
        elif current_index == 1:
            self.videos_url_entry.setPlainText(urls_text)
        else:
            self.all_url_entry.setPlainText(urls_text)

    def set_urls_from_tab(self, url):
        self.set_urls_to_active_tab(url)

    def start_download(self):
        urls = self.get_urls_from_active_tab()
        if not urls:
            QMessageBox.warning(self, "Error", "Please enter at least one URL.")
            return

        if not self.download_dir:
            QMessageBox.warning(self, "Error", "No download directory selected.")
            return

        current_index = self.tab_widget.currentIndex()
        if current_index == 0:
            media_type = 'images'
        elif current_index == 1:
            media_type = 'videos'
        else:
            media_type = 'all'

        os.makedirs(self.download_dir, exist_ok=True)

        for url in urls:
            self.add_history(url)

        self.download_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.clear_output_btn.setEnabled(False)
        self.output_area.clear()
        self.progress_details.setText("Starting download...")
        self.stop_flag.clear()

        self.signals = WorkerSignals()
        self.signals.output.connect(self.append_output)
        self.signals.progress.connect(self.update_progress)
        self.signals.finished.connect(self.download_finished)
        self.signals.error.connect(self.show_error)

        self.worker = GalleryDLWorker(urls, self.download_dir, self.signals,
                                      self.stop_flag, media_type, self.debug_mode)
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
        if total == 0:
            self.progress_details.setText("Waiting for first file...")
        else:
            self.progress_details.setText(f"Downloaded {completed} of {total} files")
            if completed == total:
                self.progress_details.setText("Download completed!")

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
        self.progress_details.setText("Error occurred")


if __name__ == "__main__":
    # ---- Set AppUserModelID (must be before QApplication) ----
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EroMeDownloader.RJ.1.0.4")
        except:
            pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # ---- Locate or create icon ----
    base_path = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_path, "assets", "icon.png")

    if os.path.exists(icon_path):
        icon = QIcon(icon_path)
        print(f"[INFO] Using icon from: {icon_path}")
    else:
        # Fallback to a built-in icon (16x16 colored square)
        print(f"[WARNING] Icon not found at {icon_path}, using built-in fallback.")
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.red)
        icon = QIcon(pixmap)

    # Set application icon (affects taskbar on Windows)
    app.setWindowIcon(icon)

    # Create and show window
    window = GalleryDLGUI()
    window.setWindowIcon(icon)
    window.show()

    sys.exit(app.exec_())
