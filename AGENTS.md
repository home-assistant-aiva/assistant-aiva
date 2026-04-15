# AGENTS.md

Reglas para trabajar en este repositorio.

- El producto se llama AIVA.
- No usar el nombre Atlas.
- No agregar Telegram en este repositorio.
- No agregar voz todavía.
- Mantener `base_url` configurable desde la UI.
- Usar endpoints relativos al backend para soportar URL directa hoy y proxy o reverse proxy mañana.
- No hardcodear dominios, IPs, secrets ni paths de proxy.
- Hacer cambios mínimos, prolijos y mantenibles.
- No exponer `secret`, `pairing_code` completo ni credenciales sensibles en logs, diagnostics, tests o respuestas.
- Mantener textos visibles para usuarios en español cuando correspondan.
- Priorizar compatibilidad con config entries existentes.
- No meter frontend complejo en esta integración.
