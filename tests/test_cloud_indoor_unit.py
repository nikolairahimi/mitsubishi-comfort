"""Cloud climate state and command contracts."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from mitsubishi_comfort import (
    CloudIndoorUnit,
    DeviceInfo,
    FanSpeed,
    MitsubishiCloudAccount,
    Mode,
    VaneDirection,
)
from mitsubishi_comfort.exceptions import CommandError


@pytest.fixture
def account() -> AsyncMock:
    account = AsyncMock(spec=MitsubishiCloudAccount)
    account.get_device_details.return_value = {
        "connected": True,
        "power": 1,
        "operationMode": "cool",
        "spCool": 24,
        "spHeat": 20,
        "fanSpeed": "auto",
        "airDirection": "swing",
    }
    account.get_zone_state.return_value = {"roomTemp": 23.5, "humidity": 45}
    account.get_device_profile.return_value = {
        "hasModeHeat": True,
        "hasModeDry": True,
        "hasModeFan": True,
        "numberOfFanSpeeds": 3,
        "hasFanSpeedAuto": True,
        "hasVaneDir": True,
        "hasVaneSwing": True,
        "minimumSetPoints": {"cool": 18, "heat": 16, "auto": 16},
        "maximumSetPoints": {"cool": 30, "heat": 28, "auto": 30},
    }
    account.get_device_status.return_value = {"firmwareVersion": "1.2"}
    return account


@pytest.fixture
def device(account: AsyncMock) -> CloudIndoorUnit:
    return CloudIndoorUnit(
        DeviceInfo("SER001", "Bedroom", "", "", "ductless", "", "", site_id="site1"),
        account,
    )


@pytest.mark.parametrize("command_first", [False, True])
def test_unit_constructed_before_run_serializes_poll_and_command(
    device: CloudIndoorUnit, account: AsyncMock, command_first: bool
) -> None:
    async def run() -> None:
        active = 0
        peak = 0

        async def operation(*args: object) -> dict:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            return {"power": 1, "operationMode": "cool"}

        account.get_device_details.side_effect = operation
        account.send_command.side_effect = operation
        calls = [device.update_status(), device.set_mode(Mode.OFF)]
        if command_first:
            calls.reverse()
        await asyncio.wait_for(asyncio.gather(*calls), timeout=1)
        assert peak == 1
        account.send_command.assert_awaited_once_with(
            "SER001", {"operationMode": "off"}
        )
        assert device.status.mode == "cool"

    asyncio.run(run())


async def test_status_and_capabilities(
    device: CloudIndoorUnit, account: AsyncMock
) -> None:
    assert await device.update_status()
    assert device.status.room_temperature == 23.5
    assert device.status.current_humidity == 45
    assert device.status.mode == "cool"
    assert device.status.cool_setpoint == 24
    assert device.status.min_heat_setpoint == 16
    assert device.status.firmware_version == "1.2"
    assert device.supported_modes == [
        Mode.OFF,
        Mode.COOL,
        Mode.HEAT,
        Mode.DRY,
        Mode.FAN,
        Mode.AUTO,
    ]
    assert device.supported_fan_speeds == [
        FanSpeed.QUIET,
        FanSpeed.LOW,
        FanSpeed.POWERFUL,
        FanSpeed.AUTO,
    ]
    assert VaneDirection.SWING in device.supported_vane_directions
    assert device.address is None
    assert await device.update_status()
    account.get_device_profile.assert_awaited_once()
    await device.close()
    account.close.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "value", "payload"),
    [
        pytest.param("set_mode", Mode.OFF, {"operationMode": "off"}, id="off"),
        pytest.param("set_mode", Mode.HEAT, {"operationMode": "heat"}, id="heat"),
        pytest.param("set_mode", Mode.AUTO, {"operationMode": "auto"}, id="auto"),
        pytest.param("set_cool_setpoint", 24.5, {"spCool": 24.5}, id="cool-setpoint"),
        pytest.param("set_heat_setpoint", 20.5, {"spHeat": 20.5}, id="heat-setpoint"),
        pytest.param("set_fan_speed", FanSpeed.AUTO, {"fanSpeed": "auto"}, id="fan"),
        pytest.param(
            "set_vane_direction",
            VaneDirection.SWING,
            {"airDirection": "swing"},
            id="vane",
        ),
    ],
)
async def test_commands(
    device: CloudIndoorUnit,
    account: AsyncMock,
    method: str,
    value: Mode | FanSpeed | VaneDirection | float,
    payload: dict,
) -> None:
    await device.update_status()
    status = device.status
    result = await getattr(device, method)(value)
    assert result.success
    account.send_command.assert_awaited_once_with("SER001", payload)
    assert device.status is status


@pytest.mark.parametrize("temperature", [float("nan"), float("inf"), 40, 10])
async def test_reject_invalid_temperature(
    device: CloudIndoorUnit,
    account: AsyncMock,
    temperature: float,
) -> None:
    await device.update_status()
    assert not (await device.set_cool_setpoint(temperature)).success
    account.send_command.assert_not_awaited()


async def test_command_rejection_preserves_state(
    device: CloudIndoorUnit, account: AsyncMock
) -> None:
    await device.update_status()
    account.send_command.side_effect = CommandError("rejected")
    with pytest.raises(CommandError):
        await device.set_mode(Mode.HEAT)
    assert device.status.mode == "cool"


@pytest.mark.parametrize(
    "raw", [{"connected": False}, {"connected": 0}, {}, {"firmwareVersion": "1"}]
)
async def test_offline_and_missing_state(
    device: CloudIndoorUnit,
    account: AsyncMock,
    raw: dict,
) -> None:
    account.get_zone_state.return_value = {}
    account.get_device_details.return_value = raw
    assert not await device.update_status()


async def test_power_off_overrides_mode(
    device: CloudIndoorUnit, account: AsyncMock
) -> None:
    account.get_device_details.return_value["power"] = 0
    assert await device.update_status()
    assert device.status.mode == "off"
