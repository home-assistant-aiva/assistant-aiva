# Release checklist

## Antes de publicar

1. Confirmar que `custom_components/aiva/manifest.json` tenga la versión correcta.
2. Confirmar que `documentation` e `issue_tracker` apunten al repositorio GitHub real.
3. Confirmar que `codeowners` y `CODEOWNERS` apunten al usuario u organización GitHub real.
4. Actualizar `CHANGELOG.md`.
5. Revisar `README.md` y `docs/README.en.md` si hubo cambios funcionales.
6. Verificar que `hacs.json` siga reflejando la estructura real del repo.
7. Ejecutar y revisar GitHub Actions de validación:
   - Tests
   - HACS validation
   - Hassfest validation

## Publicación de nueva versión

1. Actualizar `version` en `custom_components/aiva/manifest.json`.
2. Actualizar `CHANGELOG.md`.
3. Hacer commit de los cambios.
4. Crear un tag con formato `vX.Y.Z`.
5. Subir commit y tag a GitHub.
6. Esperar que el workflow `Release` cree la GitHub Release.
7. Verificar que HACS detecte la nueva versión.

## Comandos sugeridos

```bash
git add .
git commit -m "Release v0.2.9"
git tag v0.2.9
git push origin main
git push origin v0.2.9
```

## Después de publicar

1. Confirmar que la release existe en GitHub.
2. Confirmar que HACS muestra la actualización.
3. Probar la actualización en una instancia de Home Assistant.
