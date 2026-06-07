"""Tests for mitsubishi_comfort.cloud."""

import json
import aiohttp
import pytest
from unittest.mock import AsyncMock, patch
from aioresponses import aioresponses
from mitsubishi_comfort.cloud import MitsubishiCloudAccount, _SIO_EVENT
from mitsubishi_comfort.exceptions import AuthenticationError, DeviceConnectionError


@pytest.fixture
def cloud():
    return MitsubishiCloudAccount("user@example.com", "password123")


class TestLogin:
    async def test_login_success(self, cloud):
        with aioresponses() as m:
            m.post(
                "https://app-prod.kumocloud.com/v3/login",
                payload={"token": {"access": "jwt_access", "refresh": "jwt_refresh"}},
            )
            await cloud.login()

        assert cloud._access_token == "jwt_access"
        assert cloud._refresh_token == "jwt_refresh"
        await cloud.close()

    async def test_login_rejected_raises_auth_error(self, cloud):
        with aioresponses() as m:
            m.post("https://app-prod.kumocloud.com/v3/login", status=401)
            with pytest.raises(AuthenticationError):
                await cloud.login()

        assert cloud._access_token is None
        await cloud.close()

    async def test_login_server_error_raises_connection_error(self, cloud):
        with aioresponses() as m:
            m.post("https://app-prod.kumocloud.com/v3/login", status=503)
            with pytest.raises(DeviceConnectionError):
                await cloud.login()
        await cloud.close()

    async def test_login_network_error_raises_connection_error(self, cloud):
        with aioresponses() as m:
            m.post(
                "https://app-prod.kumocloud.com/v3/login",
                exception=aiohttp.ClientError("boom"),
            )
            with pytest.raises(DeviceConnectionError):
                await cloud.login()
        await cloud.close()

    async def test_login_missing_token_raises_auth_error(self, cloud):
        with aioresponses() as m:
            m.post("https://app-prod.kumocloud.com/v3/login", payload={"token": {}})
            with pytest.raises(AuthenticationError):
                await cloud.login()
        await cloud.close()


class TestGetSites:
    async def test_get_sites(self, cloud):
        cloud._access_token = "test_token"
        sites = [{"id": "site1", "name": "Home"}]
        with aioresponses() as m:
            m.get("https://app-prod.kumocloud.com/v3/sites/", payload=sites)
            result = await cloud.get_sites()
            await cloud.close()

        assert result == sites


class TestAutoRefresh:
    async def test_auto_refresh_on_401(self, cloud):
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
        assert cloud._access_token == "new_token"
        await cloud.close()


class TestDiscoverDevices:
    async def test_discover_devices(self, cloud):
        cloud._access_token = "test_token"

        with aioresponses() as m:
            m.get("https://app-prod.kumocloud.com/v3/sites/", payload=[{"id": "site1"}])
            m.get(
                "https://app-prod.kumocloud.com/v3/sites/site1/zones",
                payload=[{
                    "name": "Living Room",
                    "adapter": {
                        "deviceSerial": "SER001",
                        "isHeadless": False,
                        # The V3 adapter never carries a usable macAddress; the
                        # real MAC comes from the device status endpoint below.
                        "macAddress": "",
                    },
                }],
            )
            m.get(
                "https://app-prod.kumocloud.com/v3/devices/SER001/status",
                payload={
                    "cryptoSerial": "0102030405060708090a",
                    "mac": "24:cd:8d:1e:7b:15",
                },
            )

            with patch.object(
                cloud,
                "get_passwords_via_websocket",
                new=AsyncMock(return_value={"SER001": "dGVzdA=="}),
            ):
                devices = await cloud.discover_devices()

        assert "SER001" in devices
        assert devices["SER001"].label == "Living Room"
        assert devices["SER001"].crypto_serial == "0102030405060708090a"
        assert devices["SER001"].password == "dGVzdA=="
        # MAC is read from the status endpoint, not the adapter object.
        assert devices["SER001"].mac == "24:cd:8d:1e:7b:15"
        assert devices["SER001"].is_indoor_unit is True
        await cloud.close()

    async def test_discover_with_cached_credentials(self, cloud):
        cloud._access_token = "test_token"

        cached = {
            "SER001": {
                "password": "cached_pw",
                "crypto_serial": "0102030405060708090a",
                "mac": "24:cd:8d:1e:7b:15",
                "address": "192.168.1.100",
            }
        }

        with aioresponses() as m:
            m.get("https://app-prod.kumocloud.com/v3/sites/", payload=[{"id": "site1"}])
            m.get(
                "https://app-prod.kumocloud.com/v3/sites/site1/zones",
                payload=[{
                    "name": "Living Room",
                    "adapter": {"deviceSerial": "SER001", "isHeadless": False},
                }],
            )

            with patch.object(
                cloud,
                "get_passwords_via_websocket",
                new=AsyncMock(return_value={}),
            ) as ws_mock:
                devices = await cloud.discover_devices(cached_credentials=cached)

        assert "SER001" in devices
        assert devices["SER001"].password == "cached_pw"
        assert devices["SER001"].crypto_serial == "0102030405060708090a"
        # A cached mac (and crypto) means no per-device status fetch is needed —
        # note no status endpoint is mocked above.
        assert devices["SER001"].mac == "24:cd:8d:1e:7b:15"
        ws_mock.assert_not_awaited()
        await cloud.close()

    async def test_discover_headless_unit_type_from_is_headless(self, cloud):
        cloud._access_token = "test_token"

        with aioresponses() as m:
            m.get("https://app-prod.kumocloud.com/v3/sites/", payload=[{"id": "site1"}])
            m.get(
                "https://app-prod.kumocloud.com/v3/sites/site1/zones",
                payload=[{
                    "name": "Outdoor",
                    "adapter": {"deviceSerial": "SER002", "isHeadless": True},
                }],
            )
            m.get(
                "https://app-prod.kumocloud.com/v3/devices/SER002/status",
                payload={
                    "cryptoSerial": "0102030405060708090a",
                    "mac": "9c:50:d1:ef:11:29",
                },
            )

            with patch.object(
                cloud,
                "get_passwords_via_websocket",
                new=AsyncMock(return_value={"SER002": "dGVzdA=="}),
            ):
                devices = await cloud.discover_devices()

        assert devices["SER002"].unit_type == "headless"
        assert devices["SER002"].is_indoor_unit is False
        await cloud.close()


class TestUserIdCached:
    def test_user_id_cached(self, cloud):
        import base64

        header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=")
        payload = base64.urlsafe_b64encode(
            json.dumps({"id": 12345}).encode()
        ).rstrip(b"=")
        cloud._access_token = f"{header.decode()}.{payload.decode()}.sig"

        uid = cloud._get_user_id_from_token()
        assert uid == "12345"
        assert cloud._user_id == "12345"

        cloud._access_token = None
        uid2 = cloud._get_user_id_from_token()
        assert uid2 == "12345"


class TestSessionInjection:
    async def test_external_session_not_closed(self):
        async with aiohttp.ClientSession() as external:
            cloud = MitsubishiCloudAccount("u", "p", session=external)
            await cloud.close()
            assert not external.closed

    async def test_owned_session_closed(self):
        cloud = MitsubishiCloudAccount("u", "p")
        with aioresponses() as m:
            m.post(
                "https://app-prod.kumocloud.com/v3/login",
                payload={"token": {"access": "t", "refresh": "r"}},
            )
            await cloud.login()
        owned = cloud._session
        await cloud.close()
        assert owned is not None and owned.closed


class TestUserIdProperty:
    def test_user_id_property_exposes_cached_value(self, cloud):
        import base64

        header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=")
        payload = base64.urlsafe_b64encode(
            json.dumps({"id": 99}).encode()
        ).rstrip(b"=")
        cloud._access_token = f"{header.decode()}.{payload.decode()}.sig"

        assert cloud.user_id == "99"

    def test_user_id_none_without_token(self, cloud):
        assert cloud.user_id is None


class TestExtractPasswords:
    def test_extract_passwords_basic(self):
        passwords: dict[str, str] = {}
        serials = {"SER001", "SER002"}
        raw = f'{_SIO_EVENT}["adapter_update",{{"deviceSerial":"SER001","password":"pw123"}}]'

        MitsubishiCloudAccount._extract_passwords(raw, passwords, serials)
        assert passwords == {"SER001": "pw123"}

    def test_extract_passwords_ignores_unknown_serial(self):
        passwords: dict[str, str] = {}
        serials = {"SER001"}
        raw = f'{_SIO_EVENT}["adapter_update",{{"deviceSerial":"SER999","password":"pw"}}]'

        MitsubishiCloudAccount._extract_passwords(raw, passwords, serials)
        assert passwords == {}
