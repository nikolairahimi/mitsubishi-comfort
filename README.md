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
        devices = await account.discover_devices(cloud_fallback=True)
        info = next(info for info in devices.values() if info.is_indoor_unit)
        unit = CloudIndoorUnit(info, account)
        if await unit.update_status():
            await unit.set_mode(Mode.COOL)
            await unit.set_cool_setpoint(22.0)
    finally:
        await account.close()
```

Temperatures are in Celsius. A successful cloud command means the API accepted
the request; `unit.status` changes only after a subsequent status poll. Poll at
most once per minute. Authentication failures raise `AuthenticationError`,
transport failures raise `DeviceConnectionError`, and rejected commands raise
`CommandError`. Rate limits apply to the shared account, and timed-out commands
are not replayed automatically. Closing a cloud unit does not close its shared
account; the caller closes the account after all devices are finished.

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
