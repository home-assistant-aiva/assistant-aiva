AIVA Collector Source Setup RC5
================================

Esta version es candidata / pre-release. Usar primero en ambiente controlado.

Instalacion o actualizacion
---------------------------

1. Ejecutar como administrador AIVA-Collector-Setup-v0.2.6-source-setup-rc5.exe.
2. Se puede instalar desde cero o encima de RC4/RC3/INSTALADOR 2.5.
3. No borrar C:\ProgramData\AIVA\Collector.
4. El instalador conserva activacion, token seguro, estado, cola, mapeos y logs.
5. RC5 unifica la configuracion activa en:

   C:\ProgramData\AIVA\Collector\config.local.json

6. Si existe config.windows.json de RC4, se migra automaticamente sin borrar el original.
7. La tarea automatica sigue usando aiva-collector-background.exe sin consola cada 15 minutos.

Primera configuracion
---------------------

1. Abrir AIVA Collector.
2. Si la PC es nueva, elegir Activar Collector e ingresar el codigo de activacion.
3. Elegir Configurar o cambiar fuente.
4. Seleccionar una opcion:

   - Carpeta predeterminada de AIVA:
     C:\ProgramData\AIVA\Collector\entrada
     AIVA mueve los archivos terminados a procesados/rechazados.

   - Otra carpeta manual, por ejemplo C:\Ventas:
     AIVA trabaja en modo solo lectura y no mueve ni borra originales.

   - Buscar carpetas automaticamente:
     AIVA muestra candidatas y la persona confirma cual usar.

5. Elegir Probar fuente sin enviar.
6. Si la prueba es correcta, elegir Procesar ahora.

Control de duplicados
---------------------

- Se conserva la deduplicacion por hash local y la idempotencia del backend.
- Copiar el mismo archivo no genera ventas duplicadas.
- Probar fuente sin enviar puede repetirse y no marca archivos como enviados.
- No existe un boton comun para forzar duplicados reales.

Ejecucion automatica
--------------------

- Tarea: AIVA Collector Auto.
- Ejecutable: aiva-collector-background.exe.
- Argumentos: run-auto --config "%ProgramData%\AIVA\Collector\config.local.json".
- Inicio de sesion con demora de 60 segundos.
- Repeticion cada 15 minutos.
- Hidden=true, IgnoreNew, timeout 30 minutos y 3 reintentos cada 5 minutos.
- No usa run_auto.bat, cmd.exe ni PowerShell.

Seguridad
---------

- El instalador no contiene tokens ni configuraciones reales.
- La seleccion manual no cambia commerce_id, collector_id ni activacion.
- La carpeta externa se configura en modo solo lectura.
- AIVA envia resumenes, no archivos crudos.

Alcance
-------

RC5 incorpora configuracion local guiada y lectura automatica de la carpeta elegida.
No incorpora el flujo completo Admin/backend de FASE 6.4C, APIs ni lectura real de bases locales.

Prueba fisica pendiente
-----------------------

Federico debe confirmar en Windows que:

- la instalacion conserva activacion;
- la configuracion manual persiste al reiniciar;
- Probar fuente sin enviar no mueve el archivo;
- Procesar ahora envia una sola vez;
- el duplicado no vuelve a enviarse;
- la tarea automatica usa la misma fuente sin abrir ventanas.
