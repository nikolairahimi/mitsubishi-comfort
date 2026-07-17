"""Tests for mitsubishi_comfort.discovery."""

import re

import aiohttp
import pytest
from aioresponses import aioresponses
from unittest.mock import AsyncMock, patch
from mitsubishi_comfort.discovery import probe_candidate_ips
from mitsubishi_comfort.types import DeviceInfo


@pytest.fixture
def devices():
    return {
        "W111": DeviceInfo(
            serial="W111", label="Unit 1", address="",
            mac="AA:BB", unit_type="ductless",
            password="dGVzdHBhc3N3b3Jk",
            crypto_serial="00112233445566778899",
        ),
        "W222": DeviceInfo(
            serial="W222", label="Unit 2", address="",
            mac="CC:DD", unit_type="ductless",
            password="b3RoZXJwYXNz",
            crypto_serial="99887766554433221100",
        ),
    }


async def test_probe_matches(devices):
    async def fake_probe(ip, password, crypto_serial, timeout, session):
        return ip == "192.168.1.10" and password == devices["W111"].password

    with patch("mitsubishi_comfort.discovery._probe_ip", side_effect=fake_probe):
        result = await probe_candidate_ips(
            devices, ["192.168.1.10", "192.168.1.11"], timeout=1.0
        )

    assert result["W111"] == "192.168.1.10"


async def test_probe_no_candidates(devices):
    result = await probe_candidate_ips(devices, [], timeout=1.0)
    assert result == {}


async def test_probe_no_devices():
    result = await probe_candidate_ips({}, ["192.168.1.10"], timeout=1.0)
    assert result == {}


async def test_probe_no_match(devices):
    async def fake_probe(ip, password, crypto_serial, timeout, session):
        return False

    with patch("mitsubishi_comfort.discovery._probe_ip", side_effect=fake_probe):
        result = await probe_candidate_ips(
            devices, ["192.168.1.10"], timeout=1.0
        )

    assert result == {}


async def test_probe_matches_multiple_across_candidates(devices):
    # Each unit only authenticates against its own IP; concurrent probing must
    # still map every device to the correct address.
    async def fake_probe(ip, password, crypto_serial, timeout, session):
        if ip == "192.168.1.10" and password == devices["W111"].password:
            return True
        if ip == "192.168.1.20" and password == devices["W222"].password:
            return True
        return False

    with patch("mitsubishi_comfort.discovery._probe_ip", side_effect=fake_probe):
        result = await probe_candidate_ips(
            devices,
            ["192.168.1.10", "192.168.1.20", "192.168.1.30"],
            timeout=1.0,
        )

    assert result == {"W111": "192.168.1.10", "W222": "192.168.1.20"}


async def test_probe_forwards_injected_session(devices):
    probe = AsyncMock(return_value=False)
    sentinel = object()

    with patch("mitsubishi_comfort.discovery._probe_ip", probe):
        await probe_candidate_ips(
            devices, ["192.168.1.10"], timeout=1.0, session=sentinel
        )

    assert probe.call_count == 2
    assert all(call.args[4] is sentinel for call in probe.call_args_list)


async def test_probe_injected_session_used_and_left_open(devices):
    # aioresponses intercepts at the class level, so a successful match alone
    # cannot prove the injected session was used; forbidding construction of
    # any internal session does.
    async with aiohttp.ClientSession() as external:
        with (
            patch(
                "mitsubishi_comfort.discovery.aiohttp.ClientSession",
                side_effect=AssertionError(
                    "probe built its own session despite injection"
                ),
            ),
            aioresponses() as m,
        ):
            m.put(
                re.compile(r"http://192\.168\.1\.10/api(\?.*)?"),
                payload={"r": {"indoorUnit": {"status": {}}}},
            )
            result = await probe_candidate_ips(
                {"W111": devices["W111"]},
                ["192.168.1.10"],
                timeout=1.0,
                session=external,
            )

        assert result == {"W111": "192.168.1.10"}
        assert not external.closed
        # The per-request timeout must override the injected session's own
        # settings, or probes against dead IPs inherit them and stall.
        calls = [call for request in m.requests.values() for call in request]
        assert len(calls) == 1
        assert calls[0].kwargs["timeout"] == aiohttp.ClientTimeout(total=1.0)


async def test_probe_without_session_creates_and_closes_own(devices):
    created = []
    real_session_cls = aiohttp.ClientSession

    def tracking_session(*args, **kwargs):
        session = real_session_cls(*args, **kwargs)
        created.append(session)
        return session

    with (
        patch(
            "mitsubishi_comfort.discovery.aiohttp.ClientSession",
            side_effect=tracking_session,
        ),
        aioresponses() as m,
    ):
        m.put(
            re.compile(r"http://192\.168\.1\.10/api(\?.*)?"),
            payload={"r": {"indoorUnit": {"status": {}}}},
        )
        result = await probe_candidate_ips(
            {"W111": devices["W111"]}, ["192.168.1.10"], timeout=1.0
        )

    assert result == {"W111": "192.168.1.10"}
    assert created
    assert all(session.closed for session in created)
