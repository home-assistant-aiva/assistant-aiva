# AIVA Collector para Windows

Este paquete permite probar AIVA Collector manualmente en una PC Windows, sin instalador exe y sin servicio.

## Que es

AIVA Collector lee archivos CSV o Excel exportados por el sistema del comercio, normaliza columnas, arma un resumen por producto y, si el usuario lo confirma, envia ese resumen a AIVA Comercial.

## Que hace

- Lee archivos CSV/XLSX desde `C:\AIVA_Comercio\entrada`.
- Resume ventas por producto.
- Genera `C:\AIVA_Comercio\output\last_summary.json`.
- Puede enviar el resumen a AIVA Comercial para recomendaciones y reportes.

## Que no hace

- No factura.
- No vende.
- No modifica stock.
- No toca la base de datos del cliente.
- No borra archivos originales.
- No envia tickets completos.
- No manda el Excel completo.
- No trabaja con datos crudos en la nube.

## Instalacion manual

1. Instalar Python 3.11 o superior desde python.org y marcar `Add Python to PATH`.
2. Copiar la carpeta del collector a `C:\AIVA_Comercio\collector`.
3. Ejecutar `check_python.bat`.
4. Ejecutar `install_manual.bat`.
5. Ejecutar `install_dependencies.bat` con internet disponible.
6. Editar `C:\AIVA_Comercio\config.local.json`.
7. Pegar archivos CSV/XLSX del comercio en `C:\AIVA_Comercio\entrada`.
8. Ejecutar `run_validate.bat`.
9. Ejecutar `run_dry.bat`.
10. Revisar `C:\AIVA_Comercio\output\last_summary.json`.
11. Configurar token temporal en la misma ventana con `set AIVA_COLLECTOR_TOKEN=PEGAR_TOKEN_AQUI`.
12. Ejecutar `run_send.bat` y escribir `ENVIAR` cuando corresponda.
13. Si no hay internet, ejecutar `run_queue_status.bat` para ver pendientes.
14. Cuando vuelva internet, ejecutar `run_retry_pending.bat`.
15. Ver recomendaciones en admin AIVA Comercial.

`commerce_id` y `collector_id` salen del admin AIVA Comercial. El token del collector se copia una sola vez desde el admin y no debe guardarse en `config.local.json`.

Para abrir el summary generado:

```bat
Get-Content C:\AIVA_Comercio\output\last_summary.json -Raw
C:\Windows\System32\notepad.exe C:\AIVA_Comercio\output\last_summary.json
```

## Mapeo de columnas

Editar `column_mapping` en `config.local.json`. La izquierda es el nombre canonico de AIVA y la derecha es la columna real del archivo del comercio.

Ejemplos:

- `Articulo` -> `producto_nombre`
- `Producto` -> `producto_nombre`
- `Cod. Barras` -> `producto_codigo`
- `Cant.` -> `cantidad_vendida`
- `Unidades` -> `cantidad_vendida`
- `Precio` -> `precio_venta`
- `Existencia` -> `stock_actual`
- `Stock` -> `stock_actual`
- `Costo` -> `costo_unitario`

## Errores comunes

- Python no encontrado: instalar Python 3.11+ y marcar `Add Python to PATH`.
- Config no existe: ejecutar `install_manual.bat`.
- Carpeta entrada vacia: copiar CSV/XLSX a `C:\AIVA_Comercio\entrada`.
- Columnas no coinciden: revisar `column_mapping`.
- Token faltante: usar `set AIVA_COLLECTOR_TOKEN=PEGAR_TOKEN_AQUI` antes de `run_send.bat`.
- Backend no responde: revisar `backend_url`.
- Pendiente offline: ejecutar `run_queue_status.bat` y luego `run_retry_pending.bat` cuando vuelva la conexion.
- Comercio suspendido: revisar estado del comercio en admin.
- `duplicate_summary`: el backend ya recibio ese resumen.
- Separador incorrecto: cambiar `delimiter`, por ejemplo `;`.
- Numeros con coma decimal: el collector acepta coma decimal en valores numericos.

## Soporte

Pedir al cliente:

- `config.local.json` sin token.
- `logs\aiva_collector.log`.
- `output\last_summary.json` si no contiene datos sensibles.
- Captura del error.
- Nombre del archivo de entrada.

Nunca pedir el token por WhatsApp, chat o mensaje comun.

Para preparar un paquete de diagnostico local, ejecutar `collect_diagnostics.bat`. El script copia log, summary y config sanitizada a `C:\AIVA_Comercio\diagnostico`, no copia archivos originales del comercio y no envia nada por internet. Ver `README_SUPPORT.md`.

## Piloto Windows

Para una prueba piloto ordenada usar:

- `docs\aiva_collector_windows_pilot_checklist.md`
- `docs\aiva_collector_windows_pilot_results_template.md`
- `docs\aiva_collector_first_client_data_request.md`

## ZIP distribuible

El ZIP manual de FASE 4.5 se descomprime directamente en `C:\AIVA_Comercio\collector`. No trae `config.local.json`, `.env`, logs reales, state real, output real, `.venv` ni tokens. El detalle del paquete esta en `docs\aiva_collector_windows_package.md`.
