# Changelog

All notable changes to AIVA for Home Assistant will be documented in this file.

## 0.2.16 - Auto reconnect after Home Assistant restart

- Added automatic reconnect on config entry setup and when Home Assistant finishes starting.
- Added bounded retry/backoff when the AIVA backend is unavailable at startup.
- Made heartbeat and activation status checks part of the reconnect path.
- Added automatic entity sync after a successful reconnect.
- Added reconnect, heartbeat and sync diagnostics without exposing secrets.
- Improved status sensor states for reconnecting, unavailable, active, awaiting payment and suspended homes.

## 0.2.15 - Entity sync helpers

- Added `input_boolean` and `input_select` helpers to the useful entity sync set.
- Excluded AIVA internal entities from local entity sync counts.
- Enriched `/entities/sync` payloads with metadata such as icon, options, supported features and availability.
- Added local sync diagnostics and effective entity counts.

## 0.2.9 - HACS release cleanup

- Confirmed the onboarding flow points to `@aiva_asistente_1_bot`.
- Removed the hardcoded backend IP from the default `base_url` field.
- Aligned release documentation and setup notes with the current activation flow.
- Kept translations and visible AIVA naming consistent across the integration.

## 0.2.0 - Initial HACS-ready release

- Added HACS-ready repository structure for the `aiva` custom integration.
- Added UI-based configuration and commercial activation flow.
- Added configurable `base_url` and relative backend endpoints.
- Added AIVA status and last sync sensors.
- Added buttons to verify connection and update devices.
- Added diagnostics redaction for sensitive values.
