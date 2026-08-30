# AIVA Collector Windows installer

El instalador se compila en Windows con Inno Setup desde GitHub Actions:

```bat
iscc packaging\inno\aiva_collector_setup.iss
```

Requisitos:

- `dist\aiva-collector.exe` (interfaz gráfica);
- `dist\aiva-collector-cli.exe` (soporte);
- `dist\aiva-collector-background.exe` (tarea automática);
- `windows\config.windows.example.json` sin tokens;
- wrappers de `packaging\windows_runtime`.

El instalador conserva `C:\ProgramData\AIVA\Collector`, no incluye secretos y registra la tarea contra `config.windows.json`.
