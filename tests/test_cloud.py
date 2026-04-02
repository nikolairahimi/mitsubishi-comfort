"""Tests for mitsubishi_comfort.cloud."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aioresponses import aioresponses
from mitsubishi_comfort.cloud import MitsubishiCloudAccount
from mitsubishi_comfort.exceptions import AuthenticationError


@pytest.fixture
def cloud():
    return MitsubishiCloudAccount("user@example.com", "password123")


async def test_login_success(cloud):
    with aioresponses() as m:
        m.post(
            "https://app-prod.kumocloud.com/v3/login",
            payload={"token": {"access": "jwt_access", "refresh": "jwt_refresh"}},
        )
        result = await cloud.login()

    assert result is True


async def test_login_failure(cloud):
    with aioresponses() as m:
        m.post("https://app-prod.kumocloud.com/v3/login", status=401)
        result = await cloud.login()

    assert result is False


async def test_get_sites(cloud):
    cloud._access_token = "test_token"
    sites = [{"id": "site1", "name": "Home"}]
    with aioresponses() as m:
        m.get("https://app-prod.kumocloud.com/v3/sites/", payload=sites)
        result = await cloud.get_sites()

    assert result == sites


async def test_get_zones(cloud):
    cloud._access_token = "test_token"
    zones = [{"name": "Living Room", "adapter": {"deviceSerial": "W123", "unitType": "ductless", "macAddress": "AA:BB"}}]
    with aioresponses() as m:
        m.get("https://app-prod.kumocloud.com/v3/sites/site1/zones", payload=zones)
        result = await cloud.get_zones("site1")

    assert result == zones


async def test_get_device_status(cloud):
    cloud._access_token = "test_token"
    status = {"cryptoSerial": "aabbccdd00112233ff"}
    with aioresponses() as m:
        m.get("https://app-prod.kumocloud.com/v3/devices/W123/status", payload=status)
        result = await cloud.get_device_status("W123")

    assert result["cryptoSerial"] == "aabbccdd00112233ff"


async def test_discover_devices(cloud):
    cloud._access_token = "test_token"

    sites = [{"id": "site1"}]
    zones = [{"name": "Bedroom", "adapter": {"deviceSerial": "W999", "unitType": "ductless", "macAddress": "CC:DD"}}]
    status = {"cryptoSerial": "00112233445566778899"}

    with aioresponses() as m:
        m.get("https://app-prod.kumocloud.com/v3/sites/", payload=sites)
        m.get("https://app-prod.kumocloud.com/v3/sites/site1/zones", payload=zones)
        m.get("https://app-prod.kumocloud.com/v3/devices/W999/status", payload=status)

        with patch.object(cloud, "get_passwords_via_websocket", new_callable=AsyncMock, return_value={"W999": "base64pw"}):
            devices = await cloud.discover_devices()

    assert "W999" in devices
    assert devices["W999"].serial == "W999"
    assert devices["W999"].label == "Bedroom"
    assert devices["W999"].crypto_serial == "00112233445566778899"
    assert devices["W999"].password == "base64pw"


async def test_auto_refresh_on_401(cloud):
    cloud._access_token = "expired_token"
    cloud._refresh_token = "valid_refresh"

    with aioresponses() as m:
        m.get("https://app-prod.kumocloud.com/v3/sites/", status=401)
        m.post(
            "https://app-prod.kumocloud.com/v3/refresh",
            payload={"access": "new_token", "refresh": "new_refresh"},
        )
        m.get("https://app-prod.kumocloud.com/v3/sites/", payload=[{"id": "s1"}])

        result = await cloud.get_sites()

    assert result == [{"id": "s1"}]
