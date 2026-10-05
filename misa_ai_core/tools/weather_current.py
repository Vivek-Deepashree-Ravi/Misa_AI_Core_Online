"""Seven-day weather for Misa (Python 3.9+, requests, system timezone data).

Replace the module containing configure_weather/get_current_weather with this file.
Existing calls still work; get_current_weather now also returns daily/hourly/advice.
Register get_weather_forecast with Misa's tool dispatcher for week/tomorrow queries.

Proactive integration (start ONCE during application startup):
    from queue import Queue
    weather_events = Queue()
    stop_weather = start_weather_monitor(weather_events.put)
    # In your existing UI/voice event loop, consume weather_events and speak/display
    # event['message']. Queue callbacks run on a background thread, not the UI thread.
    # Shutdown: stop_weather.set()

No notification is delivered until your application consumes these events.
The process must stay running. Dedupe is in memory and resets on restart.
Forecast-derived heads-ups are not official emergency alerts or radar nowcasts.
"""
import copy
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)
REFRESH_SECONDS = 15 * 60
RETRY_SECONDS = 60
RAIN_CHANCE = 50
JACKET_FEELS_LIKE_C = 18
UV_THRESHOLD = 3
GUST_THRESHOLD_KMH = 40
_lock = threading.Lock()
_location = None
_generation = 0
_cache = None
_next_fetch = 0.0
_inflight = None
_last_error = None
_sent = {}
_baseline = {}
_monitor_stop = None

CURRENT = ('temperature_2m', 'apparent_temperature', 'relative_humidity_2m',
           'weather_code', 'wind_speed_10m')
HOURLY = ('temperature_2m', 'apparent_temperature', 'precipitation_probability',
          'precipitation', 'weather_code', 'wind_speed_10m', 'wind_gusts_10m',
          'uv_index')
DAILY = ('weather_code', 'temperature_2m_max', 'temperature_2m_min',
         'apparent_temperature_min', 'precipitation_probability_max',
         'precipitation_sum', 'uv_index_max', 'wind_gusts_10m_max')
DESCRIPTIONS = {
    0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
    45: 'Fog', 48: 'Freezing fog', 51: 'Light drizzle', 53: 'Moderate drizzle',
    55: 'Heavy drizzle', 56: 'Light freezing drizzle', 57: 'Heavy freezing drizzle',
    61: 'Light rain', 63: 'Moderate rain', 65: 'Heavy rain',
    66: 'Light freezing rain', 67: 'Heavy freezing rain', 71: 'Light snow',
    73: 'Moderate snow', 75: 'Heavy snow', 77: 'Snow grains',
    80: 'Light rain showers', 81: 'Moderate rain showers', 82: 'Heavy rain showers',
    85: 'Light snow showers', 86: 'Heavy snow showers',
    95: 'Thunderstorm', 96: 'Thunderstorm with hail', 99: 'Thunderstorm with heavy hail',
}


def _number(value):
    return value if (not isinstance(value, bool) and isinstance(value, (int, float))
                     and math.isfinite(value)) else None


def _weather_description(code):
    return DESCRIPTIONS.get(code, 'Conditions unavailable')


def configure_weather(latitude, longitude, location_name,
                      location_source='approximate public-IP location'):
    """Prefer explicit home/GPS coordinates; IP geolocation may be far away."""
    global _location, _generation, _cache, _next_fetch, _inflight, _last_error
    try:
        latitude, longitude = float(latitude), float(longitude)
        if not (math.isfinite(latitude) and math.isfinite(longitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            return False
    except (TypeError, ValueError, OverflowError):
        return False
    location = (latitude, longitude, str(location_name), str(location_source))
    with _lock:
        if location != _location:
            _location = location
            _generation += 1
            _cache, _last_error, _next_fetch = None, None, 0.0
            if _inflight:
                _inflight.set()  # Wake old-location waiters; discard old response.
            _inflight = None
            _sent.clear()
            _baseline.clear()
    return True


def _rows(block, fields):
    times = block['time']
    if not isinstance(times, list) or not times:
        raise ValueError('Missing forecast times')
    for field in fields:
        if not isinstance(block.get(field), list) or len(block[field]) != len(times):
            raise ValueError('Incomplete forecast arrays')
    rows = []
    for i, stamp in enumerate(times):
        datetime.fromisoformat(stamp)  # Reject malformed timestamps.
        row = {'time': stamp, **{f: _number(block[f][i]) for f in fields}}
        row['description'] = _weather_description(row.get('weather_code'))
        rows.append(row)
    return rows


def _advice(rows, daily=False):
    def values(field):
        return [r[field] for r in rows if _number(r.get(field)) is not None]
    def high(field, threshold):
        return any(v >= threshold for v in values(field))
    rain = 'precipitation_probability_max' if daily else 'precipitation_probability'
    precip = 'precipitation_sum' if daily else 'precipitation'
    feels = 'apparent_temperature_min' if daily else 'apparent_temperature'
    gust = 'wind_gusts_10m_max' if daily else 'wind_gusts_10m'
    uv = 'uv_index_max' if daily else 'uv_index'
    tips = []
    storm = any(r.get('weather_code') in (95, 96, 99) for r in rows)
    windy = high(gust, GUST_THRESHOLD_KMH)
    if high(rain, RAIN_CHANCE) or high(precip, 0.2):
        tips.append('Precipitation is forecast: take a raincoat.' if windy or storm
                    else 'Precipitation is possible: carry an umbrella.')
    if high(uv, UV_THRESHOLD):
        tips.append('Use sunscreen and sun protection if you go outside in daylight.')
    if any(v <= JACKET_FEELS_LIKE_C for v in values(feels)):
        tips.append('Carry a jacket; it may feel cool during this period.')
    if windy:
        tips.append('Strong gusts are forecast; avoid exposed outdoor areas.')
    if storm:
        tips.append('Thunderstorms are forecast; plan to stay indoors while they pass.')
    return tips


def _fetch_weather(location, generation, ready):
    global _cache, _next_fetch, _inflight, _last_error
    try:
        response = requests.get('https://api.open-meteo.com/v1/forecast', params={
            'latitude': location[0], 'longitude': location[1],
            'current': ','.join(CURRENT), 'hourly': ','.join(HOURLY),
            'daily': ','.join(DAILY), 'temperature_unit': 'celsius',
            'wind_speed_unit': 'kmh', 'precipitation_unit': 'mm',
            'timezone': 'auto', 'forecast_days': 7,
        }, timeout=(3, 8))
        response.raise_for_status()
        data = response.json()
        c = data['current']
        temperature = _number(c['temperature_2m'])
        if temperature is None:
            raise ValueError('Temperature unavailable')
        datetime.fromisoformat(c['time'])
        ZoneInfo(data['timezone'])
        daily = _rows(data['daily'], DAILY)
        hourly = _rows(data['hourly'], HOURLY)
        if len(daily) != 7:
            raise ValueError('Incomplete seven-day forecast')
        for day in daily:
            day['advice'] = _advice([day], daily=True)
        result = {
            'ok': True, 'source': 'Open-Meteo', 'location': location[2],
            'location_source': location[3], 'temperature_c': temperature,
            'feels_like_c': _number(c.get('apparent_temperature')),
            'humidity_percent': _number(c.get('relative_humidity_2m')),
            'wind_kmh': _number(c.get('wind_speed_10m')),
            'description': _weather_description(c.get('weather_code')),
            'valid_at': c['time'], 'timezone': data['timezone'],
            'retrieved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'daily': daily, 'hourly': hourly, '_generation': generation,
            'note': ('Model-based forecast; seven days includes today. Refreshed at most '
                     'every 15 minutes. Forecasts may change; not official weather alerts.'),
            'display_text': f"{temperature:g}°C · {_weather_description(c.get('weather_code'))}"
                            f" · as of {c['time'].replace('T', ' ')} · Open-Meteo",
        }
        error = None
    except Exception:
        log.warning('Weather refresh failed', exc_info=True)
        result, error = None, 'Weather lookup failed. Retrying later.'
    with _lock:
        if generation == _generation:
            if result is not None:
                _cache = result
            _last_error = error
            _next_fetch = time.monotonic() + (RETRY_SECONDS if error else REFRESH_SECONDS)
            _inflight = None
        ready.set()


def _upcoming(data, hours):
    now = datetime.now(ZoneInfo(data['timezone']))
    # Include the current hourly interval; never include earlier intervals.
    start = now.replace(minute=0, second=0, microsecond=0)
    return [r for r in data['hourly'] if start <= datetime.fromisoformat(
        r['time']).replace(tzinfo=now.tzinfo) <= now + timedelta(hours=hours)]


def get_current_weather(wait=False):
    """Backward-compatible current fields plus 7 daily summaries and hourly data."""
    global _inflight
    with _lock:
        if _location is None:
            return {'ok': False, 'error': 'Location coordinates are not available yet.',
                    'display_text': 'Weather: waiting for location…'}
        if _inflight is None and time.monotonic() >= _next_fetch:
            ready = threading.Event()
            _inflight = ready
            try:
                threading.Thread(target=_fetch_weather,
                                 args=(_location, _generation, ready), daemon=True).start()
            except Exception:
                _inflight = None
                ready.set()
                raise
        ready = _inflight
    if wait and ready is not None:
        ready.wait(timeout=12)
    with _lock:
        if _cache is None:
            return {'ok': False, 'error': _last_error or 'Weather is being updated.',
                    'display_text': 'Weather unavailable' if _last_error else 'Updating weather…'}
        result = copy.deepcopy(_cache)
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(result['retrieved_at'])).total_seconds()
        result['stale'] = bool(_last_error) or age >= REFRESH_SECONDS
        result['updating'] = _inflight is not None
        if _last_error:
            result['error'] = _last_error
        if result['stale']:
            result['display_text'] += ' · cached/stale'
    result['advice_period'] = 'Current hour through the next 12 hours (local time)'
    result['advice'] = _advice(_upcoming(result, 12)) if not result['stale'] else []
    return result


def get_weather_forecast(days=7, wait=True):
    """days=1 means today, days=2 includes tomorrow, days=7 includes next six days."""
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 7:
        return {'ok': False, 'error': 'days must be an integer from 1 to 7'}
    result = get_current_weather(wait=wait)
    if result.get('ok'):
        result['daily'] = result['daily'][:days]
        dates = {d['time'] for d in result['daily']}
        result['hourly'] = [h for h in result['hourly'] if h['time'][:10] in dates]
    return result


def check_weather_alerts():
    """Return deduplicated heads-ups for the next 3 hours. Poll every 60 seconds.

    First poll reports impending conditions; later polls also compare revisions
    for the SAME forecast hour. Per-type cooldown is 3 hours; higher severity
    bypasses cooldown. Stale/failed fetches never generate new alerts.
    """
    data = get_current_weather(wait=True)
    if not data.get('ok') or data.get('stale'):
        return []
    rows = _upcoming(data, 3)
    candidates = {}
    def add(kind, severity, row, message):
        if kind not in candidates or candidates[kind]['severity'] < severity:
            candidates[kind] = {'kind': kind, 'severity': severity,
                                'forecast_time': row['time'], 'message': message}
    with _lock:
        if data['_generation'] != _generation:
            return []
        for row in rows:
            stamp = row['time']
            label = f"{stamp.replace('T', ' ')} ({data['timezone']})"
            p, gust, feels = (row.get(k) for k in ('precipitation_probability',
                                                  'wind_gusts_10m', 'apparent_temperature'))
            if row.get('weather_code') in (95, 96, 99):
                add('storm', 2, row, f'Thunderstorms forecast around {label}. Plan to stay indoors.')
            if p is not None and p >= RAIN_CHANCE:
                add('rain', 2 if p >= 80 else 1, row,
                    f'Precipitation chance is {p:g}% around {label}. Take rain protection.')
            if gust is not None and gust >= GUST_THRESHOLD_KMH:
                add('wind', 2 if gust >= 60 else 1, row,
                    f'Gusts up to {gust:g} km/h forecast around {label}. Avoid exposed areas.')
            if feels is not None and feels <= JACKET_FEELS_LIKE_C:
                add('cold', 2 if feels <= 10 else 1, row,
                    f'It may feel like {feels:g}°C around {label}. Carry a jacket.')
            if row.get('uv_index') is not None and row['uv_index'] >= UV_THRESHOLD:
                add('uv', 1, row, f'Elevated UV forecast around {label}. Use sun protection outside.')
            previous = _baseline.get(stamp)
            if previous:
                for field, delta, unit in [('temperature_2m', 5, '°C'),
                                            ('precipitation_probability', 30, ' percentage points'),
                                            ('wind_gusts_10m', 20, ' km/h')]:
                    old, new = previous.get(field), row.get(field)
                    if old is not None and new is not None and abs(new - old) >= delta:
                        add('revision_' + field, 1, row,
                            f'Forecast changed for {label}: {field.replace("_", " ")} '
                            f'changed by {new - old:+g}{unit}. Check the updated forecast.')
        # Store all future hours so a later near-term window has a baseline.
        if _baseline.get('_retrieved_at') != data['retrieved_at']:
            _baseline.clear()
            _baseline.update({h['time']: h for h in data['hourly']})
            _baseline['_retrieved_at'] = data['retrieved_at']
        now = time.monotonic()
        alerts = []
        for kind, event in candidates.items():
            last_time, last_severity = _sent.get(kind, (-float('inf'), 0))
            if now - last_time >= 3 * 3600 or event['severity'] > last_severity:
                event.update(location=data['location'], source='Open-Meteo',
                             retrieved_at=data['retrieved_at'])
                event['message'] = f"Weather for {data['location']}: " + event['message']
                alerts.append(event)
                _sent[kind] = (now, event['severity'])
        return alerts


def start_weather_monitor(on_alert, interval_seconds=60):
    """Start once; callback receives a dict on the worker thread. Return stop Event.

    Use a queue.put callback. Callback failures are logged; that event is not
    retried until its cooldown expires. This is not a durable delivery queue.
    """
    global _monitor_stop
    if not callable(on_alert):
        raise TypeError('on_alert must be callable')
    if _number(interval_seconds) is None or interval_seconds < 30:
        raise ValueError('interval_seconds must be at least 30')
    with _lock:
        if _monitor_stop is not None and not _monitor_stop.is_set():
            return _monitor_stop
        stop = threading.Event()
        _monitor_stop = stop
    def run():
        while not stop.is_set():
            try:
                for alert in check_weather_alerts():
                    if stop.is_set():
                        break
                    try:
                        on_alert(alert)
                    except Exception:
                        log.exception('Weather notification callback failed')
            except Exception:
                log.exception('Weather monitor failed')
            stop.wait(interval_seconds)
    threading.Thread(target=run, name='misa-weather-monitor', daemon=True).start()
    return stop