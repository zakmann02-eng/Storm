import datetime as dt

from storm.openmeteo_client import OpenMeteoClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload
        self.last_params = None

    def get(self, url, params=None, timeout=None):
        self.last_params = params
        return _FakeResponse(self._payload)


def _payload():
    return {
        "daily": {
            "time": ["2026-07-19", "2026-07-20"],
            "temperature_2m_max": [82.0, 90.5],
            "temperature_2m_min": [68.0, 71.0],
            "precipitation_probability_max": [10, 60],
        }
    }


def test_get_daily_forecast_indexes_by_date():
    client = OpenMeteoClient(session=_FakeSession(_payload()))
    by_date = client.get_daily_forecast(40.71, -74.01)

    assert by_date["2026-07-20"]["temperature_max"] == 90.5
    assert by_date["2026-07-20"]["temperature_min"] == 71.0
    assert by_date["2026-07-20"]["precipitation_probability_max"] == 60


def test_get_forecast_for_date_returns_matching_day():
    client = OpenMeteoClient(session=_FakeSession(_payload()))
    forecast = client.get_forecast_for_date(40.71, -74.01, dt.date(2026, 7, 20))

    assert forecast is not None
    assert forecast["temperature_max"] == 90.5


def test_get_forecast_for_date_returns_none_when_missing():
    client = OpenMeteoClient(session=_FakeSession(_payload()))
    forecast = client.get_forecast_for_date(40.71, -74.01, dt.date(2026, 8, 1))

    assert forecast is None


def test_requests_fahrenheit_and_auto_timezone():
    session = _FakeSession(_payload())
    client = OpenMeteoClient(session=session)
    client.get_daily_forecast(40.71, -74.01)

    assert session.last_params["temperature_unit"] == "fahrenheit"
    assert session.last_params["timezone"] == "auto"
