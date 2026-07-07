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

    async def test_disconnects_when_done(self):
        """The adapter's connection slot is freed at the end of every poll."""
        station = _make_station()
        station.request = AsyncMock(return_value={})
        station.disconnect = AsyncMock()

        await station.update_status()
        station.disconnect.assert_awaited_once()

    async def test_sensor_rssi_from_external_sensor(self):
        """An external sensor's RSSI is surfaced on the status snapshot."""
        station = _make_station()
        station.request = AsyncMock(side_effect=[
            {"r": {"eqc": {"oat": 15.5}}},
            {"r": {"sensors": {"0": {"uuid": "abc", "rssi": -50}}}},
            {},  # sensor slot 1 -> break
            {"r": {"adapter": {"status": {"localNetwork": {"stationMode": {"RSSI": -40}}}}}},
        ])

        result = await station.update_status()
        assert result is True
        assert station.status.sensor_rssi == -50
        assert station.status.wifi_rssi == -40

    async def test_wifi_rssi_none_when_adapter_status_malformed(self):
        """A missing RSSI path leaves wifi_rssi None without failing the poll."""
        station = _make_station()
        station.request = AsyncMock(side_effect=[
            {"r": {"eqc": {"oat": 15.5}}},
            {},  # no sensors
            {"r": {"adapter": {"status": {}}}},  # no localNetwork -> None
        ])

        result = await station.update_status()
        assert result is True
        assert station.status.wifi_rssi is None
