"""V3 Cloud API client for Mitsubishi Comfort (Kumo Cloud).

Async adaptation of pykumo's V3 API support (https://github.com/dlarrick/pykumo,
MIT License, Copyright (c) 2019 dlarrick), originally contributed to pykumo by
Ethan Kiczek. See LICENSE for the full notice.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

import aiohttp

from .const import (
    V2_APP_VERSION,
    V2_LOGIN_URL,
    V3_APP_VERSION,
    V3_BASE_URL,
    V3_CLOUD_TIMEOUT_CONNECT,
    V3_CLOUD_TIMEOUT_READ,
    V3_SOCKET_URL,
)
from .exceptions import AuthenticationError, DeviceConnectionError
from .types import DeviceInfo

_LOGGER = logging.getLogger(__name__)

_BASE_HEADERS = {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "x-app-version": V3_APP_VERSION,
    "Content-Type": "application/json",
}

_V2_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en",
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

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._session = session
        self._owns_session = session is None
        self._user_id: str | None = None

    @property
    def user_id(self) -> str | None:
        """Cloud account user ID, resolved from the access token after login."""
        return self._get_user_id_from_token()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout())
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            sock_connect=V3_CLOUD_TIMEOUT_CONNECT,
            sock_read=V3_CLOUD_TIMEOUT_READ,
        )

    def _auth_headers(self) -> dict[str, str]:
        return {**_BASE_HEADERS, "Authorization": f"Bearer {self._access_token}"}

    # ── Authentication ──────────────────────────────────

    async def login(self) -> None:
        """Authenticate with V3 API and obtain JWT tokens.

        Raises:
            AuthenticationError: Credentials rejected or response missing tokens.
            DeviceConnectionError: Network or transport failure.
        """
        body = {
            "username": self._username,
            "password": self._password,
            "appVersion": V3_APP_VERSION,
        }
        try:
            session = await self._get_session()
            async with session.post(
                f"{V3_BASE_URL}/v3/login", headers=_BASE_HEADERS, json=body
            ) as resp:
                if resp.status in (401, 403):
                    raise AuthenticationError(f"V3 login rejected: HTTP {resp.status}")
                if not resp.ok:
                    raise DeviceConnectionError(f"V3 login failed: HTTP {resp.status}")
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as ex:
            raise DeviceConnectionError(f"V3 login error: {ex}") from ex

        token_data = data.get("token", {})
        self._access_token = token_data.get("access")
        self._refresh_token = token_data.get("refresh")
        if not self._access_token:
            raise AuthenticationError("V3 login response missing access token")

    async def refresh(self) -> None:
        """Refresh the access token using the refresh token.

        Raises:
            AuthenticationError: Refresh token rejected or missing.
            DeviceConnectionError: Network or transport failure.
        """
        if not self._refresh_token:
            raise AuthenticationError("No refresh token available")

        headers = {**_BASE_HEADERS, "Authorization": f"Bearer {self._refresh_token}"}
        try:
            session = await self._get_session()
            async with session.post(
                f"{V3_BASE_URL}/v3/refresh",
                headers=headers,
                json={"refresh": self._refresh_token},
            ) as resp:
                if resp.status in (401, 403):
                    raise AuthenticationError(f"V3 refresh rejected: HTTP {resp.status}")
                if not resp.ok:
                    raise DeviceConnectionError(f"V3 refresh failed: HTTP {resp.status}")
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as ex:
            raise DeviceConnectionError(f"V3 refresh error: {ex}") from ex

        self._access_token = data.get("access")
        self._refresh_token = data.get("refresh")
        if not self._access_token:
            raise AuthenticationError("V3 refresh response missing access token")

    # ── REST API ────────────────────────────────────────

    async def _get(self, path: str) -> Any:
        """Authenticated GET with automatic token refresh on 401.

        Raises:
            AuthenticationError: Both original and refreshed requests rejected.
            DeviceConnectionError: Network or transport failure.
        """
        url = f"{V3_BASE_URL}{path}"
        try:
            session = await self._get_session()
            async with session.get(url, headers=self._auth_headers()) as resp:
                if resp.status == 401:
                    await self.refresh()
                    async with session.get(url, headers=self._auth_headers()) as retry_resp:
                        if retry_resp.status in (401, 403):
                            raise AuthenticationError(
                                f"V3 GET {path} still unauthorized after refresh"
                            )
                        if not retry_resp.ok:
                            raise DeviceConnectionError(
                                f"V3 GET {path} failed: HTTP {retry_resp.status}"
                            )
                        return await retry_resp.json()
                if not resp.ok:
                    raise DeviceConnectionError(
                        f"V3 GET {path} failed: HTTP {resp.status}"
                    )
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as ex:
            raise DeviceConnectionError(f"V3 GET {path} error: {ex}") from ex

    async def get_sites(self) -> list[dict]:
        result = await self._get("/v3/sites/")
        return result if isinstance(result, list) else []

    async def get_zones(self, site_id: str) -> list[dict]:
        result = await self._get(f"/v3/sites/{site_id}/zones")
        return result if isinstance(result, list) else []

    async def get_device_status(self, serial: str) -> dict | None:
        return await self._get(f"/v3/devices/{serial}/status")

    # ── Legacy V2 Credential Fallback ───────────────────

    async def fetch_v2_credentials(self) -> dict[str, dict[str, str]]:
        """Fetch per-device local credentials from the legacy V2 cloud login.

        The V3 API no longer returns cryptoSerial or the Socket.IO password for
        newly provisioned accounts, so a device discovered purely through V3
        cannot be onboarded. The legacy geo-c.kumocloud.com/login endpoint still
        returns both — plus the MAC — keyed by serial.

        Returns serial -> {password, crypto_serial, mac, label, unit_type}, and
        an empty dict on any failure so discovery degrades gracefully rather than
        aborting.
        """
        body = {
            "username": self._username,
            "password": self._password,
            "appVersion": V2_APP_VERSION,
        }
        try:
            session = await self._get_session()
            async with session.post(
                V2_LOGIN_URL, headers=_V2_HEADERS, json=body
            ) as resp:
                if not resp.ok:
                    _LOGGER.warning("V2 login failed: HTTP %s", resp.status)
                    return {}
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as ex:
            _LOGGER.warning("V2 login error: %s", ex)
            return {}
        except ValueError as ex:
            _LOGGER.warning("V2 login returned malformed JSON: %s", ex)
            return {}

        return self._parse_v2_credentials(data)

    @staticmethod
    def _parse_v2_credentials(data: Any) -> dict[str, dict[str, str]]:
        """Extract serial -> credentials from a V2 login response.

        Units live in zoneTable maps nested under data[2] and its (possibly
        recursive) children. Only entries carrying a serial are returned.
        """
        creds: dict[str, dict[str, str]] = {}
        if not isinstance(data, list) or len(data) < 3 or not isinstance(data[2], dict):
            return creds

        def harvest(node: dict) -> None:
            zone_table = node.get("zoneTable")
            if isinstance(zone_table, dict):
                for raw in zone_table.values():
                    if not isinstance(raw, dict):
                        continue
                    serial = raw.get("serial")
                    if not serial:
                        continue
                    creds[serial] = {
                        "password": raw.get("password") or "",
                        "crypto_serial": raw.get("cryptoSerial") or "",
                        "mac": raw.get("mac") or "",
                        "label": raw.get("label") or "",
                        "unit_type": raw.get("unitType") or "",
                    }
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    harvest(child)

        harvest(data[2])
        return creds

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
            session = await self._get_session()
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
            try:
                await self.refresh()
            except (AuthenticationError, DeviceConnectionError):
                return
            headers["Authorization"] = f"Bearer {self._access_token}"
            post_headers["Authorization"] = f"Bearer {self._access_token}"
            await _post(_SIO_CONNECT)
            text = await _poll()

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
        if self._user_id is not None:
            return self._user_id
        if not self._access_token:
            return None
        try:
            payload_b64 = self._access_token.split(".")[1]
            payload_b64 += "=" * ((-len(payload_b64)) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            user_id = payload.get("id")
            self._user_id = str(user_id) if user_id is not None else None
            return self._user_id
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

    async def discover_devices(
        self, cached_credentials: dict[str, dict] | None = None,
    ) -> dict[str, DeviceInfo]:
        """Discover all devices on this account.

        Args:
            cached_credentials: Optional dict of serial -> {password, crypto_serial,
                mac, address, ...}. A cached password skips the Socket.IO password
                retrieval; a cached crypto_serial and mac skip the per-device status
                fetch they would otherwise be read from.

        Any device the V3 API leaves without the password, cryptoSerial, and MAC
        that onboarding needs is completed from the legacy V2 login, falling back
        to the Socket.IO password retrieval only if V2 also comes up short.

        Returns dict mapping serial -> DeviceInfo.
        """
        if not self._access_token:
            await self.login()

        cached = cached_credentials or {}

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
                        "unit_type": "headless" if adapter.get("isHeadless") else "ductless",
                        "mac": cached.get(serial, {}).get("mac", ""),
                        "password": cached.get(serial, {}).get("password", ""),
                        "crypto_serial": cached.get(serial, {}).get("crypto_serial", ""),
                    }

        if not devices:
            _LOGGER.warning("No devices found via V3 API")
            return {}

        # The V3 adapter object exposes neither the cryptoSerial nor the device's
        # LAN MAC address; both come from the per-device status endpoint. Fetch it
        # for any device still missing either (cached_credentials may supply them).
        need_status = [
            (s, d)
            for s, d in devices.items()
            if not d["crypto_serial"] or not d["mac"]
        ]
        if need_status:
            results = await asyncio.gather(
                *[self.get_device_status(s) for s, _ in need_status]
            )
            for (serial, dev), status in zip(need_status, results):
                if isinstance(status, dict):
                    crypto = status.get("cryptoSerial", "")
                    if crypto:
                        dev["crypto_serial"] = crypto
                    mac = status.get("mac", "")
                    if mac:
                        dev["mac"] = mac

        # V3 no longer supplies cryptoSerial or the Socket.IO password on newly
        # provisioned accounts, leaving devices unonboardable. Fall back to the
        # legacy V2 login, which still returns both plus the MAC, for any device
        # still missing a field onboarding needs. One call covers every device.
        need_v2 = [
            s
            for s, d in devices.items()
            if not (d["password"] and d["crypto_serial"] and d["mac"])
        ]
        if need_v2:
            _LOGGER.info(
                "Falling back to V2 login for %d/%d device(s) missing credentials",
                len(need_v2), len(devices),
            )
            v2_creds = await self.fetch_v2_credentials()
            for serial in need_v2:
                creds = v2_creds.get(serial)
                if not creds:
                    continue
                dev = devices[serial]
                for key in ("password", "crypto_serial", "mac"):
                    if not dev[key] and creds.get(key):
                        dev[key] = creds[key]

        # Only fetch passwords via Socket.IO for devices still missing them
        need_passwords = [s for s, d in devices.items() if not d["password"]]
        if need_passwords:
            _LOGGER.info(
                "Fetching passwords via Socket.IO for %d/%d devices",
                len(need_passwords), len(devices),
            )
            passwords = await self.get_passwords_via_websocket(need_passwords, timeout_secs=60)
            for serial, password in passwords.items():
                if serial in devices:
                    devices[serial]["password"] = password
        else:
            _LOGGER.info("All %d devices have cached credentials, skipping Socket.IO", len(devices))

        return {
            serial: DeviceInfo(
                serial=serial,
                label=dev["label"],
                address=cached.get(serial, {}).get("address", ""),
                mac=dev["mac"],
                unit_type=dev["unit_type"],
                password=dev["password"],
                crypto_serial=dev["crypto_serial"],
            )
            for serial, dev in devices.items()
        }
