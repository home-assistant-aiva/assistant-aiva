AIVA Collector Desktop RC2
==========================

Versión candidata para validar primero en una PC controlada del comercio.

Qué corrige
-----------

- "AIVA Collector" ahora abre una aplicación visible; ya no abre una consola que se cierra.
- La aplicación muestra si el equipo está conectado, la carpeta observada, la última sincronización y la cola pendiente.
- La configuración automática usa la ruta real: %ProgramData%\AIVA\Collector\config.windows.json.
- La tarea automática continúa en segundo plano cada 15 minutos sin mostrar una consola.
- La aplicación técnica de consola queda separada como aiva-collector-cli.exe.
- La carpeta elegida se trata como solo lectura: AIVA no mueve ni borra archivos del sistema de ventas.

Instalación
-----------

1. Ejecutar AIVA-Collector-Setup-v0.2.7-desktop-rc2.exe.
2. Dejar marcada la opción de acceso directo en el escritorio.
3. Al terminar, abrir "AIVA Collector".
4. Presionar "Conectar con AIVA".
5. Pegar el código de activación generado desde AIVA Comercial.
6. Presionar "Elegir carpeta de datos" y seleccionar la carpeta donde el sistema de ventas exporta CSV o Excel.
7. Presionar "Probar conexión".
8. Presionar "Sincronizar ahora" para la primera prueba controlada.

Uso normal
----------

- No hace falta dejar abierta la ventana.
- Windows ejecuta aiva-collector-background.exe al iniciar sesión y luego cada 15 minutos.
- Si no hay Internet, los envíos quedan en cola y se reintentan.
- La ventana puede abrirse en cualquier momento para revisar el estado o sincronizar manualmente.

Actualización desde RC6 o versiones anteriores
-----------------------------------------------

- Conserva %ProgramData%\AIVA\Collector.
- Conserva activación, token protegido, estado, cola, mapeos y registros.
- Reinstala únicamente las tareas conocidas de AIVA Collector.
- Migra una configuración previa válida a config.windows.json cuando corresponde.
- No publica tokens ni los muestra en pantalla.

Archivos y seguridad
--------------------

- Configuración: %ProgramData%\AIVA\Collector\config.windows.json
- Estado y token protegido: %ProgramData%\AIVA\Collector\estado
- Registros: %ProgramData%\AIVA\Collector\logs
- Backups de configuración: %ProgramData%\AIVA\Collector\backups
- El token se protege con Windows DPAPI para el usuario que activa el equipo.
- El Collector admite CSV y XLSX.
- Al seleccionar una carpeta externa, los archivos originales permanecen en su lugar.
- Para producción y demostraciones con datos reales, el servicio AIVA debe usar una URL HTTPS válida. La IP HTTP heredada queda únicamente para pruebas controladas.

Límite actual
-------------

Esta versión conecta de forma automática una carpeta de exportación CSV/XLSX. La conexión directa a bases propietarias del sistema de caja requiere un conector específico y no debe declararse disponible sin validarlo con ese proveedor.

Rollback
--------

1. Copiar %ProgramData%\AIVA\Collector como backup operativo.
2. Desinstalar AIVA Collector desde Windows sin borrar ProgramData.
3. Reinstalar el instalador anterior aprobado.
4. Restaurar la tarea automática de la versión anterior si fuera necesario.
