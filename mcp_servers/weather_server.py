"""
weather_server.py

MCP server for weather in metric units, from Open-Meteo (https://open-meteo.com).
No API key and no third-party packages (standard library only).

Why it exists: a weather question used to go to plain web search, which returns whatever
units the page happens to use (°F, mph, inches, 12-hour times). This server asks for metric
explicitly, refuses to show a value if Open-Meteo ever answers in another unit, and prints
every quantity the same way: 23.8 °C, 5 km/h from ESE, 0.2 mm, 1014 hPa, 4.8 km, 16:30.

Tools: get_weather (now + daily forecast), get_hourly_forecast.
Set ODYSSEUS_WEATHER_HOME to a place name to use when none is given.
"""

import asyncio
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("weather")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 12
METRIC = {"temperature_unit": "celsius", "wind_speed_unit": "kmh", "precipitation_unit": "mm"}

# What each variable must be reported in. Anything else is refused rather than mislabelled.
EXPECTED_UNITS = {
    "temperature_2m": "°C", "apparent_temperature": "°C", "temperature_2m_max": "°C", "temperature_2m_min": "°C",
    "relative_humidity_2m": "%", "cloud_cover": "%", "precipitation_probability": "%", "precipitation_probability_max": "%",
    "precipitation": "mm", "precipitation_sum": "mm", "pressure_msl": "hPa",
    "wind_speed_10m": "km/h", "wind_gusts_10m": "km/h", "wind_speed_10m_max": "km/h", "wind_direction_10m": "°",
    "visibility": "m",
}

CURRENT_VARS = ("temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,cloud_cover,"
                "pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,visibility")
DAILY_VARS = ("weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,"
              "wind_speed_10m_max,sunrise,sunset,uv_index_max")
HOURLY_VARS = "weather_code,temperature_2m,precipitation_probability,precipitation,wind_speed_10m,wind_direction_10m"

WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle", 56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Light rain", 63: "Moderate rain", 65: "Heavy rain", 66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Light snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with light hail", 99: "Thunderstorm with heavy hail",
}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


class WeatherError(Exception):
    """Something the user can act on (unknown place, offline). Shown as the tool's answer."""


# ── formatting: one way to print each quantity ───────────────────────────────

def num(value: Optional[float], places: int = 0) -> str:
    """Round half up (not Python's banker's rounding) and never print "-0"."""
    if value is None:
        return "n/a"
    rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = abs(rounded)
    return f"{rounded:.{places}f}"


def celsius(value: Optional[float], places: int = 0) -> str:
    return "n/a" if value is None else f"{num(value, places)} °C"


def kmh(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{num(value)} km/h"


def mm(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{num(value, 1)} mm"


def percent(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{num(value)} %"


def hpa(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{num(value)} hPa"


def km_from_metres(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    km = value / 1000.0
    return f"{num(km, 0 if km >= 10 else 1)} km"


def compass(degrees: Optional[float]) -> str:
    return "" if degrees is None else COMPASS[int((degrees % 360) / 22.5 + 0.5) % 16]


def wind(speed: Optional[float], degrees: Optional[float]) -> str:
    """Wind is reported by where it comes FROM, which is the meteorological convention."""
    if speed is None:
        return "n/a"
    direction = compass(degrees)
    return f"{kmh(speed)} from {direction}" if direction else kmh(speed)


def uv(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    level = round(value)
    name = "low" if level <= 2 else "moderate" if level <= 5 else "high" if level <= 7 else "very high" if level <= 10 else "extreme"
    return f"{num(value)} ({name})"


def conditions(code: Optional[int]) -> str:
    return "n/a" if code is None else WMO.get(int(code), f"Weather code {int(code)}")


def _when(iso: str) -> datetime:
    return datetime.strptime(iso[:16], "%Y-%m-%dT%H:%M")


def clock(iso: Optional[str]) -> str:
    """24-hour local time, as given by the API for the place (no timezone conversion)."""
    return "n/a" if not iso else _when(iso).strftime("%H:%M")


def day_label(iso_date: str, today: str) -> str:
    d = datetime.strptime(iso_date[:10], "%Y-%m-%d")
    delta = (d.date() - datetime.strptime(today[:10], "%Y-%m-%d").date()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return f"{d:%a} {d.day} {d:%b}"


def utc_offset(seconds: Optional[int]) -> str:
    seconds = int(seconds or 0)
    sign = "+" if seconds >= 0 else "-"
    hours, minutes = divmod(abs(seconds) // 60, 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def coordinates(lat: float, lon: float) -> str:
    return f"{abs(lat):.2f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.2f}° {'E' if lon >= 0 else 'W'}"


def table(headers: List[str], rows: List[List[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


# ── Open-Meteo ───────────────────────────────────────────────────────────────

def fetch_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "Odysseus-Weather/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            reason = json.load(e).get("reason")
        except Exception:
            reason = None
        raise WeatherError(f"Open-Meteo refused the request: {reason or f'HTTP {e.code}'}") from e
    except urllib.error.URLError as e:
        raise WeatherError(f"Could not reach Open-Meteo ({e.reason}). Check the internet connection.") from e


def check_units(payload: Dict[str, Any]) -> None:
    """A value in the wrong unit, labelled as metric, is worse than no value."""
    for block in ("current_units", "hourly_units", "daily_units"):
        for key, unit in (payload.get(block) or {}).items():
            wanted = EXPECTED_UNITS.get(key)
            if wanted is not None and unit != wanted:
                raise WeatherError(f"Open-Meteo gave {key} in '{unit}' instead of '{wanted}', so no values were shown.")


_LATLON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$")


def _hint_matches(hint: str, result: Dict[str, Any]) -> bool:
    hint = hint.strip().lower()
    if len(hint) < 2:
        return True
    if hint == str(result.get("country_code", "")).lower():
        return True
    return any(hint in str(result.get(k, "")).lower() for k in ("country", "admin1", "admin2"))


def _label(result: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("name", "admin1", "country"):
        value = str(result.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)
    return ", ".join(parts)


def resolve_location(text: str, fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    """A place name ("Pune", "Paris, France") or "lat,lon" -> {label, latitude, longitude, elevation, others}."""
    fetch = fetch or fetch_json
    text = (text or "").strip() or os.environ.get("ODYSSEUS_WEATHER_HOME", "").strip()
    if not text:
        raise WeatherError("No place was given. Ask the user which city they mean.")
    m = _LATLON.match(text)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise WeatherError(f"{text} is not a valid latitude,longitude (latitude -90 to 90, longitude -180 to 180).")
        return {"label": coordinates(lat, lon), "latitude": lat, "longitude": lon, "elevation": None, "others": [],
                "coordinates_only": True}
    head, *hints = [p.strip() for p in text.split(",") if p.strip()]
    results = (fetch(GEOCODE_URL, {"name": head, "count": 10, "language": "en", "format": "json"}).get("results")) or []
    if not results:
        raise WeatherError(f"No place called '{head}' was found. Try a bigger nearby city, 'City, Country', or 'latitude,longitude'.")
    narrowed = [r for r in results if all(_hint_matches(h, r) for h in hints)] if hints else results
    results = narrowed or results
    best = results[0]
    others = []
    if not (hints and narrowed):  # only suggest alternatives when the user gave nothing to tell them apart
        for r in results[1:]:
            if _label(r) != _label(best) and str(r.get("name", "")).lower() == str(best.get("name", "")).lower():
                others.append(_label(r))
    return {"label": _label(best), "latitude": best["latitude"], "longitude": best["longitude"],
            "elevation": best.get("elevation"), "others": others[:3]}


def _forecast(place: Dict[str, Any], fetch: Callable[..., Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    params = {"latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", **METRIC, **extra}
    payload = fetch(FORECAST_URL, params)
    if payload.get("error"):
        raise WeatherError(f"Open-Meteo said: {payload.get('reason', 'unknown error')}")
    check_units(payload)
    return payload


def _header(place: Dict[str, Any], payload: Dict[str, Any]) -> List[str]:
    now = (payload.get("current") or {}).get("time")
    elevation = payload.get("elevation", place.get("elevation"))
    where = f"Weather for {place['label']}"
    if not place.get("coordinates_only"):
        where += f" ({coordinates(place['latitude'], place['longitude'])})"
    if elevation is not None:
        where += f", elevation {num(elevation)} m"
    lines = [where]
    if now:
        t = _when(now)
        lines.append(f"Local time: {t:%a} {t.day} {t:%b %Y}, {t:%H:%M} ({payload.get('timezone', 'local')}, "
                     f"{utc_offset(payload.get('utc_offset_seconds'))})")
    lines.append("Units: metric (°C, km/h, mm, hPa, km, 24-hour time). Quote these values exactly as written; "
                 "do not convert to °F, mph or inches.")
    if place.get("others"):
        lines.append("Best match shown. Other places with this name: " + "; ".join(place["others"])
                     + ". If the user could have meant one of those, say which place you used.")
    return lines


def weather_report(location: str, days: int = 3, fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> str:
    fetch = fetch or fetch_json
    days = max(1, min(int(days or 3), 16))
    place = resolve_location(location, fetch)
    p = _forecast(place, fetch, current=CURRENT_VARS, daily=DAILY_VARS, forecast_days=days)
    cur, daily = p.get("current") or {}, p.get("daily") or {}
    today = (cur.get("time") or (daily.get("time") or [""])[0])[:10]

    out = _header(place, p) + [""]
    out.append(f"Now: {conditions(cur.get('weather_code'))}, {celsius(cur.get('temperature_2m'), 1)} "
               f"(feels like {celsius(cur.get('apparent_temperature'), 1)})")
    out.append(f"- Humidity {percent(cur.get('relative_humidity_2m'))} · Cloud cover {percent(cur.get('cloud_cover'))} "
               f"· Pressure {hpa(cur.get('pressure_msl'))}")
    out.append(f"- Wind {wind(cur.get('wind_speed_10m'), cur.get('wind_direction_10m'))}, gusts {kmh(cur.get('wind_gusts_10m'))}")
    out.append(f"- Recent precipitation {mm(cur.get('precipitation'))} · Visibility {km_from_metres(cur.get('visibility'))}")
    if daily.get("sunrise") and daily.get("sunset"):
        out.append(f"- Sunrise {clock(daily['sunrise'][0])} · Sunset {clock(daily['sunset'][0])}")

    rows = []
    for i, date in enumerate(daily.get("time") or []):
        rows.append([
            day_label(date, today or date),
            conditions(daily["weather_code"][i]),
            f"{celsius(daily['temperature_2m_min'][i])} / {celsius(daily['temperature_2m_max'][i])}",
            percent(daily["precipitation_probability_max"][i]),
            mm(daily["precipitation_sum"][i]),
            kmh(daily["wind_speed_10m_max"][i]),
            uv(daily["uv_index_max"][i]),
        ])
    if rows:
        out += ["", f"Forecast ({len(rows)} day{'s' if len(rows) != 1 else ''}):",
                table(["Day", "Conditions", "Min / Max", "Rain chance", "Rain", "Max wind", "UV"], rows)]
    return "\n".join(out)


def hourly_report(location: str, hours: int = 24, fetch: Optional[Callable[..., Dict[str, Any]]] = None) -> str:
    fetch = fetch or fetch_json
    hours = max(1, min(int(hours or 24), 72))
    place = resolve_location(location, fetch)
    p = _forecast(place, fetch, current="temperature_2m", hourly=HOURLY_VARS, forecast_hours=hours)
    h = p.get("hourly") or {}
    rows = []
    for i, iso in enumerate(h.get("time") or []):
        t = _when(iso)
        rows.append([
            f"{t:%a} {t:%H:%M}",
            conditions(h["weather_code"][i]),
            celsius(h["temperature_2m"][i], 1),
            percent(h["precipitation_probability"][i]),
            mm(h["precipitation"][i]),
            wind(h["wind_speed_10m"][i], h["wind_direction_10m"][i]),
        ])
    out = _header(place, p) + ["", f"Next {len(rows)} hours (local time):"]
    out.append(table(["Time", "Conditions", "Temp", "Rain chance", "Rain", "Wind"], rows) if rows else "No hourly data was returned.")
    return "\n".join(out)


# ── MCP ──────────────────────────────────────────────────────────────────────

_LOCATION = {
    "type": "string",
    "description": "A city ('Pune', 'Paris, France', 'Springfield, Missouri') or 'latitude,longitude' ('12.97,77.59'). "
                   "If the user has not said where, ask them; do not guess.",
}


@server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="get_weather",
            description=(
                "Current weather and a daily forecast for a place, in metric units (°C, km/h, mm, hPa, km) with 24-hour "
                "local times. Use this for any weather, temperature, rain, wind or forecast question instead of searching "
                "the web, and report the numbers exactly as returned."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "location": _LOCATION,
                    "days": {"type": "integer", "description": "Days of forecast to show, 1 to 16 (default 3).", "default": 3},
                },
                "required": ["location"],
            },
        ),
        Tool(
            name="get_hourly_forecast",
            description=(
                "Hour-by-hour forecast for a place, in metric units, starting with the current hour. Use it when the user "
                "asks about a specific time (this evening, tomorrow at 9) or when rain will start or stop."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "location": _LOCATION,
                    "hours": {"type": "integer", "description": "Hours to show, 1 to 72 (default 24).", "default": 24},
                },
                "required": ["location"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> List[TextContent]:
    arguments = arguments or {}
    try:
        loop = asyncio.get_running_loop()
        if name == "get_weather":
            text = await loop.run_in_executor(None, weather_report, arguments.get("location", ""), arguments.get("days", 3))
        elif name == "get_hourly_forecast":
            text = await loop.run_in_executor(None, hourly_report, arguments.get("location", ""), arguments.get("hours", 24))
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except WeatherError as e:
        return [TextContent(type="text", text=f"Error: {e}")]
    except (TypeError, ValueError) as e:
        return [TextContent(type="text", text=f"Error: bad argument ({e})")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error getting the weather: {e}")]
    return [TextContent(type="text", text=text)]


async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run())
