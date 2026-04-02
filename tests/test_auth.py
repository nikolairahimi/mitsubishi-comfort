"""Tests for mitsubishi_comfort.auth."""

import base64
from mitsubishi_comfort.auth import compute_token


def test_compute_token_deterministic():
    """Same inputs produce the same token."""
    password = base64.b64decode("dGVzdHBhc3N3b3Jk")  # "testpassword"
    crypto_serial = bytearray.fromhex("00112233445566778899")
    post_data = b'{"c":{"indoorUnit":{"status":{}}}}'

    token1 = compute_token(password, crypto_serial, post_data)
    token2 = compute_token(password, crypto_serial, post_data)
    assert token1 == token2


def test_compute_token_is_hex_string():
    """Token is a 64-character hex string (SHA-256 digest)."""
    password = base64.b64decode("dGVzdHBhc3N3b3Jk")
    crypto_serial = bytearray.fromhex("00112233445566778899")
    post_data = b'{"c":{"indoorUnit":{"status":{}}}}'

    token = compute_token(password, crypto_serial, post_data)
    assert len(token) == 64
    assert all(c in "0123456789abcdef" for c in token)


def test_compute_token_different_data_different_token():
    """Different post_data produces a different token."""
    password = base64.b64decode("dGVzdHBhc3N3b3Jk")
    crypto_serial = bytearray.fromhex("00112233445566778899")

    token1 = compute_token(password, crypto_serial, b'{"c":{"indoorUnit":{"status":{}}}}')
    token2 = compute_token(password, crypto_serial, b'{"c":{"indoorUnit":{"status":{"mode":"cool"}}}}')
    assert token1 != token2


def test_compute_token_different_password_different_token():
    """Different password produces a different token."""
    crypto_serial = bytearray.fromhex("00112233445566778899")
    post_data = b'{"c":{"indoorUnit":{"status":{}}}}'

    token1 = compute_token(base64.b64decode("dGVzdHBhc3N3b3Jk"), crypto_serial, post_data)
    token2 = compute_token(base64.b64decode("b3RoZXJwYXNz"), crypto_serial, post_data)
    assert token1 != token2
