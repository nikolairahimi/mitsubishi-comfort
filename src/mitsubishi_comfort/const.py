"""Constants for mitsubishi_comfort."""

# Magic bytes for local API auth token computation
W_PARAM = bytearray.fromhex(
    "44c73283b498d432ff25f5c8e06a016aef931e68f0a00ea710e36e6338fb22db"
)
S_PARAM = 0

# compute_token() reads crypto_serial[8], so a shorter serial cannot produce a
# token at all. Credentials below this length must disable requests rather than
# reach the token computation.
CRYPTO_SERIAL_MIN_BYTES = 9

# Local unit HTTP API timeouts (seconds)
DEFAULT_CONNECT_TIMEOUT = 1.2
DEFAULT_RESPONSE_TIMEOUT = 8.0

# How long to cache status before re-fetching (seconds)
CACHE_INTERVAL_SECONDS = 20

# Maximum number of external sensors per unit
MAX_SENSORS = 4

# Re-fetch the unit profile (capabilities and setpoint limits) every this many
# polls so cached bounds self-heal after a firmware/config change. At the
# typical ~60s poll cadence this is roughly hourly.
PROFILE_REFRESH_POLLS = 60

# V3 Cloud API
V3_BASE_URL = "https://app-prod.kumocloud.com"
V3_SOCKET_URL = "https://socket-prod.kumocloud.com"
V3_APP_VERSION = "3.2.4"
V3_CLOUD_TIMEOUT_CONNECT = 10
V3_CLOUD_TIMEOUT_READ = 30

# Legacy V2 Cloud API. The V3 API stopped returning cryptoSerial and the
# Socket.IO password on newly provisioned accounts; this endpoint still serves
# both (plus the MAC) and is the fallback used to onboard when V3 falls short.
V2_LOGIN_URL = "https://geo-c.kumocloud.com/login"
V2_APP_VERSION = "2.2.0"
