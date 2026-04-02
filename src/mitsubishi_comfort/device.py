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
    ) -> None:
        self._name = name
        self._address = address
        self._serial = serial
        self._password = base64.b64decode(password_b64)
        self._crypto_serial = bytearray.fromhex(crypto_serial_hex)
        self._connect_timeout = connect_timeout
        self._response_timeout = response_timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def address(self) -> str | None:
        return self._address

    @property
    def serial(self) -> str:
        return self._serial

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
        timeout = aiohttp.ClientTimeout(
            sock_connect=self._connect_timeout,
            sock_read=self._response_timeout,
        )

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(
                    url, headers=headers, data=post_data, params={"m": token}
                ) as resp:
                    return await resp.json(content_type=None)
        except TimeoutError:
            _LOGGER.warning("Device %s: timeout reaching %s", self._name, url)
        except Exception as ex:
            _LOGGER.warning("Device %s: error reaching %s: %s", self._name, url, ex)
        return {}
