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
smart faucet on the account is added as a device; faucets added to the account later
appear automatically, and ones removed can be deleted from the device page. If your password changes, Home
Assistant prompts you to re-enter it.

## Entities

Each faucet gets:

| Entity | Type | Notes |
| --- | --- | --- |
| Faucet (named after the device) | Valve | Open runs the water at the run temperature and flow rate; close stops it. |
| Run temperature | Number | Temperature used when the valve opens or the Dispense button is pressed: a slider in whole degrees from 5 °C to the faucet's safety limit. Defaults to 38 °C. |
| Flow rate | Number | How hard the water runs when the valve opens: 30–100 %. Starts at the faucet's default flow rate. |
| Dispense amount | Number | Amount poured by the Dispense button, in mL (15 mL to 3785 mL). Defaults to 250 mL. |
| Dispense | Button | Pours the dispense amount at the run temperature, straight away. |
| Preset *name* | Buttons | One per preset saved in the Moen app (shared across the account's faucets). Runs it the way the app does. Presets added, renamed or deleted in the app are picked up within 30 minutes. |
| Freeze protection | Switch (config) | When on, the faucet trickles water if its cabinet gets cold. |
| Water temperature | Sensor | Last reported outlet temperature. See [limitations](#limitations). |
| Cabinet temperature | Sensor | Temperature of the under-sink control box. |
| Water usage | Sensor | Litres through the faucet, counted session by session from when the integration was added. Suitable for the Energy dashboard's water section. |
| Last use volume / duration / temperature | Sensors | Volume, length and average temperature of the most recent use, from Moen's session history. |
| Battery | Sensor (diagnostic) | |
| Signal strength | Sensor (diagnostic) | Wi-Fi RSSI. Disabled by default. |
| Connectivity | Binary sensor (diagnostic) | Whether the faucet is connected to Moen's cloud. |
| Freeze risk | Binary sensor | The faucet's own freezing flag. |

Run temperature, flow rate and dispense amount are stored in Home Assistant, not on the
faucet, and survive restarts.

While a faucet is offline, its controls and live sensors are unavailable. Connectivity,
the settings kept in Home Assistant (run temperature, flow rate, dispense amount) and
the usage sensors stay available.

## Actions

### `moen_smart_faucet.run`

Runs the water on one or more faucet valves. Optional fields:

- `temperature`: target temperature in °C (5–60), or
- `preset`: `hottest` or `coldest`;
- `flow_rate`: 30–100 %.

Anything not given comes from the faucet's run temperature and flow rate settings. A
temperature above the safety (or child) limit is pulled down to it, and with either
limit on, `hottest` means that limit. Changing the flow rate or run temperature while
a run Home Assistant started is going adjusts it live; runs started at the faucet are
never taken over.

How a run ends: the faucet stops it on its own timers. With a flow rate set, this
integration sends the same flags as the Moen app's "temperature + flow" preset, and how
long such a run lasts before the faucet's auto shut-off (`handleTimeout`, up to 15
minutes) has not been verified. Close the valve to stop the water. A target colder than your cold
water supply can't be reached: the faucet runs until its own time limit (2 minutes on the
faucet this was developed with) and stops. Use `preset: coldest` for the coldest water
available right now.

```yaml
action: moen_smart_faucet.run
target:
  entity_id: valve.kitchen_faucet
data:
  temperature: 40
  flow_rate: 60
```

### `moen_smart_faucet.dispense`

Pours a measured amount of water, from 1 tablespoon to 1 gallon.

- `volume` (required) and `unit`: `ml` (default), `l`, `tbsp`, `fl_oz`, `cup`, `pint`,
  `quart` or `gal` (US measures).
- `temperature` or `preset`: optional. Without either, the faucet pours at its own
  default temperature.
- `start`: `now` (default), or `on_wave` to have the faucet get ready (running up to
  temperature first, if one is given) and pour when someone waves at its sensor.

```yaml
action: moen_smart_faucet.dispense
target:
  entity_id: valve.kitchen_faucet
data:
  volume: 2
  unit: cup
  temperature: 45
```

To stop the water, use `valve.close_valve`.

## Limitations

- **Cloud only.** If Moen's service or your internet connection is down, so is this
  integration.
- **No live temperature while the water runs.** The faucet reports its water
  temperature only when a run ends (the Moen app has the same limitation). The
  integration polls every 5 seconds while a faucet is running, instead of every 30, so
  the reading updates within a few seconds of the water stopping.
- **Creating or editing presets, and other faucet settings** (timeouts, default
  temperature, gesture mode, safety and child limits) are not supported yet.
- Tested with one faucet, Moen app version 3.60.0, and Home Assistant 2026.9 and
  2026.10.

## Diagnostics

Diagnostics downloads redact your email, password, device and location IDs, and
Wi-Fi network name. Check the file before sharing it anyway.

## Development

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest                      # tests, including entity snapshots
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy custom_components/moen_smart_faucet
```

- `docs/api.md` documents the Moen cloud API this integration uses.
- `api.py` has no Home Assistant dependencies.
- After editing `strings.json`, run `python script/gen_translations.py`; a test
  fails if `translations/en.json` is out of date.
- After an intentional entity change, refresh snapshots with
  `pytest --snapshot-update` and review the diff.
- CI runs lint and type checks, the tests against the oldest supported and the
  latest pinned Home Assistant (with a 95 % coverage floor), hassfest and HACS
  validation, plus a weekly run to catch new Home Assistant releases.

To try changes in a real Home Assistant without touching your main instance, run the
dev instance in Docker. The integration folder is mounted read-only, so a container
restart picks up code changes:

```bash
docker compose -f dev/docker-compose.yml up -d        # http://localhost:8124
docker compose -f dev/docker-compose.yml restart      # after editing code
```

## Credits

Login handling follows the approach of the Flo by Moen integrations, which use the
same Moen account API:
[cd1zz/homeassistant-flo-custom-component](https://github.com/cd1zz/homeassistant-flo-custom-component).

## License

MIT
