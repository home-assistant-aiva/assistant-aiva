# RC9: números argentinos, comercios sin código y configuración que muestra los datos

Candidato de prueba `0.2.8rc9`, construido sobre RC8 (`b2d8abb`). HTTPS y prueba física Windows siguen pendientes: no es una entrega comercial.

## Por qué

RC8 trajo la configuración guiada, pero tres cosas frenaban a un comercio real:

1. **Números argentinos mal leídos.** `1.890` se leía 1,89 y cualquier precio con `$` se descartaba. Una semana de kiosco de $501.760 se informaba como $501,76, con el resumen y el detalle diario de acuerdo entre sí, así que nada se veía roto. Si los precios traían `$`, el archivo se rechazaba entero.
2. **Comercios sin código de barras.** El código era obligatorio en la configuración guiada y cualquier fila sin código rechazaba la sincronización.
3. **La vista previa no mostraba los datos.** El comercio confirmaba el mapeo sin ver nunca cómo se interpretaban sus valores.

## Qué cambia

### Lectura de números (`numeric_format.py`, `normalizer.py`, `daily.py`)

- Convención decimal decidida **por columna**: `1.890` solo se puede desambiguar mirando el resto de la columna. Se limpian `$`, `ARS`, `AR$`, `U$S`, `USD`, `€`, espacios finos, `%`, y negativos con paréntesis o signo atrás.
- Una columna con solo valores tipo `2.450` (sin evidencia decisiva) se lee como miles en plata y como decimal en cantidades y stock (balanza), y queda marcada como **ambigua** para mostrarla en la configuración.
- Un único parser para resumen y detalle diario. `daily.py` ya no tiene uno propio; para valores que el Collector ya normalizó usa `canonical_decimal`, que nunca reaplica reglas locales (releer `2.450` kg ya normalizado como argentino daba 2450).
- Prioridad: `decimal_conventions` por campo (lo guarda la configuración guiada tras la vista previa) → `decimal_separator` global → detección.
- Fechas: `dd/mm/aaaa`, `dd/mm/aa`, con hora, ISO, `dd.mm.aaaa` y número de serie de Excel. Nunca `mm/dd/aaaa`.
- Filas vacías del CSV y la fila `TOTAL`/`Totales`/`Total general` al pie no son ventas ni invalidan el archivo.
- Cada fila conserva su número de fila de la planilla (`SourceRows.row_numbers`); los errores dicen fila, columna y valor. El número va aparte de las filas normalizadas para no alterar el hash normalizado ni la idempotencia.

### Productos sin código (`daily.py`, `summarizer.py`, `source_setup.py`)

- `stable_product_code`: si falta el código, `name_hash:` + 16 hex de nombre y categoría normalizados (minúsculas, sin acentos, espacios simples). El resumen agrupa los productos sin código con la misma normalización, así resumen y detalle coinciden también en cantidad de productos.
- El código pasa a ser opcional **en las fuentes configuradas con la pantalla guiada** (`source_profile`). La sincronización automática sin configurar conserva la regla de RC8 (detalle diario solo con filas que tienen código): el payload de esos comercios no cambia hasta que alguien configure la fuente y vea la vista previa.
- Renombrar un producto en el sistema de caja lo convierte en otro producto: es el costo conocido de no tener código.

### Autodetección de columnas (`column_mapping.py`)

- Los alias de RC8 conservan su puntaje y su lógica (prefijo, sufijo, parecido). Los nuevos van en `SECONDARY_ALIASES`: solo por coincidencia exacta y con puntaje menor (0,90; 0,85 los débiles), así nunca le ganan a uno de siempre (`Kg` no le gana a `Cantidad`, `Concepto` no le gana a `Producto`).
- Abreviaturas nuevas: `P. UNIT.`, `P/U`, `Pr. Unit`, `$ Unit`, `Un.`, `Unid.`, `Cdad`, `Fec.`, `F. Venta`, `Denominación`, `Concepto`, `Dto.`, `Bonif.`, `Cód. Art.`, `PLU`, `GTIN` y otras. `Ref`/`Referencia`, `Valor`, `Tipo` y `Clase` quedan afuera a propósito (número de ticket, total de línea, tipo de comprobante).
- Asignación **global por puntaje**: un campo evaluado antes no le roba la columna a otro que encaja mejor.
- Compatibilidad por valores cuando hay filas: `Desc.` con nombres es la descripción; `Día de la semana` con `Lunes` no es la fecha; `Artículo` con `00123` es código y con `Alfajor` es producto; fechas como número de serie de Excel o `aaaammdd` siguen mapeadas.
- Un código que llega por un alias nuevo y se repite con productos distintos se descarta. Los encabezados de siempre (`Código`, `SKU`, `EAN`) se respetan aunque el comercio use un código genérico tipo `999 Varios`.
- `Dto.`/`Bonif.`/`Desc.` como descuento solo en la configuración guiada: sin tipo de descuento elegido rechazarían el archivo ("descuento ambiguo"), como no lo hacía RC8.
- `fill_from_values=True` (configuración guiada) completa fecha y producto solo por sus valores, con puntaje bajo. La sincronización automática no lo usa.
- La sincronización automática decide con los alias de RC8: qué mapeo usar y cuándo reemplazar uno aprobado por la detección siguen la regla de RC8. Las abreviaturas nuevas solo entran donde RC8 se quedaba en revisión (por ejemplo, una exportación con `Cant.` y `P. UNIT.`), y la pantalla guiada las usa siempre.
- La hoja XLSX se elige primero por fecha, producto, cantidad y precio, no por cantidad de columnas reconocidas.

### Pantalla de configuración (`source_dialog.py`, `source_setup.py`)

- Tabla **“Así va a leer AIVA tus ventas”**: valor del archivo → interpretación (`$ 1.890,00 → 1.890`), solo con las columnas elegidas; se actualiza al cambiar cada desplegable; filas ilegibles en rojo.
- Formato de números por columna con un ejemplo real, aviso si es ambiguo, y elección manual (`Automático`, `1.234,56`, `1,234.56`). Al guardar, el formato confirmado queda congelado por campo.
- Controles por valores:
  - una columna Total que coincide con cantidad × precio **confirma** la lectura;
  - un “precio” que en realidad es el total de la línea se señala y se sugiere la columna correcta;
  - cantidad y precio invertidos;
  - fechas en formato de EE.UU.
- Errores con fila, columna y valor. Columna obligatoria faltante y columna repetida con mensaje claro.
- Zona horaria en desplegable (Argentina y países vecinos). Ventana desplazable con botones fijos que entra en 1366×768.

### Sincronización (`cli.py`, `token_store.py`, `config.py`)

- La huella SHA-256 se calculaba antes del primer `try`: un archivo con bloqueo exclusivo del sistema de caja o en una unidad de red caída cortaba `run-auto` entero. Ahora se omite y se reintenta.
- Red de seguridad por archivo en el ciclo de `run-auto`: una falla inesperada libera el lease (se reintenta en la próxima corrida, no en 15 minutos) y el resto sigue. El estado de la corrida se escribe siempre.
- Archivos rechazados por una versión anterior se vuelven a evaluar **una sola vez** (el evento de rechazo ahora guarda `collector_version`). Así, lo que RC8 rechazó por precios con `$` entra con RC9 sin intervención.
- `reprocess_rejected` comparaba `backend_url` sin normalizar: con mayúsculas o barra final no encontraba el archivo. Ahora usa `_backend_target`.

### Tarea programada (`install_scheduled_task.bat`)

- Principal `GroupId S-1-5-32-545` (Usuarios) sin `UserId` en el disparador, que es la forma documentada por Microsoft de disparar al iniciar sesión cualquier miembro del grupo. Antes la tarea quedaba atada a la cuenta que ejecutó el instalador elevado; el token está cifrado con DPAPI para el usuario que activó AIVA, así que con un administrador distinto la sincronización automática nunca podía descifrarlo.
- El registro sigue elevado: puede borrar tareas de versiones anteriores creadas por un administrador.
- Si otro usuario de Windows inicia sesión en la PC, `run-auto` termina sin sincronizar y sin pisar el estado del usuario que activó (`token_status` → `other_user`). Un token ilegible ya no rompe la carga de configuración.

### Números: lo que no se lee

- Un valor en otra moneda (`U$S`, `USD`, `EUR`, `€`) no se lee como pesos: AIVA no sabe a qué cotización convertir.
- `%` solo se acepta en el descuento cuando el tipo de descuento es porcentaje. Un descuento ilegible rechaza el archivo, como en RC8, con fila y columna.
- `-`, `—`, `s/d` en descuento, costo y stock significan "sin dato". `,` o `.` solos ya no valen cero. Se acepta la notación científica que Excel escribe en los CSV.
- Los mensajes que quedan en estado, logs o diagnóstico dicen fila y columna pero no el valor de la celda; la pantalla local sí lo muestra.

## Contrato con el Backend

No cambia el esquema ni los headers. Las fuentes sin configurar mandan exactamente lo mismo que con RC8 (verificado archivo por archivo contra el paquete RC8). A verificar del lado Backend antes de clientes:

- En fuentes configuradas, `product_code` puede llegar como `name_hash:<16 hex>` (26 caracteres) para productos sin código.
- Archivos que antes se enviaban con números mil veces más chicos ahora llegan correctos: si alguno llegó a enviarse con RC8, sus días quedan con el valor viejo hasta que se reenvíe ese período (los archivos ya enviados no se reenvían solos).
- Un archivo rechazado por RC8 que se reevalúa recibe la revisión diaria más nueva. Si cubre los mismos días que otro archivo enviado después, lo reemplaza: es el mismo efecto que el "Reprocesar archivo rechazado" de RC8.

## Verificación

- `pytest`: 386 tests (97 nuevos en `tests/test_rc9_*.py`).
- Revisión independiente adversarial en tres rondas: 14 hallazgos en la primera, 3 en la segunda y 2 en la tercera; todos corregidos con un test que los reproduce.
- Paridad con RC8 para fuentes sin configurar: 24 archivos (muestras del repositorio, casos de mapeo y los casos de la revisión), cada uno con y sin mapeo explícito, corridos con el paquete RC8 y con RC9 contra un Backend simulado. 42 de 48 corridas mandan exactamente lo mismo (esquema, totales, productos, detalle diario, clave de idempotencia). Las 6 restantes son las diferencias buscadas: una exportación argentina que RC8 dejaba en revisión ahora se envía, un descuento `-` ya no rechaza el archivo, y una fila vacía ya no se cuenta como descartada.
- `scripts/verify_guided_windows_ui.py` con widgets Tk reales suma una exportación argentina (`$ 1.890,00`, `2.450`, producto sin código, fila vacía y fila TOTAL) desde la pantalla hasta el payload: $501.760, 14 observaciones diarias, cobertura completa.
- El workflow oficial mantiene la actualización desde el instalador RC7 verificado por SHA-256, que cubre la migración de SQLite. Entre RC8 y RC9 no hay cambios de esquema.
- Ni Linux ni el runner de CI sustituyen la prueba física en la PC del comercio.
