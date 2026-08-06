AIVA Collector Discovery RC6
===================================

Esta version es candidata / pre-release. Usar primero en ambiente controlado.

Instalacion
-----------

1. Instalar AIVA Collector con AIVA-Collector-Setup-v0.2.6-discovery-rc6.exe.

Actualizacion desde instalador 2.5/RC anteriores:
- El instalador conserva %PROGRAMDATA%\AIVA\Collector.
- Conserva config.local.json, token seguro, estado, cola offline, mapeos y logs.
- La tarea nueva usa aiva-collector-background.exe sin consola.
- La tarea se registra al iniciar sesion, con 60 segundos de demora, repeticion cada 15 minutos, Hidden=true, IgnoreNew, timeout de 30 minutos y reintento cada 5 minutos hasta 3 veces.
- Al instalar la tarea nueva se eliminan solo tareas conocidas anteriores: AIVA Collector, AIVA Collector Scheduled, AIVA Collector Auto.
- No vuelve a activar el Collector si ya existe config.local.json y token guardado.
- No ejecuta discovery automatico repetido desde la tarea; la tarea solo corre run-auto.

Rollback:
- Desinstalar AIVA Collector desde Windows. Por defecto no borrar %PROGRAMDATA%\AIVA\Collector.
- Reinstalar el instalador anterior aprobado.
- Ejecutar "AIVA Collector - Instalar tarea automatica" si se requiere restaurar la tarea manualmente.
- Si se desea un rollback limpio completo, copiar primero %PROGRAMDATA%\AIVA\Collector como backup operativo.
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

Notas RC6
---------

- Reporta fuentes detectadas al endpoint seguro del Collector sin X-AIVA-Secret.
- Usa Authorization Bearer del Collector y X-AIVA-Collector-Id.
- Reporta la fuente elegida en config como selected_explicit para dejarla activa.
- Muestra errores HTTP concretos ante 401, 403, 404 y 422.
- Ejecucion automatica silenciosa mediante aiva-collector-background.exe.
- Salida del runner background dirigida a logs en ProgramData con rotacion.
- Costo faltante tratado como null, sin margen inventado.
- Pendiente de prueba fisica final por Federico.
- FASE 6.4C todavia no incluida.

Proximo paso
------------

Convertir la discovery en fuente desde Admin. La sincronizacion automatica desde fuente confirmada corresponde a la siguiente fase.
