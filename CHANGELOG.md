# Changelog

All notable changes to AIVA for Home Assistant will be documented in this file.

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
