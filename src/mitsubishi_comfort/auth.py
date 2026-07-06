"""Auth token computation for the Mitsubishi local HTTP API.

Derived from pykumo's PyKumoBase._token (https://github.com/dlarrick/pykumo,
MIT License, Copyright (c) 2019 dlarrick). See LICENSE for the full notice.
"""

import hashlib

from .const import S_PARAM, W_PARAM


def compute_token(password: bytes, crypto_serial: bytearray, post_data: bytes) -> str:
    """Compute the SHA-256 auth token for a local API request.

    Args:
        password: Decoded device password (from base64).
        crypto_serial: Device crypto serial as bytes (minimum 9 bytes).
        post_data: The JSON command body being sent.

    Returns:
        64-character hex string token.
    """
    data_hash = hashlib.sha256(password + post_data).digest()

    intermediate = bytearray(88)
    intermediate[0:32] = W_PARAM[0:32]
    intermediate[32:64] = data_hash[0:32]
    intermediate[64:66] = bytearray.fromhex("0840")
    intermediate[66] = S_PARAM
    intermediate[79] = crypto_serial[8]
    intermediate[80:84] = crypto_serial[4:8]
    intermediate[84:88] = crypto_serial[0:4]

    return hashlib.sha256(intermediate).hexdigest()
