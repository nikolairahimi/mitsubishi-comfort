"""Local network IP probing to match device serials to LAN addresses."""

from __future__ import annotations

import asyncio
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
    max_concurrent: int = 64,
) -> dict[str, str]:
    """Probe candidate IPs concurrently to match device serials to LAN addresses.

    Each device only authenticates against its own unit, so every (device, ip)
    pair is probed concurrently — bounded by ``max_concurrent`` — and the first
    IP a device authenticates against wins. This relies on L3 HTTP rather than
    L2 discovery, so it resolves units on other subnets/VLANs as long as they
    are routable from this host.

    Returns dict mapping serial -> IP address.
    """
    if not devices or not candidate_ips:
        return {}

    semaphore = asyncio.Semaphore(max_concurrent)
    result: dict[str, str] = {}

    async def _match(serial: str, dev: DeviceInfo, ip: str) -> None:
        if serial in result:  # already found elsewhere; skip the probe
            return
        async with semaphore:
            if serial in result:
                return
            if await _probe_ip(ip, dev.password, dev.crypto_serial, timeout):
                if result.setdefault(serial, ip) == ip:
                    _LOGGER.info("Matched %s -> %s", serial, ip)

    await asyncio.gather(
        *(
            _match(serial, dev, ip)
            for serial, dev in devices.items()
            for ip in candidate_ips
        )
    )

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
