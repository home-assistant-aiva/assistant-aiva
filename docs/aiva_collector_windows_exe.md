# Ejecutables de AIVA Collector para Windows

El paquete no requiere Python instalado y contiene tres ejecutables:

- `aiva-collector.exe`: aplicación gráfica para el cliente;
- `aiva-collector-cli.exe`: consola técnica;
- `aiva-collector-background.exe`: runner silencioso para la tarea automática.

## Configuración canónica

```text
C:\ProgramData\AIVA\Collector\config.windows.json
```

El CLI también puede descubrir configuraciones heredadas. Cuando se pasa `--config`, la ruta debe existir.

## Comandos de soporte

```bat
aiva-collector-cli.exe validate
aiva-collector-cli.exe run-once
aiva-collector-cli.exe status
aiva-collector-cli.exe queue-status
aiva-collector-cli.exe diagnose-config
```

`run-once` sin `--send` no envía al backend. El envío normal se hace mediante la aplicación o el runner automático.

## Token

La activación gráfica guarda el token fuera del JSON y lo protege con Windows DPAPI. No se debe pedir, copiar ni compartir el token por chat, tickets o capturas.

## ZIP técnico

El ZIP técnico incluye los tres ejecutables, documentación y wrappers de soporte. No contiene `.env`, configuraciones reales, logs, estado, archivos comerciales ni tokens.
