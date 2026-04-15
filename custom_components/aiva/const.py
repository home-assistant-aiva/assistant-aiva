"""Constants for the AIVA integration."""

DOMAIN = "aiva"

CONF_BASE_URL = "base_url"
# Legacy key kept only to read config entries created before pairing_code.
CONF_LINKING_CODE = "linking_code"
CONF_PAIRING_CODE = "pairing_code"
CONF_HOME_NAME = "home_name"
CONF_HOME_ID = "home_id"
CONF_SECRET = "secret"
CONF_PLAN = "plan"
CONF_SCAN_INTERVAL = "scan_interval"

PLAN_BASE = "base"
PLAN_SMART = "smart"
PLAN_PREMIUM = "premium"
PLANS = (PLAN_BASE, PLAN_SMART, PLAN_PREMIUM)

STATE_INSTALLED = "installed"
STATE_AWAITING_PAIRING = "awaiting_pairing"
STATE_AWAITING_PAYMENT = "awaiting_payment"
STATE_ACTIVE = "active"
ACTIVATION_STATES = (
    STATE_INSTALLED,
    STATE_AWAITING_PAIRING,
    STATE_AWAITING_PAYMENT,
    STATE_ACTIVE,
)

DEFAULT_SCAN_INTERVAL_SECONDS = 300
MIN_SCAN_INTERVAL_SECONDS = 30
# Development default. Production can use any direct backend URL or reverse
# proxy URL, for example https://api.example.com, because endpoints are relative.
DEFAULT_API_BASE_URL = "http://localhost:8080"
DEFAULT_API_TIMEOUT_SECONDS = 10

# Keep backend paths relative so base_url can point to a local backend today or
# to a future domain/reverse proxy without changing the integration architecture.
ENDPOINT_PAIR = "/pair"
ENDPOINT_PAIRING_START = "/pairing/start"
ENDPOINT_PAIRING_STATUS = "/pairing/status"
ENDPOINT_HEARTBEAT = "/heartbeat"
ENDPOINT_ENTITIES_SYNC = "/entities/sync"

HEADER_AIVA_SECRET = "x-aiva-secret"

FIELD_OK = "ok"
FIELD_PAIRING_CODE = "pairing_code"
FIELD_HOME_NAME = "home_name"
FIELD_HOME_ID = "home_id"
FIELD_SECRET = "secret"
FIELD_PLAN = "plan"
FIELD_STATE = "state"
FIELD_HEARTBEAT_AT = "heartbeat_at"
FIELD_ENTITIES = "entities"

ATTR_CONNECTED = "connected"
ATTR_HOME_NAME = "home_name"

SYNC_ENTITY_DOMAINS = (
    "alarm_control_panel",
    "binary_sensor",
    "climate",
    "cover",
    "light",
    "lock",
    "media_player",
    "scene",
    "script",
    "sensor",
    "switch",
)
