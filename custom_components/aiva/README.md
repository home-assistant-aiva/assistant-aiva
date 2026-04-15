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

Al activarse, la integración guarda los datos necesarios para operar con AIVA. No publiques credenciales, secrets ni códigos completos en logs, issues o capturas.

## Compatibilidad HACS

El repositorio debe incluir:

- `hacs.json` en la raíz.
- `README.md` en la raíz.
- una sola integración bajo `custom_components/aiva`.
- `manifest.json` con `domain`, `name`, `documentation`, `issue_tracker`, `codeowners` y `version`.
- branding básico en `brand/icon.png`.
