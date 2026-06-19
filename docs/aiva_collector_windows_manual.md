# Manual Windows de AIVA Collector

## A. Que es AIVA Collector

AIVA Collector es una herramienta local para comercios que leen ventas exportadas en CSV o Excel. Normaliza columnas y genera un resumen por producto para AIVA Comercial.

## B. Que hace

- Lee archivos CSV/XLSX exportados por el sistema del comercio.
- Resume ventas, facturacion, margen estimado y stock por producto.
- Genera un archivo local `last_summary.json`.
- Envia el resumen a AIVA Comercial solo cuando se ejecuta `run_send.bat` y se confirma con `ENVIAR`.
- Permite que AIVA Comercial genere recomendaciones y reportes.

## C. Que no hace

- No factura.
- No vende.
- No modifica stock.
- No toca la base de datos del cliente.
- No borra archivos originales.
- No envia tickets completos.
- No manda el Excel completo.
- No trabaja con datos crudos en la nube.
- No instala servicio Windows en esta fase.

## D. Instalacion manual

1. Instalar Python 3.11 o superior desde python.org.
2. Durante la instalacion, marcar `Add Python to PATH`.
3. Copiar la carpeta del collector a `C:\AIVA_Comercio\collector`.
4. Ejecutar `check_python.bat`.
5. Ejecutar `install_manual.bat`.
6. Ejecutar `install_dependencies.bat` con internet disponible.
7. Editar `C:\AIVA_Comercio\config.local.json`.
8. Completar `backend_url`, `commerce_id` y `collector_id`.
9. Pegar archivos del comercio en `C:\AIVA_Comercio\entrada`.
10. Ejecutar `run_validate.bat`.
11. Ejecutar `run_dry.bat`.
12. Revisar `C:\AIVA_Comercio\output\last_summary.json`.
13. Configurar token temporal: `set AIVA_COLLECTOR_TOKEN=PEGAR_TOKEN_AQUI`.
14. Ejecutar `run_send.bat`.
15. Escribir `ENVIAR` para confirmar el envio.
16. Ver recomendaciones en admin AIVA Comercial.

`commerce_id` y `collector_id` salen del admin AIVA Comercial. El token se copia una sola vez desde el admin. No guardar `collector_token` en `config.local.json`.

## E. Como mapear columnas

En `column_mapping`, la clave izquierda es el campo esperado por AIVA y el valor derecho es la columna del archivo real.

Ejemplos frecuentes:

- `Articulo` -> `producto_nombre`
- `Producto` -> `producto_nombre`
- `Cod. Barras` -> `producto_codigo`
- `Cant.` -> `cantidad_vendida`
- `Unidades` -> `cantidad_vendida`
- `Precio` -> `precio_venta`
- `Existencia` -> `stock_actual`
- `Stock` -> `stock_actual`
- `Costo` -> `costo_unitario`

Campos minimos:

- `producto_nombre`
- `cantidad_vendida`
- `precio_venta`

Campos opcionales:

- `fecha`
- `producto_codigo`
- `categoria`
- `costo_unitario`
- `stock_actual`

## F. Formato esperado

CSV:

- Encabezados en la primera fila.
- Encoding `utf-8` recomendado.
- Separador `,` por defecto. Si el archivo usa punto y coma, configurar `"delimiter": ";"`.

Excel:

- Formato `.xlsx`.
- Encabezados en la primera fila de la hoja activa.

Numeros:

- Se aceptan enteros y decimales.
- Se aceptan decimales con coma.
- Si el archivo mezcla separadores de miles y decimales, revisar el summary antes de enviar.

Fechas:

- Por defecto `%Y-%m-%d`.
- Tambien se intentan formatos comunes como `YYYY/MM/DD`, `DD/MM/YYYY` y `DD-MM-YYYY`.

## G. Errores comunes

- Python no encontrado: instalar Python 3.11+ y marcar `Add Python to PATH`.
- Config no existe: ejecutar `install_manual.bat`.
- Carpeta entrada vacia: copiar CSV/XLSX a `C:\AIVA_Comercio\entrada`.
- Columnas no coinciden: revisar `column_mapping` contra los encabezados reales.
- Token faltante: configurar `AIVA_COLLECTOR_TOKEN` antes de enviar.
- Backend no responde: revisar `backend_url` y conectividad.
- Comercio suspendido: revisar estado del comercio en admin AIVA Comercial.
- `duplicate_summary`: el resumen ya fue recibido por el backend para ese periodo y contenido.
- Archivo con separador incorrecto: cambiar `delimiter`.
- Numeros con coma decimal: soportado, pero conviene revisar `last_summary.json`.

## H. Soporte

Pedir al cliente:

- `config.local.json` sin token.
- `logs\aiva_collector.log`.
- `output\last_summary.json` si no contiene datos sensibles.
- Captura del error.
- Nombre del archivo de entrada.

Nunca pedir token por WhatsApp o mensaje comun. Si se necesita regenerar acceso, hacerlo desde admin AIVA Comercial.
