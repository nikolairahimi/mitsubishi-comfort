"""Base async device communication for the Mitsubishi local HTTP API."""

from __future__ import annotations

import base64
import logging
from typing import Any

import aiohttp

from .auth import compute_token
from .const import DEFAULT_CONNECT_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class Device:
    """Low-level async communication with a single Mitsubishi unit over LAN."""

    def __init__(
        self,
        name: str,
        address: str | None,
        password_b64: str,
        crypto_serial_hex: str,
        serial: str,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._name = name
        self._address = address
        self._serial = serial
        self._connect_timeout = connect_timeout
        self._response_timeout = response_timeout
        self._session = session
        self._owns_session = session is None

        try:
            self._password = base64.b64decode(password_b64)
        except Exception:
            _LOGGER.warning("Device %s: invalid base64 password, disabling requests", name)
            self._password = b""
            self._address = None

        try:
            self._crypto_serial = bytearray.fromhex(crypto_serial_hex)
        except Exception:
            _LOGGER.warning("Device %s: invalid hex crypto serial, disabling requests", name)
            self._crypto_serial = bytearray()
            self._address = None
        else:
            if len(self._crypto_serial) < 9:
                _LOGGER.warning(
                    "Device %s: crypto serial too short (%d bytes), disabling requests",
                    name,
                    len(self._crypto_serial),
                )
                self._address = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def address(self) -> str | None:
        return self._address

    @property
    def serial(self) -> str:
        return self._serial

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(
                sock_connect=self._connect_timeout,
                sock_read=self._response_timeout,
            ))
            self._owns_session = True
        return self._session

    async def _fetch_sensors(self) -> list[dict]:
        """Fetch external sensor data from all slots."""
        from .const import MAX_SENSORS
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
        return sensors

    async def close(self) -> None:
        """Close the underlying HTTP session if owned by this device."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def request(self, post_data: bytes) -> dict[str, Any]:
        """Send an authenticated request to the device's local API.

        Returns the JSON response dict, or {} on any failure.
        """
        if not self._address:
            _LOGGER.warning("Device %s: no address set", self._name)
            return {}

        url = f"http://{self._address}/api"
        token = compute_token(self._password, self._crypto_serial, post_data)
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }

        try:
            session = await self._get_session()
            async with session.put(
                url, headers=headers, data=post_data, params={"m": token}
            ) as resp:
                return await resp.json(content_type=None)
        except TimeoutError:
            _LOGGER.warning("Device %s: timeout reaching %s", self._name, url)
        except Exception as ex:
            _LOGGER.warning("Device %s: error reaching %s: %s", self._name, url, ex)
        return {}
