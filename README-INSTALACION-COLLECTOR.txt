AIVA Collector Desktop RC9 — 0.2.8rc9
CANDIDATO DE PRUEBA. No aprobado para instalar en clientes con HTTP.

Instalación y primera sincronización
1. Ejecutar AIVA-Collector-Setup-v0.2.8-desktop-rc9.exe.
2. Abrir AIVA Collector y vincular el comercio con su código de activación.
3. Abrir Configurar archivo y precios. Elegir una exportación CSV o XLSX.
4. AIVA propone qué columna corresponde a cada dato. Revisar la propuesta:
   fecha, producto, cantidad y precio unitario son obligatorios. El código
   de producto es opcional: si la exportación no lo tiene, AIVA identifica
   cada producto por su nombre y categoría.
   Opcionales: código, descuento, costo unitario, categoría, stock y fecha
   del stock. Para XLSX se puede indicar hoja y fila de encabezado (1 a 25).
5. Mirar la tabla "Así va a leer AIVA tus ventas": a la izquierda de cada
   flecha está lo que dice el archivo y a la derecha cómo lo entiende AIVA.
   Un precio "1.890" tiene que verse como 1.890, nunca como 1,89. Si una
   columna no tiene decimales, AIVA lo avisa: elegir el formato de números
   a mano si hace falta. Las filas en rojo no se pueden leer.
6. Definir precio bruto antes del descuento o neto ya descontado, y descuento
   por unidad, por línea o porcentaje del importe bruto (escala 0 a 100).
   No adivinar: confirmar estos significados con quien genera la exportación.
7. Previsualizar. Revisar el ejemplo, los totales y los controles. Confirmar
   cobertura completa sólo si cada archivo contiene todas las ventas de cada
   día incluido. Días ausentes no se consideran días con cero ventas.
   Guardar configuración: el formato de números confirmado queda fijo.
8. Probar conexión y Sincronizar ahora. Repetir no debe duplicar las ventas.

Actualización desde RC8
Instalar encima de RC8. Se conservan activación, token, configuración, estado
y cola. Los archivos que RC8 rechazó (por ejemplo, precios con "$") se vuelven
a evaluar una sola vez con RC9, sin intervención. Conviene abrir Configurar
archivo, Previsualizar y Guardar para fijar el formato de números.

Compatibilidad
CSV UTF-8 (con o sin BOM), separadores coma/punto y coma. XLSX con una hoja
por fuente. Números en formato argentino ($ 1.890,00 · 2.450 · (1.200)) o de
EE.UU. (1,890.00), con o sin símbolo de moneda. Fechas día/mes/año, con o sin
hora, ISO o número de serie de Excel; nunca mes/día/año. Las filas vacías y la
fila de TOTAL al pie se ignoran. Exportación tabular, precios/costos unitarios
y cantidades no negativas. Una fuente lógica por carpeta. Los archivos que
cubren el mismo día son reemplazos completos, NO lotes incrementales de
tickets. No se combinan hojas, bases, XLS antiguos ni APIs propietarias.
Stock sin fecha coincidente con el día de venta se conserva como desconocido.
Costos ausentes no se convierten en cero. Fuentes ambiguas quedan para revisión.

Preservación
La fuente es de sólo lectura. Actualizar/desinstalar conserva ProgramData.
Una nueva vinculación crea un contexto separado y exige configurar su fuente.
Las colas anteriores permanecen preservadas; no se envían con otra vinculación.
La tarea automática corre cada 15 minutos y al iniciar sesión, con la sesión
de Windows de quien la inicia (no con la cuenta que instaló). Si en la PC
entra otro usuario de Windows, la tarea no sincroniza desde esa sesión.
Un archivo bloqueado por otro programa se reintenta en la próxima corrida.
Un rechazo persistente requiere acción; fallos de red tienen reintento con espera.

Requisitos pendientes antes de clientes
- HTTPS con certificado y URL válidos. La dirección HTTP actual es sólo de prueba.
- Backend compatible con final_net_with_discounts y con códigos de producto
  derivados ("name_hash:...") de las fuentes configuradas sin código.
- Prueba física de instalación, reinicio y actualización en la PC de destino.
Las pruebas CI y Defender no sustituyen esta validación física ni la firma digital.
