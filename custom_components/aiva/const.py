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
# Current deployment default. Keep this configurable from the UI so the
# integration can later point to a direct domain or reverse proxy without code
# changes.
DEFAULT_API_BASE_URL = "http://187.77.44.118:8080"
DEFAULT_API_TIMEOUT_SECONDS = 10

# Telegram bot username used by the pairing onboarding flow. Keep it
# centralized so the config flow can expose a direct deep link without adding
# custom frontend code.
TELEGRAM_BOT_USERNAME = "aiva_asistente_1_bot"

# Keep backend paths relative so base_url can point to a local backend today or
# to a future domain/reverse proxy without changing the integration architecture.
ENDPOINT_PAIR = "/pair"
ENDPOINT_ACTIVATION_REQUEST = "/activation/request"
ENDPOINT_ACTIVATION_PAIRING_CODE = "/activation/pairing-code"
ENDPOINT_PAIRING_START = "/pairing/start"
ENDPOINT_PAIRING_STATUS = "/pairing/status"
ENDPOINT_HEARTBEAT = "/heartbeat"
ENDPOINT_ENTITIES_SYNC = "/entities/sync"
ENDPOINT_HOME_SETTINGS = "/home/settings"
ENDPOINT_HOME_AUTOMATIONS = "/home/automations"
ENDPOINT_ENTITIES_EFFECTIVE = "/entities/effective"

HEADER_AIVA_SECRET = "x-aiva-secret"

FIELD_OK = "ok"
FIELD_PAIRING_CODE = "pairing_code"
FIELD_HOME_NAME = "home_name"
FIELD_HOME_ID = "home_id"
FIELD_SECRET = "secret"
FIELD_PLAN = "plan"
FIELD_STATE = "state"
FIELD_ACTIVATION_STATE = "activation_state"
FIELD_INSTALLATION_ID = "installation_id"
FIELD_HEARTBEAT_AT = "heartbeat_at"
FIELD_ENTITIES = "entities"
FIELD_EFFECTIVE_ENTITIES = "effective_entities"
FIELD_SETTINGS = "settings"
FIELD_HOME_SETTINGS = "home_settings"
FIELD_AUTOMATIONS = "automations"
FIELD_HOME_AUTOMATIONS = "home_automations"

ATTR_CONNECTED = "connected"
ATTR_HOME_NAME = "home_name"
ATTR_INTEGRATION_VERSION = "integration_version"
ATTR_LANGUAGE = "language"
ATTR_ASSISTANT_NAME = "assistant_name"
ATTR_COUNTRY_CODE = "country_code"
ATTR_LOCALE = "locale"
ATTR_TIMEZONE = "timezone"
ATTR_RESPONSE_STYLE = "response_style"
ATTR_CUSTOM_PROMPT_CONFIGURED = "custom_prompt_configured"
ATTR_TOTAL_COUNT = "total_count"
ATTR_ALLOWED_COUNT = "allowed_count"
ATTR_VISIBLE_COUNT = "visible_count"
ATTR_REQUIRES_CONFIRMATION_COUNT = "requires_confirmation_count"
ATTR_ENABLED_COUNT = "enabled_count"
ATTR_DISABLED_COUNT = "disabled_count"
ATTR_SAMPLE = "sample"

MAX_SUMMARY_ITEMS = 10

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
