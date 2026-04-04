# mitsubishi-comfort

Async Python library for controlling Mitsubishi minisplit systems via the Kumo Cloud V3 API and local HTTP API.

## Features

- **Cloud discovery** -- authenticate with Kumo Cloud to discover devices, retrieve credentials, and fetch device status
- **Local control** -- communicate directly with minisplit units over your LAN for low-latency operation
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
| `discover_devices()` | Return `dict[serial, DeviceInfo]` with full credentials |
| `get_sites()` | List installation sites |
| `get_zones(site_id)` | List zones within a site |

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

## License

MIT
