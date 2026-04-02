"""Tests for mitsubishi_comfort.indoor_unit."""

import json
import pytest
from unittest.mock import AsyncMock, patch
from mitsubishi_comfort.indoor_unit import IndoorUnit
from mitsubishi_comfort.types import CommandResult, DeviceStatus, Mode, FanSpeed, VaneDirection


@pytest.fixture
def unit(device_name, device_address, device_credentials, device_serial):
    return IndoorUnit(
        name=device_name,
        address=device_address,
        password_b64=device_credentials["password"],
        crypto_serial_hex=device_credentials["crypto_serial"],
        serial=device_serial,
    )


def _make_status_response(
    mode="cool", standby=False, sp_heat=20.0, sp_cool=24.0,
    room_temp=22.5, fan_speed="auto", vane_dir="auto",
    filter_dirty=False, defrost=False,
):
    return {
        "r": {
            "indoorUnit": {
                "status": {
                    "mode": mode,
                    "standby": standby,
                    "spHeat": sp_heat,
                    "spCool": sp_cool,
                    "roomTemp": room_temp,
                    "fanSpeed": fan_speed,
                    "vaneDir": vane_dir,
                    "filterDirty": filter_dirty,
                    "defrost": defrost,
                }
            }
        }
    }


def _make_profile_response(
    num_fan_speeds=5, has_auto_fan=True, has_vane_swing=True,
    has_dry=True, has_heat=True, has_vent=True, has_auto=True,
    has_vane_dir=True,
):
    return {
        "r": {
            "indoorUnit": {
                "profile": {
                    "numberOfFanSpeeds": num_fan_speeds,
                    "hasFanSpeedAuto": has_auto_fan,
                    "hasVaneSwing": has_vane_swing,
                    "hasModeDry": has_dry,
                    "hasModeHeat": has_heat,
                    "hasModeVent": has_vent,
                    "hasModeAuto": has_auto,
                    "hasVaneDir": has_vane_dir,
                }
            }
        }
    }


def _make_adapter_response(
    auto_prevention=False, user_dry=True, user_heat=True,
    rssi=-55, run_state="on",
):
    return {
        "r": {
            "adapter": {
                "status": {
                    "autoModePrevention": auto_prevention,
                    "userHasModeDry": user_dry,
                    "userHasModeHeat": user_heat,
                    "localNetwork": {"stationMode": {"RSSI": rssi}},
                    "runState": run_state,
                }
            }
        }
    }


def _make_sensor_response(index, humidity=45.0, temp=22.0, battery=85, rssi=-60):
    return {
        "r": {
            "sensors": {
                str(index): {
                    "uuid": "sensor-uuid-1",
                    "humidity": humidity,
                    "temperature": temp,
                    "battery": battery,
                    "rssi": rssi,
                    "txPower": 4,
                }
            }
        }
    }


def _make_empty_sensor_response(index):
    return {"r": {"sensors": {str(index): {}}}}


def _make_mhk2_response(humidity=None):
    return {"r": {"mhk2": {"status": {"indoorHumid": humidity}}}}


async def test_update_status_success(unit):
    responses = [
        _make_status_response(),
        _make_sensor_response(0),
        _make_empty_sensor_response(1),
        _make_profile_response(),
        _make_adapter_response(),
        _make_mhk2_response(),
    ]
    with patch.object(unit, "request", new_callable=AsyncMock, side_effect=responses):
        result = await unit.update_status()

    assert result is True
    status = unit.status
    assert status.mode == "cool"
    assert status.room_temperature == 22.5
    assert status.cool_setpoint == 24.0
    assert status.heat_setpoint == 20.0
    assert status.fan_speed == "auto"
    assert status.vane_direction == "auto"
    assert status.current_humidity == 45.0
    assert status.wifi_rssi == -55
    assert status.sensor_battery == 85


async def test_update_status_failure(unit):
    with patch.object(unit, "request", new_callable=AsyncMock, return_value={}):
        result = await unit.update_status()

    assert result is False


async def test_set_mode(unit):
    unit._profile = {"hasModeHeat": True, "hasModeDry": True, "hasModeVent": True, "hasModeAuto": True}
    response = {"r": {"indoorUnit": {"status": {"mode": "heat"}}}}

    with patch.object(unit, "request", new_callable=AsyncMock, return_value=response):
        result = await unit.set_mode(Mode.HEAT)

    assert result.success is True
    assert result.value == "heat"


async def test_set_mode_invalid(unit):
    unit._profile = {}
    result = await unit.set_mode(Mode.HEAT)
    assert result.success is False


async def test_set_cool_setpoint(unit):
    response = {"r": {"indoorUnit": {"status": {"spCool": 23.0}}}}

    with patch.object(unit, "request", new_callable=AsyncMock, return_value=response):
        result = await unit.set_cool_setpoint(23.0)

    assert result.success is True
    assert result.value == 23.0


async def test_set_cool_setpoint_failure(unit):
    with patch.object(unit, "request", new_callable=AsyncMock, return_value={}):
        result = await unit.set_cool_setpoint(23.0)

    assert result.success is False


async def test_set_heat_setpoint(unit):
    response = {"r": {"indoorUnit": {"status": {"spHeat": 21.0}}}}

    with patch.object(unit, "request", new_callable=AsyncMock, return_value=response):
        result = await unit.set_heat_setpoint(21.0)

    assert result.success is True
    assert result.value == 21.0


async def test_set_fan_speed(unit):
    unit._profile = {"numberOfFanSpeeds": 5, "hasFanSpeedAuto": True}
    response = {"r": {"indoorUnit": {"status": {"fanSpeed": "quiet"}}}}

    with patch.object(unit, "request", new_callable=AsyncMock, return_value=response):
        result = await unit.set_fan_speed(FanSpeed.QUIET)

    assert result.success is True
    assert result.value == "quiet"


async def test_set_vane_direction(unit):
    unit._profile = {"hasVaneDir": True, "hasVaneSwing": True}
    response = {"r": {"indoorUnit": {"status": {"vaneDir": "swing"}}}}

    with patch.object(unit, "request", new_callable=AsyncMock, return_value=response):
        result = await unit.set_vane_direction(VaneDirection.SWING)

    assert result.success is True
    assert result.value == "swing"


async def test_get_supported_modes(unit):
    unit._profile = {"hasModeHeat": True, "hasModeDry": True, "hasModeVent": False, "hasModeAuto": True}
    modes = unit.supported_modes
    assert Mode.OFF in modes
    assert Mode.COOL in modes
    assert Mode.HEAT in modes
    assert Mode.DRY in modes
    assert Mode.FAN not in modes
    assert Mode.AUTO in modes


async def test_get_supported_fan_speeds_5(unit):
    unit._profile = {"numberOfFanSpeeds": 5, "hasFanSpeedAuto": True}
    speeds = unit.supported_fan_speeds
    assert FanSpeed.SUPER_QUIET in speeds
    assert FanSpeed.AUTO in speeds
    assert len(speeds) == 6


async def test_get_supported_fan_speeds_3(unit):
    unit._profile = {"numberOfFanSpeeds": 3, "hasFanSpeedAuto": False}
    speeds = unit.supported_fan_speeds
    assert speeds == [FanSpeed.QUIET, FanSpeed.LOW, FanSpeed.POWERFUL]


async def test_get_supported_vane_directions(unit):
    unit._profile = {"hasVaneDir": True, "hasVaneSwing": True}
    dirs = unit.supported_vane_directions
    assert VaneDirection.SWING in dirs
    assert VaneDirection.AUTO in dirs


async def test_get_supported_vane_directions_none(unit):
    unit._profile = {"hasVaneDir": False}
    dirs = unit.supported_vane_directions
    assert dirs == []
