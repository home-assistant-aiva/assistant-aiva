# AIVA Collector - Casos sintéticos de mapeo

La carpeta `samples/mapping_cases/` contiene archivos sintéticos de kiosco para validar mapeo sin datos reales.

## Casos

- `technical_columns.xlsx`: columnas canónicas técnicas. Debe ser `auto_approved`.
- `simple_columns.xlsx`: columnas simples como `producto`, `cantidad`, `precio`. Debe ser `auto_approved`.
- `pos_spanish_columns.xlsx`: exportación POS en español con `Fecha Venta`, `Descripción`, `Cant.`, `Precio Unit.`. Debe ser `auto_approved`.
- `accented_columns.csv`: encabezados con acentos como `Día`, `Código`, `Categoría`. Debe ser `auto_approved`.
- `english_columns.xlsx`: encabezados en inglés como `date`, `sku`, `item`, `quantity`, `price`. Debe tener confidence alta.
- `messy_but_mappable.xlsx`: encabezados ruidosos como `COD. PROD.` y `$ Precio Venta`. Debe mapear con confidence media/alta.
- `low_confidence_columns.xlsx`: columnas ambiguas. No debe autoaprobar.
- `missing_required_columns.xlsx`: faltan cantidad/precio. Debe fallar claro.

## Validación local

Ejecutar:

```bash
bash scripts/validate_mapping_cases.sh
```

El script:

- no usa token;
- no consulta backend;
- no llama GPT;
- no genera summaries;
- imprime una matriz de `file`, `status`, `confidence`, `missing_required` y campos mapeados;
- falla si un caso esperado alto queda bajo, si un caso bajo autoaprueba, si faltan required sin detectarse, o si una columna queda asignada a dos campos.

También escribe `samples/mapping_cases/output/mapping_validation_report.json`, ignorado por git.
