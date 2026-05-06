# AIVA para Home Assistant

Integración custom de Home Assistant para conectar una casa con AIVA.

## Funcionalidad actual

- Alta desde la UI de Home Assistant.
- Activación comercial por plan.
- Dirección `base_url` configurable.
- Heartbeat periódico hacia el backend de AIVA.
- Sincronización de entidades permitidas.
- Sensores de estado y última sincronización.
- Botones para verificar conexión y actualizar dispositivos.

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

Para probar, creá helpers como `input_boolean.luz_living_prueba`, `input_boolean.alarma_de_prueba` e `input_select.modo_casa_prueba`, tocá `Actualizar dispositivos` y revisá el sensor `Entidades efectivas`.

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
