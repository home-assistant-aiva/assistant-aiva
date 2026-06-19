# Pedido de datos para primer cliente

Para probar AIVA Collector necesitamos una exportacion simple desde el sistema del comercio. No hace falta clave del sistema y AIVA no modifica ventas, stock, facturacion ni datos del sistema.

## Que pedir

Pedir, si el sistema lo permite:

- Exportacion de ventas de los ultimos 7 o 30 dias.
- Exportacion de stock actual.
- Exportacion de productos y costos, si existe.
- Archivo en CSV o Excel.

Idealmente el archivo debe incluir estas columnas o equivalentes:

- Fecha de venta.
- Producto o codigo.
- Nombre del producto.
- Cantidad vendida.
- Precio de venta.
- Costo, si existe.
- Stock actual, si existe.
- Categoria, si existe.

Si el sistema exporta varios archivos separados, pedirlos por separado y anotar que representa cada uno.

## Que explicar al comercio

- AIVA Collector lee una copia exportada del archivo.
- AIVA no entra al sistema del comercio.
- AIVA no cambia precios, stock, facturas ni ventas.
- La primera prueba puede hacerse sin enviar nada al backend.
- El objetivo es validar que las columnas se pueden mapear y que el resumen tiene sentido.

## Que no pedir

- Contraseñas.
- Acceso remoto innecesario.
- Base de datos completa.
- Tickets con datos personales si no hace falta.
- Informacion sensible que no se usara en el piloto.
- Claves de administrador del sistema del comercio.

## Mensaje sugerido

Necesitamos una exportacion de ventas reciente, idealmente de los ultimos 7 o 30 dias, en CSV o Excel. Si tambien tenes una exportacion de stock actual y costos por producto, sirve para mejorar la prueba. No necesitamos contraseñas ni acceso al sistema; AIVA solo lee una copia del archivo exportado y no modifica nada.
