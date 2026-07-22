"""Base async device communication for the Mitsubishi local HTTP API."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import aiohttp

from .auth import compute_token
from .const import (
    CRYPTO_SERIAL_MIN_BYTES,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_RESPONSE_TIMEOUT,
)

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
        # Serializes bursts so one burst's end-of-poll disconnect() can't close
        # the shared session out from under another burst that is mid-request.
        # Created lazily on first use to bind to the running event loop.
        self._burst_lock: asyncio.Lock | None = None

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
            # Well-formed hex can still be too short to index. Cloud discovery
            # yields an empty crypto serial whenever the per-device status
            # endpoint omits cryptoSerial, and request() computes the token
            # outside its own error handling — so an unchecked short serial
            # raises IndexError out of every poll and command.
            if len(self._crypto_serial) < CRYPTO_SERIAL_MIN_BYTES:
                _LOGGER.warning(
                    "Device %s: crypto serial too short (%d bytes, need %d), "
                    "disabling requests",
                    name,
                    len(self._crypto_serial),
                    CRYPTO_SERIAL_MIN_BYTES,
                )
                self._crypto_serial = bytearray()
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

    async def disconnect(self) -> None:
        """Drop any pooled keep-alive connection to the device.

        The WiFi adapters have a very small connection table; a connection
        left idling in the pool occupies an adapter slot until the pool's
        keep-alive timer expires. Callers should invoke this once a burst of
        requests (a status poll, a command) is done, so the adapter frees
        the slot immediately. The session is recreated lazily on the next
        request.

        Only effective when the device owns its session: an injected
        session's connection pool belongs to its owner, so for LAN devices
        prefer letting each Device create its own session.
        """
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def close(self) -> None:
        """Close the underlying HTTP session if owned by this device.

        Equivalent to :meth:`disconnect`; kept as the conventional lifecycle
        name for callers that are done with the device.
        """
        await self.disconnect()

    @asynccontextmanager
    async def _burst(self):
        """Scope a burst of requests that share one pooled connection.

        When the burst ends the connection is dropped so the adapter frees
        its slot immediately instead of holding it until keep-alive expiry.

        Bursts are serialized per device: a concurrent poll and command on the
        same unit must not run at once, or one burst's closing disconnect()
        would tear down the session the other is still using — and the adapter
        only has room for one connection anyway.
        """
        if self._burst_lock is None:
            self._burst_lock = asyncio.Lock()
        async with self._burst_lock:
            try:
                yield
            finally:
                await self.disconnect()

    async def update_status(self) -> bool:
        """Poll the device and refresh its status snapshot. Returns True on success.

        The whole poll runs as one connection burst; the adapter's connection
        slot is freed as soon as the poll is done.
        """
        async with self._burst():
            return await self._refresh_status()

    async def _refresh_status(self) -> bool:
        raise NotImplementedError

    async def request(self, post_data: bytes) -> dict[str, Any]:
        """Send an authenticated request to the device's local API.

        Returns the JSON response dict, or {} on any failure.

        Call this only from within a ``_burst()`` scope (as ``update_status``
        and the command methods do). The burst lock, not this method, is what
        serializes access to the shared session, so a bare ``request()`` racing
        a concurrent burst on the same device can have its session closed
        mid-flight by that burst's end-of-poll disconnect. Serialization is
        also per-instance: distinct ``Device`` objects for one physical unit
        are not coordinated.
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

        for last_attempt in (False, True):
            try:
                session = await self._get_session()
                async with session.put(
                    url, headers=headers, data=post_data, params={"m": token}
                ) as resp:
                    # Decoded leniently rather than via resp.json(): the adapter
                    # echoes EEPROM strings (model names, manufacture numbers)
                    # with their trailing 0xff padding intact, and a strict
                    # utf-8 decode would reject the whole response over padding
                    # in fields nothing here reads.
                    raw = await resp.read()
                    body = json.loads(raw.decode("utf-8", errors="replace"))
                    # Honor the dict return type: a misbehaving adapter can
                    # yield any JSON value (list/scalar/null); callers index
                    # into a mapping, so normalize anything else to {}.
                    return body if isinstance(body, dict) else {}
            # Clause order is load-bearing: ClientConnectorError subclasses
            # ClientConnectionError, and aiohttp's timeout errors subclass
            # both a timeout base and ClientConnectionError. Only a dropped
            # established connection may reach the retrying clause. Both timeout
            # names are caught because before Python 3.11 asyncio.TimeoutError
            # is a distinct class from the builtin TimeoutError; catching only
            # the builtin would let a read timeout fall into the retry branch.
            except (TimeoutError, asyncio.TimeoutError):
                _LOGGER.warning("Device %s: timeout reaching %s", self._name, url)
            except aiohttp.ClientConnectorError as ex:
                _LOGGER.warning("Device %s: cannot connect to %s: %s", self._name, url, ex)
            except aiohttp.ClientConnectionError as ex:
                # An established connection died mid-request — typically a
                # pooled keep-alive socket the adapter closed while it sat
                # idle. A fresh connection usually succeeds.
                #
                # This retry makes writes at-least-once: if the adapter applied
                # a command PUT but the connection dropped before we read the
                # response, the identical PUT is re-sent. Safe only while every
                # command is an idempotent absolute-value write (mode, setpoint,
                # fan, vane). A future relative/toggle command must not rely on
                # this path.
                if not last_attempt:
                    _LOGGER.debug(
                        "Device %s: connection dropped, retrying: %s", self._name, ex
                    )
                    continue
                _LOGGER.warning("Device %s: connection error reaching %s: %s", self._name, url, ex)
            except Exception as ex:
                _LOGGER.warning("Device %s: error reaching %s: %s", self._name, url, ex)
            break
        return {}
