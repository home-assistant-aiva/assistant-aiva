# AIVA Collector Windows Installer

`AIVA-Collector-Setup-v0.1.0.exe` instala AIVA Collector en Windows sin requerir Python.

## Rutas instaladas

Programa:

```text
{pf}\AIVA Collector
```

Datos del comercio:

```text
C:\AIVA_Comercio
```

El instalador crea:

- `C:\AIVA_Comercio\entrada`
- `C:\AIVA_Comercio\procesados`
- `C:\AIVA_Comercio\errores`
- `C:\AIVA_Comercio\output`
- `C:\AIVA_Comercio\logs`
- `C:\AIVA_Comercio\state`
- `C:\AIVA_Comercio\diagnostico`

## Configuracion

Si no existe, crea:

```text
C:\AIVA_Comercio\config.local.json
```

La base sale de `windows/config.windows.example.json`. Si el archivo ya existe, no lo pisa.

El instalador RC4 conserva `C:\ProgramData\AIVA\Collector`, instala la tarea automatica silenciosa con `aiva-collector-background.exe` y migra automaticamente una configuracion previa valida si corresponde. Al abrir `aiva-collector.exe` sin argumentos muestra un menu interactivo que permanece visible. Los comandos del EXE resuelven el token desde entorno, config instalada heredada o token protegido por activacion, sin imprimirlo.

La tarea programada creada por RC4 usa el comando `run-auto`, no recibe token por argumentos, no ejecuta discovery automatico repetido y reemplaza solamente tareas conocidas anteriores: `AIVA Collector`, `AIVA Collector Scheduled` y `AIVA Collector Auto`.

## Accesos directos

El menu inicio incluye:

- AIVA Collector
- AIVA Collector - Procesar ahora
- AIVA Collector - Validar configuracion
- AIVA Collector - Prueba sin enviar
- AIVA Collector - Detectar fuentes sin enviar
- AIVA Collector - Reportar fuentes detectadas
- AIVA Collector - Estado conexion
- AIVA Collector - Enviar al servidor
- AIVA Collector - Diagnostico
- AIVA Collector - Abrir carpeta de entrada
- AIVA Collector - Abrir resultados

`Enviar al servidor` exige token y confirmacion exacta `ENVIAR`.

`Diagnostico` no llama al backend, no ejecuta envio, no usa curl y no copia archivos originales del comercio por defecto. Si copia config, la sanitiza.

## Build

El build real se ejecuta en GitHub Actions con runner `windows-latest`:

```text
.github/workflows/build-windows-installer.yml
```

Artifacts esperados:

- `aiva-collector.exe`
- `AIVA-Collector-Setup-v0.1.0.exe`
- `AIVA-Collector-Installer-v0.1.0.manifest.json`
- `aiva-collector-windows-exe-v0.1.0.zip`
