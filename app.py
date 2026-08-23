import sys
import subprocess
import threading
import os
import json
import re
import tempfile
import time
from pathlib import Path
from enum import Enum
from datetime import datetime
import urllib.request
import urllib.error
from html.parser import HTMLParser
from urllib.parse import urlparse

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QMessageBox,
    QProgressBar, QListWidget, QDialog, QGroupBox, QSplitter,
    QCheckBox, QPlainTextEdit, QSplashScreen, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit as QLineEditSearch,
    QSystemTrayIcon, QMenu, QStyle, QDialogButtonBox
)
from PyQt5.QtCore import pyqtSignal, QObject, Qt, QSettings, QRect, QPoint, QTimer
from PyQt5.QtGui import (
    QFont, QPalette, QColor, QIcon, QPixmap, QPainter, QTextCursor,
    QTextCharFormat, QPen, QBrush, QLinearGradient
)


# ---------- Helper Functions ----------
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


def gear_icon(size=24):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(Qt.white, 2))
    painter.setBrush(QBrush(Qt.white))
    center = QPoint(size // 2, size // 2)
    radius = size // 2 - 4
    painter.drawEllipse(center, radius, radius)
    for angle in range(0, 360, 30):
        painter.save()
        painter.translate(center)
        painter.rotate(angle)
        rect = QRect(-3, -radius + 2, 6, 6)
        painter.drawRect(rect)
        painter.restore()
    painter.end()
    return QIcon(pixmap)


def fetch_page_title(url, timeout=5):
    class TitleParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_title = False
            self.title = None

        def handle_starttag(self, tag, attrs):
            if tag.lower() == 'title':
                self.in_title = True

        def handle_endtag(self, tag):
            if tag.lower() == 'title':
                self.in_title = False

        def handle_data(self, data):
            if self.in_title:
                if self.title is None:
                    self.title = data.strip()
                else:
                    self.title += data.strip()

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            html = response.read().decode('utf-8', errors='ignore')
            parser = TitleParser()
            parser.feed(html)
            if parser.title:
                return parser.title
            else:
                return url.rstrip('/').split('/')[-1] or url
    except Exception:
        return url.rstrip('/').split('/')[-1] or url


# ========== URL NORMALISATION ==========
def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return None
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return None
    host = parsed.netloc.lower()
    if host.endswith('.erome.com') or host == 'erome.com':
        host = 'erome.com'
    normalized = f"{parsed.scheme}://{host}{parsed.path}"
    if normalized.endswith('/'):
        normalized = normalized[:-1]
    return normalized


# ---------- Settings Dialog ----------
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        media_group = QGroupBox("Media Type")
        media_layout = QVBoxLayout()
        self.checkbox_images = QCheckBox("Images only")
        self.checkbox_images.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
        self.checkbox_videos = QCheckBox("Videos only")
        self.checkbox_videos.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        media_layout.addWidget(self.checkbox_images)
        media_layout.addWidget(self.checkbox_videos)
        media_group.setLayout(media_layout)
        layout.addWidget(media_group)

        self.debug_checkbox = QCheckBox("Debug Mode")
        self.debug_checkbox.setIcon(self.style().standardIcon(QStyle.SP_DialogHelpButton))
        layout.addWidget(self.debug_checkbox)

        self.skip_checkbox = QCheckBox("Skip existing files")
        self.skip_checkbox.setIcon(self.style().standardIcon(QStyle.SP_ArrowForward))
        layout.addWidget(self.skip_checkbox)

        log_layout = QHBoxLayout()
        log_icon = self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        log_icon_label = QLabel()
        log_icon_label.setPixmap(log_icon.pixmap(16, 16))
        log_layout.addWidget(log_icon_label)
        log_layout.addWidget(QLabel("Log level:"))
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["All", "Info", "Debug", "Error"])
        log_layout.addWidget(self.log_level_combo)
        log_layout.addStretch()
        layout.addLayout(log_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #f0f0f0; }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                margin-top: 12px;
                background-color: #1a1a1a;
                color: #f0f0f0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
                background-color: #1a1a1a;
                color: #f57c00;
            }
            QCheckBox { color: #f0f0f0; spacing: 8px; }
            QCheckBox::indicator {
                width: 18px; height: 18px; border-radius: 4px;
                border: 1px solid #3a3a3a;
                background-color: #2a2a2a;
            }
            QCheckBox::indicator:checked {
                background-color: #f57c00;
                border: 1px solid #f57c00;
            }
            QComboBox {
                background-color: #2a2a2a;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #f0f0f0;
                selection-background-color: #f57c00;
            }
            QPushButton {
                background-color: #f57c00;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #ffa726; }
            QPushButton:pressed { background-color: #e65100; }
        """)

    def load_settings(self):
        settings = QSettings('settings.ini', QSettings.IniFormat)
        media_type = settings.value('media_type', 'all')
        if media_type == 'images':
            self.checkbox_images.setChecked(True)
            self.checkbox_videos.setChecked(False)
        elif media_type == 'videos':
            self.checkbox_images.setChecked(False)
            self.checkbox_videos.setChecked(True)
        else:
            self.checkbox_images.setChecked(True)
            self.checkbox_videos.setChecked(True)

        self.debug_checkbox.setChecked(settings.value('debug', False, type=bool))
        self.skip_checkbox.setChecked(settings.value('skip', True, type=bool))
        log_level = settings.value('log_level', 'All')
        index = self.log_level_combo.findText(log_level)
        if index >= 0:
            self.log_level_combo.setCurrentIndex(index)

    def save_settings(self):
        settings = QSettings('settings.ini', QSettings.IniFormat)
        if self.checkbox_images.isChecked() and self.checkbox_videos.isChecked():
            media_type = 'all'
        elif self.checkbox_images.isChecked() and not self.checkbox_videos.isChecked():
            media_type = 'images'
        elif self.checkbox_videos.isChecked() and not self.checkbox_images.isChecked():
            media_type = 'videos'
        else:
            media_type = 'all'
            self.checkbox_images.setChecked(True)
            self.checkbox_videos.setChecked(True)

        settings.setValue('media_type', media_type)
        settings.setValue('debug', self.debug_checkbox.isChecked())
        settings.setValue('skip', self.skip_checkbox.isChecked())
        settings.setValue('log_level', self.log_level_combo.currentText())

    def accept(self):
        self.save_settings()
        if self.parent:
            self.parent.load_settings()
        super().accept()


# ---------- Worker ----------
class WorkerSignals(QObject):
    output = pyqtSignal(str, str)
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)


class GalleryDLWorker(threading.Thread):
    IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp']
    VIDEO_EXTENSIONS = ['mp4', 'webm', 'mov', 'avi', 'mkv', 'm4v', 'wmv', 'flv']
    ALL_EXTENSIONS = IMAGE_EXTENSIONS + VIDEO_EXTENSIONS

    def __init__(self, urls, directory, signals, stop_flag, media_type='all',
                 debug=False, num_threads=4, skip_existing=False, resumed=False):
        super().__init__()
        self.urls = urls
        self.url = urls[0]
        self.directory = directory
        self.signals = signals
        self.stop_flag = stop_flag
        self._stop_requested = False
        self.stopped_by_user = False
        self.completed = False
        self.media_type = media_type
        self.process = None
        self.debug = debug
        self.python_cmd = get_python_command()
        self.temp_config_files = []
        self.num_threads = num_threads
        self.skip_existing = skip_existing
        self._skip_folder_printed = False
        self.resumed = resumed

    def create_config(self, url, skip_existing=False):
        config = {}
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.endswith('erome.com') or host == 'erome.com':
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
            check = subprocess.run([self.python_cmd, '-m', 'gallery_dl', '--version'],
                                   capture_output=True, text=True)
            if check.returncode != 0:
                self.signals.error.emit(f"gallery-dl not found. Install: {self.python_cmd} -m pip install gallery-dl")
                return

            pattern = r'\.(' + '|'.join(self.ALL_EXTENSIONS) + r')$'
            file_saved_pattern = re.compile(r'^([A-Za-z]:[\\/]|/).+' + pattern, re.IGNORECASE)

            for url in self.urls:
                if self._stop_requested or self.stop_flag.is_set():
                    break

                if not self.resumed:
                    self.signals.output.emit(f"\n📥 Processing: {url}\n", 'info')
                self._skip_folder_printed = False

                cmd = [self.python_cmd, "-m", "gallery_dl", "-d", self.directory]

                if self.num_threads > 1:
                    cmd.extend(["-j", str(self.num_threads)])
                    if self.debug:
                        self.signals.output.emit(f"⚙️ Using {self.num_threads} parallel threads\n", 'debug')

                config_path = self.create_config(url, self.skip_existing)
                if config_path:
                    cmd.extend(["-c", config_path])

                filter_expr = self._build_filter_expr()
                if filter_expr:
                    cmd.extend(["--filter", filter_expr])
                    if self.debug:
                        self.signals.output.emit(f"🔍 Filter: {filter_expr}\n", 'debug')

                cmd.append(url)

                if self.debug:
                    self.signals.output.emit(f"🐞 Running: {' '.join(cmd)}\n", 'debug')

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
                    if self._stop_requested or self.stop_flag.is_set():
                        self._terminate_process()
                        break

                    line_stripped = line.strip()

                    if self.skip_existing and line_stripped.startswith('#'):
                        path_part = line_stripped[1:].strip()
                        if path_part and not self._skip_folder_printed:
                            folder = os.path.basename(os.path.dirname(path_part))
                            if folder:
                                self.signals.output.emit(f"⏭️ Skipping files in folder: {folder} (already exist)\n", 'info')
                                self._skip_folder_printed = True
                        continue

                    if self.debug:
                        self.signals.output.emit(f"[RAW] {line}", 'debug')

                    level = 'info'
                    if line_stripped.startswith('ERROR') or 'error' in line_stripped.lower():
                        level = 'error'
                    elif 'skipping' in line_stripped.lower() or 'skip' in line_stripped.lower():
                        level = 'info'
                    elif 'downloaded' in line_stripped.lower():
                        level = 'info'

                    if file_saved_pattern.match(line_stripped):
                        downloaded_files += 1
                        self.signals.progress.emit(downloaded_files)
                        self.signals.output.emit(f"📄 Downloaded: {downloaded_files} files so far\n", 'info')

                    self.signals.output.emit(line, level)

                if self.process:
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self._terminate_process()
                    finally:
                        self.process = None

            if not self._stop_requested and not self.stop_flag.is_set():
                self.completed = True

            if not (self._stop_requested or self.stop_flag.is_set()):
                self.signals.output.emit("\n✅ URL finished.\n", 'info')

        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            for cfg in self.temp_config_files:
                if os.path.exists(cfg):
                    try:
                        os.remove(cfg)
                    except:
                        pass
            self.signals.finished.emit()

    def _terminate_process(self):
        if self.process:
            try:
                self.process.terminate()
                time.sleep(0.5)
                if self.process.poll() is None:
                    self.process.kill()
                if self.process.stdout:
                    self.process.stdout.close()
            except Exception:
                pass

    def stop(self):
        self._stop_requested = True
        self.stopped_by_user = True
        self._terminate_process()


# ---------- History Dialog ----------
class HistoryDialog(QDialog):
    def __init__(self, history, history_file, parent=None):
        super().__init__(parent)
        self.history = history
        self.history_file = history_file
        self.parent = parent
        self.filtered_history = history[:]
        self.setWindowTitle("Download History")
        self.setMinimumSize(700, 500)
        self.setup_ui()
        self.populate_table()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        search_layout = QHBoxLayout()
        search_label = QLabel("Filter:")
        self.search_box = QLineEditSearch()
        self.search_box.setPlaceholderText("Search URLs or titles...")
        self.search_box.textChanged.connect(self.filter_history)
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_box)
        layout.addLayout(search_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Date", "Title", "URL"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        redownload_btn = QPushButton("Re-download Selected")
        redownload_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        redownload_btn.clicked.connect(self.redownload)
        redownload_btn.setToolTip("Re-download the selected URL")

        remove_btn = QPushButton("Remove Selected")
        remove_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        remove_btn.clicked.connect(self.remove_selected)
        remove_btn.setToolTip("Remove the selected entry from history")

        clear_btn = QPushButton("Clear All")
        if hasattr(QStyle, 'SP_TrashIcon'):
            clear_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        else:
            clear_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        clear_btn.clicked.connect(self.clear_all)
        clear_btn.setToolTip("Clear all history entries")

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
            QTableWidget {
                background-color: #2d2d30;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 8px;
                font-family: monospace;
                gridline-color: #3a3a3a;
            }
            QTableWidget::item:selected { background-color: #f57c00; color: white; }
            QLineEdit {
                background-color: #2d2d30;
                color: #f0f0f0;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 6px;
            }
        """)

    def populate_table(self, history_list=None):
        if history_list is None:
            history_list = self.filtered_history
        self.table.setRowCount(len(history_list))
        for row, entry in enumerate(history_list):
            timestamp = entry.get('timestamp', 'Unknown')
            title = entry.get('title', 'Unknown')
            url = entry.get('url', '')
            if timestamp != 'Unknown':
                try:
                    dt = datetime.fromtimestamp(timestamp)
                    timestamp = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            self.table.setItem(row, 0, QTableWidgetItem(timestamp))
            self.table.setItem(row, 1, QTableWidgetItem(title))
            self.table.setItem(row, 2, QTableWidgetItem(url))
        self.table.resizeColumnsToContents()

    def filter_history(self, text):
        if not text:
            self.filtered_history = self.history[:]
        else:
            text_lower = text.lower()
            self.filtered_history = [
                e for e in self.history
                if text_lower in e.get('url', '').lower() or text_lower in e.get('title', '').lower()
            ]
        self.populate_table()

    def redownload(self):
        current_row = self.table.currentRow()
        if current_row >= 0 and current_row < len(self.filtered_history):
            url = self.filtered_history[current_row].get('url', '')
            if url:
                self.parent.set_urls_text(url)
                self.accept()
                self.parent.start_download()

    def remove_selected(self):
        current_row = self.table.currentRow()
        if current_row >= 0 and current_row < len(self.filtered_history):
            entry = self.filtered_history[current_row]
            self.history.remove(entry)
            self.filtered_history.pop(current_row)
            self.populate_table()
            self.save_history()

    def clear_all(self):
        confirm = QMessageBox.question(self, "Confirm Clear", "Clear all history?",
                                       QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.history.clear()
            self.filtered_history.clear()
            self.populate_table()
            self.save_history()

    def save_history(self):
        with open(self.history_file, "w") as f:
            json.dump(self.history, f, indent=2)


# ---------- Main GUI ----------
class DownloadState(Enum):
    IDLE = 0
    DOWNLOADING = 1
    PAUSED = 2
    STOPPED = 3


class GalleryDLGUI(QMainWindow):
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

        self.media_type = 'all'
        self.debug_mode = False
        self.skip_existing = True
        self.log_level = 'All'

        self.download_state = DownloadState.IDLE

        self.log_entries = []
        self.current_files = 0
        self._folder_message_done = False

        self.load_history()
        self.setup_ui()
        self.apply_theme()
        self.load_settings()
        self.update_ui_state()

        default_dir = get_default_downloads_folder()
        erome_dir = os.path.join(default_dir, "Erome")
        if not self._folder_message_done:
            if os.path.exists(erome_dir):
                self.append_output(f"ℹ️ Erome folder already exists at: {erome_dir}\n", 'info')
            else:
                os.makedirs(erome_dir, exist_ok=True)
                self.append_output(f"✅ Created Erome folder at: {erome_dir}\n", 'info')
            self._folder_message_done = True
        else:
            os.makedirs(erome_dir, exist_ok=True)

        self.download_dir = erome_dir
        self.dir_path.setText(self.download_dir)
        self.open_dir_btn.setEnabled(True)
        self.set_erome_folder_icon(erome_dir)

        self.tray_icon = None
        self.setup_tray_icon()

    def load_settings(self):
        settings = QSettings('settings.ini', QSettings.IniFormat)
        self.media_type = settings.value('media_type', 'all')
        self.debug_mode = settings.value('debug', False, type=bool)
        self.skip_existing = settings.value('skip', True, type=bool)
        self.log_level = settings.value('log_level', 'All')
        self.on_log_level_changed()

    def setup_tray_icon(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            icon = QIcon(self.get_icon_path())
            self.tray_icon = QSystemTrayIcon(icon, self)
            self.tray_icon.setToolTip("EroMe Downloader")
            menu = QMenu()
            show_action = menu.addAction("Show")
            show_action.triggered.connect(self.show_window)
            quit_action = menu.addAction("Quit")
            quit_action.triggered.connect(QApplication.quit)
            self.tray_icon.setContextMenu(menu)
            self.tray_icon.show()

    def show_window(self):
        self.showNormal()
        self.activateWindow()

    def get_icon_path(self):
        base_path = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_path, "assets", "icon.png")
        if os.path.exists(icon_path):
            return icon_path
        return None

    def notify_finished(self):
        if self.tray_icon:
            self.tray_icon.showMessage("Download Complete", "All files have been downloaded successfully.",
                                       QSystemTrayIcon.Information, 5000)

    # ---------- UI Setup ----------
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(2)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(15, 15, 15, 15)

        url_group = QGroupBox("URLs (one per line)")
        url_group.setToolTip("Enter one URL per line. Duplicates will be removed automatically.")
        url_layout = QVBoxLayout()
        self.url_entry = QPlainTextEdit()
        self.url_entry.setPlaceholderText(
            "Enter one URL per line\nExample:\nhttps://erome.com/a/example1"
        )
        self.url_entry.setMaximumHeight(150)
        self.url_entry.setToolTip("Paste or type URLs, each on a new line.")
        url_layout.addWidget(self.url_entry)
        url_group.setLayout(url_layout)
        left_layout.addWidget(url_group)

        dir_group = QGroupBox("Download Directory")
        dir_group.setToolTip("Folder where downloaded files will be saved.")
        dir_layout = QVBoxLayout()
        self.dir_path = QLineEdit()
        self.dir_path.setReadOnly(True)
        self.dir_path.setToolTip("Current download directory (automatically set to Downloads/Erome)")
        dir_btn_layout = QHBoxLayout()
        browse_btn = QPushButton("Browse...")
        browse_btn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse_btn.clicked.connect(self.select_directory)
        browse_btn.setToolTip("Choose a different download folder.")
        self.open_dir_btn = QPushButton("Open Folder")
        self.open_dir_btn.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        self.open_dir_btn.clicked.connect(self.open_directory)
        self.open_dir_btn.setEnabled(False)
        self.open_dir_btn.setToolTip("Open the download folder in file explorer.")
        dir_btn_layout.addWidget(browse_btn)
        dir_btn_layout.addWidget(self.open_dir_btn)
        dir_layout.addWidget(self.dir_path)
        dir_layout.addLayout(dir_btn_layout)
        dir_group.setLayout(dir_layout)
        left_layout.addWidget(dir_group)

        progress_group = QGroupBox("Progress")
        progress_group.setToolTip("Shows download progress (number of files downloaded).")
        progress_layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setToolTip("Indeterminate progress bar while downloading.")
        self.progress_label = QLabel("Ready")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setToolTip("Status and file count.")
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)
        progress_group.setLayout(progress_layout)
        left_layout.addWidget(progress_group)

        control_group = QGroupBox("Controls")
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.start_btn.clicked.connect(self.on_start_clicked)
        self.start_btn.setToolTip("Start downloading (or resume if paused).")
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.pause_btn.clicked.connect(self.pause_download)
        self.pause_btn.setToolTip("Pause the current download (resume later).")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_btn.clicked.connect(self.stop_download)
        self.stop_btn.setToolTip("Stop all downloads (cannot resume).")

        for btn in (self.start_btn, self.pause_btn, self.stop_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(36)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.pause_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addStretch()
        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)

        extra_layout = QHBoxLayout()
        self.clear_output_btn = QPushButton("Clear Log")
        self.clear_output_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        self.clear_output_btn.clicked.connect(self.clear_output)
        self.clear_output_btn.setToolTip("Clear the log output (confirmation required).")
        self.history_btn = QPushButton("History")
        self.history_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.history_btn.clicked.connect(self.show_history)
        self.history_btn.setToolTip("View download history with timestamps and search.")

        for btn in (self.clear_output_btn, self.history_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(30)
        extra_layout.addWidget(self.clear_output_btn)
        extra_layout.addWidget(self.history_btn)
        extra_layout.addStretch()

        left_layout.addLayout(extra_layout)
        left_layout.addStretch()

        bottom_layout = QHBoxLayout()
        self.settings_btn = QPushButton()
        base_path = os.path.dirname(os.path.abspath(__file__))
        settings_icon_path = os.path.join(base_path, "assets", "setico.png")
        if os.path.exists(settings_icon_path):
            self.settings_btn.setIcon(QIcon(settings_icon_path))
        else:
            self.settings_btn.setIcon(gear_icon())
        self.settings_btn.setToolTip("Open settings dialog")
        self.settings_btn.clicked.connect(self.show_settings)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setMinimumHeight(30)
        self.settings_btn.setFixedWidth(40)
        bottom_layout.addWidget(self.settings_btn)
        bottom_layout.addStretch()
        left_layout.addLayout(bottom_layout)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 15, 15, 15)
        log_group = QGroupBox("Live Log")
        log_group.setToolTip("Shows download log with color-coded messages.")
        log_layout = QVBoxLayout()
        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setFont(QFont("Courier New", 10))
        self.output_area.setToolTip("Log output. Colors: Green=Downloaded, Orange=Skipped, Red=Errors, White/Gray=Info.")
        log_layout.addWidget(self.output_area)
        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group)

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([400, 700])

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_splitter)

    def show_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec_()
        self.update_ui_state()
        self.on_log_level_changed()

    def get_media_type(self):
        return self.media_type

    def get_debug_mode(self):
        return self.debug_mode

    def get_skip_existing(self):
        return self.skip_existing

    def get_log_level(self):
        return self.log_level

    # ---------- Theme ----------
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
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {{
                border: 1px solid {theme['border']};
                border-radius: 6px;
                background-color: {theme['bg_entry']};
                color: {theme['text']};
                selection-background-color: {theme['highlight']};
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
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
                width: 18px; height: 18px; border-radius: 4px;
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
            QTableWidget {{
                background-color: {theme['bg_entry']};
                color: {theme['text']};
                border: 1px solid {theme['border']};
                border-radius: 8px;
                font-family: monospace;
                gridline-color: {theme['border']};
            }}
            QTableWidget::item:selected {{
                background-color: {theme['highlight']};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {theme['bg_panel']};
                color: {theme['text']};
                padding: 5px;
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme['bg_entry']};
                color: {theme['text']};
                selection-background-color: {theme['highlight']};
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

    def select_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if folder:
            erome_dir = os.path.join(folder, "Erome")
            if os.path.exists(erome_dir):
                self.append_output(f"ℹ️ Erome folder already exists at: {erome_dir}\n", 'info')
            else:
                os.makedirs(erome_dir, exist_ok=True)
                self.append_output(f"✅ Created Erome folder at: {erome_dir}\n", 'info')
            self.download_dir = erome_dir
            self.dir_path.setText(self.download_dir)
            self.open_dir_btn.setEnabled(True)
            self.append_output(f"Download directory set to: {self.download_dir}\n", 'info')
            self.set_erome_folder_icon(erome_dir)

    def open_directory(self):
        if self.download_dir and os.path.exists(self.download_dir):
            if sys.platform == 'win32':
                os.startfile(self.download_dir)
            else:
                os.system(f'open "{self.download_dir}"')

    def get_urls(self):
        text = self.url_entry.toPlainText()
        raw_urls = [u.strip() for u in text.splitlines() if u.strip()]
        normalized = []
        for u in raw_urls:
            norm = normalize_url(u)
            if norm:
                normalized.append(norm)
            else:
                self.append_output(f"⚠️ Invalid URL skipped: {u}\n", 'warning')
        return normalized

    def set_urls_text(self, url):
        self.url_entry.setPlainText(url)

    def _deduplicate_urls(self, urls):
        seen = set()
        unique = []
        duplicates = []
        for url in urls:
            norm = normalize_url(url)
            if norm in seen:
                duplicates.append(url)
            else:
                seen.add(norm)
                unique.append(norm)
        if duplicates:
            dup_msg = f"⚠️ Removed {len(duplicates)} duplicate URL(s): " + ", ".join(duplicates)
            self.append_output(dup_msg + "\n", 'info')
        return unique

    # ---------- Logging ----------
    def append_output(self, text, level='info'):
        self.log_entries.append((text, level))
        self._display_log_entry(text, level)

    def _display_log_entry(self, text, level):
        current_filter = self.log_level.lower()
        if current_filter != 'all' and level != current_filter:
            return

        color = None
        if 'Stopping all downloads' in text:
            color = 'red'
        elif 'Pausing...' in text:
            color = 'orange'
        elif level == 'error':
            color = 'red'
        elif level == 'debug':
            color = 'gray'
        elif '✅' in text or 'Downloaded' in text or 'finished' in text.lower():
            color = 'green'
        elif 'ℹ️' in text or '⏭️' in text or 'skip' in text.lower():
            color = 'orange'
        else:
            color = 'white'

        self.output_area.moveCursor(QTextCursor.End)
        cursor = self.output_area.textCursor()
        fmt = QTextCharFormat()
        if color == 'green':
            fmt.setForeground(QColor(0, 200, 0))
        elif color == 'orange':
            fmt.setForeground(QColor(255, 165, 0))
        elif color == 'red':
            fmt.setForeground(QColor(255, 0, 0))
        elif color == 'gray':
            fmt.setForeground(QColor(128, 128, 128))
        else:
            fmt.setForeground(QColor(240, 240, 240))
        cursor.mergeCharFormat(fmt)
        cursor.insertText(text)
        self.output_area.setTextCursor(cursor)
        self.output_area.ensureCursorVisible()

    def refresh_log_display(self):
        self.output_area.clear()
        for text, level in self.log_entries:
            self._display_log_entry(text, level)

    def clear_output(self):
        confirm = QMessageBox.question(self, "Confirm Clear", "Clear all log output?",
                                       QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.log_entries.clear()
            self.output_area.clear()

    def on_log_level_changed(self):
        self.refresh_log_display()

    # ---------- History ----------
    def show_history(self):
        dialog = HistoryDialog(self.history, self.history_file, self)
        dialog.exec_()

    def load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        if isinstance(data[0], str):
                            self.history = [{"url": url, "timestamp": int(time.time()), "title": "Unknown"} for url in data]
                        else:
                            for entry in data:
                                if 'title' not in entry:
                                    entry['title'] = 'Unknown'
                            self.history = data
                    else:
                        self.history = []
            except:
                self.history = []
        else:
            self.history = []

    def add_history(self, url, title):
        for entry in self.history:
            if entry.get('url') == url:
                entry['timestamp'] = int(time.time())
                entry['title'] = title
                break
        else:
            self.history.insert(0, {"url": url, "timestamp": int(time.time()), "title": title})
        if len(self.history) > 100:
            self.history = self.history[:100]
        with open(self.history_file, "w") as f:
            json.dump(self.history, f, indent=2)

    # ---------- UI State ----------
    def set_erome_folder_icon(self, folder_path):
        if sys.platform != 'win32':
            self.append_output("ℹ️ Custom folder icons are only supported on Windows.\n", 'info')
            return

        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
        if not os.path.exists(icon_path):
            self.append_output("ℹ️ Icon file not found, cannot set custom icon.\n", 'info')
            return

        ini_path = os.path.join(folder_path, 'desktop.ini')
        if os.path.exists(ini_path):
            try:
                with open(ini_path, 'r') as f:
                    content = f.read()
                if f'IconResource={os.path.abspath(icon_path)},0' in content:
                    self.append_output(f"ℹ️ Folder icon already set for: {folder_path}\n", 'info')
                    return
            except:
                pass

        try:
            import ctypes
            from ctypes import wintypes
            os.makedirs(folder_path, exist_ok=True)
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
            self.append_output(f"✅ Folder icon set for: {folder_path}\n", 'info')
        except Exception as e:
            self.append_output(f"❌ Failed to set folder icon: {e}\n", 'error')

    # ---------- State management ----------
    def update_ui_state(self):
        if self.download_state == DownloadState.IDLE:
            self.start_btn.setText("Start")
            self.start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.clear_output_btn.setEnabled(True)
            self.progress_label.setText("Ready")
            self.progress_bar.setVisible(False)
        elif self.download_state == DownloadState.DOWNLOADING:
            self.start_btn.setText("Start")
            self.start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.clear_output_btn.setEnabled(False)
            self.progress_label.setText(f"Downloading... {self.current_files} files")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
        elif self.download_state == DownloadState.PAUSED:
            self.start_btn.setText("Resume")
            self.start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.clear_output_btn.setEnabled(False)
            self.progress_label.setText(f"Paused ({self.current_files} files)")
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
        elif self.download_state == DownloadState.STOPPED:
            self.start_btn.setText("Start")
            self.start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.clear_output_btn.setEnabled(True)
            self.progress_label.setText("Stopped")
            self.progress_bar.setVisible(False)

    def on_start_clicked(self):
        if self.download_state == DownloadState.IDLE or self.download_state == DownloadState.STOPPED:
            self.start_download()
        elif self.download_state == DownloadState.PAUSED:
            self.resume_download()

    # ---------- Download control ----------
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

        for url in urls:
            title = fetch_page_title(url)
            self.add_history(url, title)

        self.download_state = DownloadState.DOWNLOADING
        self.stop_flag.clear()
        self.workers = []
        self.active_workers = 0
        self.completed_workers = 0
        self.url_queue = urls.copy()
        self.update_ui_state()

        self.current_files = 0

        self.signals = WorkerSignals()
        self.signals.output.connect(self.append_output)
        self.signals.error.connect(self.show_error)
        self.signals.progress.connect(self.update_progress)

        parallel_limit = 10
        num_threads = 1
        media_type = self.get_media_type()
        debug = self.get_debug_mode()
        skip = self.get_skip_existing()

        self._is_resuming = False

        def worker_finished(worker):
            self.active_workers -= 1
            self.completed_workers += 1
            if worker.stopped_by_user and not worker.completed:
                self.url_queue.insert(0, worker.url)
                self.append_output(f"↩️ Re-queued URL due to pause: {worker.url}\n", 'info')

            if self.download_state == DownloadState.DOWNLOADING and not self.stop_flag.is_set():
                if self.url_queue:
                    self._start_next_worker()
                else:
                    if self.active_workers == 0:
                        self.download_finished()
            else:
                if self.active_workers == 0:
                    if self.download_state == DownloadState.PAUSED:
                        self.append_output("All downloads paused.\n", 'info')
                        self.update_ui_state()
                    elif self.download_state == DownloadState.STOPPED:
                        self.append_output("All downloads stopped.\n", 'info')
                        self.reset_to_idle()

        def _start_next_worker(resumed=False):
            if not self.url_queue or self.stop_flag.is_set():
                return
            url = self.url_queue.pop(0)
            worker = GalleryDLWorker(
                [url], self.download_dir, self.signals,
                self.stop_flag, media_type, debug,
                num_threads, skip, resumed=resumed
            )
            worker.signals.finished.connect(lambda w=worker: worker_finished(w))
            worker.start()
            self.workers.append(worker)
            self.active_workers += 1

        self._start_next_worker = _start_next_worker

        initial_count = min(parallel_limit, len(self.url_queue))
        for _ in range(initial_count):
            _start_next_worker(resumed=False)

    def resume_download(self):
        if self.download_state != DownloadState.PAUSED:
            return
        if not self.url_queue:
            self.append_output("No remaining URLs to resume.\n", 'info')
            self.reset_to_idle()
            return

        self.download_state = DownloadState.DOWNLOADING
        self.stop_flag.clear()
        self.update_ui_state()

        self._is_resuming = True

        parallel_limit = 10
        initial_count = min(parallel_limit, len(self.url_queue))
        for _ in range(initial_count):
            self._start_next_worker(resumed=True)

    def pause_download(self):
        if self.download_state != DownloadState.DOWNLOADING:
            return
        self.download_state = DownloadState.PAUSED
        self.stop_flag.set()
        for w in self.workers:
            w.stop()
        self.append_output("Pausing... waiting for workers to finish.\n", 'info')

    def stop_download(self):
        if self.download_state not in (DownloadState.DOWNLOADING, DownloadState.PAUSED):
            return
        self.download_state = DownloadState.STOPPED
        self.stop_flag.set()
        self.url_queue.clear()
        for w in self.workers:
            w.stop()
        self.append_output("Stopping all downloads...\n", 'info')
        self.update_ui_state()

    def download_finished(self):
        self.append_output("\n✅ All downloads completed.\n", 'info')
        self.notify_finished()
        self.reset_to_idle()
        QMessageBox.information(self, "Complete", "All files downloaded.")

    def reset_to_idle(self):
        self.download_state = DownloadState.IDLE
        self.stop_flag.clear()
        self.workers.clear()
        self.active_workers = 0
        self.url_queue.clear()
        self.update_ui_state()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Ready")

    def update_progress(self, files_downloaded):
        self.current_files = files_downloaded
        if self.download_state == DownloadState.DOWNLOADING:
            self.progress_label.setText(f"Downloading... {self.current_files} files")
        elif self.download_state == DownloadState.PAUSED:
            self.progress_label.setText(f"Paused ({self.current_files} files)")

    def show_error(self, msg):
        QMessageBox.critical(self, "Error", msg)
        self.reset_to_idle()


# ========== SPLASH SCREEN WITH splash.png ==========
def create_splash_pixmap():
    """Create a splash screen using splash.png as background (native resolution),
    with progress bar overlay."""
    base_path = os.path.dirname(os.path.abspath(__file__))
    splash_path = os.path.join(base_path, "assets", "splash.png")

    # Determine splash size: use image size if exists, else fallback 600x400
    if os.path.exists(splash_path):
        bg = QPixmap(splash_path)
        width, height = bg.width(), bg.height()
    else:
        width, height = 600, 400
        bg = None

    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    if bg is not None:
        # Draw at native resolution (no scaling)
        painter.drawPixmap(0, 0, bg)
    else:
        # Fallback gradient
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0, QColor(30, 30, 30))
        gradient.setColorAt(1, QColor(10, 10, 10))
        painter.fillRect(0, 0, width, height, gradient)

    # Subtle border
    painter.setPen(QPen(QColor(60, 60, 60), 1))
    painter.drawRect(0, 0, width-1, height-1)

    # Progress bar dimensions relative to image size
    bar_w = int(width * 0.7)          # 70% of width
    bar_h = 24
    bar_x = (width - bar_w) // 2
    bar_y = height - 130              # 130px from bottom <------------

    # Draw empty bar background
    painter.setPen(QPen(QColor(60, 60, 60), 1))
    painter.setBrush(QBrush(QColor(40, 40, 40)))
    painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 4, 4)

    painter.end()

    splash_data = {
        'pixmap': pixmap,
        'bar_rect': QRect(bar_x, bar_y, bar_w, bar_h),
        'status_rect': QRect(0, height - 100, width, 25),   # status text area <------------
        'progress': 0
    }
    return splash_data

def update_splash(splash, splash_data, progress, status_text):
    """Update the splash pixmap with progress and status, then repaint."""
    pixmap = splash_data['pixmap']
    bar_rect = splash_data['bar_rect']
    status_rect = splash_data['status_rect']

    # Copy original pixmap (the background image is already painted)
    new_pix = pixmap.copy()
    painter = QPainter(new_pix)
    painter.setRenderHint(QPainter.Antialiasing)

    # Update progress bar fill
    fill_width = int(bar_rect.width() * (progress / 100.0))
    if fill_width > 0:
        gradient = QLinearGradient(bar_rect.x(), 0, bar_rect.x() + bar_rect.width(), 0)
        gradient.setColorAt(0, QColor(239, 108, 0))
        gradient.setColorAt(1, QColor(255, 171, 0))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bar_rect.x(), bar_rect.y(), fill_width, bar_rect.height(), 4, 4)

    # Update status text
    painter.setPen(QColor(200, 200, 200))
    painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
    painter.drawText(status_rect, Qt.AlignCenter, status_text)

    painter.end()

    splash.setPixmap(new_pix)
    splash.show()


# ---------- Main ----------
if __name__ == "__main__":
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EroMeDownloader.RJ.1.0.7")
        except:
            pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Create splash
    splash_data = create_splash_pixmap()
    splash = QSplashScreen(splash_data['pixmap'])
    splash.show()
    app.processEvents()

    # Loading steps (milestones for status text only)
    load_steps = [
        (10, "Loading secure core modules..."),
        (20, "Initializing high-performance UI..."),
        (30, "Loading optimized user configurations..."),
        (40, "Validating network security protocols..."),
        (50, "Performing full dependency integrity check..."),
        (60, "Activating multi-threaded download engine..."),
        (70, "Establishing secure API handshake..."),
        (80, "Allocating high-speed disk buffers..."),
        (90, "Warming up concurrent download queues..."),
        (100, "Downloader is Ready!")
    ]

    # This list will keep a reference to the main window so it doesn't get garbage-collected
    window_holder = []

    def show_main_window():
        """Create and show the main window, finishing the splash."""
        try:
            base_path = os.path.dirname(os.path.abspath(__file__))
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
            window_holder.append(window)  # Keep alive

            splash.finish(window)
            window.show()
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Failed to start application:\n{e}")
            sys.exit(1)

    # Smooth progress update
    progress = [0]          # mutable counter
    total_steps = 100
    interval_ms = 100        # update every 100ms → total 10 seconds

    def get_status_text(prog):
        """Return the status text for the last milestone reached."""
        text = load_steps[0][1]   # fallback
        for milestone, msg in reversed(load_steps):
            if prog >= milestone:
                text = msg
                break
        return text

    timer = QTimer()

    def advance():
        progress[0] += 1
        if progress[0] > total_steps:
            timer.stop()
            show_main_window()
            return
        status = get_status_text(progress[0])
        update_splash(splash, splash_data, progress[0], status)

    timer.timeout.connect(advance)
    timer.start(interval_ms)

    # Set initial status
    update_splash(splash, splash_data, 0, load_steps[0][1])

    sys.exit(app.exec_())