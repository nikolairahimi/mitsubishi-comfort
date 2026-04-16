"""Tests for mitsubishi_comfort.device."""

import json
import re
import pytest
from aioresponses import aioresponses
from mitsubishi_comfort.device import Device


@pytest.fixture
def mock_device(device_name, device_address, device_credentials, device_serial):
    return Device(
        name=device_name,
        address=device_address,
        password_b64=device_credentials["password"],
        crypto_serial_hex=device_credentials["crypto_serial"],
        serial=device_serial,
    )


async def test_device_properties(mock_device, device_name, device_address, device_serial):
    assert mock_device.name == device_name
    assert mock_device.address == device_address
    assert mock_device.serial == device_serial


async def test_request_success(mock_device):
    query = b'{"c":{"indoorUnit":{"status":{}}}}'
    response_data = {"r": {"indoorUnit": {"status": {"mode": "cool"}}}}

    with aioresponses() as m:
        m.put(re.compile(r"http://192\.168\.1\.100/api(\?.*)?"), payload=response_data)
        result = await mock_device.request(query)

    assert result == response_data


async def test_request_timeout(mock_device):
    from asyncio import TimeoutError
    query = b'{"c":{"indoorUnit":{"status":{}}}}'

    with aioresponses() as m:
        m.put(re.compile(r"http://192\.168\.1\.100/api(\?.*)?"), exception=TimeoutError())
        result = await mock_device.request(query)

    assert result == {}


async def test_request_no_address():
    device = Device(
        name="No Address",
        address=None,
        password_b64="dGVzdA==",
        crypto_serial_hex="00112233445566778899",
        serial="W00000",
    )
    result = await device.request(b'{}')
    assert result == {}


async def test_external_session_not_closed(device_credentials, device_serial):
    import aiohttp
    async with aiohttp.ClientSession() as external:
        device = Device(
            name="External Session",
            address="192.168.1.50",
            password_b64=device_credentials["password"],
            crypto_serial_hex=device_credentials["crypto_serial"],
            serial=device_serial,
            session=external,
        )
        await device.close()
        assert not external.closed


async def test_device_set_timeouts(device_credentials, device_serial):
    device = Device(
        name="Custom Timeouts",
        address="192.168.1.50",
        password_b64=device_credentials["password"],
        crypto_serial_hex=device_credentials["crypto_serial"],
        serial=device_serial,
        connect_timeout=5.0,
        response_timeout=15.0,
    )
    assert device._connect_timeout == 5.0
    assert device._response_timeout == 15.0
