from __future__ import annotations

import sys
import json
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from ..tools.weather_current import (
    configure_weather,
    get_current_weather,
)

from PyQt6.QtCore import QObject, QUrl, QTimer, pyqtSignal, pyqtSlot
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
    locationReady = pyqtSignal(str, str)

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

        # Location and its associated timezone.
        self.location_label = "Finding approximate location…"
        self.location_timezone = None
        self.location_loading = True
        self.locationReady.connect(self.set_location_label)

        # The display refreshes every second.
        # Weather requests are cached separately by weather_current.py.
        self.context_timer = QTimer(self)
        self.context_timer.timeout.connect(self.update_context_display)
        self.view.loadFinished.connect(self.start_context_display)

        self.view.load(QUrl.fromLocalFile(str(INDEX_FILE)))
        QShortcut(QKeySequence("F11"), self).activated.connect(
            self.toggle_fullscreen
        )

        # Fetch location in the background without blocking the display.
        threading.Thread(
            target=self.fetch_location,
            daemon=True,
        ).start()

    def fetch_location(self):
        label = "Location unavailable"
        timezone_name = ""

        try:
            response = requests.get(
                "https://ipwho.is/",
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and data.get("success") is True:
                parts = [
                    data.get("city"),
                    data.get("region"),
                    data.get("country"),
                ]

                place = ", ".join(
                    part.strip()
                    for part in parts
                    if isinstance(part, str) and part.strip()
                )

                if place:
                    label = f"{place} · approximate via IP"

                # Reuse this lookup's coordinates for the weather service.
                configure_weather(
                    data.get("latitude"),
                    data.get("longitude"),
                    place,
                )

                timezone_data = data.get("timezone")

                if isinstance(timezone_data, dict):
                    candidate = timezone_data.get("id")

                    if isinstance(candidate, str) and candidate:
                        ZoneInfo(candidate)
                        timezone_name = candidate

        except (
            requests.RequestException,
            ValueError,
            ZoneInfoNotFoundError,
        ):
            timezone_name = ""

        try:
            self.locationReady.emit(label, timezone_name)
        except RuntimeError:
            # The window may have closed while the lookup was running.
            pass

    @pyqtSlot(str, str)
    def set_location_label(self, label, timezone_name):
        self.location_label = label
        self.location_timezone = timezone_name or None
        self.location_loading = False

    def start_context_display(self, loaded):
        if loaded:
            self.update_context_display()
            self.context_timer.start(1000)
        else:
            self.context_timer.stop()

    def update_context_display(self):
        if self.location_timezone:
            now = datetime.now(ZoneInfo(self.location_timezone))

            display_data = {
                "time": now.strftime("%H:%M:%S"),
                "date": now.strftime("%A, %d %B %Y"),
                "timezone": self.location_timezone,
                "location": self.location_label,
            }
        else:
            display_data = {
                "time": "--:--:--",
                "date": (
                    "Finding local time…"
                    if self.location_loading
                    else "Location timezone unavailable"
                ),
                "timezone": "",
                "location": self.location_label,
            }

        # Non-blocking: returns cached weather or starts a background lookup.
        weather = get_current_weather()

        display_data["weather"] = weather.get(
            "display_text",
            "Weather unavailable",
        )

        values = json.dumps(display_data)

        script = """
        (() => {
            const data = VALUES;
            let panel = document.getElementById("misa-local-info");

            if (!panel) {
                const style = document.createElement("style");
                style.id = "misa-local-info-style";

                style.textContent = `
                    #misa-local-info {
                        position: fixed;
                        top: 18px;
                        left: 50%;
                        transform: translateX(-50%);
                        z-index: 9999;

                        width: max-content;
                        max-width: calc(100vw - 40px);
                        margin: 0;
                        padding: 0;

                        background: transparent;
                        border: none;
                        border-radius: 0;
                        box-shadow: none;
                        backdrop-filter: none;

                        color: #fffdf4;
                        text-align: center;
                        font-family:
                            Inter,
                            "Segoe UI",
                            Arial,
                            sans-serif;

                        pointer-events: none;
                    }

                    #misa-local-clock {
                        margin: 0;
                        padding: 0;
                        background: transparent;

                        color: #fffdf4;
                        font-size: clamp(38px, 6vw, 80px);
                        font-weight: 300;
                        line-height: 1;
                        letter-spacing: -0.045em;
                        font-variant-numeric: tabular-nums;
                        white-space: nowrap;
                    }

                    #misa-local-date {
                        margin-top: 9px;
                        color: #eee4b7;
                        font-size: clamp(12px, 1.25vw, 16px);
                        font-weight: 400;
                        line-height: 1.4;
                        letter-spacing: 0.04em;
                    }

                    #misa-local-location {
                        margin-top: 5px;
                        color: #e8e8e3;
                        font-size: clamp(11px, 1.1vw, 14px);
                        font-weight: 400;
                        line-height: 1.4;
                        overflow-wrap: anywhere;
                    }

                    #misa-local-timezone {
                        margin-top: 4px;
                        color: #aaa99e;
                        font-size: 10px;
                        line-height: 1.3;
                        letter-spacing: 0.06em;
                    }

                    #misa-local-weather {
                        margin: 8px auto 0;
                        max-width: 600px;
                        color: #eee4b7;
                        font-size: 13px;
                        font-weight: 400;
                        line-height: 1.4;
                        white-space: normal;
                        overflow-wrap: anywhere;
                        background: transparent;
                        border: none;
                    }

                    @media (max-height: 700px) {
                        #misa-local-info {
                            top: 12px;
                        }

                        #misa-local-clock {
                            font-size: clamp(34px, 5vw, 54px);
                        }

                        #misa-local-date {
                            margin-top: 5px;
                        }
                    }
                `;

                document.head.appendChild(style);

                panel = document.createElement("section");
                panel.id = "misa-local-info";
                panel.setAttribute(
                    "aria-label",
                    "Local time, date, approximate location and weather"
                );

                const clock = document.createElement("div");
                clock.id = "misa-local-clock";

                const date = document.createElement("div");
                date.id = "misa-local-date";

                const location = document.createElement("div");
                location.id = "misa-local-location";

                const timezone = document.createElement("div");
                timezone.id = "misa-local-timezone";

                const weather = document.createElement("div");
                weather.id = "misa-local-weather";

                panel.append(clock, date, location, timezone, weather);
                document.body.appendChild(panel);
            }

            document.getElementById("misa-local-clock").textContent =
                data.time;

            document.getElementById("misa-local-date").textContent =
                data.date;

            document.getElementById("misa-local-location").textContent =
                data.location;

            document.getElementById("misa-local-timezone").textContent =
                data.timezone
                    ? data.timezone + " · 24-hour"
                    : "";

            document.getElementById("misa-local-weather").textContent =
                data.weather;
        })();
        """.replace("VALUES", values, 1)

        self.view.page().runJavaScript(script)

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

    # Provides fresh clock data to the runtime's time tool.
    def get_current_context(self, timezone_name=None):
        if timezone_name is not None:
            if not isinstance(timezone_name, str):
                return {
                    "ok": False,
                    "error": "Timezone must be an IANA timezone name.",
                }
            timezone_name = timezone_name.strip() or None

        zone_name = timezone_name or self._window.location_timezone
        location = self._window.location_label

        if not zone_name:
            return {
                "ok": False,
                "error": "Location timezone is not available yet.",
                "location": location,
            }

        try:
            now = datetime.now(ZoneInfo(zone_name))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            return {
                "ok": False,
                "error": "Invalid or unavailable timezone.",
                "location": location,
            }

        return {
            "ok": True,
            "source": "system_clock",
            "timestamp": now.isoformat(timespec="seconds"),
            "date": now.strftime("%A, %d %B %Y"),
            "time_24h": now.strftime("%H:%M:%S"),
            "time_12h": now.strftime("%I:%M:%S %p"),
            "timezone": zone_name,
            "utc_offset": now.strftime("%z"),
            "timezone_source": (
                "requested" if timezone_name else "IP location estimate"
            ),
            "location": location,
            "note": (
                "Fresh time at tool execution, already converted to the "
                "returned timezone. Do not apply another timezone offset. "
                "Location is approximate. Host clock synchronization "
                "has not been verified."
            ),
        }

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")