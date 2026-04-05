"""Tests for mitsubishi_comfort.kumo_station."""

from __future__ import annotations

from unittest.mock import AsyncMock

from mitsubishi_comfort.kumo_station import KumoStation


VALID_PASSWORD_B64 = "dGVzdHBhc3N3b3Jk"
VALID_CRYPTO_HEX = "0102030405060708090a"


def _make_station() -> KumoStation:
    return KumoStation(
        name="Outdoor Unit",
        address="192.168.1.101",
        password_b64=VALID_PASSWORD_B64,
        crypto_serial_hex=VALID_CRYPTO_HEX,
        serial="KUMO001",
    )


class TestUpdateStatus:
    async def test_success(self):
        station = _make_station()
        responses = [
            {"r": {"eqc": {"oat": 15.5}}},
            {},  # sensors slot 0 (no uuid -> break)
            {"r": {"adapter": {"status": {"localNetwork": {"stationMode": {"RSSI": -40}}}}}},
        ]
        station.request = AsyncMock(side_effect=responses)

        result = await station.update_status()
        assert result is True
        assert station.status.outdoor_temperature == 15.5
        assert station.status.wifi_rssi == -40

    async def test_failure(self):
        station = _make_station()
        station.request = AsyncMock(return_value={})

        result = await station.update_status()
        assert result is False
