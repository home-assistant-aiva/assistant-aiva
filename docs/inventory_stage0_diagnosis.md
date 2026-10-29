# Diagnóstico aislado de ventas e inventario (2026-10-29)

## Estado revisado

- Collector: `feat/connection-assistant-rc10`, HEAD inicial `c44bf2fba90808b822bb9cec7319360a65af7c69`, sin cambios locales. Backend: `feat/demo-sellers-admin`, HEAD inicial `cb23a8fff736edc4dc25b770f5fd1443231c94f5`, sin cambios locales; no tiene upstream configurado.
- La memoria maestra vigente en `/opt/aiva-docs/AIVA_COMERCIAL_MASTER_CONTEXT_CODEX.md` termina con una adenda de 2026-10-24, pero su resumen principal llama “actual” a Collector `0.2.7rc2`; el código actual es candidato `0.3.0rc1` con correcciones posteriores. Prevalecen código y tests.
- El ZIP `dist/aiva-collector-windows-manual-v0.3.0-desktop-rc1.zip` difiere del árbol actual en nueve archivos: `cli.py` (bloquea envío manual sobre una fuente del Asistente), `connection_setup.py` (preview con totales), `connection_sync.py` (stock ilegible, costos desconocidos y orden de recuperación), `connection_wizard.py` (carga de perfil y cierre), `connectors/files.py` (caché de lectura), `connectors/rest.py` (validación de ruta), `connectors/sqlite.py` (base interna prohibida), `desktop_service.py` (diagnóstico delegado) y `offline_queue.py` (aislamiento de cola dañada). El ZIP no contiene el Excel de ferretería.

## Archivo real y flujo de cuatro productos

Se leyó **sólo en aislamiento** el adjunto `Ferreteria_DEMO_v2_Ventas_y_Stock_01-04_al_17-10-2026.xlsx` (2.200.045 bytes). Tiene una hoja `Ventas`, 17.197 filas físicas con encabezado y 23 columnas; 17.196 filas leídas, 348 códigos distintos, 164 fechas de ventas entre 01/04 y 17/10/2026. No tiene una segunda hoja de inventario. Columnas relevantes: `Fecha` (venta), `Código`, `Descripción`, `Cantidad`, `Precio Unit.` (cobrado), `Costo Unit.`, `Precio Venta Actual`, `Existencia`, `Fecha Existencia`, `Fecha Costo y Precio`. `Últ. Venta` es otro campo y no fecha del stock. En las 348 identidades hay un valor no vacío de `Existencia`, `Costo Unit.` y `Precio Venta Actual`, con fechas explícitas del 17/10/2026. No se detectó contradicción de valor por producto y fecha en esos tres campos. Esto **no** prueba que los 348 sean el catálogo completo del comercio.

| Producto (código) | Última fila de venta | Cantidad / precio cobrado | Costo del archivo / precio actual | Stock y fecha |
| --- | --- | --- | --- | --- |
| Hidrolavadora 1600 W (`HEL0011`) | 17106, 17/10, cantidad 0; `Últ. Venta` 27/02 | 0 / 210.000 | 152.173,91 / 210.000 | 4 al 17/10 |
| Látex interior blanco mate 20 LT (`PIN0001`) | 17026, 16/10 | 1 / 99.900 | 75.681,82 / 99.900 | 5 al 17/10 |
| Membrana líquida blanca 20 KG (`PIN0026`) | 16175, 06/10 | 1 / 125.000 | 94.696,97 / 125.000 | **0** al 17/10 |
| Caloventor 2000 W (`CAL0001`) | 10290, 31/07 | 5 / 38.000 | 26.760,56 / 38.000 | 14 al 17/10 |

La detección automática actual eligió bien las ocho columnas básicas, pero **no** eligió `Fecha Existencia`, `Fecha Costo y Precio` ni `Precio Venta Actual`. Con mapeo explícito, el normalizador reconoció las 17.196 filas sin descartes, fallos numéricos o fechas inválidas. El resumen heredado retuvo stock para los 348 códigos y calculó costo/margen a partir de `Costo Unit.` en filas de abril a octubre, aun cuando su fecha de costo es 17/10. Para `HEL0011` emitió `dias_sin_ventas=30` por una fila con cantidad cero; el archivo indica última venta el 27/02. El resumen heredado no acredita la antigüedad de cada observación.

El Asistente con `cost_basis=current`, `dated_stock` y mapeo explícito quitó el costo histórico y no inventó margen, pero tampoco conservó el costo actual ni el precio actual. Su métrica del 31/07 para `CAL0001` y `PIN0001` tiene `closing_stock=null`; el 17/10 sólo hay 119 métricas y 119 stocks fechados. Entre los cuatro productos, sólo `HEL0011` está ese día. **La hipótesis 119/348 y 229 faltantes queda confirmada para el payload diario del Asistente actual**, no para el Excel: los 229 tienen stock explícito en el archivo. La regla `stock_as_of_date == business_date` del contrato diario impide trasladar esa foto a una venta de julio. El Backend v2 no usa `stock_actual` ni `dias_sin_ventas` del resumen ancho; sí los usa en v1 para reglas, readiness, recomendaciones y reportes heredados. Gestión/Resultados v2 leen observaciones diarias fechadas y aplican límites de frescura, pero con este payload faltan 229 productos en la foto.

## Capacidad y espacio

Mediciones locales, con Python 3.12 del `.venv` de Collector y datos ficticios; el modelo SQLite de 600.000 métricas representa almacenamiento, **no** el tiempo de la API completa:

| Caso | Tiempo | Memoria máxima del proceso | Espacio |
| --- | ---: | ---: | ---: |
| Excel real, lectura + normalización + resumen | 4,375 s (lectura 3,627 s) | 131.568 KiB | archivo 2.200.045 B |
| CSV sintético de 50.000 filas, lectura + normalización + resumen | 3,836 s | 149.212 KiB (mismo proceso, pico acumulado) | archivo 3.633.999 B; resumen limitado a 1.000 productos por configuración heredada |
| 5.000 productos × 120 días, 600.000 métricas sintéticas en SQLite con PK e índice de fecha | 3,246 s de inserción directa | 149.212 KiB (pico acumulado) | DB 129.503.232 B tras checkpoint; WAL 130.286.792 B antes del checkpoint |
| Dos consultas idénticas al modelo, sin insertar | 0,0001 s | mismo proceso | crecimiento DB **0 B** |
| Una cola pendiente de 5.000 productos | no es envío | mismo proceso | JSON 420.001 B; DB creció 417.792 B |
| Backup SQLite íntegro del modelo con una cola | no cronometrado | mismo proceso | DB y backup 129.921.024 B cada uno; `integrity_check=ok` |

La prueba de dos consultas sólo mide el modelo de almacenamiento, no dos corridas del Collector. La ampliación a varios pilotos es **proyección lineal**, no medición: cinco comercios con ese volumen podrían sumar aproximadamente 650 MB de DB más ~650 MB de backups de una generación, antes de WAL, índices adicionales, payloads pendientes y archivos temporales. El modelo mide una sola fuente ficticia; no justifica subir el límite actual del conector (`max_rows=50.000` por defecto). Archivos mayores deben dividirse por **días completos no superpuestos**, conservando una fuente y códigos estables; si un solo día excede el límite, se requiere un contrato de paginación/completitud revisado.

El VPS tenía **45.095.583.744 B libres** en `/opt` al final de esta medición; `/tmp` comparte el mismo filesystem. El directorio `aiva-backend/data` ocupa 445 MB según `du`, sin abrir ni copiar la base productiva. El `dist` actual de Collector ocupa 47 MB y un EXE candidato previo 23.483.599 B. Para planificar un piloto de tamaño similar al modelo, reservar al menos ~130 MB de DB, ~130 MB de WAL pico, ~130 MB de backup, ~130 MB de copia de rollback y ~50 MB de build/temporales, más margen operativo; **~570 MB es un piso estimado, no una garantía**. Antes de una migración real hay que medir DB, WAL y respaldos reales y verificar espacio suficiente para respaldo, restauración temporal y reversión. No se pudo medir el disco de la PC Windows: no está conectada a este entorno. La observación histórica de 45,6 GB libres no acredita ese equipo ni el VPS hoy.

## Riesgo histórico y siguiente corrección

Los resúmenes v1 ya aceptados de esta u otras fuentes que copiaron un costo actual a ventas anteriores **podrían** contener costo y margen históricamente mal atribuidos; no se inspeccionó producción ni se cuantificaron registros reales. Identificarlos por `source_schema_version=1.0.0`, `source_id`, período y procedencia de costo en una copia restaurada de la DB. Preparar recarga aislada desde ventas originales con `cost_basis=unknown` cuando no haya costo histórico acreditado, comparar reportes, y sólo entonces planificar corrección productiva reversible con backup íntegro. Ningún dato productivo se reescribió aquí.

La tarea de Windows usa un `GroupId` de Usuarios y trigger de logon cada 15 minutos; DPAPI protege el token para **la cuenta que vinculó**. Otra sesión no puede descifrarlo. La cuenta efectiva de la tarea y el espacio de la PC requieren prueba física (`schtasks /Query /XML`, sesión de vínculo, corrida con otro usuario y diagnóstico local). No se debe convertir el token a texto plano ni ampliar su protección a toda la máquina.
