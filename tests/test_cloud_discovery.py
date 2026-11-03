"""Contracts for cloud discovery without local credentials."""

from unittest.mock import AsyncMock, patch

import pytest
from aioresponses import aioresponses
from mitsubishi_comfort import DeviceInfo, MitsubishiCloudAccount
from mitsubishi_comfort.const import V3_BASE_URL
from mitsubishi_comfort.exceptions import AuthenticationError, DeviceConnectionError


async def test_discover_cloud_devices() -> None:
    """Discover indoor units across sites without calling credential endpoints."""
    account = MitsubishiCloudAccount("test@example.com", "password")
    with (
        aioresponses() as response,
        patch.object(account, "fetch_v2_credentials", new_callable=AsyncMock) as v2,
        patch.object(
            account, "get_passwords_via_websocket", new_callable=AsyncMock
        ) as passwords,
        patch.object(account, "get_device_status", new_callable=AsyncMock) as status,
    ):
        response.post(
            f"{V3_BASE_URL}/v3/login",
            payload={"token": {"access": "access", "refresh": "refresh"}},
        )
        response.get(
            f"{V3_BASE_URL}/v3/sites/", payload=[{}, {"id": "first"}, {"id": "second"}]
        )
        response.get(
            f"{V3_BASE_URL}/v3/sites/first/zones",
            payload=[
                {"name": "Living Room", "adapter": {"deviceSerial": "A"}},
                {"adapter": {"deviceSerial": "STATION", "isHeadless": True}},
                {"name": "No adapter"},
                {"adapter": {}},
            ],
        )
        response.get(
            f"{V3_BASE_URL}/v3/sites/second/zones",
            payload=[{"adapter": {"deviceSerial": "B", "isHeadless": False}}],
        )
        try:
            assert await account.discover_cloud_devices() == {
                "A": DeviceInfo(
                    serial="A",
                    label="Living Room",
                    site_id="first",
                    unit_type="ductless",
                    address="",
                    mac="",
                    password="",
                    crypto_serial="",
                ),
                "B": DeviceInfo(
                    serial="B",
                    label="",
                    site_id="second",
                    unit_type="ductless",
                    address="",
                    mac="",
                    password="",
                    crypto_serial="",
                ),
            }
            assert sum(map(len, response.requests.values())) == 4
            v2.assert_not_awaited()
            passwords.assert_not_awaited()
            status.assert_not_awaited()
        finally:
            await account.close()


@pytest.mark.parametrize(
    "zones",
    [
        pytest.param([], id="empty"),
        pytest.param(
            [{"adapter": {"deviceSerial": "STATION", "isHeadless": True}}],
            id="station-only",
        ),
        pytest.param([{"name": "No adapter"}, {"adapter": {}}], id="no-serial"),
    ],
)
async def test_no_cloud_devices(zones: list[dict]) -> None:
    """Unsupported or empty zones return no supported units."""
    account = MitsubishiCloudAccount("test@example.com", "password")
    account._access_token = "access"
    with aioresponses() as response:
        response.get(f"{V3_BASE_URL}/v3/sites/", payload=[{"id": "site"}])
        response.get(f"{V3_BASE_URL}/v3/sites/site/zones", payload=zones)
        try:
            assert await account.discover_cloud_devices() == {}
            assert sum(map(len, response.requests.values())) == 2
        finally:
            await account.close()


@pytest.mark.parametrize(
    ("status", "error"),
    [
        pytest.param(403, AuthenticationError, id="authentication"),
        pytest.param(503, DeviceConnectionError, id="connection"),
    ],
)
async def test_cloud_discovery_errors(status: int, error: type[Exception]) -> None:
    """Discovery failures propagate to the integration."""
    account = MitsubishiCloudAccount("test@example.com", "password")
    account._access_token = "access"
    with aioresponses() as response:
        response.get(f"{V3_BASE_URL}/v3/sites/", payload=[{"id": "site"}])
        response.get(f"{V3_BASE_URL}/v3/sites/site/zones", status=status)
        try:
            with pytest.raises(error):
                await account.discover_cloud_devices()
        finally:
            await account.close()
