# Changelog

All notable changes to AIVA for Home Assistant will be documented in this file.

## 0.2.30 - Premium Voice speakers

- Agrega soporte seguro para `media_player.play_media` usado por AIVA Premium Voice.
- Permite únicamente URLs temporales de AIVA bajo `/premium-voice/audio/`.
- Mantiene bloqueados otros servicios `media_player`, URLs externas y tipos de contenido no permitidos.
- Conserva action queue, `lease_id` y reporte seguro de errores al backend.

## 0.2.29 - Safe cover close actions

- Agrega soporte seguro para ejecutar `cover.close_cover` desde acciones autorizadas de AIVA.
- Mantiene bloqueadas acciones sensibles o riesgosas como cerraduras, alarmas, cámaras, sirenas, aspiradoras y apertura de covers.
- Mejora el reporte seguro de errores de ejecución hacia el backend.
- Mantiene compatibilidad con action queue, lease_id y reportes de resultado.

## 0.2.28 - Safe entity attributes sync

- Envía atributos sanitizados de entidades al backend para mejorar rutinas locales.
- Conserva `input_select.options` para que AIVA use opciones reales y no inventadas.
- Agrega `entity_category` al payload de sincronización.
- Agrega soporte para solicitudes de sync completo desde Admin.
- Excluye tokens, claves, URLs sensibles e imágenes/base64 del sync.

## 0.2.27 - Service selection onboarding

- Agrega selección inicial de servicio: Home, Seguridad y Rentals.
- Habilita AIVA Home como servicio disponible.
- Muestra Seguridad y Rentals como próximamente.
- Mantiene compatibilidad con instalaciones existentes.

## 0.2.26 - Activation-aware business security

- Consulta la configuración de AIVA Seguridad Negocios desde el backend.
- Escucha únicamente sensores activos configurados para el home.
- Envía eventos automáticos usando el `secret` propio del home en `x-aiva-secret`; no usa `AIVA_INTERNAL_SECRET`.
- Respeta la activación única de AIVA: un home no activo no consulta configuración ni envía eventos de seguridad.
- Permite validar el flujo sin sensor físico con `input_boolean.puerta_negocio_prueba`.

## 0.2.25 - Sync entity state after queued action

- Envía el estado final de la entidad al reportar una acción completada.
- Actualiza el backend para responder correctamente consultas de luces prendidas.
- Mantiene compatibilidad con la cola de acciones y lease_id.

## 0.2.24 - Fix queued action result reporting

- Corrige reporte de acciones con lease_id.
- Corrige llamadas con home_id a endpoints del backend.
- Mejora logs del action manager.

## 0.2.23 - Reliable queued actions

- Agrega `lease_id` para ejecucion idempotente de acciones.
- Mejora proteccion contra doble ejecucion con cache TTL local.
- Reporta resultados con lease.
- Mejora diagnostico del action manager.

## 0.2.22 - Local action queue execution

- Polls pending AIVA actions through the per-home secret.
- Executes allowlisted services locally in Home Assistant and reports results.
- Blocks sensitive domains and avoids duplicate local execution.
- Adds action polling diagnostics without Home Assistant tokens or AI calls.

## 0.2.21 - GitHub validation fix

- Corrige el orden de claves del manifest para Hassfest.
- Mejora el workflow de validación.
- Mantiene compatibilidad con HACS.
- No cambia comportamiento funcional de la integración.

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
