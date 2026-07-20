# AIVA_COLLECTOR_WINDOWS_PILOT_CHECKLIST

Estado: PENDIENTE DE PRUEBA FISICA POR FEDERICO

## 1. Requisitos de Windows

- Windows 10/11 con permisos de administrador para instalar.
- Acceso a Internet hacia el backend de AIVA.
- Usuario con permiso de lectura sobre la carpeta donde el comercio deja CSV/XLSX.
- Hora del sistema correcta.

Resultado esperado: la PC permite instalar, crear carpetas en `C:\ProgramData\AIVA\Collector` y ejecutar la tarea programada.

## 2. Instalacion en PC limpia

1. Ejecutar el instalador de AIVA Collector como administrador.
2. Confirmar que los binarios queden en `C:\Program Files\AIVA Collector`.
3. Confirmar que los datos mutables queden en `C:\ProgramData\AIVA\Collector`.

Resultado esperado: el directorio de instalacion no contiene estado, logs, cola ni summaries.

## 3. Ubicaciones finales

- Configuracion: `C:\ProgramData\AIVA\Collector\config.windows.json`.
- Logs: `C:\ProgramData\AIVA\Collector\logs`.
- Estado local: `C:\ProgramData\AIVA\Collector\estado`.
- Cola offline: `C:\ProgramData\AIVA\Collector\estado\queue`.
- Entrada: `C:\ProgramData\AIVA\Collector\entrada`.
- Procesados: `C:\ProgramData\AIVA\Collector\procesados`.
- Rechazados: `C:\ProgramData\AIVA\Collector\rechazados`.
- Ultimo summary: `C:\ProgramData\AIVA\Collector\ultimo_summary\last_summary.json`.
- Mapeos: `C:\ProgramData\AIVA\Collector\mapeos`.

Resultado esperado: todas las carpetas existen y sobreviven a reinicio, actualizacion y reinstalacion no destructiva.

## 4. Activacion del Collector

1. Crear comercio y collector desde el admin.
2. Generar codigo de activacion.
3. Ejecutar `AIVA Collector - Activar`.
4. No guardar tokens en documentos ni capturas.

Resultado esperado: `config.windows.json` queda con `commerce_id`, `collector_id` y el token queda en almacenamiento local seguro o variable de entorno, no impreso en logs.

## 5. Carpeta de entrada

Crear o validar `C:\ProgramData\AIVA\Collector\entrada`.

Resultado esperado: el usuario de la tarea programada puede leer los archivos y el Collector puede mover procesados/rechazados.

## 6. CSV minimo de prueba

Archivo `ventas_minimo.csv`:

```csv
fecha,producto_codigo,producto_nombre,categoria,cantidad_vendida,precio_venta,costo_unitario,stock_actual
2026-07-10,SKU-1,Yerba 1kg,Almacen,2,3500,2500,8
2026-07-10,SKU-2,Producto sin costo,Almacen,1,1000,,5
```

Resultado esperado: el producto sin costo viaja con costo y margen `null`, no con margen 100%.

## 7. XLSX minimo de prueba

Crear un XLSX con las mismas columnas del CSV minimo.

Resultado esperado: el summary del XLSX coincide con el CSV en cantidad de productos, ventas y tratamiento de costo faltante.

## 8. Mapeo de columnas

Validar `column_mapping` en `config.windows.json` o desde admin.

Resultado esperado: si cambian nombres de columnas, el Collector bloquea el envio y pide revisar mapeo; no inventa columnas.

## 9. Primera ejecucion manual

Ejecutar:

```bat
run_validate.bat
run_dry.bat
```

Resultado esperado: se genera `last_summary.json`, no se envia nada al backend y los logs no muestran token.

## 10. Tarea programada

Ejecutar `AIVA Collector - Instalar tarea automatica`.

Resultado esperado: existe la tarea `AIVA Collector Auto`, corre cada 15 minutos y escribe log en ProgramData.

## 11. Corte de Internet

Desconectar Internet y ejecutar `Procesar ahora`.

Resultado esperado: el payload queda en cola offline y no se pierde el archivo.

## 12. Reenvio de cola offline

Restaurar Internet y ejecutar `Reintentar Pendientes`.

Resultado esperado: la cola baja a cero o informa errores HTTP concretos sin duplicar summaries aceptados.

## 12.1 Envio controlado

Ejecutar:

```bat
run_send.bat
```

Escribir `ENVIAR` solo si Federico decide enviar el summary real al backend.

Resultado esperado: si no se escribe `ENVIAR`, no se envio nada al backend; si se confirma, el backend responde con summary aceptado o duplicado.

## 13. Reinicio de Windows

Reiniciar la PC.

Resultado esperado: logs, estado, cola y configuracion siguen en ProgramData; la tarea programada sigue instalada.

## 14. Archivo duplicado

Copiar el mismo CSV dos veces.

Resultado esperado: el Collector detecta duplicado por hash/idempotencia y no duplica ventas en backend.

## 15. Archivo invalido

Enviar un CSV sin `producto_nombre` o sin `precio_venta`.

Resultado esperado: el archivo se rechaza o queda con filas descartadas, con motivo visible en logs/admin.

## 16. Cambio de columnas

Renombrar `precio_venta` a `precio`.

Resultado esperado: si no hay mapeo compatible, se bloquea el envio y se registra candidato de mapeo.

## 17. Verificacion en admin

Revisar comercio, collector, ultima ingesta, archivos fuente, calidad de datos y recomendaciones.

Resultado esperado: el admin muestra ultima conexion, errores, productos sin costo y recomendaciones sin margen inventado.

## 18. Verificacion del reporte

Generar reporte semanal.

Resultado esperado: la reposicion se muestra como estimacion a revisar e incluye el aviso de validar bulto, proveedor, proxima compra y tiempo de entrega.

## 19. Verificacion de preguntas

Preguntar por margen, ganancia, precio y combo ante un producto sin costo.

Resultado esperado: AIVA responde que no puede calcular margen/ganancia/precio seguro porque falta costo.

## 20. Desinstalacion y reinstalacion

Desinstalar y reinstalar sin borrar ProgramData.

Resultado esperado: la configuracion y estado sobreviven; no se escribe estado dentro de Program Files.

## 21. Resultado esperado final

El piloto queda aprobado solo si Federico confirma en PC fisica:

- procesamiento CSV y XLSX;
- cola offline;
- reinicio;
- duplicados;
- archivo invalido;
- cambio de columnas;
- visualizacion admin;
- reporte;
- preguntas.

Estado final hasta esa prueba: PENDIENTE DE PRUEBA FISICA POR FEDERICO.
