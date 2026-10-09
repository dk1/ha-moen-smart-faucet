# Moen Smart Faucet for Home Assistant

A custom integration for the Moen Smart Faucet (the voice- and motion-controlled
kitchen faucet, called "VAK" inside the Moen app). It shows the faucet's state
and temperatures, and can start and stop the water from Home Assistant.

> **Unofficial.** This project is not affiliated with, endorsed by, or supported by
> Moen or Fortune Brands. It uses the same cloud API as the Moen app, which Moen can
> change at any time.

## How it works

The faucet has no local API. It talks only to Moen's cloud: an AWS IoT device
shadow, reached through Moen's API with your Moen account. This integration logs
in the same way the Moen app does, polls every 30 seconds, and writes commands to
the faucet's shadow. An internet connection is required.

## Installation

### HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/dk1/ha-moen-smart-faucet` with the type **Integration**.
3. Install **Moen Smart Faucet** and restart Home Assistant.

### Manual

Copy `custom_components/moen_smart_faucet` into your Home Assistant
`config/custom_components/` folder and restart.

## Setup

Go to **Settings → Devices & services → Add integration**, search for **Moen Smart
Faucet**, and sign in with the email and password you use in the Moen app. Every
smart faucet on the account is added as a device. If your password changes, Home
Assistant prompts you to re-enter it.

## Entities

Each faucet gets:

| Entity | Type | Notes |
| --- | --- | --- |
| Faucet (named after the device) | Valve | Open runs the water at the run temperature; close stops it. |
| Run temperature | Number (config) | The temperature used when the valve is opened: a slider in whole degrees. Stored in Home Assistant, not on the faucet. The range follows the coldest and hottest water the faucet has learned (it reports these itself, so it widens as the seasons change), capped at the safety limit while safety mode is on. Defaults to 38 °C. |
| Water temperature | Sensor | Last reported outlet temperature. See [limitations](#limitations). |
| Cabinet temperature | Sensor | Temperature of the under-sink control box. |
| Battery | Sensor (diagnostic) | |
| Signal strength | Sensor (diagnostic) | Wi-Fi RSSI. Disabled by default. |
| Connectivity | Binary sensor (diagnostic) | Whether the faucet is connected to Moen's cloud. |
| Freeze risk | Binary sensor | The faucet's own freezing flag. |

While a faucet is offline its entities are unavailable, except for connectivity and
run temperature.

## Actions

### `moen_smart_faucet.run`

Runs the water on one or more faucet valves. Give at most one of:

- `temperature`: target temperature in °C (5–60).
- `preset`: `hottest` or `coldest`.

With neither, the faucet's run temperature is used. A temperature outside what the faucet can deliver is
pulled into its range, since the faucet would otherwise run until it times out chasing it. Use
`preset: coldest` for the coldest water available right now.

```yaml
action: moen_smart_faucet.run
target:
  entity_id: valve.kitchen_faucet
data:
  temperature: 40
```

To stop the water, use `valve.close_valve`.

## Limitations

- **Cloud only.** If Moen's service or your internet connection is down, so is this
  integration.
- **No live temperature while the water runs.** The faucet reports its water
  temperature only when a run ends (the Moen app has the same limitation). The
  integration polls every 5 seconds while a faucet is running, instead of every 30, so
  the reading updates within a few seconds of the water stopping.
- **Dispensing a measured volume, presets and faucet settings** (safety limit, child
  mode, timeouts) are not supported yet.
- Tested with one faucet, Moen app version 3.60.0, and Home Assistant 2026.9 and
  2026.10.

## Diagnostics

Diagnostics downloads redact your email, password, device and location IDs, and
Wi-Fi network name. Check the file before sharing it anyway.

## Development

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The API client in `api.py` has no Home Assistant dependencies.

## Credits

Login handling follows the approach of the Flo by Moen integrations, which use the
same Moen account API:
[cd1zz/homeassistant-flo-custom-component](https://github.com/cd1zz/homeassistant-flo-custom-component).

## License

MIT
