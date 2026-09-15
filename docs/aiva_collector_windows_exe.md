# Ejecutables de AIVA Collector para Windows

El paquete no requiere Python instalado y contiene tres ejecutables en una
distribución PyInstaller `onedir` con dependencias compartidas:

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

## Compatibilidad antivirus y firma

UPX está deshabilitado tanto en los tres ejecutables como en el directorio
final, y el build inspecciona todos los PE para rechazar secciones UPX. La
distribución `onedir` evita los tres archivos autocontenidos grandes anteriores y
permite que Inno instale una sola copia de las dependencias compartidas.

El workflow registra tipo PE, tamaño, imports, recursos de versión, hashes,
firma embebida y SHA del commit. También solicita un análisis de Microsoft
Defender; si Defender no está disponible en el runner, la evidencia lo declara
sin simular un resultado limpio.

No hay actualmente un certificado comercial de firma configurado para este
repositorio. Los candidatos de prueba quedan `NotSigned`; para distribución
general se necesita un certificado Authenticode legítimo, su clave privada en
un secreto autorizado, la contraseña correspondiente y un servicio de
timestamp confiable, firmando con SHA-256 antes y después de Inno según
corresponda.
