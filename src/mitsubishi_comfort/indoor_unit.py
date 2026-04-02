"""Indoor unit control for Mitsubishi minisplits."""

from __future__ import annotations

import logging

from .const import MAX_SENSORS
from .device import Device
from .types import CommandResult, DeviceStatus, FanSpeed, Mode, VaneDirection

_LOGGER = logging.getLogger(__name__)

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
        self._sensors: list[dict] = []

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

    async def update_status(self) -> bool:
        """Poll the device for current status, profile, and sensors. Returns True on success."""
        # Indoor unit status
        query = b'{"c":{"indoorUnit":{"status":{}}}}'
        response = await self.request(query)
        try:
            raw = response["r"]["indoorUnit"]["status"]
        except (KeyError, TypeError):
            _LOGGER.warning("Device %s: failed to retrieve status", self._name)
            return False

        # Sensors
        sensors = []
        for i in range(MAX_SENSORS):
            query = f'{{"c":{{"sensors":{{"{i}":{{}}}}}}}}'.encode()
            response = await self.request(query)
            try:
                sensor = response["r"]["sensors"][str(i)]
                if isinstance(sensor, dict) and sensor.get("uuid"):
                    sensors.append(sensor)
                else:
                    break
            except (KeyError, TypeError):
                break

        # Profile
        query = b'{"c":{"indoorUnit":{"profile":{}}}}'
        response = await self.request(query)
        try:
            self._profile = response["r"]["indoorUnit"]["profile"]
        except (KeyError, TypeError):
            _LOGGER.warning("Device %s: failed to retrieve profile", self._name)
            return False

        # Adapter status
        query = b'{"c":{"adapter":{"status":{}}}}'
        response = await self.request(query)
        try:
            adapter = response["r"]["adapter"]["status"]
            self._profile["hasModeAuto"] = not adapter.get("autoModePrevention", False)
            if not adapter.get("userHasModeDry", False):
                self._profile["hasModeDry"] = False
            if not adapter.get("userHasModeHeat", False):
                self._profile["hasModeHeat"] = False
            try:
                wifi_rssi = adapter["localNetwork"]["stationMode"]["RSSI"]
            except KeyError:
                wifi_rssi = None
            run_state = adapter.get("runState")
        except (KeyError, TypeError):
            _LOGGER.warning("Device %s: failed to retrieve adapter status", self._name)
            return False

        # MHK2 humidity (optional)
        mhk2_humidity = None
        query = b'{"c":{"mhk2":{"status":{}}}}'
        response = await self.request(query)
        try:
            mhk2 = response.get("r", {}).get("mhk2")
            if isinstance(mhk2, dict):
                mhk2_humidity = mhk2.get("status", {}).get("indoorHumid")
        except (KeyError, TypeError):
            pass

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

        self._sensors = sensors
        self._status = DeviceStatus(
            mode=raw.get("mode"),
            standby=raw.get("standby"),
            heat_setpoint=raw.get("spHeat"),
            cool_setpoint=raw.get("spCool"),
            room_temperature=raw.get("roomTemp"),
            fan_speed=raw.get("fanSpeed"),
            vane_direction=raw.get("vaneDir"),
            filter_dirty=raw.get("filterDirty"),
            defrost=raw.get("defrost"),
            current_humidity=humidity,
            wifi_rssi=wifi_rssi,
            sensor_battery=sensor_battery,
            sensor_rssi=sensor_rssi,
            run_state=run_state,
        )
        return True

    async def set_mode(self, mode: Mode) -> CommandResult:
        if mode not in self.supported_modes:
            _LOGGER.warning("Device %s: mode %s not supported", self._name, mode.value)
            return CommandResult(success=False)
        command = f'{{"c":{{"indoorUnit":{{"status":{{"mode":"{mode.value}"}}}}}}}}'.encode()
        response = await self.request(command)
        if response and "r" in response:
            return CommandResult(success=True, value=mode.value)
        return CommandResult(success=False)

    async def set_cool_setpoint(self, temperature: float) -> CommandResult:
        temp = round(float(temperature), 1)
        command = f'{{"c":{{"indoorUnit":{{"status":{{"spCool":{temp}}}}}}}}}'.encode()
        response = await self.request(command)
        if response and "r" in response:
            return CommandResult(success=True, value=temp)
        return CommandResult(success=False)

    async def set_heat_setpoint(self, temperature: float) -> CommandResult:
        temp = round(float(temperature), 1)
        command = f'{{"c":{{"indoorUnit":{{"status":{{"spHeat":{temp}}}}}}}}}'.encode()
        response = await self.request(command)
        if response and "r" in response:
            return CommandResult(success=True, value=temp)
        return CommandResult(success=False)

    async def set_fan_speed(self, speed: FanSpeed) -> CommandResult:
        if speed not in self.supported_fan_speeds:
            _LOGGER.warning("Device %s: fan speed %s not supported", self._name, speed.value)
            return CommandResult(success=False)
        command = f'{{"c":{{"indoorUnit":{{"status":{{"fanSpeed":"{speed.value}"}}}}}}}}'.encode()
        response = await self.request(command)
        if response and "r" in response:
            return CommandResult(success=True, value=speed.value)
        return CommandResult(success=False)

    async def set_vane_direction(self, direction: VaneDirection) -> CommandResult:
        if direction not in self.supported_vane_directions:
            _LOGGER.warning("Device %s: vane direction %s not supported", self._name, direction.value)
            return CommandResult(success=False)
        command = f'{{"c":{{"indoorUnit":{{"status":{{"vaneDir":"{direction.value}"}}}}}}}}'.encode()
        response = await self.request(command)
        if response and "r" in response:
            return CommandResult(success=True, value=direction.value)
        return CommandResult(success=False)
