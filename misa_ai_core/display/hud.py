"""Misa's Qt HUD. Place hud.css/hud.js beside web/index.html.

Requires the upgraded tools/weather_current.py supplied with this bundle.
Weather alerts appear on screen. For speech, assign ui.on_weather_alert to
an enqueue-only runtime callback; the callback receives the weather event dict.
Do not call Gemini's async session directly from the Qt thread.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow

from ..tools.weather_current import (
    configure_weather,
    get_current_weather,
    get_weather_forecast,
    start_weather_monitor,
)

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent / 'web'
INDEX_FILE = WEB_DIR / 'index.html'


class MisaBridge(QObject):
    """Keep the existing HTML/runtime bridge contract."""

    stateChanged = pyqtSignal(str)
    messageAdded = pyqtSignal(str, str)
    mutedChanged = pyqtSignal(bool)
    # Queued delivery keeps runtime-thread callbacks off Qt widgets.
    weatherAlert = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_text_command = None
        self.on_toggle_mute = None

    @pyqtSlot(str)
    def sendText(self, text: str):
        message = str(text or '').strip()
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
        self.setWindowTitle('Misa AI')
        self.setMinimumSize(480, 360)
        self._closed = False
        self._page_ready = False
        self._weather = {}
        self._weather_checked_at = -float('inf')
        self._weather_events = Queue(maxsize=100)
        self._latest_alert = None
        self._alert_until = 0.0
        self._stop_weather = None
        # Fail clearly when a companion file wasn't copied.
        self._hud_css = (WEB_DIR / 'hud.css').read_text(encoding='utf-8')
        self._hud_js = (WEB_DIR / 'hud.js').read_text(encoding='utf-8')

        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)
        self.bridge = MisaBridge(self)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject('misa', self.bridge)
        self.view.page().setWebChannel(self.channel)

        self.location_label = 'Finding approximate location…'
        self.location_timezone = None
        self.location_loading = True
        self.locationReady.connect(self.set_location_label)
        self.context_timer = QTimer(self)
        self.context_timer.timeout.connect(self.update_context_display)
        self.view.loadStarted.connect(self._page_loading)
        self.view.loadFinished.connect(self.start_context_display)
        self.view.load(QUrl.fromLocalFile(str(INDEX_FILE)))
        self.fullscreen_shortcut = QShortcut(QKeySequence('F11'), self)
        self.fullscreen_shortcut.activated.connect(self.toggle_fullscreen)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)
        threading.Thread(target=self.fetch_location, name='misa-location', daemon=True).start()

    def fetch_location(self):
        label, timezone_name = 'Location unavailable', ''
        try:
            response = requests.get('https://ipwho.is/', timeout=(3, 8))
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get('success') is True:
                parts = (data.get('city'), data.get('region'), data.get('country'))
                place = ', '.join(p.strip() for p in parts if isinstance(p, str) and p.strip())
                if place:
                    label = f'{place} · approximate via IP'
                configure_weather(data.get('latitude'), data.get('longitude'),
                                  place or 'Approximate location')
                zone = data.get('timezone')
                candidate = zone.get('id') if isinstance(zone, dict) else None
                if isinstance(candidate, str) and candidate:
                    ZoneInfo(candidate)
                    timezone_name = candidate
        except (requests.RequestException, ValueError, ZoneInfoNotFoundError):
            log.warning('Location/timezone lookup failed', exc_info=True)
        if not self._closed:
            try:
                self.locationReady.emit(label, timezone_name)
            except RuntimeError:
                pass  # Qt object was destroyed during the network call.

    @pyqtSlot(str, str)
    def set_location_label(self, label, timezone_name):
        self.location_label = label
        self.location_timezone = timezone_name or None
        self.location_loading = False
        self._weather_checked_at = -float('inf')

    def _page_loading(self):
        self._page_ready = False

    def start_context_display(self, loaded):
        if not loaded or self._closed:
            self._page_ready = False
            self.context_timer.stop()
            return
        # Asset injection avoids changing the user's existing index.html/app.js.
        script = (
            '(() => { let s = document.getElementById("misa-hud-style");'
            'if (!s) { s = document.createElement("style");'
            's.id = "misa-hud-style"; document.head.appendChild(s); }'
            f's.textContent = {json.dumps(self._hud_css)}; }})();\n'
            + self._hud_js
        )
        self.view.page().runJavaScript(script, self._hud_loaded)

    def _hud_loaded(self, _result):
        if self._closed:
            return
        self._page_ready = True
        if self._stop_weather is None:
            self._stop_weather = start_weather_monitor(self._weather_events.put_nowait)
        self.update_context_display()
        self.context_timer.start(1000)

    def _drain_weather_events(self):
        # Only the GUI thread consumes these messages or touches the web view.
        for _ in range(20):
            try:
                event = self._weather_events.get_nowait()
            except Empty:
                break
            self._latest_alert = event
            self._alert_until = time.monotonic() + 120
            self.bridge.messageAdded.emit('misa', event.get('message', 'Weather update'))
            self.bridge.weatherAlert.emit(event)

    def update_context_display(self):
        if not self._page_ready or self._closed:
            return
        self._drain_weather_events()
        if self.location_timezone:
            now = datetime.now(ZoneInfo(self.location_timezone))
            clock = {'time': now.strftime('%H:%M:%S'),
                     'date': now.strftime('%A, %d %B %Y'),
                     'timezone': self.location_timezone}
        else:
            clock = {'time': '--:--:--', 'timezone': '',
                     'date': 'Finding local time…' if self.location_loading
                             else 'Location timezone unavailable'}
        # Clock ticks each second; weather payload is only copied every 15 seconds.
        tick = time.monotonic()
        weather_changed = tick - self._weather_checked_at >= 15
        if weather_changed:
            self._weather = get_current_weather(wait=False)
            self._weather_checked_at = tick
        data = {**clock, 'location': self.location_label,
                'alert': self._latest_alert if tick < self._alert_until else None}
        if weather_changed:
            w = self._weather
            data['weather'] = {k: w.get(k) for k in (
                'ok', 'display_text', 'temperature_c', 'description', 'feels_like_c',
                'humidity_percent', 'wind_kmh', 'daily', 'advice', 'advice_period',
                'stale', 'updating', 'retrieved_at', 'timezone', 'valid_at', 'note')}
        self.view.page().runJavaScript(
            f'window.misaHud && window.misaHud.update({json.dumps(data)});'
        )

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def shutdown(self):
        self._closed = True
        self.context_timer.stop()
        if self._stop_weather is not None:
            self._stop_weather.set()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()


class MisaUI:
    """Runtime-compatible UI. Speech remains the runtime's responsibility."""

    def __init__(self, face_path: str, size=None):
        del face_path, size
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._muted = False
        self._state = 'INITIALISING'
        self._current_file = None
        self._on_text_command = None
        self.on_weather_alert = None
        self._window = MainWindow()
        self.root = _RootShim(self._app)
        self._window.bridge.on_text_command = self._handle_text_command
        self._window.bridge.on_toggle_mute = self._toggle_mute
        self._window.bridge.weatherAlert.connect(self._handle_weather_alert)
        self._window.showFullScreen()

    def _handle_text_command(self, text: str):
        if self._on_text_command:
            self._on_text_command(text)

    def _handle_weather_alert(self, event: dict):
        # Do not interrupt a conversation or speak while muted. Visual alerts
        # still appear. Skipped speech is not replayed later as stale advice.
        if self.muted or self._state != 'LISTENING':
            return
        if callable(self.on_weather_alert):
            try:
                self.on_weather_alert(dict(event))
            except Exception:
                log.exception('Runtime weather callback failed')

    def _toggle_mute(self):
        self.muted = not self.muted

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, value: bool):
        value = bool(value)
        if value != self._muted:
            self._muted = value
            self._window.bridge.mutedChanged.emit(value)
            self.set_state('MUTED' if value else 'LISTENING')

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
        self._state = str(state or '').upper()
        self._window.bridge.stateChanged.emit(self._state)

    def write_log(self, text: str):
        line = str(text or '').strip()
        if line.startswith('You:'):
            self._window.bridge.messageAdded.emit('user', line[4:].strip())
        elif line.startswith('Misa:'):
            self._window.bridge.messageAdded.emit('misa', line[5:].strip())
        elif line.startswith('ERR:'):
            self._window.bridge.messageAdded.emit('misa', line)

    def wait_for_api_key(self):
        return None  # The existing runtime validates GEMINI_API_KEY.

    def get_current_context(self, timezone_name=None):
        if timezone_name is not None:
            if not isinstance(timezone_name, str):
                return {'ok': False, 'error': 'Timezone must be an IANA timezone name.'}
            timezone_name = timezone_name.strip() or None
        zone_name = timezone_name or self._window.location_timezone
        location = self._window.location_label
        if not zone_name:
            return {'ok': False, 'error': 'Location timezone is not available yet.',
                    'location': location}
        try:
            now = datetime.now(ZoneInfo(zone_name))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            return {'ok': False, 'error': 'Invalid or unavailable timezone.', 'location': location}
        return {
            'ok': True, 'source': 'system_clock',
            'timestamp': now.isoformat(timespec='seconds'),
            'date': now.strftime('%A, %d %B %Y'), 'time_24h': now.strftime('%H:%M:%S'),
            'time_12h': now.strftime('%I:%M:%S %p'), 'timezone': zone_name,
            'utc_offset': now.strftime('%z'),
            'timezone_source': 'requested' if timezone_name else 'IP location estimate',
            'location': location,
            'note': ('Fresh time at tool execution, already converted to the returned timezone. '
                     'Do not apply another timezone offset. Location is approximate. '
                     'Host clock synchronization has not been verified.'),
        }

    def get_weather_forecast(self, days=7):
        """Nonblocking accessor. Runtime must still register its Gemini tool."""
        return get_weather_forecast(days=days, wait=False)

    def start_speaking(self):
        self.set_state('SPEAKING')

    def stop_speaking(self):
        if not self.muted:
            self.set_state('LISTENING')