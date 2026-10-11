"""Constants for the E.ON Drive integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "eon_drive"

BASE_URL = "https://eon-drive-cz.eu-eon.charge.ampeco.tech/api/v1/app"
OPERATOR_COUNTRY = "CZ"
APP_BUNDLE_ID = "com.eon.drive.cz"
APP_PLATFORM = "ios"
APP_INTERNAL_VERSION = "3.255.0"
APP_USER_AGENT = "ChargeMobile/1790797529 CFNetwork/3896.100.1.1.1 Darwin/27.0.0"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_DEVICE_ID = "device_id"
CONF_LOCATIONS = "locations"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_QUERY = "query"

# Be a polite client: far fewer requests than the app itself makes.
DEFAULT_SCAN_INTERVAL = 600
MIN_SCAN_INTERVAL = 300
MAX_SCAN_INTERVAL = 3600
# Upper bound for the automatic back-off after errors / rate limiting.
MAX_BACKOFF = 3600

# Charging history changes rarely; refresh it less often than charger status.
HISTORY_INTERVAL = timedelta(hours=1)
REQUEST_TIMEOUT = 30

EVSE_STATES = [
    "available",
    "charging",
    "preparing",
    "finishing",
    "suspended",
    "reserved",
    "unavailable",
    "out_of_order",
    "unknown",
]
