"""Types, enums, and dataclasses for mitsubishi_comfort."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Mode(Enum):
    """HVAC operating modes (values match the local API protocol)."""
    OFF = "off"
    COOL = "cool"
    HEAT = "heat"
    DRY = "dry"
    FAN = "vent"
    AUTO = "auto"


class FanSpeed(Enum):
    """Fan speed settings (values match the local API protocol)."""
    SUPER_QUIET = "superQuiet"
    QUIET = "quiet"
    LOW = "low"
    POWERFUL = "powerful"
    SUPER_POWERFUL = "superPowerful"
    AUTO = "auto"


class VaneDirection(Enum):
    """Vane direction settings (values match the local API protocol)."""
    HORIZONTAL = "horizontal"
    MID_HORIZONTAL = "midhorizontal"
    MIDPOINT = "midpoint"
    MID_VERTICAL = "midvertical"
    VERTICAL = "vertical"
    AUTO = "auto"
    SWING = "swing"


@dataclass(frozen=True)
class CommandResult:
    """Result of a command sent to a device."""
    success: bool
    value: Any = None


@dataclass
class DeviceInfo:
    """Static info about a discovered device."""
    serial: str
    label: str
    address: str
    mac: str
    unit_type: str
    password: str
    crypto_serial: str

    @property
    def is_indoor_unit(self) -> bool:
        return self.unit_type != "headless"


@dataclass
class DeviceStatus:
    """Mutable snapshot of a device's current state."""
    mode: str | None = None
    standby: bool | None = None
    heat_setpoint: float | None = None
    cool_setpoint: float | None = None
    room_temperature: float | None = None
    fan_speed: str | None = None
    vane_direction: str | None = None
    filter_dirty: bool | None = None
    defrost: bool | None = None
    current_humidity: float | None = None
    outdoor_temperature: float | None = None
    wifi_rssi: int | None = None
    sensor_battery: int | None = None
    sensor_rssi: int | None = None
    run_state: str | None = None
    vane_left_right: str | None = None
    uptime: int | None = None
    firmware_version: str | None = None
    hardware_version: str | None = None
    min_cool_setpoint: float | None = None
    max_cool_setpoint: float | None = None
    min_heat_setpoint: float | None = None
    max_heat_setpoint: float | None = None
    min_auto_setpoint: float | None = None
    max_auto_setpoint: float | None = None
