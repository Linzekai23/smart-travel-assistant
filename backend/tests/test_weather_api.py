import datetime as dt

import httpx
from httpx import MockTransport

from app.tools import weather_api


def _make_client(days: int, lat: float, lng: float) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert f"latitude={lat}" in url and f"longitude={lng}" in url
        assert f"forecast_days={days}" in url
        return httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2026-10-01", "2026-10-02"],
                    "temperature_2m_max": [24.0, 21.0],
                    "temperature_2m_min": [16.0, 14.0],
                    "weathercode": [1, 61],
                }
            },
        )

    return httpx.Client(transport=MockTransport(handler))


def test_get_weather_success():
    fake = _make_client(2, 30.57, 104.06)
    out = weather_api.get_weather(30.57, 104.06, days=2, client=fake)
    assert out == [
        {"date": "2026-10-01", "t_max": 24.0, "t_min": 16.0, "condition": "多云", "source": "open-meteo"},
        {"date": "2026-10-02", "t_max": 21.0, "t_min": 14.0, "condition": "雨", "source": "open-meteo"},
    ]


def test_get_weather_falls_back_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    fake = httpx.Client(transport=MockTransport(handler))
    out = weather_api.get_weather(30.57, 104.06, days=2, client=fake)
    assert len(out) == 2
    assert all(d["source"] == "simulated" for d in out)
    assert out[0]["date"] == dt.date.today().isoformat()


def test_get_weather_falls_back_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    fake = httpx.Client(transport=MockTransport(handler))
    out = weather_api.get_weather(30.57, 104.06, days=2, client=fake)
    assert all(d["source"] == "simulated" for d in out)


def test_weathercodes_cover_simulated_default():
    assert weather_api.WEATHERCODES[0] == "晴"
