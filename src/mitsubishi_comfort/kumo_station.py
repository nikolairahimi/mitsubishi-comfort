"""KumoStation device (headless outdoor unit with temperature sensor)."""

from __future__ import annotations

import logging

from .device import Device
from .types import DeviceStatus

_LOGGER = logging.getLogger(__name__)


class KumoStation(Device):
    """A headless Kumo Station unit (outdoor temperature + sensors only)."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._status = DeviceStatus()

    @property
    def status(self) -> DeviceStatus:
        return self._status

    async def update_status(self) -> bool:
        """Poll the station for outdoor temperature, sensors, and WiFi RSSI."""
        query = b'{"c":{"eqc":{"oat":{}}}}'
        response = await self.request(query)
        try:
            outdoor_temp = response["r"]["eqc"]["oat"]
        except (KeyError, TypeError):
            _LOGGER.warning("Device %s: failed to retrieve outdoor temperature", self._name)
            return False

        sensors = await self._fetch_sensors()

        query = b'{"c":{"adapter":{"status":{}}}}'
        response = await self.request(query)
        try:
            wifi_rssi = response["r"]["adapter"]["status"]["localNetwork"]["stationMode"]["RSSI"]
        except (KeyError, TypeError):
            wifi_rssi = None

        sensor_rssi = None
        for sensor in sensors:
            if sensor.get("rssi") is not None:
                sensor_rssi = sensor["rssi"]
                break

        self._status = DeviceStatus(
            outdoor_temperature=outdoor_temp,
            wifi_rssi=wifi_rssi,
            sensor_rssi=sensor_rssi,
        )
        return True
