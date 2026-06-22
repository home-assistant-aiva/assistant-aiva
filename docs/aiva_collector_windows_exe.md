# AIVA Collector Windows EXE

`aiva-collector.exe` es el ejecutable tecnico de consola para Windows. No requiere Python instalado en la PC del comercio.

## Configuracion por defecto

En Windows, si no se pasa `--config`, el collector usa:

```text
C:\AIVA_Comercio\config.local.json
```

En Linux se mantiene el comportamiento historico: se debe pasar `--config`.

## Comandos

```bat
aiva-collector.exe validate --config C:\AIVA_Comercio\config.local.json
aiva-collector.exe run-once --config C:\AIVA_Comercio\config.local.json
aiva-collector.exe status --config C:\AIVA_Comercio\config.local.json
aiva-collector.exe send --config C:\AIVA_Comercio\config.local.json
```

Tambien existe `service-status` como alias de `status`.

`run-once` sin `--send` es dry-run: genera `last_summary.json` y no envia nada al backend.

## Token

El token nunca se guarda en `config.local.json`. Para enviar o consultar estado contra el backend, debe existir la variable de entorno:

```bat
set AIVA_COLLECTOR_TOKEN=PEGAR_TOKEN_SOLO_EN_LA_PC_DEL_COMERCIO
```

No compartir tokens por chat, tickets ni capturas.

## ZIP tecnico

El artifact opcional `aiva-collector-windows-exe-v0.1.0.zip` contiene:

- `dist/aiva-collector.exe`
- documentacion minima
- `windows/config.windows.example.json`
- wrappers `.bat` para ejecutar acciones comunes

No contiene `.env`, `config.local.json`, logs, state ni outputs reales.
