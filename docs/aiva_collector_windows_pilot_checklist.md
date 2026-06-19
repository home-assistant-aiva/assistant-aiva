# Checklist piloto Windows de AIVA Collector

## A. Preparacion

- Confirmar Python 3.11 o superior instalado.
- Confirmar que durante la instalacion se marco `Add Python to PATH`.
- Crear la carpeta `C:\AIVA_Comercio`.
- Descomprimir el ZIP en `C:\AIVA_Comercio\collector`.
- Ejecutar `C:\AIVA_Comercio\collector\windows\check_python.bat`.
- Ejecutar `C:\AIVA_Comercio\collector\windows\install_manual.bat`.
- Ejecutar `C:\AIVA_Comercio\collector\windows\install_dependencies.bat`.

## B. Configuracion

- Abrir `C:\AIVA_Comercio\config.local.json`.
- Configurar `backend_url`.
- Configurar `commerce_id`.
- Configurar `collector_id`.
- Configurar `column_mapping` segun las columnas reales del archivo.
- No poner token en `config.local.json`.
- Guardar el archivo.

## C. Prueba sin envio

- Copiar el CSV/XLSX exportado del comercio a `C:\AIVA_Comercio\entrada`.
- Ejecutar `C:\AIVA_Comercio\collector\windows\run_validate.bat`.
- Ejecutar `C:\AIVA_Comercio\collector\windows\run_dry.bat`.
- Revisar `C:\AIVA_Comercio\output\last_summary.json`.
- Confirmar `productos_resumidos > 0`.
- Confirmar que `filas_descartadas` sea razonable para el archivo probado.
- Confirmar que no se envio nada al backend.

Para abrir el summary:

```bat
Get-Content C:\AIVA_Comercio\output\last_summary.json -Raw
C:\Windows\System32\notepad.exe C:\AIVA_Comercio\output\last_summary.json
```

## D. Prueba con envio controlado

- Configurar token temporal en la misma consola:

```bat
set AIVA_COLLECTOR_TOKEN=...
```

- Ejecutar `C:\AIVA_Comercio\collector\windows\run_status.bat`.
- Ejecutar `C:\AIVA_Comercio\collector\windows\run_send.bat`.
- Escribir `ENVIAR` solo si se quiere enviar el summary.
- Confirmar en admin `/aiva-comercial`:
  - collector status
  - recomendaciones
  - ultimo reporte
  - audit summaries

## E. Cierre

- No compartir token.
- Guardar captura del resultado.
- Guardar logs para soporte si hubo error.
- Si hace falta soporte, ejecutar `C:\AIVA_Comercio\collector\windows\collect_diagnostics.bat`.
