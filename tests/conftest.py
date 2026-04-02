"""Shared test fixtures for mitsubishi_comfort."""

import base64
import pytest


@pytest.fixture
def device_credentials():
    """Return a dict with test device credentials."""
    return {
        "password": base64.b64encode(b"testpassword").decode(),
        "crypto_serial": "00112233445566778899",
    }


@pytest.fixture
def device_address():
    return "192.168.1.100"


@pytest.fixture
def device_serial():
    return "W12345678"


@pytest.fixture
def device_name():
    return "Test Unit"
