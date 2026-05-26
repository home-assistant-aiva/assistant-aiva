# AIVA para Home Assistant

Integración custom de Home Assistant para conectar una casa con AIVA.

## Funcionalidad actual

- Alta desde la UI de Home Assistant.
- Activación comercial por plan.
- Dirección `base_url` configurable.
- Heartbeat periódico hacia el backend de AIVA.
- Sincronización de entidades permitidas.
- Agente de conversación para Assist.
- Auto-reconexión después de reinicio o pérdida temporal del backend.
- Sync automático de entidades después de reconectar.
- AIVA Seguridad Negocios con sensores configurados desde el backend.
- Sensores de estado y última sincronización.
- Botones para verificar conexión y actualizar dispositivos.

## Reconexión

Al cargar la config entry, AIVA deja sensores disponibles y arranca una recuperación en segundo plano. El flujo envía heartbeat, consulta `activation/status` y, si la casa está `active`, sincroniza entidades automáticamente.

Si el backend no responde durante el arranque, la integración no bloquea Home Assistant. El estado pasa a `Reconectando` o `Sin conexión con AIVA` y se reintenta cada 30 segundos durante los primeros minutos; luego baja la frecuencia. Cuando la red o el backend vuelven, AIVA se marca como `Activo` sin intervención del usuario.

Los botones `Verificar conexión` y `Actualizar dispositivos` siguen disponibles como respaldo manual, pero no deberían ser necesarios después de cada reinicio.

## Sincronización de entidades

AIVA incluye entidades útiles de estos dominios:

- `input_boolean`
- `input_select`
- `alarm_control_panel`
- `light`
- `switch`
- `sensor`
- `binary_sensor`
- `cover`
- `climate`
- `lock`
- `media_player`
- `fan`
- `scene`
- `script`
- `automation`

Los helpers `input_boolean` e `input_select` cuentan como entidades efectivas aunque no tengan `device_id`.

No se sincronizan entidades internas de AIVA (`sensor.aiva_*`, `button.aiva_*` o integración `aiva`) ni dominios internos o sensibles como `update`, `persistent_notification`, `zone`, `person`, `device_tracker`, `sun` y `weather`.

Para probar, creá helpers como `input_boolean.luz_living_prueba`, `input_boolean.alarma_de_prueba` e `input_select.modo_casa_prueba`, reiniciá Home Assistant o tocá `Actualizar dispositivos` y revisá el sensor `Entidades efectivas`.

## Seguridad Negocios

La integración consulta periódicamente `GET /homes/{home_id}/security/config` usando el `secret` propio del home en `x-aiva-secret`. Si el home está activo y seguridad está habilitada, escucha solo los `entity_id` activos que devuelve el backend y manda eventos útiles a `POST /homes/{home_id}/security/events`. Si el home no está activo, no consulta configuración ni envía eventos; no usa `AIVA_INTERNAL_SECRET`.

Para probar sin sensor físico:

1. Creá el helper `input_boolean.puerta_negocio_prueba`.
2. En Admin AIVA, entrá a `Seguridad Negocios` y elegí el home.
3. Agregá el sensor `input_boolean.puerta_negocio_prueba` como `Puerta principal`, tipo `door`, área `Entrada`, activo.
4. Configurá el horario permitido.
5. Esperá hasta 60 segundos y cambiá el helper desde Home Assistant.
6. Revisá en Admin AIVA el evento registrado y la alerta si fue fuera de horario.

AIVA ignora estados `unknown`, `unavailable` y cambios sin diferencia real de estado.

## Assist

AIVA registra la entidad `conversation.aiva` con el nombre `AIVA`. Para usarla:

1. Abrí `Ajustes > Asistentes de voz`.
2. Editá o creá un pipeline.
3. Elegí `AIVA` como agente de conversación.
4. Mantené tu STT y TTS configurados en Home Assistant si querés usar voz hablada.

Requisitos: casa vinculada, activación `active`, plan Smart o Premium y backend accesible desde el `base_url` configurado.

La integración no instala Piper, Whisper, micrófonos, wake word ni cambia `configuration.yaml`. En esta primera versión no ejecuta servicios locales desde texto libre; envía el texto al backend AIVA por `POST /conversation/handle` y devuelve la respuesta textual a Home Assistant.

Si el endpoint de conversación no responde, hay fallback local para preguntas básicas como si AIVA está conectada, estado de la casa y verificación de conexión.

## Instalación

La forma recomendada es instalar desde HACS como custom repository.

Para desarrollo manual, copiá esta carpeta en:

```text
config/custom_components/aiva
```

Reiniciá Home Assistant y agregá la integración desde:

```text
Ajustes > Dispositivos y servicios > Añadir integración > AIVA
```

## Configuración

Campos principales:

- `base_url`: URL base del backend de AIVA.
- `home_name`: nombre visible de la casa.
- `plan`: plan comercial de AIVA.
- `scan_interval`: intervalo de actualización en segundos.

Durante la activación, Home Assistant genera un código de vinculación y muestra un acceso directo al bot `@aiva_asistente_1_bot` para completar el paso externo sin frontend adicional.

Al activarse, la integración guarda los datos necesarios para operar con AIVA. No publiques credenciales, secrets ni códigos completos en logs, issues o capturas.

## Compatibilidad HACS

El repositorio debe incluir:

- `hacs.json` en la raíz.
- `README.md` en la raíz.
- una sola integración bajo `custom_components/aiva`.
- `manifest.json` con `domain`, `name`, `documentation`, `issue_tracker`, `codeowners` y `version`.
- branding básico en `brand/icon.png`.
