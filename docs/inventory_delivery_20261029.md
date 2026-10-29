# Ventas e inventario: entrega local y límites (29/10/2026)

Este documento complementa [el diagnóstico previo](inventory_stage0_diagnosis.md). Ningún servicio productivo, instalación Windows ni comercio existente se modificó. Las pruebas usaron comercios ficticios, SQLite temporal y un cliente HTTP simulado; no se enviaron mensajes.

## Etapa 0 — diagnóstico confirmado

El Excel v2 real tiene 17.196 filas de datos, 23 columnas y 348 códigos. En el archivo, los 348 códigos tienen stock, costo y precio actual explícitos con fecha 17/10/2026. El Asistente anterior emitía sólo 119 stocks en el payload diario del 17/10 porque asociaba la foto a las ventas de ese día: omitía 229 códigos **en ese payload**, aunque están presentes en el Excel. La lectura heredada mantenía 348 códigos pero aplicaba el costo actual a ventas anteriores. `dias_sin_ventas=30` afectaba los servicios heredados v1, no Gestión ni Resultados v2. El código del servidor difiere del ZIP `0.3.0rc1` en los nueve archivos y comportamientos enumerados en el diagnóstico; el ZIP se trató como referencia, no como fuente vigente.

Los cuatro productos se siguieron de fila a payload, base temporal y preview:

| Código | Última fila de venta | Stock al 17/10 | Costo actual al 17/10 | Precio actual al 17/10 |
| --- | --- | ---: | ---: | ---: |
| `HEL0011` hidrolavadora 1600 W | 17/10, cantidad 0; `Últ. Venta` 27/02 | 4 | 152.173,91 | 210.000 |
| `PIN0001` látex interior blanco 20 L | 16/10 | 5 | 75.681,82 | 99.900 |
| `PIN0026` membrana líquida 20 kg | 06/10 | **0** | 94.696,97 | 125.000 |
| `CAL0001` caloventor 2000 W | 31/07 | 14 | 26.760,56 | 38.000 |

`Fecha` es fecha de venta, `Precio Unit.` es precio cobrado, `Fecha Existencia` fecha del stock, `Fecha Costo y Precio` fecha de costo y precio actuales, y `Precio Venta Actual` la columna distinta que acredita precio actual. `Últ. Venta` no fecha inventario. En el nuevo flujo, los cuatro códigos y los 348 stocks llegaron a la base temporal como observaciones del 17/10. El archivo no demuestra que 348 códigos sean todo el catálogo.

## Etapa 1 — contrato y decisiones

`inventory_snapshot` versión `1.0.0` usa `POST /commerce/collector/inventory-snapshots`, autenticación de Collector y `Idempotency-Key`. Tiene `commerce_id`, `collector_id`, `source_id`, `content_sha256`, `revision`, `scope="partial"` y hasta 50.000 observaciones. Cada observación tiene `product_code` estable, nombre, categoría, `kind` (`stock`, `current_cost`, `current_price`), `value`, `observed_on`, `date_provenance` (`mapped_column`, `operator_confirmed`, `unknown`), `provenance="source_export"` y `quality` (`verified`, `undated`, `conflict`). La fecha y calidad son **por valor**. El Backend comprueba comercio y Collector autenticados, hash, revisión y esquema.

- Un producto ausente no borra su última observación ni significa cero. Stock cero es un valor explícito. Dos valores incompatibles del mismo producto, campo y fecha producen `conflict`; no se escoge uno. Sin fecha acreditada se conserva el valor con `undated`, pero no alimenta Gestión/Resultados actuales.
- Una fecha mapeada o de exportación verificable prevalece. La confirmación del operador se liga al SHA-256 del archivo y al `source_id`, se muestra en preview y no sirve para otro contenido. La mtime de Windows y la última venta no acreditan fechas de inventario.
- `cost_basis=historical` permite COGS en ventas si se confirma su significado; `current` envía costo como observación actual y deja COGS histórico sin acreditar; `unknown` deja margen desconocido. Precio cobrado no pasa a precio vigente. Un costo histórico no pasa a actual por ser el último.
- El Backend negocia `inventory_snapshot_v1` en `ingestion_features`. Collector nuevo + Backend anterior que no la anuncia devuelve `backend_upgrade_required` antes de enviar la foto o avanzar ventas de la fuente: error visible, lote pendiente intacto. Backend nuevo + Collector anterior sigue aceptando su contrato anterior, pero no crea una foto nueva. La opción de días vacíos exige también `empty_daily`.
- Gestión y Resultados reciben observaciones aisladas por comercio, Collector, fuente y producto. El 17/10 la membrana sin stock aparece en Reponer ya; al 29/10 la foto del 17/10 aparece como antigua, sin reposición actual. No se cambiaron las fórmulas canónicas. Resultados conserva su **estimación explícita** de ganancia de octubre con costos al 17/10; no certifica costo histórico de julio ni reescribe ventas anteriores.

## Etapa 2 — Asistente e historial

La opción predeterminada es tres meses calendario cerrados más el mes en curso, en la zona horaria del comercio, hasta ayer: 29/10 → 01/07–28/10; 01/11 → 01/08–31/10. Se muestran rango de proceso y rango que debe exportarse. Incluir hoy exige elección y lo marca parcial. Siguen 30/90/180/365 días y rango manual.

El archivo acredita cobertura de ventas por día sólo con declaración de completitud y rango explícito; esto no acredita inventario completo. El Asistente registra detección y hash de cada exportación. Una exportación posterior completa puede reemplazar su día; días diferentes coexisten. Superposición simultánea, cobertura desconocida o reemplazo parcial exige revisión antes de enviar ventas o inventario. La versión queda vinculada al hash de origen. El límite del conector sigue en 50.000 filas: dividir por días completos no superpuestos, con mismos códigos y fuente; si un día solo excede el límite, revisar paginación/completitud con el proveedor.

## Etapa 3 — continuidad, estado y capacidad

El Collector persiste días confirmados, archivos detectados, revisiones y lotes pendientes. Tras apagado recupera días no confirmados y la ventana configurable de correcciones; el tiempo por corrida se limita a 240 s. Una foto idéntica por fuente, fecha y contenido se almacena una vez. Una revisión nueva tiene hash y número de revisión propios. El payload aceptado se vacía del lote local; no se conserva otra copia íntegra del Excel por intento ni una fila por latido. El servicio autenticado de estado registra contacto aunque no haya ventas y devuelve nombre de comercio. Admin muestra último contacto, último día de ventas confirmado, fecha de inventario y código de error resumido; sin credencial no se puede contactar Backend y Admin sólo puede mostrar contacto antiguo.

La tarea Windows del candidato usa `GroupId=Users`: puede ejecutarse bajo otro usuario del que activó DPAPI. El Collector registra localmente esa falta de acceso y no traslada el token a texto plano. Para la prueba física se debe leer el XML efectivo de la tarea, confirmar la cuenta vinculante y probar una tarea limitada a esa cuenta con `InteractiveToken`; comprobar inicio de sesión, bloqueo, reinicio y permisos. No se modificó aquí la tarea instalada.

| Medición aislada | Tiempo / memoria | Espacio y crecimiento |
| --- | --- | --- |
| Excel v2, lectura + normalización + resumen heredado | 4,375 s; RSS máximo 131.568 KiB | Excel 2.200.045 B |
| CSV sintético 50.000 filas | 3,836 s; pico acumulado 149.212 KiB | archivo 3.633.999 B |
| Modelo 5.000 productos × 120 días, 600.000 métricas, inserción SQLite directa | 3,246 s; pico acumulado 149.212 KiB | DB 129.503.232 B, WAL pico 130.286.792 B, cola 420.001 B + 417.792 B de DB, respaldo verificado 129.921.024 B |
| Excel v2 → Collector nuevo, fuente ficticia, primera carga | 26,88 s | 109 payloads diarios + 1 foto, 8.377.440 B de payload simulado, SQLite local 393.216 B |
| Misma fuente y contenido, segunda corrida | 0 ventas y 0 fotos emitidas | SQLite local 393.216 B, crecimiento **0 B** |
| Los 110 payloads → Backend temporal | 7,689 s; RSS máximo 80.080 KiB | DB 1.511.424 → 20.951.040 B, crecimiento 19.439.616 B; WAL 0 B tras cierre |
| Respaldo y restauración de esa DB temporal | backup SQLite 0,17 s en la primera medición y 0,964 s en una segunda; copia de restauración 0,083 s | backup y DB restaurada de 20.951.040 B cada una; `integrity_check=ok`, 9.617 métricas diarias y 1.044 observaciones recuperadas |

El WAL pico de 130 MB pertenece al **modelo** de 600.000 métricas, no a la API real. El WAL 0 B del flujo real se midió tras cerrar la conexión; no acredita su pico durante ingesta. La cola y el JSON de 8,38 MB son artefactos de prueba separados. Cinco pilotos de 5.000 productos × 120 días proyectan ~647,5 MB de DB, ~647,5 MB para una generación de respaldo y hasta ~651,4 MB de WAL si los picos coinciden, antes de rollback, índices adicionales y temporales: **proyección lineal**, no medición de cinco comercios. El piso de ~570 MB por piloto del modelo (DB, WAL, backup, rollback, build/temporales) requiere remedirse con la DB y los respaldos reales. La activación desde RC9 calcula espacio disponible y rechaza si no cubre tres copias de la DB, dos WAL, dos colas, dos archivos de exportación y 64 MiB de margen; es un guardarraíl estimado, no sustituye un respaldo íntegro comprobado.

`df -B1` al cierre de este trabajo: **45.216.993.280 B libres** en `/opt` y `/tmp` (mismo filesystem). No hay acceso a la PC Windows y su espacio libre actual sigue **sin medir**. No se borraron históricos ni backups. Política para revisar tras pilotos: conservar la historia diaria y las observaciones que alimentan Resultados; conservar la trazabilidad de revisiones y hashes; retirar sólo payloads transitorios ya aceptados y evaluar retención de logs operativos y generaciones de backup después de verificar restauración y requisitos comerciales. No se aplicó una purga.

## Etapa 4 — migración preparada, cambio de camino pendiente

El Asistente carga mapeo, formato numérico congelado, semántica de precio y descuento, cobertura, zona horaria y `source_id` RC9 para **revisión**, sin activarse. El costo anterior se propone como `unknown` hasta confirmarlo. Cambiar de carpeta/formato o detectar un formato numérico discordante requiere revisión visible. El plan mide espacio antes de activar. La configuración RC9, token protegido, estado local, pendientes y tarea quedan intactos. Una configuración del Asistente sin envíos puede archivarse atómicamente para volver a RC9; con cualquier lote o día ya registrado, el rollback automático se detiene y exige conciliación para no pisar datos nuevos.

En copia **sintética RC9** se verificaron preview, activación, `source_id` idéntico, cola pendiente intacta y reversión de configuración. En copia **sintética de estado del Asistente** se verificó reconfiguración sin transición falsa. Una prueba de poco espacio bloqueó la activación sin modificar estado. No se dispone de una instalación física RC9 ni `0.3.0rc1` para comprobar arranque, tarea, DPAPI, primera sincronización, reinicio y rollback real. Por esa falta de paridad física, “Configurar archivo y precios” permanece visible y el Asistente **no** pasó a ser el único camino principal. No se activó ninguna migración real.

## Etapa 5 — pantalla y edad de venta

La pantalla prioriza envío confirmado, ventas hasta e inventario observado el; deja contadores en “Ver detalle”. El nombre del comercio viene del endpoint autenticado propio y el ID se abrevia. “Volver a vincular” está en Opciones avanzadas y explica que la conexión anterior deja de enviar, sin borrar cola ni estado. En el resumen heredado, `dias_sin_ventas` usa venta positiva acreditada o fecha explícita `Últ. Venta`; si no hay historia acreditada, vale `null`, nunca 0/30 por defecto. La fecha de última venta no se usa como fecha de stock.

## Pruebas, regresiones y límites de la evidencia

- Collector: 420 pruebas de la suite aplicable sin sockets pasaron; la suite de conectores con servidor local se corrió por separado (4 pasaron, 1 omitida) tras el permiso de socket del sandbox. `compileall` de módulos cambiados pasó. CSV coma/punto y coma, BOM, XLSX con encabezado desplazado, TOTAL/vacíos, números y fechas argentinas, productos sin código, cero/desconocido, costos faltantes, día parcial, superposiciones, fuente incompleta, 12 días sin PC, cola/reinicio y Backend anterior tienen pruebas focalizadas. Las copias de instalación Windows son sintéticas.
- Backend: 48 pruebas focalizadas de inventario/servicios pasaron; 8 de estado/autenticación pasaron. El grupo de demos, menús de Gestión/Resultados, inventario y autenticación volvió a pasar con `AIVA_DB_PATH` temporal. Las cuatro demos y otros comercios no recibieron datos de prueba. `compileall` pasó. No se generó EXE ni instalador.
- Durante implementación se detectaron y corrigieron dos regresiones nuevas en Backend: filas de precio simuladas sin `product_key` y texto de advertencia de Reponer ya. Ambas se volvieron a probar.
- En una corrida amplia previa quedaron fuera de validación dos errores por falta del puente Node local y uno por prohibición de sockets del sandbox. Un fallo de contactos WhatsApp entre comercios no se clasificó como histórico porque no se ejecutó una comparación de baseline; requiere investigación separada. No se enviaron WhatsApp reales.
- Una invocación temprana de tests Backend sin `AIVA_DB_PATH` temporal hizo consultas `SELECT` sobre la ruta por defecto y falló por una tabla ausente; no escribió datos de prueba ni mostró filas. Las siguientes corridas fijaron una DB temporal explícita. Este desvío de aislamiento se registra para no repetirlo.

Los previews aislados con reloj 17/10 mostraron MENÚ, Reponer ya (`answered`, 11 productos, `PIN0026` sin stock), Plata parada (`answered`, 48) y Resultados de octubre (`answered`, datos hasta 17/10). Con reloj 29/10, Reponer ya y Plata parada dieron `insufficient_data`; Resultados siguió mostrando datos hasta 17/10 y su estimación fechada, y prioridades rechazó stock/precios/costos antiguos. No hubo llamadas externas.

## Datos históricos y despliegue posterior

Los resúmenes v1 aceptados con `Costo Unit.` actual pudieron atribuir costo del 17/10 a ventas de abril–octubre. No se leyó ni reescribió la DB productiva, por lo que no hay conteo real. En una copia restaurada, localizar resúmenes v1 por comercio/fuente/período y procedencia de costo; contrastar con ventas originales, recalcular sólo donde haya costo histórico acreditado, marcar el resto como desconocido, comparar Resultados y preparar una corrección versionada por día con respaldo y rollback. Nunca corregir por nombre coincidente.

Plan **no ejecutado**: medir disco de VPS y PC, tamaño de DB/WAL/cola por comercio y fuente y exportación máxima; detener si falta espacio. Pausar sólo el Collector piloto, hacer respaldo íntegro de Backend y estado Windows (configuración, token DPAPI cifrado con ACL, cola, SQLite con online backup y tarea XML) y probar restauración aislada. Actualizar Backend primero, verificar `inventory_snapshot_v1`, salud y autenticación real sin datos de prueba. Conservar copia de código/config RC9 y `0.3.0rc1`; actualizar sólo un Collector piloto tras revisión de semánticas y espacio. Probar exportación real, día cerrado, foto fechada, Admin, 15 minutos, reinicio, otro usuario y rollback. Si falla, detener nuevos envíos, restaurar código y configuración bajo la misma identidad, **sin restaurar una DB vieja encima de datos nuevos**; conciliar primero lotes pendientes y días aceptados. Registrar resultados, después considerar otros pilotos. No push, merge, despliegue ni release en esta tarea.

Documentación a actualizar antes de piloto: guía de instalación Windows y cuenta de tarea; pedido de CSV/XLSX al comercio (ventas completas por día, rango, código estable, precio cobrado y columnas separadas de stock/costo/precio actual con sus fechas); guía de mapeo y significado de costo/descuento; recuperación/rollback; límites de frescura y lectura de Admin. Un archivo de inventario separado o segunda hoja queda para una mejora posterior. Ninguna guía debe prometer stock para productos ausentes de un archivo de ventas.
