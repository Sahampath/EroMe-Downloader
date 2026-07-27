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
    QCheckBox, QPlainTextEdit, QSplashScreen
)
from PyQt5.QtCore import pyqtSignal, QObject, Qt
from PyQt5.QtGui import QFont, QPalette, QColor, QIcon, QPixmap, QPainter


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

    def __init__(self, urls, directory, signals, stop_flag, media_type='all',
                 debug=False, num_threads=4, skip_existing=False):
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
        self.num_threads = num_threads
        self.skip_existing = skip_existing
        self._skip_folder_printed = False

    def create_config(self, url, skip_existing=False):
        """Create a temporary config file with Erome directory template and/or skip option."""
        config = {}
        if "erome.com" in url.lower():
            config["extractor"] = {"erome": {"directory": ["{title}"]}}
        if skip_existing:
            config["downloader"] = {"skip": True}
        if not config:
            return None
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
            # Check gallery-dl availability
            check = subprocess.run([self.python_cmd, '-m', 'gallery_dl', '--version'],
                                   capture_output=True, text=True)
            if check.returncode != 0:
                self.signals.error.emit(f"gallery-dl not found. Install: {self.python_cmd} -m pip install gallery-dl")
                return

            pattern = r'\.(' + '|'.join(self.ALL_EXTENSIONS) + r')$'
            file_saved_pattern = re.compile(r'^([A-Za-z]:[\\/]|/).+' + pattern, re.IGNORECASE)

            for url in self.urls:
                if self.stop_flag.is_set():
                    break

                self.signals.output.emit(f"\n📥 Processing: {url}\n")
                self._skip_folder_printed = False

                cmd = [self.python_cmd, "-m", "gallery_dl", "-d", self.directory]

                if self.num_threads > 1:
                    cmd.extend(["-j", str(self.num_threads)])
                    if self.debug:
                        self.signals.output.emit(f"⚙️ Using {self.num_threads} parallel threads\n")

                # Create config file if needed (for Erome folder or skip)
                config_path = self.create_config(url, self.skip_existing)
                if config_path:
                    cmd.extend(["-c", config_path])

                filter_expr = self._build_filter_expr()
                if filter_expr:
                    cmd.extend(["--filter", filter_expr])
                    if self.debug:
                        self.signals.output.emit(f"🔍 Filter: {filter_expr}\n")

                cmd.append(url)

                if self.debug:
                    self.signals.output.emit(f"🐞 Running: {' '.join(cmd)}\n")

                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                    bufsize=1
                )

                downloaded_files = 0

                for line in self.process.stdout:
                    if self.stop_flag.is_set():
                        self.process.terminate()
                        break

                    line_stripped = line.strip()

                    if self.skip_existing and line_stripped.startswith('#'):
                        path_part = line_stripped[1:].strip()
                        if path_part and not self._skip_folder_printed:
                            folder = os.path.basename(os.path.dirname(path_part))
                            if folder:
                                self.signals.output.emit(f"⏭️ Skipping files in folder: {folder} (already exist)\n")
                                self._skip_folder_printed = True
                        continue

                    if self.debug:
                        self.signals.output.emit(f"[RAW] {line}")

                    if file_saved_pattern.match(line_stripped):
                        downloaded_files += 1
                        self.signals.output.emit(f"📄 Downloaded: {downloaded_files} files so far\n")

                    if not self.debug:
                        self.signals.output.emit(line)

                if self.process:
                    self.process.wait()

            if not self.stop_flag.is_set():
                self.signals.finished.emit()
            else:
                self.signals.output.emit("\n⏹️ Download stopped by user.\n")

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
        self.setWindowTitle("📜 Download History")
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
        redownload_btn = QPushButton("🔁 Re-download Selected")
        redownload_btn.clicked.connect(self.redownload)
        remove_btn = QPushButton("❌ Remove Selected")
        remove_btn.clicked.connect(self.remove_selected)
        clear_btn = QPushButton("🗑️ Clear All History")
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
            QListWidget::item:selected { background-color: #f57c00; color: white; }
        """)

    def redownload(self):
        current = self.list_widget.currentItem()
        if current:
            self.parent.set_urls_text(current.text())
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
    # ---------- ORANGE & BLACK THEME ----------
    THEME = {
        'bg_main': '#0d0d0d',
        'bg_panel': '#1a1a1a',
        'bg_entry': '#2a2a2a',
        'text': '#f0f0f0',
        'border': '#3d3d3d',
        'highlight': '#f57c00',
        'highlight_hover': '#ffa726',
        'highlight_pressed': '#e65100',
        'disabled_text': '#6a6a6a',
        'progress_start': '#ef6c00',
        'progress_end': '#ffab00',
        'scrollbar_bg': '#1a1a1a',
        'scrollbar_handle': '#4a4a4a',
        'scrollbar_handle_hover': '#5a5a5a',
    }
    # ----------------------------------------------

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EroMe Media Downloader")
        self.setMinimumSize(1100, 700)

        self.download_dir = ""
        self.history_file = "download_history.json"
        self.stop_flag = threading.Event()
        self.workers = []
        self.active_workers = 0
        self.completed_workers = 0
        self.url_queue = []
        self.signals = None
        self.debug_mode = False
        self.skip_existing = True

        self.load_history()
        self.setup_ui()
        self.apply_theme()

        default_dir = get_default_downloads_folder()
        erome_dir = os.path.join(default_dir, "Erome")
        os.makedirs(erome_dir, exist_ok=True)
        self.download_dir = erome_dir
        self.dir_path.setText(self.download_dir)
        self.open_dir_btn.setEnabled(True)
        self.set_erome_folder_icon(erome_dir)

    def set_erome_folder_icon(self, folder_path):
        """Set custom icon for the Erome folder (Windows only)."""
        if sys.platform != 'win32':
            self.append_output("ℹ️ Custom folder icons are only supported on Windows.\n")
            return

        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
        if not os.path.exists(icon_path):
            self.append_output(f"⚠️ Icon file not found: {icon_path}\n")
            return

        try:
            import ctypes
            from ctypes import wintypes

            os.makedirs(folder_path, exist_ok=True)

            ini_path = os.path.join(folder_path, 'desktop.ini')
            with open(ini_path, 'w') as f:
                f.write('[.ShellClassInfo]\n')
                f.write(f'IconResource={os.path.abspath(icon_path)},0\n')

            FILE_ATTRIBUTE_READONLY = 0x1
            FILE_ATTRIBUTE_SYSTEM = 0x4
            ctypes.windll.kernel32.SetFileAttributesW(folder_path, FILE_ATTRIBUTE_READONLY | FILE_ATTRIBUTE_SYSTEM)
            ctypes.windll.kernel32.SetFileAttributesW(ini_path, 0x2 | 0x4)

            SHCNE_ASSOCCHANGED = 0x08000000
            SHCNF_IDLIST = 0x0000
            ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)

            self.append_output(f"✅ Folder icon set for: {folder_path}\n")

        except Exception as e:
            self.append_output(f"❌ Failed to set folder icon: {e}\n")

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(2)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(15, 15, 15, 15)

        url_group = QGroupBox("🔗 URLs (one per line)")
        url_layout = QVBoxLayout()
        self.url_entry = QPlainTextEdit()
        self.url_entry.setPlaceholderText(
            "Enter one URL per line\nExample:\nhttps://erome.com/a/example1"
        )
        self.url_entry.setMaximumHeight(150)
        url_layout.addWidget(self.url_entry)
        url_group.setLayout(url_layout)
        left_layout.addWidget(url_group)

        media_group = QGroupBox("🎞️ Media Type")
        media_layout = QHBoxLayout()
        self.checkbox_images = QCheckBox("🖼️ Images only")
        self.checkbox_videos = QCheckBox("🎥 Videos only")
        self.checkbox_images.setChecked(True)
        self.checkbox_videos.setChecked(True)
        self.checkbox_images.toggled.connect(self._ensure_one_checked)
        self.checkbox_videos.toggled.connect(self._ensure_one_checked)
        media_layout.addWidget(self.checkbox_images)
        media_layout.addWidget(self.checkbox_videos)
        media_layout.addStretch()
        media_group.setLayout(media_layout)
        left_layout.addWidget(media_group)

        dir_group = QGroupBox("📂 Download Directory")
        dir_layout = QVBoxLayout()
        self.dir_path = QLineEdit()
        self.dir_path.setReadOnly(True)
        dir_btn_layout = QHBoxLayout()
        browse_btn = QPushButton("📁 Browse...")
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

        progress_group = QGroupBox("📊 Progress")
        progress_layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel("Ready")
        self.progress_label.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)
        progress_group.setLayout(progress_layout)
        left_layout.addWidget(progress_group)

        btn_layout = QVBoxLayout()
        self.download_btn = QPushButton("🚀 Start Download")
        self.download_btn.clicked.connect(self.start_download)
        self.stop_btn = QPushButton("⏹️ Stop Download")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_download)
        self.clear_output_btn = QPushButton("🗑️ Clear Log")
        self.clear_output_btn.clicked.connect(self.clear_output)
        self.history_btn = QPushButton("📜 History")
        self.history_btn.clicked.connect(self.show_history)

        for btn in (self.download_btn, self.stop_btn, self.clear_output_btn, self.history_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn_layout.addWidget(btn)

        options_layout = QHBoxLayout()
        self.debug_checkbox = QCheckBox("🐞 Debug Mode")
        self.debug_checkbox.stateChanged.connect(self.toggle_debug)
        options_layout.addWidget(self.debug_checkbox)

        self.skip_checkbox = QCheckBox("⏭️ Skip existing files")
        self.skip_checkbox.setChecked(True)
        self.skip_checkbox.stateChanged.connect(self.toggle_skip)
        options_layout.addWidget(self.skip_checkbox)
        options_layout.addStretch()
        btn_layout.addLayout(options_layout)

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

    def _ensure_one_checked(self):
        if not self.checkbox_images.isChecked() and not self.checkbox_videos.isChecked():
            self.checkbox_images.setChecked(True)
            self.checkbox_videos.setChecked(True)

    def get_media_type(self):
        images = self.checkbox_images.isChecked()
        videos = self.checkbox_videos.isChecked()
        if images and videos:
            return 'all'
        elif images:
            return 'images'
        elif videos:
            return 'videos'
        return 'all'

    def generate_stylesheet(self):
        theme = self.THEME
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
                color: {theme['highlight']};
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
                height: 20px;
                text-align: center;
                font-weight: bold;
                color: {theme['text']};
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
        """

    def apply_theme(self):
        self.setStyleSheet(self.generate_stylesheet())
        palette = QPalette()
        theme = self.THEME
        palette.setColor(QPalette.Window, QColor(theme['bg_main']))
        palette.setColor(QPalette.WindowText, QColor(theme['text']))
        palette.setColor(QPalette.Base, QColor(theme['bg_entry']))
        palette.setColor(QPalette.AlternateBase, QColor(theme['bg_panel']))
        palette.setColor(QPalette.Text, QColor(theme['text']))
        palette.setColor(QPalette.Button, QColor(theme['bg_panel']))
        palette.setColor(QPalette.ButtonText, QColor(theme['text']))
        palette.setColor(QPalette.Highlight, QColor(theme['highlight']))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        QApplication.instance().setPalette(palette)

    def toggle_debug(self, state):
        self.debug_mode = (state == Qt.Checked)
        self.append_output(f"🐞 Debug mode {'ON' if self.debug_mode else 'OFF'}\n")

    def toggle_skip(self, state):
        self.skip_existing = (state == Qt.Checked)
        self.append_output(f"⏭️ Skip existing files {'ON' if self.skip_existing else 'OFF'}\n")

    def select_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if folder:
            erome_dir = os.path.join(folder, "Erome")
            os.makedirs(erome_dir, exist_ok=True)
            self.download_dir = erome_dir
            self.dir_path.setText(self.download_dir)
            self.open_dir_btn.setEnabled(True)
            self.append_output(f"📁 Download directory set to: {self.download_dir}\n")
            self.set_erome_folder_icon(erome_dir)

    def open_directory(self):
        if self.download_dir and os.path.exists(self.download_dir):
            if sys.platform == 'win32':
                os.startfile(self.download_dir)
            else:
                os.system(f'open "{self.download_dir}"')

    def get_urls(self):
        text = self.url_entry.toPlainText()
        return [url.strip() for url in text.splitlines() if url.strip()]

    def set_urls_text(self, url):
        self.url_entry.setPlainText(url)

    def _deduplicate_urls(self, urls):
        seen = set()
        unique = []
        duplicates = []
        for url in urls:
            if url in seen:
                duplicates.append(url)
            else:
                seen.add(url)
                unique.append(url)
        if duplicates:
            dup_msg = f"⚠️ Removed {len(duplicates)} duplicate URL(s): " + ", ".join(duplicates)
            self.append_output(dup_msg + "\n")
        return unique

    def start_download(self):
        urls = self.get_urls()
        if not urls:
            QMessageBox.warning(self, "Error", "Please enter at least one URL.")
            return

        urls = self._deduplicate_urls(urls)

        if not urls:
            QMessageBox.warning(self, "Error", "All URLs are duplicates. Nothing to download.")
            return

        if not self.download_dir:
            QMessageBox.warning(self, "Error", "No download directory selected.")
            return

        media_type = self.get_media_type()
        num_threads = 1
        parallel_limit = 10

        os.makedirs(self.download_dir, exist_ok=True)

        for url in urls:
            self.add_history(url)

        self.download_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.clear_output_btn.setEnabled(False)
        self.output_area.clear()
        self.progress_label.setText("Downloading...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.stop_flag.clear()

        self.workers = []
        self.active_workers = 0
        self.completed_workers = 0
        self.url_queue = urls.copy()

        self.signals = WorkerSignals()
        self.signals.output.connect(self.append_output)
        self.signals.error.connect(self.show_error)

        def worker_finished():
            self.active_workers -= 1
            self.completed_workers += 1
            if not self.stop_flag.is_set() and self.url_queue:
                start_next_worker()
            elif self.active_workers == 0:
                self.download_finished()

        def start_next_worker():
            if not self.url_queue or self.stop_flag.is_set():
                return
            url = self.url_queue.pop(0)
            worker = GalleryDLWorker(
                [url], self.download_dir, self.signals,
                self.stop_flag, media_type, self.debug_mode,
                num_threads, self.skip_existing
            )
            worker.signals.finished.connect(worker_finished)
            worker.start()
            self.workers.append(worker)
            self.active_workers += 1

        initial_workers = min(parallel_limit, len(self.url_queue))
        for _ in range(initial_workers):
            start_next_worker()

    def stop_download(self):
        if self.workers:
            self.stop_flag.set()
            for w in self.workers:
                w.stop()
            self.append_output("\n⏹️ Stopping all downloads...\n")
            self.progress_label.setText("Stopped")
            self.progress_bar.setVisible(False)
        else:
            self.download_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def append_output(self, text):
        self.output_area.moveCursor(self.output_area.textCursor().End)
        self.output_area.insertPlainText(text)
        self.output_area.moveCursor(self.output_area.textCursor().End)
        scrollbar = self.output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def download_finished(self):
        self.append_output("\n✅ All downloads completed.\n")
        self.download_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.clear_output_btn.setEnabled(True)
        self.progress_label.setText("✅ Completed!")
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        QMessageBox.information(self, "Complete", "All files downloaded.")

    def clear_output(self):
        self.output_area.clear()

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
        self.progress_label.setText("❌ Error")
        self.progress_bar.setVisible(False)


if __name__ == "__main__":
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EroMeDownloader.RJ.1.0.6")
        except:
            pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Splash screen
    splash_pix = QPixmap()
    base_path = os.path.dirname(os.path.abspath(__file__))
    splash_path = os.path.join(base_path, "assets", "splash.png")
    if os.path.exists(splash_path):
        splash_pix.load(splash_path)
    else:
        icon_path = os.path.join(base_path, "assets", "icon.png")
        if os.path.exists(icon_path):
            splash_pix.load(icon_path)
        else:
            splash_pix = QPixmap(400, 200)
            splash_pix.fill(QColor(13, 13, 13))
            painter = QPainter(splash_pix)
            painter.setPen(QColor(245, 124, 0))
            painter.setFont(QFont("Arial", 16))
            painter.drawText(splash_pix.rect(), Qt.AlignCenter, "EroMe Downloader\nLoading...")
            painter.end()

    splash = QSplashScreen(splash_pix)
    splash.show()
    app.processEvents()

    # Application icon
    icon_path = os.path.join(base_path, "assets", "icon.png")
    if os.path.exists(icon_path):
        icon = QIcon(icon_path)
    else:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.red)
        icon = QIcon(pixmap)

    app.setWindowIcon(icon)
    window = GalleryDLGUI()
    window.setWindowIcon(icon)

    splash.finish(window)
    window.show()
    sys.exit(app.exec_())