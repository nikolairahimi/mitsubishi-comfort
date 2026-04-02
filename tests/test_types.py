"""Tests for mitsubishi_comfort.types."""

from mitsubishi_comfort.types import (
    CommandResult,
    DeviceInfo,
    DeviceStatus,
    FanSpeed,
    Mode,
    VaneDirection,
)


def test_mode_values():
    assert Mode.OFF.value == "off"
    assert Mode.COOL.value == "cool"
    assert Mode.HEAT.value == "heat"
    assert Mode.DRY.value == "dry"
    assert Mode.FAN.value == "vent"
    assert Mode.AUTO.value == "auto"


def test_fan_speed_values():
    assert FanSpeed.SUPER_QUIET.value == "superQuiet"
    assert FanSpeed.QUIET.value == "quiet"
    assert FanSpeed.LOW.value == "low"
    assert FanSpeed.POWERFUL.value == "powerful"
    assert FanSpeed.SUPER_POWERFUL.value == "superPowerful"
    assert FanSpeed.AUTO.value == "auto"


def test_vane_direction_values():
    assert VaneDirection.HORIZONTAL.value == "horizontal"
    assert VaneDirection.MID_HORIZONTAL.value == "midhorizontal"
    assert VaneDirection.MIDPOINT.value == "midpoint"
    assert VaneDirection.MID_VERTICAL.value == "midvertical"
    assert VaneDirection.VERTICAL.value == "vertical"
    assert VaneDirection.AUTO.value == "auto"
    assert VaneDirection.SWING.value == "swing"


def test_command_result_success():
    result = CommandResult(success=True, value=22.0)
    assert result.success is True
    assert result.value == 22.0


def test_command_result_failure():
    result = CommandResult(success=False)
    assert result.success is False
    assert result.value is None


def test_device_info():
    info = DeviceInfo(
        serial="W123456",
        label="Living Room",
        address="192.168.1.100",
        mac="24CD8D112233",
        unit_type="ductless",
        password="base64password",
        crypto_serial="aabbccdd00112233ff",
    )
    assert info.serial == "W123456"
    assert info.label == "Living Room"
    assert info.is_indoor_unit is True


def test_device_info_headless():
    info = DeviceInfo(
        serial="S999",
        label="Outdoor",
        address="192.168.1.101",
        mac="",
        unit_type="headless",
        password="pw",
        crypto_serial="00",
    )
    assert info.is_indoor_unit is False


def test_device_status_defaults():
    status = DeviceStatus()
    assert status.mode is None
    assert status.standby is None
    assert status.heat_setpoint is None
    assert status.cool_setpoint is None
    assert status.room_temperature is None
    assert status.fan_speed is None
    assert status.vane_direction is None
    assert status.filter_dirty is None
    assert status.defrost is None
    assert status.current_humidity is None
    assert status.outdoor_temperature is None
    assert status.wifi_rssi is None
    assert status.sensor_battery is None
    assert status.sensor_rssi is None
    assert status.run_state is None
