# Exportaciones diarias — contrato 2.0.0

RC5 conserva métricas por fecha comercial y código estable en `daily_snapshot`, además del resumen global compatible. Actualizar Backend antes de habilitar el Collector para reportes diarios. La carpeta origen no se modifica.

Desktop sigue en modo sólo lectura. `run-auto` envía un snapshot por archivo. Los comandos antiguos que fusionan varios archivos no pueden emitir un snapshot diario seguro: mantienen v1 por compatibilidad si no se pidió explícitamente v2. Con versión 2.0.0 explícita, rechazan la combinación y solicitan `run-auto`.

## Cobertura declarada

La configuración existente se preserva. Campos aditivos:

```json
{
  "source_schema_version": "2.0.0",
  "daily_source_id": "exportacion-completa-caja",
  "daily_snapshot_complete": false,
  "business_timezone": "America/Argentina/Buenos_Aires",
  "price_semantics": "final_net"
}
```

`daily_snapshot_complete` permanece falso/desconocido por defecto. Sólo establecer `true` si el exportador garantiza que cada fecha presente contiene TODOS los productos y movimientos del comercio, sin filtros parciales. No se deduce esa garantía a partir de filas o nombres. Una fila explícita con cantidad cero conserva el día; una fecha ausente nunca se completa automáticamente. Filas descartadas o fechas/códigos parcialmente ausentes dejan todos los días unknown. Backend conserva diagnóstico y bloquea reportes incompletos.

Sin versión configurada, fuentes con fechas/códigos emiten v2; fuentes sin ninguna observación diaria identificable mantienen v1. Versión explícita 2.0.0 rechaza ausencia de fechas/códigos. Versión 1.0.0 conserva legacy. No borrar estado ni cola para forzar upgrade. Archivos ya enviados permanecen procesados: no se vuelven a sincronizar automáticamente.

`daily_source_id` identifica el flujo estable, NO cada archivo. Si falta, se deriva un identificador opaco de la carpeta configurada. Mantenerlo estable en exportaciones completas sucesivas. No reutilizarlo para alcances distintos. Backend bloquea fuentes/Collectors que declaran cubrir simultáneamente todo el comercio; no los suma.

## Valores y correcciones

Precio venta es precio final unitario: ingreso = cantidad × precio. Descuento debe ser cero o ausente; descuento no cero y precio bruto se rechazan hasta contar con contrato explícito. Importes diarios se calculan con Decimal y se serializan con seis decimales HALF_EVEN. Los promedios no reconstruyen totales. Costo parcial queda desconocido. Stock se conserva sólo cuando las observaciones del día coinciden; valores distintos no demuestran cuál fue el cierre.

Cada captura recibe una revisión monotónica persistida localmente. `snapshot_replace` reemplaza sólo fechas declaradas del mismo comercio/Collector/fuente, preservando auditoría y fechas fuera de ese alcance. Reexportar un archivo antiguo como una captura nueva es una nueva declaración del operador; `mtime` no se interpreta como revisión comercial.

La clave idempotente incluye contexto, esquema, fuente, cobertura y métricas, excluyendo revisión de captura. El mismo contenido no se duplica. La cola conserva el payload original, incluida revisión; retry no relee Excel. Secuencia local y versión son aditivas; colas v1 mantienen clave y contenido. Contenido diferente con una clave ya usada se rechaza como conflicto, no como duplicado exitoso.

## Windows

El build oficial incorpora tzdata para zonas IANA. Usar `build-collector-windows-release.yml` con `publish_release=false`. No crear tags ni instalar sobre la PC del usuario durante esta etapa. Verificar manifest, SHA, smoke y preservación de ProgramData antes de aprobación operativa.
