# AIVA Collector - Mapeo inteligente de columnas

Desde v0.2.3, AIVA Collector puede leer CSV/XLSX de distintos sistemas sin pedirle al comercio que renombre columnas manualmente.

## Campos canónicos

Requeridos:

- `producto_nombre`
- `cantidad_vendida`
- `precio_venta`

Opcionales recomendados:

- `fecha`
- `producto_codigo`
- `categoria`
- `costo_unitario`
- `stock_actual`

## Aliases soportados

- Producto: `producto`, `producto_nombre`, `nombre_producto`, `descripcion`, `descripción`, `articulo`, `artículo`, `item`, `detalle`, `nombre`, `name`, `nombre descripcion producto`.
- Código: `codigo`, `código`, `cod`, `sku`, `cod prod`, `codigo articulo`, `producto_codigo`, `cod_articulo`, `cod_producto`, `codigo_producto`, `ean`, `barcode`, `barra`, `codigo_barras`.
- Cantidad: `cantidad`, `cant`, `cantidad_vendida`, `unidades`, `unidades_vendidas`, `unid vend`, `qty`, `quantity`, `vendido`, `ventas`.
- Precio: `precio`, `precio_venta`, `precio unitario`, `precio unit`, `pvp`, `venta`, `valor_unitario`, `importe_unitario`, `precio final`, `precio venta`, `price`.
- Costo: `costo`, `costo_unitario`, `precio_costo`, `costo compra`, `costo unitario`, `compra`, `precio_compra`, `cost`.
- Stock: `stock`, `stock_actual`, `existencia`, `existencias`, `inventario`, `inventory`, `disponible`, `stock disponible`.
- Fecha: `fecha`, `fecha_venta`, `fecha venta`, `dia`, `día`, `date`, `fecha_movimiento`, `fecha comprobante`.
- Categoría: `categoria`, `categoría`, `rubro`, `familia`, `linea`, `línea`, `grupo`, `departamento`, `category`, `seccion`, `sección`.

La normalización convierte mayúsculas a minúsculas, quita acentos, limpia signos y colapsa espacios/guiones/puntos.

## Confianza

- `auto_approved`: confidence `>= 0.85` y campos requeridos presentes. AIVA procesa.
- `needs_review`: confidence media. AIVA no debe enviar summary en `run-auto`; crea candidato para revisar.
- `failed`: faltan requeridos o el mapeo no es confiable. El archivo queda en entrada.

El mapping explícito de `config.local.json` o el mapping activo del backend tienen prioridad si sus columnas existen. Si no coinciden con el archivo, AIVA intenta autodetectar.

## Revisión desde admin

En AIVA Comercial, abrir el comercio y usar la sección `Mapeo de columnas`:

1. Revisar candidatos pendientes.
2. Ver headers detectados, mapping sugerido y confidence.
3. Aprobar candidato para activar el mapping.
4. O editar manualmente producto, cantidad y precio.

El mapping activo se reutiliza en próximos archivos del mismo comercio/collector.

## IA opcional

GPT no procesa todo el Excel. Sólo puede sugerir mapping si un admin lo pide explícitamente desde un candidato, usando headers y preview limitado/sanitizado. El collector nunca llama GPT automáticamente.

## Qué pedir al cliente si no mapea

Pedir una exportación con encabezados visibles y al menos estas columnas:

- producto o descripción
- cantidad vendida
- precio de venta

Opcionalmente pedir código/SKU, categoría/rubro, costo, stock y fecha.
