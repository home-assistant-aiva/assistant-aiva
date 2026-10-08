# RC8: configuración guiada y descuentos diarios

Candidato de prueba `0.2.8rc8`. HTTPS y prueba física Windows pendientes: no es una entrega comercial. No se habilitan envíos reales por canales.

## Problema y solución

RC7 asumía `final_net`, tanto en Collector como en Backend, y rechazaba descuentos no nulos. El diagnóstico previo disponible no certificaba el significado de precios ni la completitud de la fuente. No se confirmó que ese diagnóstico represente el comercio recién vinculado; no se ingirieron sus datos.

La ventana Configurar archivo y precios permite seleccionar CSV/XLSX, hoja y encabezado XLSX, mapear fecha, producto, código estable, cantidad, precio unitario, descuento, costo unitario, categoría y stock con su fecha. Exige elegir precio bruto/neto y descuento por unidad/línea/porcentaje. Ofrece cálculo de primera línea y totales locales antes de guardar. No envía filas crudas ni archivos durante la vista previa.

- Bruto: neto = cantidad × precio − descuento monetario.
- Neto: neto = cantidad × precio; el descuento informado no se resta otra vez.
- Porcentaje sobre bruto: descuento = bruto × porcentaje / 100. Si el precio es neto, se reconstruye descuento = neto × porcentaje / (100 − porcentaje); 100% neto es ambiguo y se bloquea.
- Costos ausentes quedan desconocidos. Stock sólo corresponde al día si su fecha coincide.
- Fechas/códigos inválidos, encabezados cambiados y descuentos no numéricos bloquean ese archivo.

El payload v2 mantiene `snapshot_replace` y precios unitarios **netos**. El enum aditivo `final_net_with_discounts` permite conservar el descuento total como dato informativo. Backend continúa verificando cantidad × precio neto = venta neta; Admin presenta el documento canónico y no resta de nuevo descuentos. `final_net` anterior sigue exigiendo descuento cero. Actualizar Backend antes de enviar el nuevo enum.

## Alcance y aislamiento

Una fuente lógica por carpeta; CSV UTF-8/BOM con coma o punto y coma; XLSX de una sola hoja y encabezado en filas 1–25. No se combinan hojas, lotes incrementales ni archivos parciales como si fueran días completos. No se admiten XLS, conectores propietarios, cantidades negativas ni precios totales de línea en el campo unitario. Cobertura completa exige declaración explícita; no se inventan días ausentes.

Vincular crea estado separado por Backend/comercio/Collector y exige configurar fuente. Cada fuente incluye carpeta, formato y hoja; mapping y completitud quedan asociados al contexto. La cola valida propietario antes de cambiar estado/enviar. Deduplicación local incorpora fuente mediante migración aditiva, conservando historial y pendientes.

Antes de migrar SQLite RC7 se genera una copia consistente local `aiva_collector.pre-rc8-*.db` con `integrity_check`. Se prueba restauración en SQLite temporal. Esta copia es local, nunca se publica. Para volver a RC7 hay que detener tareas y preservar el estado RC8; **no** abrir con RC7 una base que ya contenga hashes iguales de distintas fuentes, porque el índice antiguo no admite esa distinción. Restaurar una copia anterior descarta observaciones posteriores: requiere revisión operativa, no es un downgrade automático.

Archivos rechazados sin cambios se omiten con instrucciones visibles. Reprocesar archivo rechazado exige pertenencia al contexto/fuente activo y selecciona sólo ese archivo; no vacía la cola ni borra historial. La tarea respeta el backoff en vez de forzar reintentos inmediatos.

## Validación y entrega

- Suite Collector y aceptación de las seis combinaciones de precios/descuentos.
- Integración entre repositorios: configuración guardada → ingesta → duplicado 409 → reportes semanal y septiembre completo; agosto preservado. SQLite temporal, automatización de canales deshabilitada.
- Admin consume descuentos canónicos; suite completa y build.
- Workflow oficial con `publish_release=false`, checkout del SHA inmutable, Tk real en runner Windows, PyInstaller/Inno, actualización desde instalador RC7 SHA-256 `a280e24643ff454043acddf398db063802121c0025b28fb03da038560b4fd5a3`, conservación de ProgramData, SQLite/cola/DPAPI, tarea, desinstalación, análisis PE y Defender.
- El runner no acredita prueba física ni reinicio de una PC cliente. HTTP continúa siendo sólo de prueba por decisión del usuario de no asignar dominio todavía.

Los parches acompañantes Backend/Admin y la secuencia de despliegue se entregan en la rama candidata del repositorio de infraestructura. No se desplegaron servicios ni se alteraron datos productivos. La revisión automática rechazó copiar la base productiva al no haber despliegue en curso; se conserva pendiente el backup operativo previo a un futuro despliegue.
