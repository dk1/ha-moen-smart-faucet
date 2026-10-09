"""Constants for the Moen Smart Faucet integration."""

from datetime import timedelta
import logging

DOMAIN = "moen_smart_faucet"
LOGGER = logging.getLogger(__package__)

MANUFACTURER = "Moen"
MODEL = "Smart Faucet"

SCAN_INTERVAL = timedelta(seconds=30)
RUNNING_SCAN_INTERVAL = timedelta(seconds=5)
PRESET_SCAN_INTERVAL = timedelta(minutes=30)
# The faucet reflects a command in its shadow within a few seconds.
COMMAND_REFRESH_DELAY = 3
# How long a just-sent run counts as active before the faucet reports it.
RUN_START_GRACE = 15

STATE_RUNNING = "running"

DEFAULT_RUN_TEMPERATURE = 38.0
MIN_RUN_TEMPERATURE = 5.0
MAX_RUN_TEMPERATURE = 60.0

DEFAULT_FLOW_RATE = 100
MIN_FLOW_RATE = 30
MAX_FLOW_RATE = 100

DEFAULT_DISPENSE_ML = 250.0
MIN_DISPENSE_ML = 15.0
MAX_DISPENSE_ML = 3785.0

SERVICE_RUN = "run"
SERVICE_DISPENSE = "dispense"
ATTR_TEMPERATURE = "temperature"
ATTR_PRESET = "preset"
ATTR_FLOW_RATE = "flow_rate"
ATTR_VOLUME = "volume"
ATTR_UNIT = "unit"
ATTR_START = "start"
START_NOW = "now"
START_ON_WAVE = "on_wave"

# Microlitres per unit, as the Moen app converts them (US customary units).
UNIT_TO_UL = {
    "ml": 1_000,
    "l": 1_000_000,
    "tbsp": 14_786.765,
    "fl_oz": 29_573.53,
    "cup": 236_588.236,
    "pint": 473_176.473,
    "quart": 946_352.946,
    "gal": 3_785_411.784,
}
