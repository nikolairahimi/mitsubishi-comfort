"""Indoor unit control through the Mitsubishi Comfort cloud."""

from __future__ import annotations

import asyncio

from .cloud import MitsubishiCloudAccount
from .const import PROFILE_REFRESH_POLLS
from .indoor_unit import _coerce_float
from .indoor_unit_controls import IndoorUnitControls
from .types import CommandResult, DeviceInfo, DeviceStatus, FanSpeed, Mode


class CloudIndoorUnit(IndoorUnitControls):
    """An indoor unit using an account-owned cloud connection."""

    def __init__(self, info: DeviceInfo, account: MitsubishiCloudAccount) -> None:
        self._name = info.label
        self._serial = info.serial
        self._site_id = info.site_id
        self._account = account
        self._status = DeviceStatus()
        self._profile: dict = {}
        self._metadata: dict = {}
        self._polls_since_profile = 0
        self._lock: asyncio.Lock | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def address(self) -> None:
        """Cloud devices do not require a LAN address."""
        return None

    @property
    def supported_modes(self) -> list[Mode]:
        modes = [Mode.OFF]
        maximum = self._profile.get("maximumSetPoints", {})
        for mode, flag in (
            (Mode.COOL, "hasModeCool"),
            (Mode.HEAT, "hasModeHeat"),
            (Mode.DRY, "hasModeDry"),
            (Mode.FAN, "hasModeVent"),
            (Mode.AUTO, "hasModeAuto"),
        ):
            if self._profile.get(flag) or mode.value in maximum:
                modes.append(mode)
        return modes

    @property
    def supported_fan_speeds(self) -> list[FanSpeed]:
        if not self._profile.get("numberOfFanSpeeds"):
            return [FanSpeed.AUTO] if self._profile.get("hasFanSpeedAuto") else []
        return super().supported_fan_speeds

    async def close(self) -> None:
        """The shared account's lifetime is managed by the caller."""

    async def update_status(self) -> bool:
        """Refresh actual device state without merging submitted commands."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            zone = (
                await self._account.get_zone_state(self._site_id, self.serial)
                if self._site_id
                else {}
            )
            raw = {**zone, **await self._account.get_device_details(self.serial)}
            if raw.get("connected") is False or raw.get("connected") == 0:
                return False
            if not any(key in raw for key in ("operationMode", "roomTemp", "power")):
                return False
            if not self._profile or self._polls_since_profile >= PROFILE_REFRESH_POLLS:
                profile = await self._account.get_device_profile(self.serial)
                metadata = await self._account.get_device_status(self.serial)
                self._metadata = metadata if isinstance(metadata, dict) else {}
                self._profile = profile
                self._profile["hasModeVent"] = profile.get(
                    "hasModeVent", profile.get("hasModeFan", False)
                )
                self._polls_since_profile = 0
            self._polls_since_profile += 1
            minimum = self._profile.get("minimumSetPoints", {})
            maximum = self._profile.get("maximumSetPoints", {})
            self._status = DeviceStatus(
                mode="off" if raw.get("power") == 0 else raw.get("operationMode"),
                heat_setpoint=_coerce_float(raw.get("spHeat")),
                cool_setpoint=_coerce_float(raw.get("spCool")),
                room_temperature=_coerce_float(raw.get("roomTemp")),
                current_humidity=_coerce_float(raw.get("humidity")),
                fan_speed=raw.get("fanSpeed"),
                vane_direction=raw.get("airDirection"),
                firmware_version=self._metadata.get("firmwareVersion"),
                hardware_version=self._metadata.get("hardwareVersion"),
                min_cool_setpoint=_coerce_float(minimum.get("cool")),
                max_cool_setpoint=_coerce_float(maximum.get("cool")),
                min_heat_setpoint=_coerce_float(minimum.get("heat")),
                max_heat_setpoint=_coerce_float(maximum.get("heat")),
                min_auto_setpoint=_coerce_float(minimum.get("auto")),
                max_auto_setpoint=_coerce_float(maximum.get("auto")),
            )
            return True

    async def _send_command(self, field: str, value: str | float) -> CommandResult:
        """Submit an absolute setting; the next poll confirms actual state."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        cloud_field = {"mode": "operationMode", "vaneDir": "airDirection"}.get(
            field, field
        )
        async with self._lock:
            await self._account.send_command(self.serial, {cloud_field: value})
        return CommandResult(success=True, value=value)
