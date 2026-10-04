import math
import threading
import time
from datetime import datetime, timezone

import requests


_lock = threading.Lock()
_ready = threading.Event()
_location = None
_cache = None
_busy = False
_next_fetch = 0.0


def configure_weather(latitude, longitude, location_name):
    global _location, _cache, _next_fetch

    try:
        latitude = float(latitude)
        longitude = float(longitude)

        if not (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        ):
            return
    except (TypeError, ValueError):
        return

    location = (latitude, longitude, str(location_name))

    with _lock:
        if location != _location:
            _location = location
            _cache = None
            _next_fetch = 0.0


def _weather_description(code):
    descriptions = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Freezing fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Heavy drizzle",
        56: "Freezing drizzle",
        57: "Freezing drizzle",
        61: "Light rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Freezing rain",
        67: "Freezing rain",
        71: "Light snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Light rain showers",
        81: "Moderate rain showers",
        82: "Heavy rain showers",
        85: "Snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        97: "Heavy thunderstorm",
        99: "Thunderstorm with hail",
    }
    return descriptions.get(code, "Conditions unavailable")


def _fetch_weather(location):
    global _cache, _busy, _next_fetch

    latitude, longitude, location_name = location

    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,apparent_temperature,"
                    "relative_humidity_2m,weather_code,wind_speed_10m"
                ),
                "temperature_unit": "celsius",
                "wind_speed_unit": "kmh",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=(3, 8),
        )
        response.raise_for_status()
        data = response.json()
        current = data["current"]

        temperature = current["temperature_2m"]
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature)
        ):
            raise ValueError("Temperature unavailable")

        description = _weather_description(current.get("weather_code"))
        valid_at = current["time"]

        result = {
            "ok": True,
            "source": "Open-Meteo",
            "location": location_name,
            "location_source": "approximate public-IP location",
            "temperature_c": temperature,
            "feels_like_c": current.get("apparent_temperature"),
            "humidity_percent": current.get("relative_humidity_2m"),
            "wind_kmh": current.get("wind_speed_10m"),
            "description": description,
            "valid_at": valid_at,
            "timezone": data.get("timezone"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            "note": (
                "Model-based current conditions for an approximate location. "
                "May be cached for up to 15 minutes. "
                "This result does not include tomorrow's forecast."
            ),
            "display_text": (
                f"{temperature:g}°C · {description}"
                f" · as of {valid_at.replace('T', ' ')}"
                " · Open-Meteo"
            ),
        }
        delay = 15 * 60

    except Exception:
        result = {
            "ok": False,
            "error": "Weather lookup failed. Try again later.",
            "display_text": "Weather unavailable",
        }
        delay = 5 * 60

    with _lock:
        if _location == location:
            _cache = result
            _next_fetch = time.monotonic() + delay

        _busy = False
        _ready.set()


def get_current_weather(wait=False):
    global _busy

    with _lock:
        if _location is None:
            return {
                "ok": False,
                "error": "Location coordinates are not available yet.",
                "display_text": "Weather: waiting for location…",
            }

        if not _busy and time.monotonic() >= _next_fetch:
            _busy = True
            _ready.clear()

            threading.Thread(
                target=_fetch_weather,
                args=(_location,),
                daemon=True,
            ).start()

    if wait:
        _ready.wait(timeout=12)

    with _lock:
        if _busy:
            return {
                "ok": False,
                "error": "Weather is being updated. Try again shortly.",
                "display_text": "Updating weather…",
            }

        return dict(_cache or {
            "ok": False,
            "error": "Weather is not available yet.",
            "display_text": "Weather unavailable",
        })