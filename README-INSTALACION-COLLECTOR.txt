AIVA Collector Desktop RC8 — 0.2.8rc8
CANDIDATO DE PRUEBA. No aprobado para instalar en clientes con HTTP.

Instalación y primera sincronización
1. Ejecutar AIVA-Collector-Setup-v0.2.8-desktop-rc8.exe.
2. Abrir AIVA Collector y vincular el comercio con su código de activación.
3. Abrir Configurar archivo y precios. Elegir una exportación CSV o XLSX.
4. Asignar fecha, producto, código estable, cantidad y precio unitario.
   Opcionales: descuento, costo unitario, categoría, stock y fecha del stock.
   Para XLSX se puede indicar hoja y fila de encabezado (1 a 25).
5. Definir precio bruto antes del descuento o neto ya descontado, y descuento
   por unidad, por línea o porcentaje del importe bruto (escala 0 a 100).
   No adivinar: confirmar estos significados con quien genera la exportación.
6. Revisar el ejemplo y los totales de Previsualizar. Confirmar cobertura
   completa sólo si cada archivo contiene todas las ventas de cada día incluido.
   Días ausentes no se consideran días con cero ventas. Guardar configuración.
7. Probar conexión y Sincronizar ahora. Repetir no debe duplicar las ventas.
8. Para un archivo previamente rechazado, corregir la configuración y usar
   Reprocesar archivo rechazado, eligiendo únicamente ese archivo.

Compatibilidad
CSV UTF-8 (con o sin BOM), separadores coma/punto y coma. XLSX con una hoja
por fuente. Exportación tabular, precios/costos unitarios y cantidades no
negativas. Una fuente lógica por carpeta. Los archivos que cubren el mismo día
son reemplazos completos, NO lotes incrementales de tickets. No se combinan
hojas, bases, XLS antiguos ni APIs propietarias. Fechas deben ser inequívocas.
Stock sin fecha coincidente con el día de venta se conserva como desconocido.
Costos ausentes no se convierten en cero. Fuentes ambiguas quedan para revisión.

Preservación
La fuente es de sólo lectura. Actualizar/desinstalar conserva ProgramData.
Una nueva vinculación crea un contexto separado y exige configurar su fuente.
Las colas anteriores permanecen preservadas; no se envían con otra vinculación.
La tarea automática usa el proceso background cada 15 minutos y al iniciar sesión.
Un rechazo persistente requiere acción; fallos de red tienen reintento con espera.

Requisitos pendientes antes de clientes
- HTTPS con certificado y URL válidos. La dirección HTTP actual es sólo de prueba.
- Backend compatible con final_net_with_discounts y Admin con el dato canónico.
  Los cambios acompañantes deben desplegarse antes de enviar descuentos.
- Prueba física de instalación, reinicio y actualización en la PC de destino.
Las pruebas CI y Defender no sustituyen esta validación física ni la firma digital.
No ejecutar herramientas especiales del piloto RC7 para configurar RC8.
