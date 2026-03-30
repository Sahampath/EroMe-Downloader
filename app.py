import sys
import subprocess
import threading
import os
import json
import time

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QFileDialog, QMessageBox, QProgressBar,
    QListWidget, QDialog
)

from PyQt5.QtCore import pyqtSignal, QObject


class WorkerSignals(QObject):
    output = pyqtSignal(str)
    progress = pyqtSignal(int, int, float)
    finished = pyqtSignal()
    error = pyqtSignal(str)


class GalleryDLWorker(threading.Thread):

    def __init__(self, urls, directory, signals, stop_flag):
        super().__init__()
        self.urls = urls
        self.directory = directory
        self.signals = signals
        self.stop_flag = stop_flag
        self.process = None

    def run(self):
        try:
            for url in self.urls:

                if self.stop_flag.is_set():
                    break

                self.signals.output.emit(f"Downloading: {url}\n")

                self.process = subprocess.Popen(
                    [sys.executable, "-m", "gallery_dl", "-d", self.directory, url],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )

                total = 0
                downloaded = 0
                start_time = time.time()

                for line in self.process.stdout:

                    if self.stop_flag.is_set():
                        break

                    self.signals.output.emit(line)

                    if "Downloading" in line:
                        total += 1

                    if "Finished" in line:
                        downloaded += 1
                        self.signals.progress.emit(
                            downloaded,
                            total,
                            start_time
                        )

                self.process.wait()

            self.signals.finished.emit()

        except Exception as e:
            self.signals.error.emit(str(e))


class GalleryDLGUI(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Erome Downloader")
        self.setGeometry(300, 200, 750, 600)

        self.download_dir = ""
        self.history_file = "download_history.json"
        self.stop_flag = threading.Event()

        self.load_history()
        self.init_ui()

    def init_ui(self):

        layout = QVBoxLayout()

        # URL Input
        url_layout = QHBoxLayout()
        url_label = QLabel("Enter URL(s):")
        self.url_entry = QLineEdit()

        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_entry)

        layout.addLayout(url_layout)

        # Directory
        dir_layout = QHBoxLayout()

        self.dir_button = QPushButton("Select Download Directory")
        self.dir_button.clicked.connect(self.select_directory)

        self.dir_label = QLabel("No directory selected")

        dir_layout.addWidget(self.dir_button)
        dir_layout.addWidget(self.dir_label)

        layout.addLayout(dir_layout)

        # Buttons
        btn_layout = QHBoxLayout()

        self.download_btn = QPushButton("⬇ Download")
        self.download_btn.clicked.connect(self.start_download)

        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_download)

        self.history_btn = QPushButton("🕒 History")
        self.history_btn.clicked.connect(self.show_history)

        btn_layout.addWidget(self.download_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.history_btn)

        layout.addLayout(btn_layout)

        # Progress Bar
        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.progress_label = QLabel("")
        layout.addWidget(self.progress_label)

        # Output
        self.output = QTextEdit()
        self.output.setReadOnly(True)

        layout.addWidget(self.output)

        # Open Folder Button
        self.open_btn = QPushButton("Open Download Directory")
        self.open_btn.clicked.connect(self.open_directory)
        self.open_btn.hide()

        layout.addWidget(self.open_btn)

        self.setLayout(layout)

    def select_directory(self):

        folder = QFileDialog.getExistingDirectory(self)

        if folder:
            self.download_dir = folder
            self.dir_label.setText(folder)

    def start_download(self):

        urls = [u.strip() for u in self.url_entry.text().split(",")]

        if not urls or not self.download_dir:
            QMessageBox.warning(
                self,
                "Error",
                "Enter URL(s) and select directory"
            )
            return

        # Save URLs to history immediately
        for url in urls:
            self.add_history(url)

        self.download_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.output.clear()
        self.progress.setValue(0)
        self.stop_flag.clear()

        self.signals = WorkerSignals()

        self.signals.output.connect(self.append_output)
        self.signals.progress.connect(self.update_progress)
        self.signals.finished.connect(self.download_finished)
        self.signals.error.connect(self.show_error)

        self.worker = GalleryDLWorker(
            urls,
            self.download_dir,
            self.signals,
            self.stop_flag
        )

        self.worker.start()

    def stop_download(self):

        self.stop_flag.set()

        self.download_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        self.append_output("Download stopped by user.\n")

    def append_output(self, text):

        self.output.moveCursor(self.output.textCursor().End)
        self.output.insertPlainText(text)
        self.output.moveCursor(self.output.textCursor().End)

    def update_progress(self, downloaded, total, start):

        if total == 0:
            return

        percent = int((downloaded / total) * 100)
        self.progress.setValue(percent)

        elapsed = time.time() - start

        if downloaded > 0:
            eta = (elapsed / downloaded) * total - elapsed
            self.progress_label.setText(
                f"{downloaded}/{total} - {percent}% - ETA: {self.format_time(eta)}"
            )

    def format_time(self, seconds):

        seconds = int(seconds)

        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)

        if h:
            return f"{h}h {m}m {s}s"
        if m:
            return f"{m}m {s}s"

        return f"{s}s"

    def download_finished(self):

        self.append_output("All downloads completed.\n")

        self.download_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        self.open_btn.show()

    def open_directory(self):

        if os.path.exists(self.download_dir):
            os.startfile(self.download_dir)

    def load_history(self):

        if os.path.exists(self.history_file):
            with open(self.history_file, "r") as f:
                self.history = json.load(f)
        else:
            self.history = []

    def add_history(self, url):

        if url not in self.history:
            self.history.append(url)

            with open(self.history_file, "w") as f:
                json.dump(self.history, f, indent=2)

    def show_history(self):

        dialog = QDialog(self)
        dialog.setWindowTitle("Download History")
        dialog.resize(400, 300)

        layout = QVBoxLayout()

        list_widget = QListWidget()
        for url in self.history:
            list_widget.addItem(url)

        layout.addWidget(list_widget)

        # Buttons layout
        btn_layout = QHBoxLayout()

        redownload = QPushButton("Re-download")
        clear_history = QPushButton("Clear History")

        btn_layout.addWidget(redownload)
        btn_layout.addWidget(clear_history)

        layout.addLayout(btn_layout)

        # Re-download action
        def do_redownload():
            if list_widget.currentItem():
                self.url_entry.setText(list_widget.currentItem().text())
                dialog.close()
                self.start_download()

        redownload.clicked.connect(do_redownload)

        # Clear history action
        def do_clear_history():
            confirm = QMessageBox.question(
                self,
                "Confirm Clear",
                "Are you sure you want to clear all download history?",
                QMessageBox.Yes | QMessageBox.No
            )
            if confirm == QMessageBox.Yes:
                self.history = []
                with open(self.history_file, "w") as f:
                    json.dump(self.history, f, indent=2)
                list_widget.clear()

        clear_history.clicked.connect(do_clear_history)

        dialog.setLayout(layout)
        dialog.exec_()

    def show_error(self, msg):

        QMessageBox.critical(self, "Error", msg)


if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = GalleryDLGUI()
    window.show()

    sys.exit(app.exec_())