# Soporte Windows de AIVA Collector

## Que mandar a soporte

Cuando haya un problema, mandar:

- Captura de pantalla del error.
- Nombre del BAT ejecutado.
- Version de Python mostrada por `check_python.bat`.
- Carpeta `C:\AIVA_Comercio\diagnostico` generada por `collect_diagnostics.bat`.
- `config.sanitized.json`, revisado antes de compartir.
- `aiva_collector.log`, si existe.
- `last_summary.json`, solo si no contiene datos sensibles para el comercio.

## Que no mandar

- Tokens.
- Contraseñas.
- `.env`.
- `config.local.json` sin revisar.
- Archivos originales del comercio, salvo que soporte los pida y el cliente lo autorice.
- Base de datos completa del sistema del comercio.
- Tickets con datos personales si no son necesarios.

## Como ejecutar diagnostico

1. Ir a `C:\AIVA_Comercio\collector\windows`.
2. Ejecutar `collect_diagnostics.bat`.
3. Revisar `C:\AIVA_Comercio\diagnostico`.
4. Abrir `config.sanitized.json` y confirmar que no tenga tokens ni datos sensibles.
5. Enviar el ZIP `aiva_collector_diagnostico.zip` o la carpeta de diagnostico revisada.

`collect_diagnostics.bat` no ejecuta envio, no llama al backend y no manda nada por internet.

## Como describir el problema

Incluir:

- Que paso.
- Que BAT se ejecuto.
- Que archivo de entrada se uso.
- Si fallo `run_validate`, `run_dry`, `run_status` o `run_send`.
- Si el error aparecio antes o despues de confirmar `ENVIAR`.
- Cambios hechos en `column_mapping`.

Nunca mandar token por chat, ticket, email o captura. Si se sospecha que un token fue compartido, regenerarlo desde admin AIVA Comercial.
