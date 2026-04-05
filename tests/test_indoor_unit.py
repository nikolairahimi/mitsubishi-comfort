"""Tests for mitsubishi_comfort.indoor_unit."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mitsubishi_comfort.indoor_unit import IndoorUnit
from mitsubishi_comfort.types import (
    FanSpeed,
    Mode,
    VaneDirection,
)


VALID_PASSWORD_B64 = "dGVzdHBhc3N3b3Jk"
VALID_CRYPTO_HEX = "0102030405060708090a"


def _make_unit() -> IndoorUnit:
    return IndoorUnit(
        name="Test Unit",
        address="192.168.1.100",
        password_b64=VALID_PASSWORD_B64,
        crypto_serial_hex=VALID_CRYPTO_HEX,
        serial="TEST001",
    )


def _status_response(
    mode="cool",
    sp_cool=24.0,
    sp_heat=21.0,
    room_temp=23.5,
    fan="auto",
    vane="auto",
) -> dict:
    return {
        "r": {
            "indoorUnit": {
                "status": {
                    "mode": mode,
                    "standby": False,
                    "spCool": sp_cool,
                    "spHeat": sp_heat,
                    "roomTemp": room_temp,
                    "fanSpeed": fan,
                    "vaneDir": vane,
                    "filterDirty": False,
                    "defrost": False,
                }
            }
        }
    }


def _profile_response(**overrides) -> dict:
    profile = {
        "hasModeHeat": True,
        "hasModeDry": True,
        "hasModeVent": True,
        "hasModeAuto": True,
        "hasVaneDir": True,
        "hasVaneSwing": True,
        "hasFanSpeedAuto": True,
        "numberOfFanSpeeds": 5,
        "minimumSetPoints": {"cool": 18.0, "heat": 16.0},
        "maximumSetPoints": {"cool": 30.0, "heat": 28.0},
    }
    profile.update(overrides)
    return {"r": {"indoorUnit": {"profile": profile}}}


def _adapter_status_response(**overrides) -> dict:
    adapter = {
        "autoModePrevention": False,
        "userHasModeDry": True,
        "userHasModeHeat": True,
        "localNetwork": {"stationMode": {"RSSI": -55}},
        "runState": "on",
        "uptime": 86400,
    }
    adapter.update(overrides)
    return {"r": {"adapter": {"status": adapter}}}


def _adapter_info_response() -> dict:
    return {
        "r": {
            "adapter": {
                "info": {
                    "firmwareVersion": "2.1.0",
                    "hardwareVersion": "1.0.0",
                }
            }
        }
    }


def _mhk2_response(humidity=None) -> dict:
    if humidity is not None:
        return {"r": {"mhk2": {"status": {"indoorHumid": humidity}}}}
    return {"r": {"mhk2": None}}


class TestUpdateStatus:
    async def test_update_status_success(self):
        """Parses all status fields correctly on first poll."""
        unit = _make_unit()
        responses = [
            _status_response(),          # indoorUnit status
            {},                           # sensors slot 0 (no uuid -> break)
            _profile_response(),          # profile
            _adapter_status_response(),   # adapter status
            _adapter_info_response(),     # adapter info
            _mhk2_response(),            # mhk2 (None -> skip)
        ]
        unit.request = AsyncMock(side_effect=responses)

        result = await unit.update_status()
        assert result is True
        assert unit.status.mode == "cool"
        assert unit.status.cool_setpoint == 24.0
        assert unit.status.heat_setpoint == 21.0
        assert unit.status.room_temperature == 23.5
        assert unit.status.fan_speed == "auto"
        assert unit.status.vane_direction == "auto"
        assert unit.status.wifi_rssi == -55
        assert unit.status.uptime == 86400
        assert unit.status.firmware_version == "2.1.0"
        assert unit.status.min_cool_setpoint == 18.0
        assert unit.status.max_cool_setpoint == 30.0

    async def test_update_status_failure(self):
        """Returns False on bad response."""
        unit = _make_unit()
        unit.request = AsyncMock(return_value={})

        result = await unit.update_status()
        assert result is False

    async def test_profile_cached_after_first_poll(self):
        """Profile only fetched once."""
        unit = _make_unit()
        # First poll: full set of responses
        first_poll = [
            _status_response(),
            {},  # sensors
            _profile_response(),
            _adapter_status_response(),
            _adapter_info_response(),
            _mhk2_response(),
        ]
        unit.request = AsyncMock(side_effect=first_poll)
        await unit.update_status()
        assert unit._profile_fetched is True

        # Second poll: only status + sensors + adapter status + mhk2
        second_poll = [
            _status_response(mode="heat"),
            {},  # sensors
            _adapter_status_response(),
            _mhk2_response(),
        ]
        unit.request = AsyncMock(side_effect=second_poll)
        result = await unit.update_status()
        assert result is True
        assert unit.status.mode == "heat"
        # Profile limits carried forward
        assert unit.status.min_cool_setpoint == 18.0


class TestSetCommands:
    async def test_set_mode_success(self):
        unit = _make_unit()
        unit._profile = {"hasModeHeat": True}
        unit.request = AsyncMock(return_value={"r": {"indoorUnit": {"status": {}}}})

        result = await unit.set_mode(Mode.HEAT)
        assert result.success is True
        assert result.value == "heat"

    async def test_set_mode_unsupported(self):
        unit = _make_unit()
        unit._profile = {}

        result = await unit.set_mode(Mode.AUTO)
        assert result.success is False

    async def test_set_cool_setpoint(self):
        unit = _make_unit()
        unit.request = AsyncMock(return_value={"r": {"indoorUnit": {"status": {}}}})

        result = await unit.set_cool_setpoint(22.5)
        assert result.success is True
        assert result.value == 22.5
        call_data = unit.request.call_args[0][0]
        assert b'"spCool":22.5' in call_data

    async def test_set_heat_setpoint(self):
        unit = _make_unit()
        unit.request = AsyncMock(return_value={"r": {"indoorUnit": {"status": {}}}})

        result = await unit.set_heat_setpoint(20.0)
        assert result.success is True
        assert result.value == 20.0

    async def test_set_fan_speed(self):
        unit = _make_unit()
        unit._profile = {"numberOfFanSpeeds": 5, "hasFanSpeedAuto": True}
        unit.request = AsyncMock(return_value={"r": {"indoorUnit": {"status": {}}}})

        result = await unit.set_fan_speed(FanSpeed.AUTO)
        assert result.success is True
        assert result.value == "auto"

    async def test_set_vane_direction(self):
        unit = _make_unit()
        unit._profile = {"hasVaneDir": True, "hasVaneSwing": True}
        unit.request = AsyncMock(return_value={"r": {"indoorUnit": {"status": {}}}})

        result = await unit.set_vane_direction(VaneDirection.SWING)
        assert result.success is True
        assert result.value == "swing"


class TestSupportedModes:
    def test_supported_modes(self):
        unit = _make_unit()
        unit._profile = {
            "hasModeHeat": True,
            "hasModeDry": True,
            "hasModeVent": True,
            "hasModeAuto": True,
        }
        modes = unit.supported_modes
        assert Mode.OFF in modes
        assert Mode.COOL in modes
        assert Mode.HEAT in modes
        assert Mode.DRY in modes
        assert Mode.FAN in modes
        assert Mode.AUTO in modes

    def test_supported_modes_minimal(self):
        unit = _make_unit()
        unit._profile = {}
        modes = unit.supported_modes
        assert modes == [Mode.OFF, Mode.COOL]


class TestSupportedFanSpeeds:
    def test_4_speed_config(self):
        unit = _make_unit()
        unit._profile = {"numberOfFanSpeeds": 4, "hasFanSpeedAuto": False}
        speeds = unit.supported_fan_speeds
        assert len(speeds) == 4
        assert FanSpeed.AUTO not in speeds

    def test_5_speed_config(self):
        unit = _make_unit()
        unit._profile = {"numberOfFanSpeeds": 5, "hasFanSpeedAuto": True}
        speeds = unit.supported_fan_speeds
        assert len(speeds) == 6
        assert FanSpeed.SUPER_QUIET in speeds
        assert FanSpeed.AUTO in speeds


class TestMHK2:
    async def test_mhk2_skipped_after_none(self):
        unit = _make_unit()
        responses = [
            _status_response(),
            {},  # sensors
            _profile_response(),
            _adapter_status_response(),
            _adapter_info_response(),
            _mhk2_response(humidity=None),
        ]
        unit.request = AsyncMock(side_effect=responses)

        await unit.update_status()
        assert unit._has_mhk2 is False
