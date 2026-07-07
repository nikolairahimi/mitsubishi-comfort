"""Indoor unit control for Mitsubishi minisplits."""

from __future__ import annotations

import json
import logging
import math

from .const import PROFILE_REFRESH_POLLS
from .device import Device
from .types import CommandResult, DeviceStatus, FanSpeed, Mode, VaneDirection

_LOGGER = logging.getLogger(__name__)


def _coerce_float(value: object) -> float | None:
    """Best-effort float from a profile value; None if absent or non-numeric."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

_FAN_SPEEDS_BY_COUNT = {
    3: [FanSpeed.QUIET, FanSpeed.LOW, FanSpeed.POWERFUL],
    4: [FanSpeed.QUIET, FanSpeed.LOW, FanSpeed.POWERFUL, FanSpeed.SUPER_POWERFUL],
    5: [FanSpeed.SUPER_QUIET, FanSpeed.QUIET, FanSpeed.LOW, FanSpeed.POWERFUL, FanSpeed.SUPER_POWERFUL],
}

_BASE_VANE_DIRECTIONS = [
    VaneDirection.HORIZONTAL,
    VaneDirection.MID_HORIZONTAL,
    VaneDirection.MIDPOINT,
    VaneDirection.MID_VERTICAL,
    VaneDirection.VERTICAL,
    VaneDirection.AUTO,
]


class IndoorUnit(Device):
    """An indoor minisplit unit with full mode/setpoint/fan/vane control."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._status = DeviceStatus()
        self._profile: dict = {}
        self._profile_fetched = False
        self._polls_since_profile = 0
        self._has_mhk2: bool = True

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

    async def _refresh_status(self) -> bool:
        """Fetch current status, profile, and sensors. Returns True on success."""
        # Indoor unit status (always fetch)
        query = b'{"c":{"indoorUnit":{"status":{}}}}'
        response = await self.request(query)
        try:
            raw = response["r"]["indoorUnit"]["status"]
        except (KeyError, TypeError):
            _LOGGER.warning("Device %s: failed to retrieve status", self._name)
            return False

        # Sensors (always fetch)
        sensors = await self._fetch_sensors()

        # Profile, adapter status, adapter info, MHK2 — only when (re)fetching
        # the profile; otherwise cheaper polls carry these forward.
        min_cool_sp = None
        max_cool_sp = None
        min_heat_sp = None
        max_heat_sp = None
        min_auto_sp = None
        max_auto_sp = None
        firmware_version = None
        hardware_version = None
        uptime = None
        wifi_rssi = None
        run_state = None
        mhk2_humidity = None

        # Re-fetch the profile on the first poll and periodically thereafter so
        # cached capabilities and setpoint limits self-heal after a firmware or
        # configuration change.
        refresh_profile = (
            not self._profile_fetched
            or self._polls_since_profile >= PROFILE_REFRESH_POLLS
        )

        if refresh_profile:
            # Profile
            query = b'{"c":{"indoorUnit":{"profile":{}}}}'
            response = await self.request(query)
            try:
                self._profile = response["r"]["indoorUnit"]["profile"]
            except (KeyError, TypeError):
                if not self._profile_fetched:
                    _LOGGER.warning("Device %s: failed to retrieve profile", self._name)
                    return False
                # A periodic refresh failed transiently: keep the last good
                # profile (and re-derive its bounds below) rather than failing
                # an otherwise-healthy poll. Retried on the next interval.
                _LOGGER.debug("Device %s: profile refresh failed; keeping cached", self._name)

            # Read setpoint limits from profile (last-good if a refresh failed).
            # Bounds are coerced to float so a stringified limit can't crash the
            # setpoint range check.
            min_sp = self._profile.get("minimumSetPoints", {})
            max_sp = self._profile.get("maximumSetPoints", {})
            min_cool_sp = _coerce_float(min_sp.get("cool"))
            min_heat_sp = _coerce_float(min_sp.get("heat"))
            min_auto_sp = _coerce_float(min_sp.get("auto"))
            max_cool_sp = _coerce_float(max_sp.get("cool"))
            max_heat_sp = _coerce_float(max_sp.get("heat"))
            max_auto_sp = _coerce_float(max_sp.get("auto"))

            # Adapter status
            query = b'{"c":{"adapter":{"status":{}}}}'
            response = await self.request(query)
            try:
                adapter = response["r"]["adapter"]["status"]
                self._profile["hasModeAuto"] = self._compute_has_mode_auto(
                    adapter.get("autoModePrevention", False)
                )
                if not adapter.get("userHasModeDry", False):
                    self._profile["hasModeDry"] = False
                if not adapter.get("userHasModeHeat", False):
                    self._profile["hasModeHeat"] = False
                try:
                    wifi_rssi = adapter["localNetwork"]["stationMode"]["RSSI"]
                except KeyError:
                    wifi_rssi = None
                run_state = adapter.get("runState")
                uptime = adapter.get("uptime")
            except (KeyError, TypeError):
                _LOGGER.warning("Device %s: failed to retrieve adapter status", self._name)
                return False

            # Adapter info (firmware/hardware versions)
            query = b'{"c":{"adapter":{"info":{}}}}'
            response = await self.request(query)
            try:
                adapter_info = response["r"]["adapter"]["info"]
                firmware_version = adapter_info.get("firmwareVersion")
                hardware_version = adapter_info.get("hardwareVersion")
            except (KeyError, TypeError):
                _LOGGER.debug("Device %s: could not retrieve adapter info", self._name)

            # MHK2 humidity (optional)
            if self._has_mhk2:
                query = b'{"c":{"mhk2":{"status":{}}}}'
                response = await self.request(query)
                try:
                    mhk2 = response.get("r", {}).get("mhk2")
                    if isinstance(mhk2, dict) and mhk2.get("status"):
                        mhk2_humidity = mhk2.get("status", {}).get("indoorHumid")
                    else:
                        self._has_mhk2 = False
                except (KeyError, TypeError):
                    self._has_mhk2 = False

            self._profile_fetched = True
            self._polls_since_profile = 0
        else:
            self._polls_since_profile += 1
            # Subsequent polls: only fetch adapter status for wifi/run_state/uptime
            query = b'{"c":{"adapter":{"status":{}}}}'
            response = await self.request(query)
            try:
                adapter = response["r"]["adapter"]["status"]
                try:
                    wifi_rssi = adapter["localNetwork"]["stationMode"]["RSSI"]
                except KeyError:
                    wifi_rssi = None
                run_state = adapter.get("runState")
                uptime = adapter.get("uptime")
            except (KeyError, TypeError):
                _LOGGER.warning("Device %s: failed to retrieve adapter status", self._name)
                wifi_rssi = self._status.wifi_rssi
                run_state = self._status.run_state
                uptime = self._status.uptime

            # MHK2 humidity (optional, skip if previously returned no data)
            if self._has_mhk2:
                query = b'{"c":{"mhk2":{"status":{}}}}'
                response = await self.request(query)
                try:
                    mhk2 = response.get("r", {}).get("mhk2")
                    if isinstance(mhk2, dict) and mhk2.get("status"):
                        mhk2_humidity = mhk2.get("status", {}).get("indoorHumid")
                    else:
                        self._has_mhk2 = False
                except (KeyError, TypeError):
                    self._has_mhk2 = False

            # Carry forward cached values from previous status
            min_cool_sp = self._status.min_cool_setpoint
            max_cool_sp = self._status.max_cool_setpoint
            min_heat_sp = self._status.min_heat_setpoint
            max_heat_sp = self._status.max_heat_setpoint
            min_auto_sp = self._status.min_auto_setpoint
            max_auto_sp = self._status.max_auto_setpoint
            firmware_version = self._status.firmware_version
            hardware_version = self._status.hardware_version

        # Build status
        humidity = None
        sensor_battery = None
        sensor_rssi = None
        for sensor in sensors:
            if humidity is None and sensor.get("humidity") is not None:
                humidity = sensor["humidity"]
            if sensor_battery is None and sensor.get("battery") is not None:
                sensor_battery = sensor["battery"]
            if sensor_rssi is None and sensor.get("rssi") is not None:
                sensor_rssi = sensor["rssi"]
        if humidity is None and mhk2_humidity is not None:
            humidity = mhk2_humidity

        self._status = DeviceStatus(
            mode=raw.get("mode"),
            standby=raw.get("standby"),
            heat_setpoint=raw.get("spHeat"),
            cool_setpoint=raw.get("spCool"),
            room_temperature=raw.get("roomTemp"),
            fan_speed=raw.get("fanSpeed"),
            vane_direction=raw.get("vaneDir"),
            vane_left_right=raw.get("vaneLR"),
            filter_dirty=raw.get("filterDirty"),
            defrost=raw.get("defrost"),
            current_humidity=humidity,
            wifi_rssi=wifi_rssi,
            sensor_battery=sensor_battery,
            sensor_rssi=sensor_rssi,
            run_state=run_state,
            uptime=uptime,
            firmware_version=firmware_version,
            hardware_version=hardware_version,
            min_cool_setpoint=min_cool_sp,
            max_cool_setpoint=max_cool_sp,
            min_heat_setpoint=min_heat_sp,
            max_heat_setpoint=max_heat_sp,
            min_auto_setpoint=min_auto_sp,
            max_auto_setpoint=max_auto_sp,
        )
        return True

    async def _send_command(self, field: str, value: str | float) -> CommandResult:
        payload = {"c": {"indoorUnit": {"status": {field: value}}}}
        command = json.dumps(payload, separators=(",", ":")).encode()
        async with self._burst():
            response = await self.request(command)
        if "r" in response:
            return CommandResult(success=True, value=value)
        return CommandResult(success=False)

    def _valid_setpoint(
        self, label: str, temp: float, low: float | None, high: float | None
    ) -> bool:
        """Reject non-finite or out-of-range setpoints before sending them.

        Range bounds come from the unit profile (populated after the first
        poll); when a bound is unknown it is not enforced. A non-finite value
        would also serialize to invalid JSON, so it is always rejected.
        """
        if not math.isfinite(temp):
            _LOGGER.warning("Device %s: %s setpoint %s is not a finite number", self._name, label, temp)
            return False
        if low is not None and temp < low:
            _LOGGER.warning("Device %s: %s setpoint %s below minimum %s", self._name, label, temp, low)
            return False
        if high is not None and temp > high:
            _LOGGER.warning("Device %s: %s setpoint %s above maximum %s", self._name, label, temp, high)
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
        highs = [b for b in (mode_high, self._status.max_auto_setpoint) if b is not None]
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
            _LOGGER.warning("Device %s: fan speed %s not supported", self._name, speed.value)
            return CommandResult(success=False)
        return await self._send_command("fanSpeed", speed.value)

    async def set_vane_direction(self, direction: VaneDirection) -> CommandResult:
        if direction not in self.supported_vane_directions:
            _LOGGER.warning("Device %s: vane direction %s not supported", self._name, direction.value)
            return CommandResult(success=False)
        return await self._send_command("vaneDir", direction.value)
