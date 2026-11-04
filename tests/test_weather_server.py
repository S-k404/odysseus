"""mcp_servers/weather_server.py: metric weather from Open-Meteo, printed one consistent way.

Open-Meteo is stubbed with responses shaped like the real ones (captured 2026-11-04); no test goes online.
"""

import asyncio
import sys
from pathlib import Path

import pytest

from mcp_servers import weather_server as w

BENGALURU = {"name": "Bengaluru", "admin1": "Karnataka", "admin2": "Bengaluru Urban", "country": "India",
             "country_code": "IN", "latitude": 12.97194, "longitude": 77.59369, "elevation": 920.0}

FORECAST = {
    "timezone": "Asia/Kolkata", "utc_offset_seconds": 19800, "elevation": 918.0,
    "current_units": {"temperature_2m": "°C", "apparent_temperature": "°C", "relative_humidity_2m": "%", "precipitation": "mm",
                      "cloud_cover": "%", "pressure_msl": "hPa", "wind_speed_10m": "km/h", "wind_direction_10m": "°",
                      "wind_gusts_10m": "km/h", "visibility": "m"},
    "current": {"time": "2026-11-04T16:30", "temperature_2m": 23.8, "apparent_temperature": 26.0, "relative_humidity_2m": 70,
                "precipitation": 0.2, "weather_code": 53, "cloud_cover": 98, "pressure_msl": 1013.9, "wind_speed_10m": 4.8,
                "wind_direction_10m": 112, "wind_gusts_10m": 22.3, "visibility": 4800.0},
    "daily_units": {"temperature_2m_max": "°C", "temperature_2m_min": "°C", "precipitation_sum": "mm",
                    "precipitation_probability_max": "%", "wind_speed_10m_max": "km/h"},
    "daily": {"time": ["2026-11-04", "2026-11-05", "2026-11-06"], "weather_code": [53, 51, 63],
              "temperature_2m_max": [28.9, 29.5, -0.4], "temperature_2m_min": [19.7, 20.0, -3.5],
              "precipitation_sum": [4.0, 1.0, 0.04], "precipitation_probability_max": [82, 82, 86],
              "wind_speed_10m_max": [8.4, 13.2, 12.5], "sunrise": ["2026-11-04T06:14", "x", "x"],
              "sunset": ["2026-11-04T17:52", "x", "x"], "uv_index_max": [8.15, 6.9, 2.4]},
}
HOURLY = {
    "timezone": "Asia/Kolkata", "utc_offset_seconds": 19800, "elevation": 918.0,
    "current_units": {"temperature_2m": "°C"}, "current": {"time": "2026-11-04T16:30", "temperature_2m": 23.8},
    "hourly_units": {"temperature_2m": "°C", "precipitation_probability": "%", "precipitation": "mm",
                     "wind_speed_10m": "km/h", "wind_direction_10m": "°"},
    "hourly": {"time": ["2026-11-04T16:00", "2026-11-04T23:00", "2026-11-05T00:00"], "weather_code": [3, 0, 61],
               "temperature_2m": [30.1, 25.2, 24.0], "precipitation_probability": [20, 0, 55],
               "precipitation": [0.0, 0.0, 1.25], "wind_speed_10m": [9.4, 6.0, 3.1], "wind_direction_10m": [67, 70, 355]},
}


class Api:
    """A fake Open-Meteo that remembers what it was asked."""

    def __init__(self, geocode=None, forecast=None):
        self.geocode = {"results": [BENGALURU]} if geocode is None else geocode
        self.forecast = FORECAST if forecast is None else forecast
        self.calls = []

    def __call__(self, url, params):
        self.calls.append((url, params))
        return self.geocode if url == w.GEOCODE_URL else self.forecast

    @property
    def forecast_params(self):
        return next(p for u, p in self.calls if u == w.FORECAST_URL)


# ── formatting ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, places, expected", [
    (28.5, 0, "29"), (29.5, 0, "30"), (-28.5, 0, "-29"),   # half rounds away from zero, not to even
    (-0.4, 0, "0"), (-0.0, 0, "0"), (-0.04, 1, "0.0"),     # never "-0"
    (23.84, 1, "23.8"), (1013.9, 0, "1014"), (None, 0, "n/a"),
])
def test_numbers_round_half_up_and_never_show_negative_zero(value, places, expected):
    assert w.num(value, places) == expected


def test_each_quantity_carries_its_metric_unit_and_negative_temperatures_keep_their_sign():
    assert w.celsius(-3.5, 1) == "-3.5 °C" and w.celsius(23.8, 1) == "23.8 °C" and w.celsius(None) == "n/a"
    assert w.kmh(4.8) == "5 km/h" and w.mm(0.2) == "0.2 mm" and w.hpa(1013.9) == "1014 hPa" and w.percent(70) == "70 %"


def test_visibility_is_converted_from_metres_to_km():
    assert w.km_from_metres(4800) == "4.8 km" and w.km_from_metres(24140) == "24 km" and w.km_from_metres(None) == "n/a"


def test_wind_is_named_by_where_it_comes_from_on_a_16_point_compass():
    assert [w.compass(d) for d in (0, 112, 180, 270, 348.75, 359)] == ["N", "ESE", "S", "W", "N", "N"]
    assert w.wind(4.8, 112) == "5 km/h from ESE" and w.wind(None, 10) == "n/a" and w.wind(7, None) == "7 km/h"


def test_times_are_24_hour_and_days_are_relative_to_the_place():
    assert w.clock("2026-11-04T17:52") == "17:52" and w.clock("2026-11-04T06:05") == "06:05" and w.clock(None) == "n/a"
    assert [w.day_label(d, "2026-11-04") for d in ("2026-11-04", "2026-11-05", "2026-11-09")] == ["Today", "Tomorrow", "Mon 9 Nov"]
    assert w.utc_offset(19800) == "UTC+05:30" and w.utc_offset(-21600) == "UTC-06:00" and w.utc_offset(0) == "UTC+00:00"


def test_coordinates_use_compass_letters_not_signs():
    assert w.coordinates(12.97, 77.59) == "12.97° N, 77.59° E"
    assert w.coordinates(-33.87, -70.65) == "33.87° S, 70.65° W"


def test_uv_and_conditions_have_words():
    assert w.uv(8.15) == "8 (very high)" and w.uv(2.4) == "2 (low)" and w.uv(11.2) == "11 (extreme)"
    assert w.conditions(53) == "Moderate drizzle" and w.conditions(999) == "Weather code 999" and w.conditions(None) == "n/a"


# ── the report ───────────────────────────────────────────────────────────────

def test_the_weather_report_shows_every_value_in_metric():
    report = w.weather_report("Bengaluru", 3, fetch=Api())
    assert "Weather for Bengaluru, Karnataka, India (12.97° N, 77.59° E), elevation 918 m" in report
    assert "Local time: Wed 4 Nov 2026, 16:30 (Asia/Kolkata, UTC+05:30)" in report
    assert "Now: Moderate drizzle, 23.8 °C (feels like 26.0 °C)" in report
    assert "Humidity 70 % · Cloud cover 98 % · Pressure 1014 hPa" in report
    assert "Wind 5 km/h from ESE, gusts 22 km/h" in report
    assert "Recent precipitation 0.2 mm · Visibility 4.8 km" in report
    assert "Sunrise 06:14 · Sunset 17:52" in report
    assert "| Today | Moderate drizzle | 20 °C / 29 °C | 82 % | 4.0 mm | 8 km/h | 8 (very high) |" in report
    assert "| Tomorrow | Light drizzle | 20 °C / 30 °C | 82 % | 1.0 mm | 13 km/h | 7 (high) |" in report
    assert "| Fri 6 Nov | Moderate rain | -4 °C / 0 °C | 86 % | 0.0 mm | 13 km/h | 2 (low) |" in report
    data = "\n".join(line for line in report.splitlines() if not line.startswith("Units:"))  # that line names °F and mph on purpose
    for imperial in ("°F", "mph", "inch", " AM", " PM"):
        assert imperial not in data


def test_the_report_tells_the_model_not_to_convert_the_units():
    assert "Quote these values exactly as written" in w.weather_report("Bengaluru", 1, fetch=Api())


def test_metric_is_requested_explicitly_not_left_to_the_api_default():
    api = Api()
    w.weather_report("Bengaluru", 3, fetch=api)
    assert {k: api.forecast_params[k] for k in ("temperature_unit", "wind_speed_unit", "precipitation_unit")} == {
        "temperature_unit": "celsius", "wind_speed_unit": "kmh", "precipitation_unit": "mm"}
    assert api.forecast_params["timezone"] == "auto"


@pytest.mark.parametrize("block, key, unit", [
    ("current_units", "temperature_2m", "°F"), ("current_units", "wind_speed_10m", "mp/h"),
    ("daily_units", "precipitation_sum", "inch"), ("daily_units", "temperature_2m_max", "K"),
])
def test_a_value_in_another_unit_is_refused_rather_than_shown_with_a_metric_label(block, key, unit):
    bad = {**FORECAST, block: {**FORECAST[block], key: unit}}
    with pytest.raises(w.WeatherError, match=f"{key} in '{unit}'"):
        w.weather_report("Bengaluru", 3, fetch=Api(forecast=bad))


def test_the_number_of_days_is_kept_between_1_and_16():
    for asked, sent in ((99, 16), (-5, 1), (0, 3), ("2", 2)):
        api = Api()
        w.weather_report("Bengaluru", asked, fetch=api)
        assert api.forecast_params["forecast_days"] == sent


def test_an_api_error_body_becomes_a_clear_message():
    with pytest.raises(w.WeatherError, match="Open-Meteo said: Latitude must be in range"):
        w.weather_report("Bengaluru", 1, fetch=Api(forecast={"error": True, "reason": "Latitude must be in range of -90 to 90"}))


# ── hourly ───────────────────────────────────────────────────────────────────

def test_the_hourly_forecast_is_a_table_in_local_24_hour_time():
    api = Api(forecast=HOURLY)
    report = w.hourly_report("Bengaluru", 3, fetch=api)
    assert api.forecast_params["forecast_hours"] == 3
    assert "Next 3 hours (local time):" in report
    assert "| Wed 16:00 | Overcast | 30.1 °C | 20 % | 0.0 mm | 9 km/h from ENE |" in report
    assert "| Wed 23:00 | Clear sky | 25.2 °C | 0 % | 0.0 mm | 6 km/h from ENE |" in report
    assert "| Thu 00:00 | Light rain | 24.0 °C | 55 % | 1.3 mm | 3 km/h from N |" in report  # 1.25 mm rounds up


def test_the_number_of_hours_is_kept_between_1_and_72():
    for asked, sent in ((500, 72), (0, 24), (-1, 1)):
        api = Api(forecast=HOURLY)
        w.hourly_report("Bengaluru", asked, fetch=api)
        assert api.forecast_params["forecast_hours"] == sent


# ── finding the place ────────────────────────────────────────────────────────

def _result(name, admin1, country, code, lat=0.0, lon=0.0):
    return {"name": name, "admin1": admin1, "country": country, "country_code": code, "latitude": lat, "longitude": lon}


SPRINGFIELDS = [_result("Springfield", "Missouri", "United States", "US"), _result("Springfield", "Illinois", "United States", "US"),
                _result("Springfield", "Victoria", "Australia", "AU"), _result("Springfield Lakes", "Queensland", "Australia", "AU")]


def test_coordinates_are_accepted_directly_and_validated():
    place = w.resolve_location("12.97, 77.59", fetch=Api())
    assert (place["latitude"], place["longitude"], place["coordinates_only"]) == (12.97, 77.59, True)
    assert w.resolve_location("-33.87 -70.65", fetch=Api())["longitude"] == -70.65
    with pytest.raises(w.WeatherError, match="not a valid latitude,longitude"):
        w.resolve_location("95,10", fetch=Api())


def test_a_bare_name_takes_the_best_match_and_lists_others_with_the_same_name_only():
    place = w.resolve_location("Springfield", fetch=Api(geocode={"results": SPRINGFIELDS}))
    assert place["label"] == "Springfield, Missouri, United States"
    assert place["others"] == ["Springfield, Illinois, United States", "Springfield, Victoria, Australia"]  # not "Springfield Lakes"


def test_a_country_or_region_after_a_comma_picks_the_right_place_and_stops_the_warning():
    api = Api(geocode={"results": SPRINGFIELDS})
    place = w.resolve_location("Springfield, Australia", fetch=api)
    assert place["label"] == "Springfield, Victoria, Australia" and place["others"] == []
    assert w.resolve_location("Springfield, Illinois", fetch=api)["label"].startswith("Springfield, Illinois")
    assert w.resolve_location("Springfield, AU", fetch=api)["label"].endswith("Australia")
    assert api.calls[0][1]["name"] == "Springfield"  # only the name part goes to the geocoder


def test_a_hint_that_matches_nothing_falls_back_to_the_best_match():
    assert w.resolve_location("Springfield, Narnia", fetch=Api(geocode={"results": SPRINGFIELDS}))["label"].startswith("Springfield, Missouri")


def test_an_unknown_place_says_what_to_try():
    with pytest.raises(w.WeatherError, match="No place called 'Qzx' was found"):
        w.resolve_location("Qzx", fetch=Api(geocode={}))


def test_no_place_asks_for_one_unless_a_home_is_set(monkeypatch):
    monkeypatch.delenv("ODYSSEUS_WEATHER_HOME", raising=False)
    with pytest.raises(w.WeatherError, match="Ask the user which city"):
        w.resolve_location("  ", fetch=Api())
    monkeypatch.setenv("ODYSSEUS_WEATHER_HOME", "Bengaluru")
    api = Api()
    assert w.resolve_location("", fetch=api)["label"].startswith("Bengaluru")
    assert api.calls[0][1]["name"] == "Bengaluru"


# ── the MCP surface ──────────────────────────────────────────────────────────

def _call(name, arguments, monkeypatch, api=None):
    monkeypatch.setattr(w, "fetch_json", api or Api())
    (content,) = asyncio.run(w.call_tool(name, arguments))
    return content.text


def test_the_tools_are_listed_with_a_required_location():
    tools = {t.name: t for t in asyncio.run(w.list_tools())}
    assert set(tools) == {"get_weather", "get_hourly_forecast"}
    assert all(t.inputSchema["required"] == ["location"] for t in tools.values())
    assert "metric" in tools["get_weather"].description


def test_call_tool_returns_the_report_or_an_error_the_model_can_act_on(monkeypatch):
    assert "Now: Moderate drizzle, 23.8 °C" in _call("get_weather", {"location": "Bengaluru"}, monkeypatch)
    assert "Next 3 hours" in _call("get_hourly_forecast", {"location": "Bengaluru", "hours": 3}, monkeypatch, Api(forecast=HOURLY))
    assert _call("get_weather", {"location": "Qzx"}, monkeypatch, Api(geocode={})).startswith("Error: No place called 'Qzx'")
    assert _call("get_weather", {"location": "Bengaluru", "days": "many"}, monkeypatch).startswith("Error: bad argument")
    assert _call("nope", {}, monkeypatch) == "Unknown tool: nope"


def test_an_offline_network_is_reported_not_raised(monkeypatch):
    def offline(url, params):
        raise w.WeatherError("Could not reach Open-Meteo (nodename nor servname provided). Check the internet connection.")

    assert "Could not reach Open-Meteo" in _call("get_weather", {"location": "Pune"}, monkeypatch, offline)


def test_the_server_starts_and_lists_its_tools_over_stdio():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    script = Path(w.__file__).resolve()

    async def handshake():
        params = StdioServerParameters(command=sys.executable, args=[str(script)])
        async with stdio_client(params) as (r, wr):
            async with ClientSession(r, wr) as session:
                await session.initialize()
                return sorted(t.name for t in (await session.list_tools()).tools)

    assert asyncio.run(asyncio.wait_for(handshake(), 30)) == ["get_hourly_forecast", "get_weather"]
