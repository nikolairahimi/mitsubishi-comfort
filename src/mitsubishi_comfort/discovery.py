"""Local network IP probing to match device serials to LAN addresses."""

from __future__ import annotations

import base64
import logging

import aiohttp

from .auth import compute_token
from .types import DeviceInfo

_LOGGER = logging.getLogger(__name__)

_PROBE_QUERY = b'{"c":{"indoorUnit":{"status":{}}}}'


async def probe_candidate_ips(
    devices: dict[str, DeviceInfo],
    candidate_ips: list[str],
    timeout: float = 3.0,
) -> dict[str, str]:
    """Probe candidate IPs to match device serials to LAN addresses.

    Returns dict mapping serial -> IP address.
    """
    if not devices or not candidate_ips:
        return {}

    result: dict[str, str] = {}
    unmatched = set(devices.keys())

    for ip in candidate_ips:
        if not unmatched:
            break
        for serial in list(unmatched):
            dev = devices[serial]
            if await _probe_ip(ip, dev.password, dev.crypto_serial, timeout):
                result[serial] = ip
                unmatched.discard(serial)
                _LOGGER.info("Matched %s -> %s", serial, ip)
                break

    return result


async def _probe_ip(
    ip: str, password_b64: str, crypto_serial_hex: str, timeout: float
) -> bool:
    """Try a status query against an IP with given credentials."""
    try:
        password = base64.b64decode(password_b64)
        crypto_serial = bytearray.fromhex(crypto_serial_hex)
        if len(crypto_serial) < 9:
            return False
    except Exception:
        return False

    token = compute_token(password, crypto_serial, _PROBE_QUERY)
    url = f"http://{ip}/api"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
    }

    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.put(
                url, headers=headers, data=_PROBE_QUERY, params={"m": token}
            ) as resp:
                if resp.ok:
                    data = await resp.json(content_type=None)
                    return isinstance(data, dict) and "r" in data
    except Exception:
        pass
    return False
