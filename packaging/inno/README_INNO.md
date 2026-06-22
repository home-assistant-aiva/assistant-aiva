# AIVA Collector Windows installer

Este instalador se compila en Windows con Inno Setup desde GitHub Actions.

Entrada principal:

```bat
iscc packaging\inno\aiva_collector_setup.iss
```

Requisitos previos:

- `dist\aiva-collector.exe` generado por PyInstaller.
- `windows\config.windows.example.json` sin tokens.
- Wrappers en `packaging\windows_runtime`.

El instalador crea `C:\AIVA_Comercio\config.local.json` solo si no existe. No guarda tokens y no ejecuta envios al backend durante instalacion.
