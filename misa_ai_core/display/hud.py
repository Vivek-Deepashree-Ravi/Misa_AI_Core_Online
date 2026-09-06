from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow

WEB_DIR = Path(__file__).resolve().parent / "web"
INDEX_FILE = WEB_DIR / "index.html"


class MisaBridge(QObject):
    """Connects the supplied web UI to the Python Gemini Live runtime."""

    stateChanged = pyqtSignal(str)
    messageAdded = pyqtSignal(str, str)
    mutedChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_text_command = None
        self.on_toggle_mute = None

    @pyqtSlot(str)
    def sendText(self, text: str):
        message = str(text or "").strip()
        if message and self.on_text_command:
            self.on_text_command(message)

    @pyqtSlot()
    def toggleMute(self):
        if self.on_toggle_mute:
            self.on_toggle_mute()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Misa AI")
        self.setMinimumSize(900, 650)
        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)
        self.bridge = MisaBridge(self)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("misa", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.load(QUrl.fromLocalFile(str(INDEX_FILE)))
        QShortcut(QKeySequence("F11"), self).activated.connect(self.toggle_fullscreen)

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()


class MisaUI:
    """Runtime-compatible UI backed by the supplied HTML and CSS."""

    def __init__(self, face_path: str, size=None):
        del face_path, size
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._window = MainWindow()
        self._window.showFullScreen()
        self.root = _RootShim(self._app)
        self._muted = False
        self._state = "INITIALISING"
        self._current_file = None
        self._on_text_command = None
        self._window.bridge.on_text_command = self._handle_text_command
        self._window.bridge.on_toggle_mute = self._toggle_mute

    def _handle_text_command(self, text: str):
        if self._on_text_command:
            self._on_text_command(text)

    def _toggle_mute(self):
        self.muted = not self.muted

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, value: bool):
        value = bool(value)
        if value == self._muted:
            return
        self._muted = value
        self._window.bridge.mutedChanged.emit(value)
        self.set_state("MUTED" if value else "LISTENING")

    @property
    def current_file(self):
        return self._current_file

    @property
    def on_text_command(self):
        return self._on_text_command

    @on_text_command.setter
    def on_text_command(self, callback):
        self._on_text_command = callback

    def set_state(self, state: str):
        self._state = str(state or "").upper()
        self._window.bridge.stateChanged.emit(self._state)

    def write_log(self, text: str):
        line = str(text or "").strip()
        if line.startswith("You:"):
            self._window.bridge.messageAdded.emit("user", line[4:].strip())
        elif line.startswith("Misa:"):
            self._window.bridge.messageAdded.emit("misa", line[5:].strip())
        elif line.startswith("ERR:"):
            self._window.bridge.messageAdded.emit("misa", line)

    def wait_for_api_key(self):
        # The Docker runtime validates GEMINI_API_KEY through require_secret().
        return None

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
