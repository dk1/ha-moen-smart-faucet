"""Constants for the Moen Smart Faucet integration."""

from datetime import timedelta
import logging

DOMAIN = "moen_smart_faucet"
LOGGER = logging.getLogger(__package__)

MANUFACTURER = "Moen"
MODEL = "Smart Faucet"

SCAN_INTERVAL = timedelta(seconds=30)
RUNNING_SCAN_INTERVAL = timedelta(seconds=5)
# The faucet reflects a command in its shadow within a few seconds.
COMMAND_REFRESH_DELAY = 3

STATE_RUNNING = "running"

DEFAULT_RUN_TEMPERATURE = 38.0
MIN_RUN_TEMPERATURE = 5.0
MAX_RUN_TEMPERATURE = 60.0

SERVICE_RUN = "run"
ATTR_TEMPERATURE = "temperature"
ATTR_PRESET = "preset"
