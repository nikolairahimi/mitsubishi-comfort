"""HTTP contracts for cloud control."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from aioresponses import CallbackResult, aioresponses
from yarl import URL

from mitsubishi_comfort import MitsubishiCloudAccount
from mitsubishi_comfort.const import V2_LOGIN_URL, V3_BASE_URL
from mitsubishi_comfort.exceptions import (
    AuthenticationError,
    CommandError,
    DeviceConnectionError,
)


@pytest.fixture
def account() -> MitsubishiCloudAccount:
    account = MitsubishiCloudAccount("test@example.com", "password")
    account._access_token = "old"
    account._refresh_token = "refresh"
    return account


async def test_command_refresh_and_payload(account: MitsubishiCloudAccount) -> None:
    url = f"{V3_BASE_URL}/v3/devices/send-command"
    with aioresponses() as response:
        response.post(url, status=401)
        response.post(
            f"{V3_BASE_URL}/v3/refresh", payload={"access": "new", "refresh": "rotated"}
        )
        response.post(url, status=204)
        await account.send_command("SER001", {"spCool": 24.5})
        calls = next(
            calls
            for (method, _), calls in response.requests.items()
            if method == "POST" and len(calls) == 2
        )
        assert calls[0].kwargs["json"] == {
            "deviceSerial": "SER001",
            "commands": {"spCool": 24.5},
        }
        assert calls[1].kwargs["headers"]["Authorization"] == "Bearer new"
    await account.close()


@pytest.mark.parametrize(
    ("status", "payload", "error"),
    [
        pytest.param(400, {}, CommandError, id="bad-command"),
        pytest.param(403, {}, AuthenticationError, id="forbidden"),
        pytest.param(503, {}, DeviceConnectionError, id="outage"),
        pytest.param(200, {"success": False}, CommandError, id="rejected"),
        pytest.param(200, {"error": "offline"}, CommandError, id="offline"),
    ],
)
async def test_command_errors(
    account: MitsubishiCloudAccount,
    status: int,
    payload: dict,
    error: type[Exception],
) -> None:
    with aioresponses() as response:
        response.post(
            f"{V3_BASE_URL}/v3/devices/send-command", status=status, payload=payload
        )
        with pytest.raises(error):
            await account.send_command("SER001", {"operationMode": "heat"})
    await account.close()


@pytest.mark.parametrize("timeout", [TimeoutError, asyncio.TimeoutError])
@pytest.mark.parametrize("operation", ["login", "refresh", "details", "command", "v2"])
async def test_timeouts_are_wrapped_without_retry(
    account: MitsubishiCloudAccount, timeout: type[Exception], operation: str
) -> None:
    calls = {
        "login": ("POST", f"{V3_BASE_URL}/v3/login", account.login, ()),
        "refresh": ("POST", f"{V3_BASE_URL}/v3/refresh", account.refresh, ()),
        "details": (
            "GET", f"{V3_BASE_URL}/v3/devices/SER001",
            account.get_device_details, ("SER001",),
        ),
        "command": (
            "POST", f"{V3_BASE_URL}/v3/devices/send-command",
            account.send_command, ("SER001", {"operationMode": "heat"}),
        ),
        "v2": ("POST", V2_LOGIN_URL, account.fetch_v2_credentials, ()),
    }
    method, url, call, args = calls[operation]
    error = timeout()
    with aioresponses() as response:
        response.add(url, method=method, exception=error, repeat=True)
        if operation == "v2":
            assert await call(*args) == {}
        else:
            with pytest.raises(DeviceConnectionError) as caught:
                await call(*args)
            assert caught.value.__cause__ is error
        assert sum(map(len, response.requests.values())) == 1
    await account.close()


def test_account_constructed_before_run_limits_concurrent_requests(
    account: MitsubishiCloudAccount,
) -> None:
    async def run() -> None:
        active = 0
        peak = 0

        async def respond(url: URL, **kwargs: object) -> CallbackResult:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            return CallbackResult(payload={"power": 1})

        try:
            with aioresponses() as response:
                for serial in ("A", "B", "C"):
                    response.get(f"{V3_BASE_URL}/v3/devices/{serial}", callback=respond)
                results = await asyncio.wait_for(
                    asyncio.gather(*(
                        account.get_device_details(serial) for serial in ("A", "B", "C")
                    )), timeout=1,
                )
                assert results == [{"power": 1}] * 3
                assert peak == 2
        finally:
            await account.close()

    asyncio.run(run())


def test_account_constructed_before_run_serializes_zone_polls(
    account: MitsubishiCloudAccount,
) -> None:
    async def run() -> None:
        async def zones(site_id: str) -> list[dict]:
            await asyncio.sleep(0)
            return [{"adapter": {"deviceSerial": "A", "roomTemp": 21}}]

        with patch.object(account, "get_zones", side_effect=zones) as get_zones:
            results = await asyncio.wait_for(
                asyncio.gather(*(
                    account.get_zone_state("site", "A") for _ in range(2)
                )), timeout=1,
            )
            assert results == [{"deviceSerial": "A", "roomTemp": 21}] * 2
            get_zones.assert_awaited_once_with("site")

    asyncio.run(run())


async def test_rate_limit_shared_across_devices(
    account: MitsubishiCloudAccount,
) -> None:
    with (
        aioresponses() as response,
        patch("mitsubishi_comfort.cloud.time.monotonic", return_value=100) as clock,
    ):
        response.get(
            f"{V3_BASE_URL}/v3/devices/A", status=429, headers={"Retry-After": "120"}
        )
        with pytest.raises(DeviceConnectionError, match="rate limit"):
            await account.get_device_details("A")
        with pytest.raises(DeviceConnectionError, match="rate limit"):
            await account.get_device_details("B")
        assert sum(map(len, response.requests.values())) == 1
        clock.return_value = 221
        response.get(f"{V3_BASE_URL}/v3/devices/B", payload={"connected": True})
        assert await account.get_device_details("B") == {"connected": True}
    await account.close()


@pytest.mark.parametrize("profile", [{"hasModeHeat": True}, [{"hasModeHeat": True}]])
async def test_profile_shapes(
    account: MitsubishiCloudAccount, profile: dict | list
) -> None:
    with aioresponses() as response:
        response.get(f"{V3_BASE_URL}/v3/devices/A/profile", payload=profile)
        assert await account.get_device_profile("A") == {"hasModeHeat": True}
    await account.close()


@pytest.mark.parametrize("now", [0, 100])
async def test_concurrent_zone_polls_share_request(
    account: MitsubishiCloudAccount,
    now: float,
) -> None:
    with patch("mitsubishi_comfort.cloud.time.monotonic", return_value=now), patch.object(
        account,
        "get_zones",
        new=AsyncMock(
            return_value=[
                {"adapter": {"deviceSerial": "A", "roomTemp": 21}},
                {"adapter": {"deviceSerial": "B", "roomTemp": 23}},
            ]
        ),
    ) as zones:
        first, second = await asyncio.gather(
            account.get_zone_state("site", "A"),
            account.get_zone_state("site", "B"),
        )
        assert first["roomTemp"] == 21
        assert second["roomTemp"] == 23
        zones.assert_awaited_once_with("site")


async def test_new_account_skips_unusable_password_fetch(
    account: MitsubishiCloudAccount,
) -> None:
    with (
        patch.object(account, "get_sites", return_value=[{"id": "site"}]),
        patch.object(
            account,
            "get_zones",
            return_value=[{"name": "Bedroom", "adapter": {"deviceSerial": "A"}}],
        ),
        patch.object(account, "get_device_status", return_value={}),
        patch.object(account, "fetch_v2_credentials", return_value={}),
        patch.object(account, "get_passwords_via_websocket") as passwords,
    ):
        devices = await account.discover_devices(cloud_fallback=True)
        assert devices["A"].site_id == "site"
        assert not devices["A"].crypto_serial
        passwords.assert_not_awaited()


def test_concurrent_unauthorized_requests_refresh_once(
    account: MitsubishiCloudAccount,
) -> None:
    asyncio.run(_concurrent_unauthorized_requests(account))


async def _concurrent_unauthorized_requests(
    account: MitsubishiCloudAccount,
) -> None:
    first_seen = asyncio.Event()
    second_seen = asyncio.Event()

    async def first(url: URL, **kwargs: object) -> CallbackResult:
        first_seen.set()
        await second_seen.wait()
        return CallbackResult(status=401)

    async def second(url: URL, **kwargs: object) -> CallbackResult:
        second_seen.set()
        await first_seen.wait()
        return CallbackResult(status=401)

    async def refresh(url: URL, **kwargs: object) -> CallbackResult:
        await asyncio.sleep(0)
        return CallbackResult(payload={"access": "new", "refresh": "rotated"})

    with aioresponses() as response:
        response.get(f"{V3_BASE_URL}/v3/devices/A", callback=first)
        response.get(f"{V3_BASE_URL}/v3/devices/B", callback=second)
        response.post(
            f"{V3_BASE_URL}/v3/refresh",
            callback=refresh,
        )
        response.get(f"{V3_BASE_URL}/v3/devices/A", payload={"power": 1})
        response.get(f"{V3_BASE_URL}/v3/devices/B", payload={"power": 0})
        assert await asyncio.wait_for(
            asyncio.gather(
                account.get_device_details("A"),
                account.get_device_details("B"),
            ),
            timeout=1,
        ) == [{"power": 1}, {"power": 0}]
        assert len(response.requests[("POST", URL(f"{V3_BASE_URL}/v3/refresh"))]) == 1
    await account.close()
