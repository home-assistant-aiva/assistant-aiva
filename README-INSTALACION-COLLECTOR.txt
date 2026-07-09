AIVA Collector v0.2.6 Discovery RC2
===================================

Esta version es candidata / pre-release. Usar primero en ambiente controlado.

Instalacion
-----------

1. Instalar AIVA Collector con AIVA-Collector-Setup-v0.2.6-discovery-rc2.exe.
2. El instalador detecta y migra automaticamente configuraciones previas a C:\ProgramData\AIVA Collector\config.windows.json.
3. Si no hay configuracion valida, ejecutar "AIVA Collector - Activar".
4. Ejecutar "AIVA Collector - Diagnosticar configuracion" si se quiere revisar la migracion sin mostrar secretos.
5. Ejecutar "AIVA Collector - Detectar fuentes sin enviar".
6. Revisar el resultado local.
7. Ejecutar "AIVA Collector - Reportar fuentes detectadas" solo cuando corresponda.
8. Verificar en Admin: AIVA Comercial > Fuentes de datos > Fuentes detectadas.
9. Convertir la discovery en fuente desde Admin antes de activarla.

Seguridad y privacidad
----------------------

- AIVA solo detecta posibles fuentes.
- AIVA no modifica archivos, bases, ventas, stock ni precios.
- AIVA no sube archivos del comercio.
- AIVA no lee contenido comercial completo en esta fase.
- AIVA no se conecta a bases reales en esta fase.
- AIVA no envia Telegram real desde Discovery.
- AIVA no usa GPT ni LLM desde Discovery.

Incluye
-------

- Deteccion segura de carpetas candidatas.
- Deteccion de CSV, XLSX y XLS.
- Deteccion por extension de SQLite, Access y Firebird.
- Deteccion basica de servicios DB en Windows sin conectarse.
- Migracion automatica de configuracion previa con backup local.
- Filtro estricto para evitar Program Files, Desktop/Downloads genericos y software no comercial.
- Comando local dry-run.
- Reporte de metadata segura al backend de Fuentes de datos.

Proximo paso
------------

Convertir la discovery en fuente desde Admin. La sincronizacion automatica desde fuente confirmada corresponde a la siguiente fase.
