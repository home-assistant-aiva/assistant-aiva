# AGENTS.md — AIVA Collector

Instrucciones específicas para trabajar en `/opt/aiva-collector`. Complementan las reglas globales de Codex; no las repiten.

**Versión:** `1.0.0-rc.1`
**Estado:** candidato para pruebas
**Última verificación:** `2026-09-09`

## Autoridad y contexto

Aplicar este orden de verdad:

1. pedido explícito actual del usuario;
2. código, tests, packaging y workflows reales;
3. este `AGENTS.md`;
4. `/opt/aiva-docs/AIVA_COMERCIAL_MASTER_CONTEXT_CODEX.md`;
5. documentación histórica.

El contexto maestro conserva hitos y RC anteriores. Para versiones, nombres de artefactos, rutas Windows y proceso de release, verificar siempre `pyproject.toml`, `packaging/`, `.github/workflows/` y tests actuales. No hacer coincidir el código con un hito histórico “a ojo”.

## Responsabilidad y límites

El rol definido aquí es el **Agente Collector** y su alcance de escritura es exclusivamente `/opt/aiva-collector`.

AIVA Collector es la capa instalada en Windows del comercio. Descubre y configura fuentes, lee exportaciones de forma segura, mapea y normaliza columnas, valida, resume, conserva estado/cola, reintenta y se comunica autenticadamente con AIVA Backend.

No contiene reglas comerciales canónicas, Decision Readiness, recomendaciones, cálculo final de impacto ni lógica específica de Admin. Esas decisiones pertenecen al Backend. Ante una incompatibilidad, no adaptar silenciosamente el contrato Backend desde Collector: identificar el dueño y coordinar una tarea multidominio explícita.

No tocar AIVA Home, Seguridad, Home Assistant u OpenClaw desde una tarea del Collector salvo integración explícitamente solicitada.

## Acciones prohibidas

- No modificar otros repositorios ni adaptar unilateralmente el contrato Backend sin una tarea multidominio explícita.
- No borrar comercios reales, datos productivos, fuentes del cliente, estado o cola; no usar producción para ejecutar tests.
- No exponer secretos, tokens, credenciales, filas crudas ni rutas sensibles en artefactos, comandos, logs o informes.
- No hacer build, push, tag, dispatch de workflow, publicación, release o deploy sin autorización específica para cada acción.
- No inventar resultados ni validaciones, sobrescribir cambios existentes del usuario o resolver por suposición una decisión que cambiaría materialmente el resultado; en ese caso, detenerse y preguntar.

## Mapa del repositorio

- `aiva_collector/readers.py`: descubrimiento de archivos y lectura CSV/XLSX.
- `aiva_collector/column_mapping.py`: autodetección, confianza y `needs_review`.
- `aiva_collector/normalizer.py`, `validation.py` y `summarizer.py`: formato canónico, calidad y summary.
- `aiva_collector/file_fingerprint.py`: hash físico, hash normalizado y `file_id` contextual.
- `aiva_collector/local_state.py`: SQLite local para archivos, eventos y cola.
- `aiva_collector/offline_queue.py`: payloads pendientes, backoff, reintentos y duplicados.
- `aiva_collector/client.py`: contrato HTTP autenticado con Backend.
- `aiva_collector/discovery.py`: detección y sanitización de candidatos.
- `aiva_collector/desktop_app.py` y `desktop_service.py`: experiencia Desktop y configuración segura.
- `packaging/pyinstaller/`, `packaging/inno/` y `packaging/windows_runtime/`: ejecutables, instalador y tarea programada.
- `scripts/`: build y verificaciones de paquetes/instalador.
- `.github/workflows/`: CI Windows, artefactos y publicación condicional.
- `tests/`: ingesta, mapping, aislamiento, cola, Desktop y packaging.

No hay un mecanismo Docker de producto en este repositorio; no agregarlo como atajo para validar comportamiento Windows.

## Seguridad de datos del comercio

La carpeta externa seleccionada por Desktop es de sólo lectura. `desktop_service.py` configura `source_read_only=true`, desactiva movimientos de procesados/errores y conserva originales.

- Nunca escribir, renombrar, mover, borrar o bloquear de forma exclusiva archivos de la fuente externa ni modificar bases del comercio.
- Distinguir esa fuente externa de los inbox/directorios gestionados por flujos manuales heredados, donde la configuración actual aún puede archivar copias. No ampliar ese comportamiento a una carpeta origen elegida por el cliente.
- No enviar archivos CSV/XLSX, tickets, bases ni filas crudas. Enviar sólo summaries y metadata mínima admitida por el contrato.
- No incluir contenido comercial, rutas completas sensibles, tokens o credenciales en logs, state, cola, diagnóstico, manifests, ZIPs o errores.
- Tokens no van en argumentos ni en JSON operativo nuevo. Preservar el almacenamiento protegido por DPAPI y las rutas seguras de migración/configuración existentes.
- Discovery no modifica ni copia candidatos y debe sanitizar paths/metadata antes de reportar.

## Formatos y mapping reales

La ingesta actual admite `.csv` y `.xlsx`; no afirmar soporte de `.xls`, bases o APIs propietarias sólo porque Discovery pueda detectarlas como candidatas.

Al modificar lectura o mapping, cubrir:

- CSV con `,` y `;`, autodetección/fallback de delimitador, UTF-8 con BOM y encabezado preservado;
- filas vacías y archivo con sólo encabezado;
- XLSX con encabezado desplazado dentro de las primeras filas inspeccionadas;
- selección de hoja/encabezado por compatibilidad semántica o `xlsx_sheet` configurada;
- mapping explícito válido, autodetección, `auto_approved`, `needs_review` y fallo;
- columnas requeridas y opcionales, duplicados de asignación y valores inválidos.

`read_xlsx` selecciona una hoja candidata; no combina todas las hojas. Cambiar esa semántica exige contrato, estrategia de deduplicación y tests explícitos. Un mapping ambiguo debe quedar para revisión y poder reprocesarse luego de aprobar el mapping; no forzar una confianza artificial.

## Tenant, idempotencia y cola

Toda configuración y memoria local pertenece al contexto de `commerce_id`, `collector_id` y destino Backend.

- `file_id` y deduplicación local incorporan tenant/destino y hash; el mismo archivo de otra activación debe seguir siendo elegible.
- La idempotency key del summary usa comercio, Collector y hash normalizado; si no existe, usa período y hash estable del summary. No cambiarla sin revisar Backend, segunda sincronización y payloads ya en cola.
- `processed_files` mantiene hash físico, hash normalizado, status y lease; recuperar processing vencido, pero omitir un lease activo y una ejecución concurrente.
- Un archivo ya `sent`, `duplicate`, `pending_send` o `retrying` en el mismo contexto no se reprocesa sin causa.
- La cola persiste el payload normalizado sin claves sensibles, valida que la idempotency key coincida, trata duplicados como terminales y reintenta sólo fallos temporales con el backoff configurado.
- No perder ni reescribir payloads pendientes durante upgrades. Una segunda sincronización debe ser idempotente y explicar encontrados, elegibles, omitidos, procesados, duplicados, rechazados, revisión y pendientes.
- Cambios de esquema SQLite local deben ser aditivos/idempotentes y probar upgrade desde el esquema anterior relevante sin perder filas.

## Contrato Backend

`client.py` usa `Authorization: Bearer <collector_token>`, `X-AIVA-Collector-Id` y `X-Idempotency-Key` para summaries. El payload y las credenciales deben coincidir con el comercio/Collector activado.

- Preservar rutas, headers, códigos 200/201/409 y clasificación segura de 4xx frente a errores temporales.
- No usar el secreto administrativo interno desde una PC cliente.
- No registrar headers de autorización ni respuestas crudas. Mantener mensajes accionables para códigos de activación inválidos, expirados, usados o revocados.
- Para una modificación de contrato, ejecutar tests en Collector y los tests de endpoints/auth/ingesta correspondientes en Backend cuando la tarea incluya ambos repositorios.

## Coordinación entre repositorios

Antes de cambiar payloads, headers, estados o idempotencia, identificar consumidores y dueño del contrato, revisar Backend y Admin afectados y definir compatibilidad y orden de implementación. El **Arquitecto/Coordinador AIVA** interviene bajo demanda en tareas multidominio y no reemplaza a este agente. El **Auditor independiente QA/Release** revisa después de la implementación, no desarrolla el mismo cambio y no publica ni despliega. No crear un rol separado de Release.

## Windows, instalación y upgrade

El producto Desktop separa GUI, CLI técnica y proceso background. El instalador Inno requiere privilegios de administrador, instala bajo Program Files, conserva datos mutables en `%ProgramData%\AIVA\Collector` y registra una tarea programada que usa el ejecutable background sin token en argumentos.

Tratar como regresiones críticas:

- instalación limpia y self-check de los tres ejecutables;
- upgrade conservando activación, configuración, DPAPI token, state, cola, mappings y logs;
- tarea programada, ejecución silenciosa, permisos y single-run lock;
- desinstalación que quite sólo tareas conocidas y preserve ProgramData por defecto;
- reinstalación/rollback desde backup operativo;
- diagnóstico sin archivos fuente ni secretos;
- SmartScreen/Defender y prueba física en Windows, que no quedan validados sólo por tests Linux.

No hardcodear una ruta manual histórica cuando `config.py`/Desktop define la ubicación actual. No borrar ProgramData, estado o cola para “arreglar” una actualización.

## Tests, packaging y releases

El proyecto usa Python `>=3.10`, dependencias de `pyproject.toml` y pytest:

```bash
.venv/bin/python -m pytest tests/test_readers.py tests/test_column_mapping.py tests/test_rc2_hotfix.py
.venv/bin/python -m pytest tests/test_offline_queue.py tests/test_collector_deduplication.py tests/test_local_state.py
.venv/bin/python -m pytest tests/test_windows_exe_packaging.py tests/test_windows_package.py tests/test_windows_assets.py
.venv/bin/python -m pytest
```

Si `.venv` no existe, crear un entorno aislado e instalar `-e ".[dev]"`; no instalar dependencias globalmente. Usar tests focalizados primero y suite completa para cambios de ingesta, estado, auth, Desktop o packaging. Para cambios sólo documentales no hace falta ejecutar la suite.

El build Windows usa PyInstaller, Inno Setup, verificadores de `scripts/` y workflows de GitHub Actions. Antes de ejecutar uno, leer su trigger y condición de publicación:

- `build-collector-windows-release.yml` es el único workflow autorizado para generar el instalador y publicar una pre-release. Se ejecuta sólo mediante `workflow_dispatch`, siempre sube artifacts y sólo publica con `publish_release=true`.
- No agregar un segundo workflow de instalador o publicación. Cualquier compatibilidad futura debe reutilizar el workflow oficial sin duplicar packaging, permisos de escritura ni lógica de release.

Build local, push, dispatch de workflow, tag y GitHub Release son acciones distintas. No crear tags, disparar workflows, publicar ni sobrescribir assets sin autorización explícita. Verificar nombre/version contra `pyproject.toml` y packaging, manifests, SHA256 y ciclo limpio/upgrade/uninstall antes de considerar un instalador validado. Conservar artefactos anteriores y documentar cualquier validación física pendiente.

## Definición de terminado e informe obligatorio

Una intervención termina sólo cuando el alcance solicitado está resuelto, el diff fue revisado, contratos y upgrades fueron considerados y las verificaciones aplicables se ejecutaron o quedaron declaradas como pendientes. No afirmar éxito ni que un instalador está validado si falta una validación crítica o la prueba física en Windows requerida.

Informar por separado y sin inferencias qué fue **revisado**, **probado**, **compilado**, **desplegado** y **probado físicamente**; tests Linux o CI no equivalen a prueba física Windows. El cierre debe incluir objetivo, rama/HEAD y estado inicial, archivos cambiados, formatos/contextos/contratos, tests con resultados, build y validación Windows/packaging, artefactos y checksums, riesgos, pendientes, reversión, commit y confirmación separada de push, workflow, tag, release y deploy.
