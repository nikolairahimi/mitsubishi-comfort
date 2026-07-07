"""Tests for mitsubishi_comfort.device."""

import asyncio
import json
import re
from types import SimpleNamespace

import aiohttp
import pytest
from aioresponses import aioresponses
from mitsubishi_comfort.device import Device

API_URL_RE = re.compile(r"http://192\.168\.1\.100/api(\?.*)?")


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
        m.put(API_URL_RE, payload=response_data)
        result = await mock_device.request(query)

    assert result == response_data


async def test_request_timeout(mock_device):
    query = b'{"c":{"indoorUnit":{"status":{}}}}'

    with aioresponses() as m:
        # aiohttp raises ServerTimeoutError on a read timeout, not the builtin.
        m.put(API_URL_RE, exception=aiohttp.ServerTimeoutError())
        result = await mock_device.request(query)

    assert result == {}


async def test_request_retries_once_on_connection_drop(mock_device):
    """A connection that dies mid-request (stale keep-alive) is retried once."""
    query = b'{"c":{"indoorUnit":{"status":{}}}}'
    payload = {"r": {"indoorUnit": {"status": {"mode": "heat"}}}}

    with aioresponses() as m:
        m.put(API_URL_RE,
              exception=aiohttp.ServerDisconnectedError())
        m.put(API_URL_RE, payload=payload)
        result = await mock_device.request(query)

    assert result == payload


async def test_request_connection_drop_retried_only_once(mock_device):

    with aioresponses() as m:
        m.put(API_URL_RE,
              exception=aiohttp.ServerDisconnectedError(), repeat=True)
        result = await mock_device.request(b'{}')

    assert result == {}
    assert sum(len(calls) for calls in m.requests.values()) == 2


async def test_request_connect_failure_not_retried(mock_device):
    """Failure to establish a connection at all is not worth retrying."""

    conn_key = SimpleNamespace(ssl=None, host="192.168.1.100", port=80)
    with aioresponses() as m:
        m.put(API_URL_RE,
              exception=aiohttp.ClientConnectorError(conn_key, OSError("refused")),
              repeat=True)
        result = await mock_device.request(b'{}')

    assert result == {}
    assert sum(len(calls) for calls in m.requests.values()) == 1


@pytest.mark.parametrize(
    "exc_factory",
    [
        # Builtin and asyncio timeouts are distinct classes before Python 3.11;
        # aiohttp raises ServerTimeoutError (subclasses both asyncio.TimeoutError
        # and ClientConnectionError) on a read timeout. All must be treated as a
        # terminal timeout, never routed into the connection-drop retry branch.
        pytest.param(lambda: TimeoutError(), id="builtin-timeout"),
        pytest.param(lambda: asyncio.TimeoutError(), id="asyncio-timeout"),
        pytest.param(lambda: aiohttp.ServerTimeoutError(), id="aiohttp-server-timeout"),
    ],
)
async def test_request_timeout_not_retried(mock_device, exc_factory):
    with aioresponses() as m:
        m.put(API_URL_RE, exception=exc_factory(), repeat=True)
        result = await mock_device.request(b'{}')

    assert result == {}
    assert sum(len(calls) for calls in m.requests.values()) == 1


async def test_request_swallows_unexpected_error(mock_device):
    """A non-timeout, non-connection error is logged and yields {} (not retried)."""
    with aioresponses() as m:
        m.put(API_URL_RE, exception=RuntimeError("boom"), repeat=True)
        result = await mock_device.request(b'{}')

    assert result == {}
    assert sum(len(calls) for calls in m.requests.values()) == 1


async def test_base_update_status_not_implemented(mock_device):
    """The base Device provides the burst-scoped template; _refresh_status is abstract."""
    with pytest.raises(NotImplementedError):
        await mock_device.update_status()


async def test_disconnect_closes_owned_session(mock_device):
    with aioresponses() as m:
        m.put(API_URL_RE, payload={"r": {}})
        await mock_device.request(b'{}')

    session = mock_device._session
    assert session is not None
    await mock_device.disconnect()
    assert session.closed
    assert mock_device._session is None


async def test_disconnect_leaves_external_session_open(device_credentials, device_serial):
    async with aiohttp.ClientSession() as external:
        device = Device(
            name="External Session",
            address="192.168.1.50",
            password_b64=device_credentials["password"],
            crypto_serial_hex=device_credentials["crypto_serial"],
            serial=device_serial,
            session=external,
        )
        await device.disconnect()
        assert not external.closed


async def test_request_works_after_disconnect(mock_device):
    """The session is recreated lazily after a disconnect."""
    payload = {"r": {}}
    with aioresponses() as m:
        m.put(API_URL_RE, payload=payload, repeat=True)
        assert await mock_device.request(b'{}') == payload
        await mock_device.disconnect()
        assert await mock_device.request(b'{}') == payload
    await mock_device.close()


async def test_concurrent_bursts_are_serialized(mock_device):
    """A poll and a command on the same device must not run at once, or one
    burst's end-of-poll disconnect() would close the session the other is
    still using. The per-device lock guarantees at most one burst body runs."""
    active = 0
    max_active = 0

    async def one_burst():
        nonlocal active, max_active
        async with mock_device._burst():
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0)  # yield so a second burst could interleave
            active -= 1

    await asyncio.gather(one_burst(), one_burst())
    assert max_active == 1


@pytest.mark.parametrize("body", [5, True, "ok", ["r"], None])
async def test_request_normalizes_non_dict_body_to_empty(mock_device, body):
    """A non-mapping JSON body is coerced to {} so callers can index safely."""
    with aioresponses() as m:
        m.put(API_URL_RE, payload=body)
        result = await mock_device.request(b'{}')

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
