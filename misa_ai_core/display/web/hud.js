/* Injected by hud.py after the existing page loads. No HTML edits required. */
(() => {
    'use strict';
    if (window.misaHud) return;
    document.getElementById('misa-local-info')?.remove();
    const make = (tag, className, text) => {
        const el = document.createElement(tag);
        if (className) el.className = className;
        if (text !== undefined) el.textContent = text;
        return el;
    };
    const finite = value => typeof value === 'number' && Number.isFinite(value);
    const number = (value, unit = '') => finite(value) ? `${Math.round(value)}${unit}` : '—';
    function weatherIcon(code, description = '') {
        const text = String(description || '').toLowerCase();
        let kind = 'unknown';
        if ([95, 96, 99].includes(code) || /thunder/.test(text)) kind = 'storm';
        else if ([71, 73, 75, 77, 85, 86].includes(code) || /snow/.test(text)) kind = 'snow';
        else if ([51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82].includes(code) || /rain|drizzle/.test(text)) kind = 'rain';
        else if ([45, 48].includes(code) || /fog/.test(text)) kind = 'fog';
        else if (code === 2 || /partly/.test(text)) kind = 'partly';
        else if (code === 3 || /overcast|cloud/.test(text)) kind = 'cloud';
        else if ([0, 1].includes(code) || /clear|sun/.test(text)) kind = 'sun';
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('viewBox', '0 0 64 64');
        svg.setAttribute('class', 'hud-weather-icon');
        svg.setAttribute('aria-hidden', 'true');
        const shape = (tag, attrs) => {
            const el = document.createElementNS(ns, tag);
            Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
            svg.append(el);
        };
        if (kind === 'sun' || kind === 'partly') {
            shape('circle', {cx: 29, cy: 27, r: 12, fill: '#ffd36a'});
            shape('path', {d: 'M29 5v5 M29 44v5 M7 27h5 M46 27h5 M13 11l4 4 M41 39l4 4 M13 43l4-4 M41 15l4-4', stroke: '#ffd36a', 'stroke-width': 3, 'stroke-linecap': 'round', fill: 'none'});
        }
        if (['partly', 'cloud', 'rain', 'snow', 'storm', 'fog'].includes(kind)) {
            shape('path', {d: 'M17 43a10 10 0 0 1-1-20 15 15 0 0 1 28-1 11 11 0 0 1 3 21Z', fill: '#c4d5ea', stroke: '#e1ebf8', 'stroke-width': 1.5});
        }
        if (kind === 'rain') shape('path', {d: 'M21 49l-3 7 M33 49l-3 7 M45 49l-3 7', stroke: '#61baff', 'stroke-width': 3.5, 'stroke-linecap': 'round'});
        if (kind === 'storm') shape('path', {d: 'M34 38l-9 13h8l-3 11 14-17h-9l5-7Z', fill: '#ffd36a'});
        if (kind === 'snow') [20, 33, 46].forEach(cx => shape('circle', {cx, cy: 53, r: 2.5, fill: '#e1f5ff'}));
        if (kind === 'fog') shape('path', {d: 'M13 49h38 M18 55h28', stroke: '#98abc2', 'stroke-width': 3, 'stroke-linecap': 'round'});
        if (kind === 'unknown') shape('path', {d: 'M20 32h24', stroke: '#98abc2', 'stroke-width': 3, 'stroke-linecap': 'round'});
        return svg;
    }
    const root = make('section');
    root.id = 'misa-hud';
    root.setAttribute('aria-label', 'Local time and weather');
    const clock = make('div', 'hud-clock', '--:--');
    const date = make('div', 'hud-date');
    const location = make('div', 'hud-location');
    const week = make('div', 'hud-week');
    week.setAttribute('aria-label', 'Three-day weather forecast');
    root.append(clock, date, location, week);
    document.getElementById('misa-hud-alert')?.remove();
    document.body.append(root);
    // Reserve a separate region between the actual HUD and voice controls.
    // Recalculate after font loading, weather changes and window resizing.
    let layoutFrame = 0;
    function placeOrb() {
        layoutFrame = 0;
        const controls = document.querySelector('.controls');
        const viewportHeight = window.innerHeight;
        const top = Math.ceil(root.getBoundingClientRect().bottom) + 24;
        const controlTop = controls ? controls.getBoundingClientRect().top : viewportHeight - 72;
        const bottom = Math.max(16, viewportHeight - controlTop + 20);
        const available = Math.max(0, viewportHeight - top - bottom);
        // Leave room for the glow and the existing speaking/breathing animation.
        const diameter = Math.max(0, Math.min(360, window.innerWidth * 0.39,
                                            (available - 80) / 1.15));
        const style = document.documentElement.style;
        style.setProperty('--misa-orb-top', `${top}px`);
        style.setProperty('--misa-orb-bottom', `${bottom}px`);
        style.setProperty('--misa-orb-size', `${diameter}px`);
    }
    function scheduleOrbLayout() {
        if (!layoutFrame) layoutFrame = requestAnimationFrame(placeOrb);
    }
    if (typeof ResizeObserver !== 'undefined') {
        const observer = new ResizeObserver(scheduleOrbLayout);
        observer.observe(root);
        const controls = document.querySelector('.controls');
        if (controls) observer.observe(controls);
    }
    window.addEventListener('resize', scheduleOrbLayout);
    if (document.fonts) document.fonts.ready.then(scheduleOrbLayout);
    scheduleOrbLayout();
    function updateWeather(w) {
        week.replaceChildren();
        const days = Array.isArray(w.daily) ? w.daily.slice(0, 3) : [];
        Array.from({length: 3}, (_, index) => days[index] || {}).forEach((day, index) => {
            const card = make('article', 'hud-day');
            // Parse as local noon so date labels don't shift through UTC conversion.
            const parsed = new Date(`${day.time}T12:00:00`);
            const label = Number.isNaN(parsed.getTime()) ? 'Day 3'
                : parsed.toLocaleDateString(undefined, {weekday: 'short'});
            card.append(make('strong', 'hud-day-name', index === 0 ? 'Today' : index === 1 ? 'Tomorrow' : label),
                weatherIcon(day.weather_code, day.description),
                make('span', 'hud-day-temp', `${number(day.temperature_2m_max, '°')} / ${number(day.temperature_2m_min, '°')}`),
                make('span', 'hud-condition', w.stale ? 'Stale forecast' : (day.description || 'Unavailable')),
                make('span', 'hud-rain', `Precipitation ${number(day.precipitation_probability_max, '%')}`));
            week.append(card);
        });

    }
    updateWeather({});
    window.misaHud = {
        update(data) {
            clock.textContent = (data.time || '--:--').slice(0, 5);
            date.textContent = data.date || '';
            location.textContent = (data.location || '').replace(/\s*·\s*approximate via IP\s*$/i, '');
            if (data.weather) updateWeather(data.weather);
            scheduleOrbLayout();

        }
    };
})();