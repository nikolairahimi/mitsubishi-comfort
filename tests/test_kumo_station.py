"""Tests for mitsubishi_comfort.kumo_station."""

import pytest
from unittest.mock import AsyncMock, patch
from mitsubishi_comfort.kumo_station import KumoStation


@pytest.fixture
def station(device_name, device_address, device_credentials, device_serial):
    return KumoStation(
        name=device_name,
        address=device_address,
        password_b64=device_credentials["password"],
        crypto_serial_hex=device_credentials["crypto_serial"],
        serial=device_serial,
    )


async def test_update_status_success(station):
    responses = [
        {"r": {"eqc": {"oat": 15.5}}},
        {"r": {"sensors": {"0": {"uuid": "s1", "humidity": 60.0, "temperature": 16.0, "battery": 90, "rssi": -50, "txPower": 4}}}},
        {"r": {"sensors": {"1": {}}}},
        {"r": {"adapter": {"status": {"localNetwork": {"stationMode": {"RSSI": -40}}}}}},
    ]
    with patch.object(station, "request", new_callable=AsyncMock, side_effect=responses):
        result = await station.update_status()

    assert result is True
    assert station.status.outdoor_temperature == 15.5
    assert station.status.wifi_rssi == -40


async def test_update_status_failure(station):
    with patch.object(station, "request", new_callable=AsyncMock, return_value={}):
        result = await station.update_status()

    assert result is False
