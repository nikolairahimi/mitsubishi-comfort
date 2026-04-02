"""Constants for mitsubishi_comfort."""

# Magic bytes for local API auth token computation
W_PARAM = bytearray.fromhex(
    "44c73283b498d432ff25f5c8e06a016aef931e68f0a00ea710e36e6338fb22db"
)
S_PARAM = 0

# Local unit HTTP API timeouts (seconds)
DEFAULT_CONNECT_TIMEOUT = 1.2
DEFAULT_RESPONSE_TIMEOUT = 8.0

# How long to cache status before re-fetching (seconds)
CACHE_INTERVAL_SECONDS = 20

# Maximum number of external sensors per unit
MAX_SENSORS = 4

# V3 Cloud API
V3_BASE_URL = "https://app-prod.kumocloud.com"
V3_SOCKET_URL = "https://socket-prod.kumocloud.com"
V3_APP_VERSION = "3.2.4"
V3_CLOUD_TIMEOUT_CONNECT = 10
V3_CLOUD_TIMEOUT_READ = 30
