# Moen smart faucet cloud API

Reverse-engineered from the Moen Android app (package `com.moen.smartwater`, v3.60.0)
and checked against one faucet (firmware v1.1.2q). Moen doesn't document this API and
can change it without notice.

Status key: **verified** = exercised against a real faucet; **code** = read from the app
only.

## Transport

| Piece | Value |
| --- | --- |
| Login | `POST https://api.prod.iot.moen.com/v1/oauth2/token`, JSON `{client_id, grant_type: "client_credentials", username, password}` → `{token: {access_token, id_token, refresh_token, expires_in}}`. Yes, `client_credentials` with a username: `"password"` returns HTTP 501. **verified** |
| Refresh | Same URL, `{client_id, grant_type: "refresh_token", refresh_token}`. **verified** |
| Calls | `POST https://api.prod.iot.moen.com/v1/invoker`, `Authorization: Bearer <access_token>`, body `{fn, parse: true, escape: true, body}`. `fn` names a Lambda function. **verified** |
| Live updates | AWS IoT MQTT, `$aws/things/<clientId>/shadow/update/accepted`, via Cognito identity credentials. The app uses it only on its temperature screen. **code** |
| Device | An AWS IoT thing with a per-device certificate. No local API, BLE only for Wi-Fi setup. |

## Functions used for the faucet

| `fn` | Body | Purpose |
| --- | --- | --- |
| `smartwater-app-device-api-prod-list` | none | All devices, reported shadow state flattened in. **verified** |
| `smartwater-app-device-api-prod-get` | `{clientId}` | One device. **verified** |
| `smartwater-app-device-api-prod-update` | `{clientId, nickname}` | Rename. **code** |
| `smartwater-app-shadow-api-prod-get` | `{clientId}` | Raw AWS IoT shadow (desired/reported/delta, per-field timestamps). **verified** |
| `smartwater-app-shadow-api-prod-update` | `{clientId, payload}` | Commands **and** settings: every key in `payload` is written to the shadow. Returns `{"status": true}`. **verified** |
| `smartwater-app-session-api-prod-get-v1` | `{clientId, limit, deviceType: "VAK", lastEvaluatedKey?}` | Water-use sessions, newest first, under `data`; the response's `lastEvaluatedKey` pages further back. **verified** (paging: **code**) |
| `smartwater-app-usage-api-prod-get-v1` | `{depth, devices: [clientId], queryDate (ms), timezoneOffset}` | Usage history. `depth` is daily/weekly/monthly/yearly. **code** |
| `smartwater-app-preset-api-prod-list` / `-get` / `-create` / `-update` / `-delete` | varies; get/delete take `{presetId}` | Saved presets (stored server-side). **code** |
| `smartwater-app-preset-api-prod-run` | `{clientId, presetId}` | Run a saved preset. Returns `{status, errorMessage}`. **code** |
| `fbgpg_alerts_v1_acknowledge_alert_prod`, `fbgpg_alerts_v1_silence_alert_prod` | `{pathParameters: {duid, alertEventId}}` | Alerts. Lists come from `GET /v3/events` and `/v3/events/alerts`. **code** |

## Commands (`payload` of shadow-api update)

All carry `commandSrc: "app"` except `stop`.

| Command | Payload | Behaviour |
| --- | --- | --- |
| `run` | `temperature` (°C, or `"hottest"`/`"coldest"`) | Water runs. **verified**. With a target the cold supply can't reach, it stops after `purgeTimeout` (120 s on the test faucet). **verified** |
| `run` + flow | `temperature`, `flowRate` (30–100 %), `purge: false`, `wait: false` | The app's "run at temperature with a flow rate" preset. **verified** 2026-10-09: peak flow dropped from ~5.1 to ~3.7 L/min. Without `purge: false` the faucet ignored `flowRate`. Re-sending `run` with a new `flowRate` changes a running faucet's flow within moments (**verified** 2026-10-09, as the app's live screen does). |
| `run` (flow preview) | `flowRate`, plus `defaultFlowRate` or `lowFlowRate`, no temperature | The flow-settings screen. Writes the setting as a side effect. **code** |
| `dispense_no_wait` | `volume` (µL), optional `temperature`, `purge: false`, `wait: false` | Pours now. 250 mL poured 0.25 L in 4.5 s. **verified** |
| `dispense` | `volume`, `wait: true`, optional `temperature` + `purge: true` | Gets ready (runs up to temperature if `purge`) and pours when someone waves. **code** |
| `dispense_no_purge` | `volume`, `temperature`, `purge: false`, `wait: false` | Preset case 2a. **code** |
| `preheat` | `temperature`, `purge: true` | Runs to temperature, stops, waits for a wave. **code** |
| `stop` | `{command: "stop"}` | **verified** |

**How runs end** is only partly known. A plain `run` with an unreachable target stopped
at `purgeTimeout` (verified). Whether a `run` with `purge: false` stops at temperature,
or only at the auto shut-off (`handleTimeout`, 60–900 s), is **not verified**.

Volume limits in the app: 1 US tablespoon (14 787 µL) to 1 US gallon (3 785 412 µL).

## Settings (also shadow-api update `payload`)

| Key | Values | Notes |
| --- | --- | --- |
| `defaultTemp` | `handle`, `coldest`, `hottest` | Temperature for gesture/voice starts. **code** |
| `handleTimeout` | 60, 120, 300, 900 s | Auto shut-off. **code** |
| `sensorTimeout`, `voiceTimeout` | 60, 120, 300, 600, 900 s | **code** |
| `dispenseActivateTimeout` | 60, 120, 300 s | How long a "wait for wave" dispense stays armed. **code** |
| `defaultFlowRate`, `lowFlowRate` | 30–100 % | **code** |
| `freezeEnable` | bool | Freeze protection: trickles water based on cabinet temperature. **code** |
| `gestureMode` | values not found in the app; `na` on the test faucet | **code** |

Safety mode and the safety limit are **location** preferences (location API), not
faucet settings.

## Reported state (shadow `state.reported`)

| Key | Meaning |
| --- | --- |
| `state` | `idle` or `running` (the app knows no others) |
| `temperature` | Outlet temperature. **Only updated when a run ends**, not during it. |
| `temperatureLast` | Final temperature of the last run (what the app shows) |
| `temperatureGoal` | `specific`, `hottest`, ... |
| `volume` | Last session's water use in µL (not a counter) |
| `learnedMinTemp`, `learnedMaxTemp` | Re-estimated by the faucet; `learnedMinTemp` **rises** after short runs, so it's not a floor |
| `defaultFlowRate`, `lowFlowRate`, `maxFlowRate`, `trickleFlowRate` | % |
| `handleTimeout`, `sensorTimeout`, `voiceTimeout`, `dispenseActivateTimeout`, `purgeTimeout`, `unwinterizeTimeout`, `healthProtectTimeout` | s |
| `safetyModeEnabled`, `safetyLimitTemp`, `childModeEnabled`, `childLimitTemp` | Mirrored from location preferences |
| `freezeEnable`, `isFreezing`, `assemblyAirTemp` | Freeze protection and cabinet temperature (°C) |
| `connected`, `lastConnect`, `wifiRssi`, `wifiNetwork`, `wifiNoPoll` | Connectivity |
| `batteryPercentage`, `batteryLifeRemaining`, `powerSource`, `batterySavingLevel` | Power |
| `firmwareVersion`, `handleFW`, `latchFW`, `gestureFW`; `*CommError` | Firmware and component faults |
| `alerts` | `{code: {timestamp, state}}`, e.g. `2802` |

## Sessions (session API `data[]`)

`timestamp` (Unix s), `totalVolUl`, `durationMs`, `avgTempC`, `minTempC`, `maxTempC`,
`targetTempC`, `timeToTargetTemp`, `maxFlowUlPerSec`, `purgeVolUl`, `source`
(`app`, `handle`, ...), `sessionEndReason` (`complete`, ...), `cmdSrcBitmask`, gesture
fields, motor current/time fields. The test faucet peaks at ~5 L/min at full flow.
