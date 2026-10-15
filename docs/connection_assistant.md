# Asistente de conexión — candidato 0.3.0rc1

Implementación sobre Collector RC9 `f5751d792d3ae3c0833eea2fa48b0a8328b5c96f`.
El checkout persistente oficial es `/opt/aiva-collector`, rama
`feat/connection-assistant-rc10`. Backend parte de `a15c2f1` y Admin de `25214cc`.
RC9, su rama y sus artefactos no se reemplazan. La versión cambia a 0.3.0rc1
por incorporar conectores y configuración nueva. El manifest del artefacto es
la autoridad sobre el commit exacto que se compiló.

## Arquitectura y contrato

`connectors/`: acceso y lectura acotada. `connection_config.py`: configuración
versionada y pertenencia. `connection_setup.py`: propuestas locales y confirmación.
`connection_sync.py`: snapshots durables y recuperación. `source_credentials.py`:
DPAPI. `connection_wizard.py`: interfaz Tk; no servidor web de configuración.
El normalizador, descuentos, identidades y summary RC9 se reutilizan.
El Backend conserva métricas, reglas, reposición y confianza canónicas.

Registro: CSV/XLSX y SQLite implementados; REST genérico implementado y probado
con dos estructuras sintéticas mediante HTTP local; SQL Server ODBC implementado,
con test real preparado pero pendiente de motor y cuenta autorizados.
PostgreSQL, MySQL/MariaDB, Firebird y Access requieren adaptación y pruebas;
no se habilitan por encontrar un controlador. No hay compatibilidad universal.
No se afirma compatibilidad con proveedores comerciales sin probar sus perfiles.

El contrato sigue siendo v2 `snapshot_replace`, `whole_commerce`, por día.
Metadata incluye fuente y revisiones de configuración y mapeo.
Backend candidato agrega procedencia opcional `stock_as_of_date` y `cost_basis`,
y días explícitamente vacíos sin productos. Collector consulta `ingestion_features`:
con Backend RC9 omite campos nuevos y mantiene stock desconocido; rechaza días
vacíos si el servidor no los admite. Sin fecha no convierte stock RC9 en actual.
Un costo actual o no confirmado se conserva como limitación; la nueva ruta no
lo usa para una ganancia histórica. Costos RC9 heredados conservan su contrato.

## Instalación y configuración controlada

1. Obtener el EXE y SHA256SUMS del workflow oficial; verificar el hash.
2. Instalar encima de RC9 sin borrar ProgramData. Instalador x64; necesita
   administrador para Program Files y tarea. No necesita Python de desarrollo.
3. Abrir AIVA con el usuario de Windows que hará las sincronizaciones. Activar
   el comercio contra un Backend HTTPS con certificado válido. La URL HTTP
   histórica no permite sincronizar desde el asistente nuevo.
4. Abrir **Asistente de conexión**. Elegir archivos, SQLite, API u ODBC.
   Detectar requiere autorización explícita y sólo inspecciona la carpeta elegida,
   nombres de DSN y controladores. No recorre discos ni redes ni busca claves.
5. Archivos: elegir una exportación de referencia; una hoja XLSX por fuente.
   SQLite: elegir base comercial, tabla ordinaria, columnas necesarias y fecha ISO.
   API/ODBC: cargar un perfil JSON revisado por el proveedor. Los ejemplos en
   `configs/integration_profiles` son plantillas sintéticas, no endpoints reales.
   Si falta perfil, documentación o acceso, se informa el requisito y se propone
   una exportación CSV/XLSX; no se declara conectado por detectar una URL o driver.
6. Ingresar sólo credenciales específicas de la fuente y Probar conexión.
   No confundir login de la aplicación con acceso a la base o API.
7. Revisar sugerencia y ejemplos origen → interpretación. Confirmar formato,
   precio unitario bruto/neto, descuento por unidad/línea/porcentaje y si el costo
   es histórico. No restar dos veces descuentos incluidos en precio neto.
8. Elegir 30/90/180/365 días o rango personalizado. El final predeterminado es
   ayer en la zona del comercio. Incluir hoy genera cobertura parcial. 90 son
   90 días, no tres meses calendario. Vista previa muestra rango encontrado en
   muestra y registros dentro/fuera; la muestra no demuestra la cobertura total.
9. Declarar cobertura completa sólo si cada lectura contiene todas las ventas
   del comercio por cada fecha incluida. Fechas ausentes son desconocidas.
   Activar después de confirmar. La primera sincronización es supervisada y el
   resultado informa envíos, duplicados, días completos/parciales/sin información
   y capacidades devueltas por Backend. Si faltan costos, stock vigente o calidad,
   las funciones permanecen limitadas. Una conexión no habilita todo.
10. Guardar avances permite continuar sin muestras ni secretos en el borrador.
    Abrir otra vez para cambiar credenciales, confirmar mapeo, ampliar el rango,
    pausar o reanudar. La última recepción y próximo intento son visibles.

La configuración guiada nueva complementa la de archivos RC9. Una fuente activa
del asistente usa siempre esa configuración, tanto GUI como background.
No cambia a otra fuente al fallar. Un cambio de fuente lógica se bloquea y requiere
conciliación y transición explícita en Backend. No se mezclan ventas de una API
con stock de otro origen ni sucursales o depósitos sin vinculación revisada.

## Perfil y límites de lectura

REST sólo GET para datos; auth none/Bearer/header API key/Basic o OAuth PKCE.
Los perfiles definen estructura, campos, filtros, fechas, paginación page/cursor/
next_link y límites; no contienen código, SQL ni secretos. Las rutas de las
plantillas deben sustituirse según documentación real. No se siguen redirecciones
ni enlaces a otro origen con credenciales. TLS se verifica siempre; HTTP sólo es
posible con el parámetro interno de prueba de loopback, nunca en el asistente.
401/403 son intervención; 429/5xx respetan Retry-After. No se guardan páginas
parciales: tras fallo se vuelve a leer ese día desde la primera página. Hay límite
de páginas, tiempo, bytes y filas, y detección de páginas repetidas. La API debe
permitir releer snapshots completos por día; endpoints de deltas necesitan
adaptación y no se habilitan silenciosamente.

SQLite usa URI mode=ro, query_only, authorizer y límites; no carga extensiones,
no ejecuta SQL libre, vistas ni tablas virtuales. Usa WAL/SHM originales, sin
copiar ni restaurar la base. Si no se puede abrir de forma segura, se pide una
exportación o copia consistente autorizada. Fechas deben ser ISO comerciales
locales para el filtro SQL; timestamps en otra zona necesitan un perfil de
exportación que entregue la fecha comercial correcta. No se adivina esa semántica.
La SQLite interna del Collector no es una fuente comercial.

ODBC SQL Server genera SELECT parametrizado sobre tabla ordinaria configurada,
valida identificadores, restringe columnas y comprueba permisos efectivos de
servidor/base/objeto. Rechaza permisos de escritura, ejecución o administración.
`ApplicationIntent=ReadOnly` es sólo intención de acceso; no reemplaza la cuenta
específica con SELECT mínimo. No modifica permisos ni instala controladores.
SQL Server y SQLite no admiten SQL arbitrario, procedimientos ni perfiles con
funciones. No se certifican vistas o joins propietarios en este candidato.

Límites iniciales: 50.000 filas por lectura/día (configurable hasta 200.000),
64 columnas, campos escalares de hasta 4096 caracteres, 50 MB de lectura de API,
20 MB por respuesta como máximo y archivo de hasta 50 MB por defecto, 200 archivos.
SQLite limita además tamaño de valores. API máximo 100 páginas por defecto,
1.000 absoluto, timeout hasta 120 segundos. Una ejecución cede tras aproximadamente
240 segundos entre unidades de trabajo. ODBC depende también de que el driver
cumpla sus timeouts; la prueba real queda pendiente. Para más volumen, exportar
por períodos menores y probar carga antes del piloto. XLS no implementado.

La configuración reconoce sólo el alcance de comercio completo. No transforma
cajas a unidades ni agrega depósitos automáticamente. Identificadores de operación/
línea del perfil detectan repeticiones. Un perfil puede declarar estados aceptados
y anulados; estados nuevos bloquean la lectura. Devoluciones con cantidades o
importes negativos requieren revisión: el contrato actual no las interpreta como
ventas positivas ni promete conciliación fiscal. El proveedor debe entregar la
representación neta compatible o requerirá una extensión explícita.

## Sincronización, ampliación y recuperación

Carga histórica: un día por unidad durable. El payload normalizado y su revisión
se guardan antes del envío. Sólo un 200/201 o duplicado 409 confirmado marca
recepción. Reiniciar tras perder la respuesta repite la misma clave/payload.
Los payloads RC9 pendientes se conservan y se procesan mediante su cola existente.
No se guardan credenciales ni filas originales en las colas.

Una secuencia monotónica, una clave por contenido y el reemplazo diario evitan
sumar dos veces. Releer los últimos 7 días por defecto recoge ventas tardías y
correcciones; la ventana es configurable (1–365). Una revisión menor que llega
tarde no revierte una mayor. Un snapshot completo más nuevo reemplaza el día
entero, incluso productos ausentes; los lotes incrementales no son compatibles.
Ampliar el historial o confirmar otro mapeo incrementa la revisión de configuración:
el hash físico del archivo no bloquea esa relectura. El source_id permanece estable.
Un archivo histórico recapturado sigue constituyendo una nueva declaración; el
sistema no puede deducir su antigüedad comercial sólo por la fecha de captura.

Lock del sistema operativo coordina nuevas ejecuciones y cambios de configuración;
no se roba un lock vivo por tiempo. Los fallos temporales tienen hasta 10 reintentos;
un error permanente requiere corrección y reanudación explícita. No se avanza por
una página fallida. Pausar conserva estado, cola y credenciales. Recomendación de
fuente usa evidencia de campos/acceso, cobertura, estabilidad, automatización,
lectura segura e impacto; no tiene una prioridad fija API/base/archivo.

## Credenciales y diagnóstico

DPAPI de usuario + ACL por SID. La tarea RC9 inicia bajo el usuario que abre la
sesión; debe ser quien activó/configuró AIVA. Otro usuario no puede usar las claves.
No se cambia a SYSTEM ni se comparte DPAPI entre cuentas. El verificador Windows
comprueba lectura desde CLI y background congelados bajo la misma identidad.
En Linux no hay fallback de texto plano para credenciales de integración.
Se pueden reemplazar o eliminar; la revocación también debe realizarse en el proveedor.

OAuth es authorization code con PKCE S256, state aleatorio y loopback temporal
127.0.0.1/puerto efímero. No hay secreto confidencial incrustado. El proveedor debe
registrar una aplicación pública y admitir loopback; scopes/URLs/client_id deben
ser documentados. Refresh token protegido, renovación acotada y reautorización
cuando vence/se revoca. No hay compatibilidad OAuth con un proveedor real aún.

Diagnóstico agrega sólo versión, source_id opaco, etapa, códigos, conteos, fechas
de confirmación y siguiente intento; excluye perfiles, almacén DPAPI y batches.
No contiene bases/archivos originales ni sus filas. Los ejemplos sólo se ven en
la pantalla local, nunca se envían a IA. No hay exposición de la UI a la red.

## Dependencias y verificación

El EXE incluye pyodbc 5.3.0 y dependencias Python; el controlador Microsoft ODBC
18 x64 y un SQL Server autorizado son externos. Un DSN de 32 bits no prueba
compatibilidad con este Collector x64. No se descargan drivers automáticamente.
Instalar sólo desde la documentación oficial de Microsoft; revisar sus requisitos
actuales de Visual C++ según versión. pyodbc se distribuye bajo su licencia MIT-0.

Pruebas reales locales: SQLite con WAL y HTTP loopback con dos estructuras y
paginación. Dobles de Backend verifican pérdida de respuesta, idempotencia y avance.
Las pruebas cruzadas de Backend usan su motor SQLite temporal y reglas canónicas.
El test real ODBC se habilita con AIVA_TEST_SQLSERVER_PROFILE (ruta de JSON sin
secretos), AIVA_TEST_SQLSERVER_USER/PASSWORD para una base sintética autorizada.
Sin ese entorno se omite explícitamente; no certifica SQL Server real ni Windows.
CI Windows prueba widgets Tk, DPAPI, lectura desde procesos congelados, instalación,
actualización desde RC9, estado/cola preservados, desinstalación y Defender.
CI no equivale a prueba física del comercio; binario candidato sin firma.

## Recuperación antes de un despliegue futuro

No se despliega con esta tarea. Antes de desplegar Backend: backup consistente y
verificado con el servicio existente, integridad, hash y restauración temporal;
conservar imagen y configuración actuales. La procedencia diaria se añade en una
tabla separada, preservando los INSERT RC9; rollback de código no exige borrar
historial ni restaurar automáticamente la base. Nunca restaurar datos posteriores
sin conciliación y autorización.

Antes de actualizar una PC: pausar, conservar ProgramData y comprobar backup
operativo con el usuario correcto. No borrar cola, cursores ni credenciales.
Para volver a RC9, mantener la fuente nueva pausada, conservar sus archivos de
configuración y revisar qué períodos ya fueron confirmados antes de reanudar la
ruta heredada. RC9 no interpreta los conectores nuevos. La desinstalación conserva
ProgramData por defecto. No borrar bases ni archivos del sistema comercial.

Pedir al negocio: sistema/versión, una muestra anonimizada, zona horaria, sucursales,
SKU y unidades, significado de precios/descuentos, costo histórico o actual, stock
con fecha, volumen e historial. Pedir al proveedor: documentación, mecanismos de
acceso de lectura, tablas/rutas autorizadas, paginación/filtros, cobertura, estados
de anulaciones/devoluciones, límites y método de corrección/exportación automática.
Priorizar la alternativa probada que cubra esos datos con menos impacto y cambios.

Fuentes oficiales consultadas:
- https://www.sqlite.org/uri.html y https://www.sqlite.org/wal.html
- https://docs.python.org/3/library/sqlite3.html
- https://requests.readthedocs.io/en/stable/api/
- https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server
- https://github.com/mkleehammer/pyodbc/blob/master/src/pyodbc.pyi
- https://learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
- https://www.rfc-editor.org/rfc/rfc8252
