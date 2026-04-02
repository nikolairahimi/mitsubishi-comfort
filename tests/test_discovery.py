"""Tests for mitsubishi_comfort.discovery."""

import pytest
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
    async def fake_probe(ip, password, crypto_serial, timeout):
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
    async def fake_probe(ip, password, crypto_serial, timeout):
        return False

    with patch("mitsubishi_comfort.discovery._probe_ip", side_effect=fake_probe):
        result = await probe_candidate_ips(
            devices, ["192.168.1.10"], timeout=1.0
        )

    assert result == {}
