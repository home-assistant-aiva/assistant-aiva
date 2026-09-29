# Piloto diario v2 RC7 — comercio demo

Este soporte es sólo para `commerce_a0e93d3ec7ac`. El preflight inspecciona RC6, deshabilita temporalmente la tarea y conserva/verifica un backup local de ProgramData. No instala RC7 ni sincroniza.

Instalador oficial RC7: https://github.com/home-assistant-aiva/assistant-aiva/actions/runs/36514597488
Archivo dentro del artifact: `AIVA-Collector-Setup-v0.2.7-desktop-rc7.exe`
SHA-256 instalador: `1899cf40b4b36f7198aded997f1fd8a25238ab5f5eb63681b84933183ad2cbf4`

SHA-256 de `Run-AIVA-RC7-Preflight.ps1`: `d4e03702cecf41426855700682e10698d0bdb4e60f0b59d12155f354941ebf9e`
SHA-256 de `aiva-demo-daily-v2-source-20260929.zip`: `5b258b2edf6745c6149aef4a4c9ecb7dc061522ad5c15e8378a2c235302e37ef`
SHA-256 del XLSX dentro del ZIP: `2a173badfd6bad847af779d89b947139110af3a3d0108601edb05a96e53f2cd3`

Guardá el instalador, el script y el ZIP sintético en `C:\AIVA-Piloto-RC7`. En PowerShell de 64 bits como administrador, verificá el SHA del script y ejecutá:

```powershell
$p='C:\AIVA-Piloto-RC7\Run-AIVA-RC7-Preflight.ps1'; if((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'd4e03702cecf41426855700682e10698d0bdb4e60f0b59d12155f354941ebf9e'){throw 'SHA del script incorrecto'}; powershell.exe -NoProfile -ExecutionPolicy Bypass -File $p
```

El script verifica también los SHA del instalador y del bundle. Si termina, el JSON sanitizado se entrega al VPS por Taildrop. Si falla, detené el piloto y compartí sólo el mensaje de error; no instales manualmente.
