"""Shared indoor unit state, capabilities, and command validation."""

from __future__ import annotations

import logging
import math

from .types import CommandResult, DeviceStatus, FanSpeed, Mode, VaneDirection

_LOGGER = logging.getLogger(__name__)


_FAN_SPEEDS_BY_COUNT = {
    3: [FanSpeed.QUIET, FanSpeed.LOW, FanSpeed.POWERFUL],
    4: [FanSpeed.QUIET, FanSpeed.LOW, FanSpeed.POWERFUL, FanSpeed.SUPER_POWERFUL],
    5: [
        FanSpeed.SUPER_QUIET,
        FanSpeed.QUIET,
        FanSpeed.LOW,
        FanSpeed.POWERFUL,
        FanSpeed.SUPER_POWERFUL,
    ],
}

_BASE_VANE_DIRECTIONS = [
    VaneDirection.HORIZONTAL,
    VaneDirection.MID_HORIZONTAL,
    VaneDirection.MIDPOINT,
    VaneDirection.MID_VERTICAL,
    VaneDirection.VERTICAL,
    VaneDirection.AUTO,
]


class IndoorUnitControls:
    """Transport-independent indoor unit controls."""

    _name: str
    _status: DeviceStatus
    _profile: dict

    @property
    def status(self) -> DeviceStatus:
        return self._status

    @property
    def supported_modes(self) -> list[Mode]:
        modes = [Mode.OFF, Mode.COOL]
        if self._profile.get("hasModeHeat"):
            modes.append(Mode.HEAT)
        if self._profile.get("hasModeDry"):
            modes.append(Mode.DRY)
        if self._profile.get("hasModeVent"):
            modes.append(Mode.FAN)
        if self._profile.get("hasModeAuto"):
            modes.append(Mode.AUTO)
        return modes

    def _compute_has_mode_auto(self, auto_mode_prevention: bool) -> bool:
        """Whether the unit supports auto (heat/cool changeover) mode.

        The adapter's ``autoModePrevention`` flag is honored, but some installer
        configurations report it ``True`` even though the unit (and the
        Mitsubishi Comfort app) still treat auto as supported. In that case the
        unit profile's auto setpoint range is the ground truth, so fall back to
        checking ``minimumSetPoints``/``maximumSetPoints`` for an ``"auto"`` key.

        Ported from pykumo's fix of the same issue (dlarrick/pykumo commit
        211b4fc, contributed by Jon Gordner).
        """
        if not auto_mode_prevention:
            return True
        min_sp = self._profile.get("minimumSetPoints", {}) or {}
        max_sp = self._profile.get("maximumSetPoints", {}) or {}
        return "auto" in min_sp or "auto" in max_sp

    @property
    def supported_fan_speeds(self) -> list[FanSpeed]:
        count = self._profile.get("numberOfFanSpeeds", 5)
        speeds = list(_FAN_SPEEDS_BY_COUNT.get(count, _FAN_SPEEDS_BY_COUNT[5]))
        if self._profile.get("hasFanSpeedAuto"):
            speeds.append(FanSpeed.AUTO)
        return speeds

    @property
    def supported_vane_directions(self) -> list[VaneDirection]:
        if not self._profile.get("hasVaneDir"):
            return []
        dirs = list(_BASE_VANE_DIRECTIONS)
        if self._profile.get("hasVaneSwing"):
            dirs.append(VaneDirection.SWING)
        return dirs

    async def _send_command(self, field: str, value: str | float) -> CommandResult:
        raise NotImplementedError

    def _valid_setpoint(
        self, label: str, temp: float, low: float | None, high: float | None
    ) -> bool:
        """Reject non-finite or out-of-range setpoints before sending them.

        Range bounds come from the unit profile (populated after the first
        poll); when a bound is unknown it is not enforced. A non-finite value
        would also serialize to invalid JSON, so it is always rejected.
        """
        if not math.isfinite(temp):
            _LOGGER.warning(
                "Device %s: %s setpoint %s is not a finite number",
                self._name,
                label,
                temp,
            )
            return False
        if low is not None and temp < low:
            _LOGGER.warning(
                "Device %s: %s setpoint %s below minimum %s",
                self._name,
                label,
                temp,
                low,
            )
            return False
        if high is not None and temp > high:
            _LOGGER.warning(
                "Device %s: %s setpoint %s above maximum %s",
                self._name,
                label,
                temp,
                high,
            )
            return False
        return True

    async def set_mode(self, mode: Mode) -> CommandResult:
        if mode not in self.supported_modes:
            _LOGGER.warning("Device %s: mode %s not supported", self._name, mode.value)
            return CommandResult(success=False)
        return await self._send_command("mode", mode.value)

    def _effective_bounds(
        self, mode_low: float | None, mode_high: float | None
    ) -> tuple[float | None, float | None]:
        """Widen a mode's setpoint range with the auto-changeover range.

        In AUTO mode the unit accepts setpoints across its (often wider) auto
        range, and the last-polled mode may lag a mode the user just set, so
        the effective bound is the union of the mode range and the auto range.
        This validates against the widest range the device could accept,
        rejecting only values out of range for every mode.
        """
        lows = [b for b in (mode_low, self._status.min_auto_setpoint) if b is not None]
        highs = [
            b for b in (mode_high, self._status.max_auto_setpoint) if b is not None
        ]
        return (min(lows) if lows else None, max(highs) if highs else None)

    async def set_cool_setpoint(self, temperature: float) -> CommandResult:
        temp = round(float(temperature), 1)
        low, high = self._effective_bounds(
            self._status.min_cool_setpoint, self._status.max_cool_setpoint
        )
        if not self._valid_setpoint("cool", temp, low, high):
            return CommandResult(success=False)
        return await self._send_command("spCool", temp)

    async def set_heat_setpoint(self, temperature: float) -> CommandResult:
        temp = round(float(temperature), 1)
        low, high = self._effective_bounds(
            self._status.min_heat_setpoint, self._status.max_heat_setpoint
        )
        if not self._valid_setpoint("heat", temp, low, high):
            return CommandResult(success=False)
        return await self._send_command("spHeat", temp)

    async def set_fan_speed(self, speed: FanSpeed) -> CommandResult:
        if speed not in self.supported_fan_speeds:
            _LOGGER.warning(
                "Device %s: fan speed %s not supported", self._name, speed.value
            )
            return CommandResult(success=False)
        return await self._send_command("fanSpeed", speed.value)

    async def set_vane_direction(self, direction: VaneDirection) -> CommandResult:
        if direction not in self.supported_vane_directions:
            _LOGGER.warning(
                "Device %s: vane direction %s not supported",
                self._name,
                direction.value,
            )
            return CommandResult(success=False)
        return await self._send_command("vaneDir", direction.value)
