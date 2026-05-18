# Changelog

All notable changes to AIVA for Home Assistant will be documented in this file.

## 0.2.20 - AIVA Seguridad Negocios MVP

- Consulta configuración de seguridad desde backend.
- Escucha sensores configurados.
- Envía eventos automáticos al backend.
- Permite prueba sin sensor real con `input_boolean.puerta_negocio_prueba`.
- No usa `AIVA_INTERNAL_SECRET`.

## 0.2.17 - Conversation agent for Assist

- Added AIVA as a Home Assistant `conversation` platform so it can be selected as the conversation agent in Assist pipelines.
- Added `POST /conversation/handle` support using the existing AIVA secret authentication.
- Added plan and activation guards for voice: Smart or Premium plan, linked home and active activation state.
- Added safe local fallback responses for basic AIVA connectivity/status questions when the conversation backend is unavailable.
- Added conversation diagnostics without exposing secrets.
- Documented Assist setup, requirements and current limitations.

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
