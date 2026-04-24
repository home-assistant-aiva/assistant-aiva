# AIVA para Home Assistant

[![Validate](https://github.com/home-assistant-aiva/assistant-aiva/actions/workflows/validate.yml/badge.svg)](https://github.com/home-assistant-aiva/assistant-aiva/actions/workflows/validate.yml)

AIVA es una integración custom para Home Assistant que conecta una casa con la plataforma AIVA.

La integración permite activar el servicio desde la UI de Home Assistant, mantener la conexión con el backend de AIVA y sincronizar información básica de dispositivos para que la casa quede disponible dentro del producto.

## Qué incluye

- Instalación desde HACS como custom repository.
- Configuración desde `Ajustes > Dispositivos y servicios`.
- Activación comercial guiada por plan.
- `base_url` configurable desde la UI.
- Sensor de estado de AIVA.
- Sensor de última sincronización.
- Botón para verificar conexión.
- Botón para actualizar dispositivos.
- Diagnósticos con datos sensibles redactados.

## Requisitos

- Home Assistant con soporte para custom integrations.
- HACS instalado en Home Assistant.
- Backend de AIVA accesible desde la instancia de Home Assistant.
- Cuenta, instalación o proceso comercial habilitado en AIVA.

## Instalación por HACS

1. Abrí Home Assistant.
2. Entrá en `HACS > Integraciones`.
3. Abrí el menú de tres puntos.
4. Seleccioná `Repositorios personalizados`.
5. Pegá `https://github.com/home-assistant-aiva/assistant-aiva`.
6. Elegí la categoría `Integración`.
7. Instalá `AIVA`.
8. Reiniciá Home Assistant.
9. Entrá en `Ajustes > Dispositivos y servicios > Añadir integración`.
10. Buscá `AIVA` y comenzá la configuración.

## Configuración inicial

Durante el alta, Home Assistant solicita:

- `Dirección de conexión de AIVA`: URL base del backend de AIVA.
- `Nombre de la casa`: nombre visible para identificar la instalación.
- `Plan de AIVA`: plan que se va a activar.

La dirección de conexión se guarda como `base_url` y puede modificarse luego desde las opciones de la integración.

La integración usa endpoints relativos al backend, por lo que la misma configuración puede funcionar con una URL directa hoy y con un proxy o reverse proxy más adelante.

## Activación

Después de iniciar la configuración, AIVA genera un código de vinculación.

1. Abrí el bot de Telegram `@aiva_asistente_1_bot` desde el enlace directo que muestra Home Assistant o buscándolo manualmente en Telegram.
2. Enviá el código de vinculación exacto al bot.
3. Volvé a Home Assistant.
4. Marcá la confirmación y continuá el flujo.
5. Cuando AIVA confirme la vinculación y el estado comercial, la integración queda activa.

Al finalizar, Home Assistant guarda internamente los identificadores y credenciales necesarios para operar con AIVA. No publiques `secret`, códigos completos de vinculación ni credenciales en logs, issues o capturas.

## Planes

La integración permite seleccionar uno de estos planes durante la activación:

- `base`
- `smart`
- `premium`

La disponibilidad, precio y alcance de cada plan dependen de la oferta comercial vigente de AIVA.

## Soporte básico

Si la integración no conecta:

- Confirmá que Home Assistant pueda acceder a la dirección configurada en `base_url`.
- Verificá que el backend de AIVA esté disponible.
- Revisá que el flujo de activación haya sido completado.
- Reiniciá Home Assistant después de instalar o actualizar desde HACS.
- Usá el botón `Verificar conexión` desde la integración.

Si la sincronización no se actualiza:

- Usá el botón `Actualizar dispositivos`.
- Revisá el sensor `Última sincronización`.
- Confirmá que la integración esté cargada sin errores en Home Assistant.

Para reportar un problema en GitHub, incluí versión de Home Assistant, versión de AIVA y logs redactados. No incluyas credenciales ni códigos completos.

## Desarrollo

Instalación manual para desarrollo:

```bash
mkdir -p /config/custom_components
cp -R custom_components/aiva /config/custom_components/aiva
```

Validaciones locales:

```bash
python3 -m json.tool hacs.json
python3 -m json.tool custom_components/aiva/manifest.json
python3 -m compileall custom_components/aiva
python3 -m pytest
```

Estructura principal:

```text
custom_components/aiva/
  __init__.py
  manifest.json
  config_flow.py
  api.py
  coordinator.py
  sensor.py
  button.py
  diagnostics.py
  translations/
hacs.json
brand/icon.png
```

## Publicación

Para publicar una nueva versión:

1. Actualizá `version` en `custom_components/aiva/manifest.json`.
2. Actualizá `CHANGELOG.md`.
3. Creá un commit.
4. Creá un tag con formato `vX.Y.Z`.
5. Subí el commit y el tag a GitHub.
6. Esperá que GitHub Actions cree la release.
7. Confirmá que HACS detecte la nueva versión.
