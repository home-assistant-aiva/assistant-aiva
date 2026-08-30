# AIVA Collector para Windows

El instalador Desktop RC1 separa las tres responsabilidades del Collector:

- `aiva-collector.exe`: aplicación gráfica para el cliente;
- `aiva-collector-cli.exe`: comandos técnicos y soporte;
- `aiva-collector-background.exe`: sincronización automática sin consola.

## Experiencia del cliente

El acceso directo `AIVA Collector` abre un panel que muestra:

- activación del equipo;
- carpeta de datos seleccionada;
- cantidad de CSV/XLSX disponibles;
- última ejecución, archivos procesados, resúmenes enviados y cola pendiente;
- estado de la tarea automática;
- acciones para probar conexión y sincronizar ahora.

La primera configuración requiere solamente un código de AIVA Comercial y elegir la carpeta de exportación del sistema de ventas. La URL del servicio queda dentro de configuración avanzada.

## Rutas

Programa:

```text
C:\Program Files\AIVA Collector
```

Datos persistentes:

```text
C:\ProgramData\AIVA\Collector
```

La configuración canónica es:

```text
C:\ProgramData\AIVA\Collector\config.windows.json
```

El instalador conserva ProgramData durante actualizaciones. La activación guarda el token fuera del JSON y lo protege con Windows DPAPI.

Para producción, `backend_url` debe usar HTTPS con un certificado válido. La aplicación marca una conexión HTTP como modo de prueba para evitar presentarla como una instalación final segura.

## Sincronización automática

La tarea `AIVA Collector Auto` ejecuta:

```text
aiva-collector-background.exe run-auto --config "%ProgramData%\AIVA\Collector\config.windows.json"
```

Se inicia 60 segundos después del inicio de sesión, se repite cada 15 minutos, evita instancias superpuestas y reintenta fallas temporales.

## Seguridad de la fuente

Cuando el usuario elige una carpeta desde la aplicación, se configura como fuente observada de solo lectura:

- `move_processed_files=false`;
- `move_error_files=false`;
- `keep_original_files=true`.

AIVA calcula una huella local para evitar reenvíos. No mueve ni borra los archivos originales del sistema de ventas.

## Empaquetado

El build se ejecuta con el workflow:

```text
.github/workflows/build-collector-windows-release.yml
```

Artefactos esperados:

- `AIVA-Collector-Setup-v0.2.7-desktop-rc1.exe`;
- `AIVA-Collector-Installer-v0.2.7rc1.manifest.json`;
- `aiva-collector-windows-manual-v0.2.7-desktop-rc1.zip`;
- `SHA256SUMS.txt`.
