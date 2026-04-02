"""V3 Cloud API client for Mitsubishi Comfort (Kumo Cloud)."""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import aiohttp

from .const import (
    V3_APP_VERSION,
    V3_BASE_URL,
    V3_CLOUD_TIMEOUT_CONNECT,
    V3_CLOUD_TIMEOUT_READ,
    V3_SOCKET_URL,
)
from .exceptions import AuthenticationError
from .types import DeviceInfo

_LOGGER = logging.getLogger(__name__)

_BASE_HEADERS = {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "x-app-version": V3_APP_VERSION,
    "Content-Type": "application/json",
}

# Engine.IO / Socket.IO protocol constants
_EIO_PING = "2"
_EIO_PONG = "3"
_SIO_CONNECT = "40"
_SIO_EVENT = "42"
_SIO_CONNECT_ERROR = "44"


class MitsubishiCloudAccount:
    """Async client for the Mitsubishi Comfort V3 cloud API."""

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            sock_connect=V3_CLOUD_TIMEOUT_CONNECT,
            sock_read=V3_CLOUD_TIMEOUT_READ,
        )

    def _auth_headers(self) -> dict[str, str]:
        return {**_BASE_HEADERS, "Authorization": f"Bearer {self._access_token}"}

    # ── Authentication ──────────────────────────────────

    async def login(self) -> bool:
        """Authenticate with V3 API and obtain JWT tokens."""
        body = {
            "username": self._username,
            "password": self._password,
            "appVersion": V3_APP_VERSION,
        }
        try:
            async with aiohttp.ClientSession(timeout=self._timeout()) as session:
                async with session.post(
                    f"{V3_BASE_URL}/v3/login", headers=_BASE_HEADERS, json=body
                ) as resp:
                    if not resp.ok:
                        _LOGGER.warning("V3 login failed: HTTP %s", resp.status)
                        return False
                    data = await resp.json()
        except Exception as ex:
            _LOGGER.warning("V3 login error: %s", ex)
            return False

        token_data = data.get("token", {})
        self._access_token = token_data.get("access")
        self._refresh_token = token_data.get("refresh")
        return bool(self._access_token)

    async def refresh(self) -> bool:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            return False

        headers = {**_BASE_HEADERS, "Authorization": f"Bearer {self._refresh_token}"}
        try:
            async with aiohttp.ClientSession(timeout=self._timeout()) as session:
                async with session.post(
                    f"{V3_BASE_URL}/v3/refresh",
                    headers=headers,
                    json={"refresh": self._refresh_token},
                ) as resp:
                    if not resp.ok:
                        return False
                    data = await resp.json()
        except Exception:
            return False

        self._access_token = data.get("access")
        self._refresh_token = data.get("refresh")
        return bool(self._access_token)

    # ── REST API ────────────────────────────────────────

    async def _get(self, path: str) -> Any:
        """Authenticated GET with automatic token refresh on 401."""
        url = f"{V3_BASE_URL}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout()) as session:
                async with session.get(url, headers=self._auth_headers()) as resp:
                    if resp.status == 401 and await self.refresh():
                        async with session.get(url, headers=self._auth_headers()) as retry_resp:
                            if not retry_resp.ok:
                                return None
                            return await retry_resp.json()
                    if not resp.ok:
                        return None
                    return await resp.json()
        except Exception as ex:
            _LOGGER.warning("V3 GET %s error: %s", path, ex)
            return None

    async def get_sites(self) -> list[dict]:
        result = await self._get("/v3/sites/")
        return result if isinstance(result, list) else []

    async def get_zones(self, site_id: str) -> list[dict]:
        result = await self._get(f"/v3/sites/{site_id}/zones")
        return result if isinstance(result, list) else []

    async def get_device_status(self, serial: str) -> dict | None:
        return await self._get(f"/v3/devices/{serial}/status")

    # ── Socket.IO Password Retrieval ────────────────────

    async def get_passwords_via_websocket(
        self, device_serials: list[str], timeout_secs: int = 30
    ) -> dict[str, str]:
        """Connect to Socket.IO and collect adapter_update events with passwords.

        Returns dict mapping serial -> base64-encoded password.
        """
        if not self._access_token:
            return {}

        serials_needed = set(device_serials)
        passwords: dict[str, str] = {}

        try:
            async with aiohttp.ClientSession() as session:
                await self._socketio_poll(session, serials_needed, timeout_secs, passwords)
        except Exception as ex:
            _LOGGER.warning("WebSocket password retrieval error: %s", ex)

        return passwords

    async def _socketio_poll(
        self,
        session: aiohttp.ClientSession,
        serials_needed: set[str],
        timeout_secs: int,
        passwords: dict[str, str],
    ) -> None:
        """Run a complete Socket.IO long-polling session."""
        base_params = {"EIO": "4", "transport": "polling"}
        headers = {"Authorization": f"Bearer {self._access_token}", "Accept": "*/*"}
        post_headers = {**headers, "Content-Type": "text/plain;charset=UTF-8"}

        # Handshake
        async with session.get(
            f"{V3_SOCKET_URL}/socket.io/", params=base_params, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if not resp.ok:
                return
            text = await resp.text()
            if not text.startswith("0"):
                return
            sid = json.loads(text[1:]).get("sid")

        poll_params = {**base_params, "sid": sid}

        async def _post(data: str) -> None:
            async with session.post(
                f"{V3_SOCKET_URL}/socket.io/", params=poll_params,
                headers=post_headers, data=data, timeout=aiohttp.ClientTimeout(total=10)
            ):
                pass

        async def _poll(timeout: float = 10) -> str:
            async with session.get(
                f"{V3_SOCKET_URL}/socket.io/", params=poll_params,
                headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if not resp.ok:
                    return ""
                return await resp.text()

        # Namespace connect
        await _post(_SIO_CONNECT)
        text = await _poll()

        if text.startswith(_SIO_CONNECT_ERROR):
            if await self.refresh():
                headers["Authorization"] = f"Bearer {self._access_token}"
                post_headers["Authorization"] = f"Bearer {self._access_token}"
                await _post(_SIO_CONNECT)
                text = await _poll()
            else:
                return

        # Account subscribe
        user_id = self._get_user_id_from_token()
        if user_id:
            await _post(f'{_SIO_EVENT}["subscribe","","{user_id}"]')
            text = await _poll()
            self._extract_passwords(text, passwords, serials_needed)

        # Device subscribe
        await _post("\x1e".join(f'{_SIO_EVENT}["subscribe","{s}"]' for s in serials_needed))
        text = await _poll()
        self._extract_passwords(text, passwords, serials_needed)

        # Force adapter updates
        await _post("\x1e".join(
            f'{_SIO_EVENT}["force_adapter_request","{s}","adapterStatus"]'
            for s in serials_needed
        ))

        # Trigger device_status_v2
        msgs = [f'{_SIO_EVENT}["device_status_v2",""]']
        msgs.extend(f'{_SIO_EVENT}["device_status_v2","{s}"]' for s in serials_needed)
        await _post("\x1e".join(msgs))

        # Poll for responses
        deadline = time.monotonic() + timeout_secs
        while time.monotonic() < deadline and serials_needed - set(passwords.keys()):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                text = await _poll(timeout=min(25, remaining + 1))
            except TimeoutError:
                continue
            except Exception:
                break

            if not text:
                break

            self._extract_passwords(text, passwords, serials_needed)

            if _EIO_PING in self._split_messages(text):
                try:
                    await _post(_EIO_PONG)
                except Exception:
                    pass

        _LOGGER.info("Socket.IO: found passwords for %d/%d devices",
                      len(passwords), len(serials_needed))

    def _get_user_id_from_token(self) -> str | None:
        if not self._access_token:
            return None
        try:
            payload_b64 = self._access_token.split(".")[1]
            payload_b64 += "=" * ((-len(payload_b64)) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            user_id = payload.get("id")
            return str(user_id) if user_id is not None else None
        except Exception:
            return None

    @staticmethod
    def _split_messages(raw: str) -> list[str]:
        if not raw:
            return []
        return raw.split("\x1e") if "\x1e" in raw else [raw]

    @staticmethod
    def _extract_passwords(raw: str, passwords: dict[str, str], serials_needed: set[str]) -> None:
        for msg in MitsubishiCloudAccount._split_messages(raw):
            if ":" in msg and msg.split(":")[0].isdigit():
                msg = msg.split(":", 1)[1]
            if not msg.startswith(_SIO_EVENT):
                continue
            try:
                payload = json.loads(msg[len(_SIO_EVENT):])
            except (json.JSONDecodeError, IndexError):
                continue
            if (isinstance(payload, list) and len(payload) >= 2
                    and payload[0] == "adapter_update"
                    and isinstance(payload[1], dict)):
                serial = payload[1].get("deviceSerial", "")
                password = payload[1].get("password", "")
                if serial in serials_needed and password:
                    passwords[serial] = password

    # ── High-Level Discovery ───────────────────────────

    async def discover_devices(self) -> dict[str, DeviceInfo]:
        """Discover all devices on this account.

        Returns dict mapping serial -> DeviceInfo.
        """
        if not self._access_token and not await self.login():
            raise AuthenticationError("V3 login failed")

        devices: dict[str, dict] = {}
        for site in await self.get_sites():
            site_id = site.get("id")
            if not site_id:
                continue
            for zone in await self.get_zones(site_id):
                adapter = zone.get("adapter", {})
                serial = adapter.get("deviceSerial", "")
                if serial:
                    devices[serial] = {
                        "label": zone.get("name", ""),
                        "unit_type": adapter.get("unitType", "ductless"),
                        "mac": adapter.get("macAddress", ""),
                        "password": "",
                        "crypto_serial": "",
                    }

        if not devices:
            _LOGGER.warning("No devices found via V3 API")
            return {}

        # Get cryptoSerials
        for serial in devices:
            status = await self.get_device_status(serial)
            if isinstance(status, dict):
                crypto = status.get("cryptoSerial", "")
                if crypto:
                    devices[serial]["crypto_serial"] = crypto

        # Get passwords via Socket.IO
        passwords = await self.get_passwords_via_websocket(list(devices.keys()), timeout_secs=60)
        for serial, password in passwords.items():
            if serial in devices:
                devices[serial]["password"] = password

        return {
            serial: DeviceInfo(
                serial=serial,
                label=dev["label"],
                address="",
                mac=dev["mac"],
                unit_type=dev["unit_type"],
                password=dev["password"],
                crypto_serial=dev["crypto_serial"],
            )
            for serial, dev in devices.items()
        }
