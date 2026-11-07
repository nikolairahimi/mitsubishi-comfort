# mitsubishi-comfort

Async Python library for controlling Mitsubishi minisplit systems via the Kumo Cloud V3 API and local HTTP API.

## Features

- **Cloud discovery** -- authenticate with Kumo Cloud to discover devices, retrieve credentials, and fetch device status
- **Local control** -- communicate directly with minisplit units over your LAN for low-latency operation
- **Cloud control** -- control indoor units when local credentials or a LAN address are unavailable
- **Indoor units** -- full control of mode, temperature setpoints, fan speed, and vane direction
- **Kumo stations** -- read outdoor temperature and signal strength from headless outdoor units
- **Async native** -- built on `aiohttp` for use in asyncio applications

## Installation

```bash
pip install mitsubishi-comfort
```

## Quick start

```python
import asyncio
from mitsubishi_comfort import MitsubishiCloudAccount, IndoorUnit, Mode

async def main():
    # Discover devices via cloud API
    account = MitsubishiCloudAccount("user@example.com", "password")
    await account.login()
    devices = await account.discover_devices()

    # Control a device locally
    info = list(devices.values())[0]
    unit = IndoorUnit(
        name=info.label,
        address=info.address,
        password_b64=info.password,
        crypto_serial_hex=info.crypto_serial,
        serial=info.serial,
    )
    await unit.update_status()
    print(f"Room temp: {unit.status.room_temperature}")

    await unit.set_mode(Mode.COOL)
    await unit.set_cool_setpoint(22.0)

asyncio.run(main())
```

## API overview

### Cloud account

`MitsubishiCloudAccount(username, password)` authenticates with the Kumo Cloud V3 API.

| Method | Description |
|--------|-------------|
| `login()` | Authenticate and obtain JWT tokens |
| `refresh()` | Refresh an expired access token |
| `discover_devices(cloud_fallback=True)` | Return `dict[serial, DeviceInfo]`, retaining any available local credentials |
| `discover_cloud_devices()` | Return supported indoor units as `dict[serial, DeviceInfo]` without retrieving local credentials |
| `get_sites()` | List installation sites |
| `get_zones(site_id)` | List zones within a site |
| `get_device_details(serial)` | Read cloud device state |
| `get_device_profile(serial)` | Read capabilities and setpoint limits |
| `send_command(serial, commands)` | Submit absolute settings through the cloud |

### Cloud indoor unit

Mitsubishi no longer supplies the credentials needed for local control on new
accounts. `CloudIndoorUnit(info, account)` provides the same status, capability,
and command interface as `IndoorUnit`, using a shared `MitsubishiCloudAccount`.
It needs an internet connection, but no LAN address, MAC, password, or crypto serial
for the device. Kumo Station cloud monitoring is not implemented.

```python
from mitsubishi_comfort import CloudIndoorUnit, MitsubishiCloudAccount, Mode

async def control():
    account = MitsubishiCloudAccount("user@example.com", "password")
    try:
        await account.login()
        devices = await account.discover_cloud_devices()
        info = next(iter(devices.values()))
        unit = CloudIndoorUnit(info, account)
        if await unit.update_status():
            await unit.set_mode(Mode.COOL)
            await unit.set_cool_setpoint(22.0)
    finally:
        await account.close()
```

Temperatures are in Celsius. Cloud setpoints are rounded to the nearest 0.5 °C
before sending, because the cloud rejects any other value. Local `IndoorUnit`
setters retain their existing 0.1 °C rounding. A successful cloud command
means the API accepted the request; `unit.status` changes only after a
subsequent status poll. Poll at
most once per minute. Authentication failures raise `AuthenticationError`,
transport failures raise `DeviceConnectionError`, and rejected commands raise
`CommandError`. Rate limits apply to the shared account, and timed-out commands
are not replayed automatically. Closing a cloud unit does not close its shared
account; the caller closes the account after all devices are finished.

### Comfort app Fahrenheit setpoints

The Comfort app uses a lookup table rather than ordinary unit conversion:
71 °F selects 22.0 °C, and 72 °F selects 22.5 °C. To match those selections,
convert the original Fahrenheit request with `fahrenheit_to_setpoint` and
convert the returned Celsius setpoint with `setpoint_to_fahrenheit`:

```python
from mitsubishi_comfort import fahrenheit_to_setpoint, setpoint_to_fahrenheit

result = await unit.set_cool_setpoint(fahrenheit_to_setpoint(72))
if result.success:
    print(setpoint_to_fahrenheit(result.value))  # 72
```

Both local and cloud setters still accept Celsius and return Celsius in
`CommandResult.value`. The helpers
use the [documented app table](https://github.com/dlarrick/hass-kumo/pull/199)
for 61–80 °F, with arithmetic fallback outside that range. Fractional
Fahrenheit requests round to the nearest whole degree (half degrees up).
Non-finite inputs raise `ValueError`. These are setpoint helpers; measured
room temperatures should continue to use ordinary unit conversion.

Outside 61–80 °F, the request fallback converts `(F - 32) / 1.8` to the nearest
0.5 °C; the display fallback rounds `C * 1.8 + 32` to a whole degree. These are
arithmetic defaults, not verified current Comfort app mappings. For example,
84 °F falls back to 29.0 °C, whereas the
[older Kumo app table](https://github.com/dlarrick/pykumo/issues/15#issuecomment-987140863)
maps it to 28.5 °C. App parity outside the documented range remains unverified.

Home Assistant consumers must use Fahrenheit as the climate entity's native
unit when the user selects Fahrenheit, then call these helpers at the library
boundary. Otherwise Home Assistant converts 72 °F to 22.2 °C before the
library receives it, losing the original app selection. Report setpoints and
temperature limits in the same native unit, and leave Celsius users on the
existing Celsius path.

### Indoor unit

`IndoorUnit` controls a minisplit indoor unit over the local HTTP API.

| Method | Returns | Description |
|--------|---------|-------------|
| `update_status()` | `bool` | Poll device for current state |
| `set_mode(Mode)` | `CommandResult` | Set operating mode |
| `set_cool_setpoint(temp)` | `CommandResult` | Set cooling target temperature |
| `set_heat_setpoint(temp)` | `CommandResult` | Set heating target temperature |
| `set_fan_speed(FanSpeed)` | `CommandResult` | Set fan speed |
| `set_vane_direction(VaneDirection)` | `CommandResult` | Set vane direction |

### Kumo station

`KumoStation` reads data from headless outdoor units (no control commands).

| Method | Returns | Description |
|--------|---------|-------------|
| `update_status()` | `bool` | Poll device for current state |

### Enums

- `Mode` -- OFF, COOL, HEAT, DRY, FAN, AUTO
- `FanSpeed` -- SUPER_QUIET, QUIET, LOW, POWERFUL, SUPER_POWERFUL, AUTO
- `VaneDirection` -- HORIZONTAL, MID_HORIZONTAL, MIDPOINT, MID_VERTICAL, VERTICAL, AUTO, SWING

### Network discovery

`probe_candidate_ips(devices, candidate_ips)` matches device serials to LAN IP addresses by probing with device credentials.

## Acknowledgments

This library builds on the protocol work of [pykumo](https://github.com/dlarrick/pykumo)
by Doug Larrick and contributors, which reverse-engineered the Kumo Cloud service and
the local HTTP API used by Mitsubishi WiFi adapters. In particular:

- The local API auth token computation (`auth.py`) is derived from pykumo's
  `PyKumoBase._token`.
- The V3 cloud client (`cloud.py`), including the Socket.IO credential retrieval
  flow, is an async adaptation of pykumo's V3 support contributed by Ethan Kiczek.
- The credential-probe approach to matching device serials to LAN addresses
  (`discovery.py`) follows pykumo's local discovery design.

mitsubishi-comfort exists as a separate library because it targets asyncio
applications (notably Home Assistant), which requires a different architecture
than pykumo's synchronous design. If you need a synchronous client, use pykumo.

## License

MIT. Portions derived from pykumo, Copyright (c) 2019 dlarrick, also under the
MIT license — see the third-party notices in [LICENSE](LICENSE).
