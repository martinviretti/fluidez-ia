# Changelog

Todos los cambios notables de **fluidez-ia** se registran acá.
El formato sigue [Keep a Changelog](https://keepachangelog.com/) y el proyecto
apunta a [Versionado Semántico](https://semver.org/).

## [1.0.0] — 2026-06-25

Primer release tagueado de fluidez-ia — fork localizado al **español rioplatense**
de [Claude Insight](https://github.com/Feloguarin/claude-insight).

### Added
- **Detección bilingüe (ES + EN)** de señales de Instrucción e Iteración: los
  prompts en español rioplatense ya no quedan subvaluados como pasaba con el motor
  original, que solo matcheaba regex en inglés.
- **Fix de UTF-8 en Windows**: reconfigura `stdout`/`stderr` a UTF-8 para que el
  resumen no reviente con `UnicodeEncodeError` en consolas cp1252.
- **Instalador robusto**: detecta un Python 3.8+ que *realmente ejecuta* (maneja el
  alias `python3` del Store de Windows) y reescribe el intérprete en `SKILL.md`.
- **Suite de 39 tests** (stdlib puro) y **CI** que corre en cada push a `main` y cada
  pull request, sobre Python 3.8 / 3.10 / 3.12. Nada mergea en rojo.
- **LICENSE** (MIT) reteniendo la atribución al proyecto original, y este changelog.
- Reporte HTML, salida de terminal y CLI completamente en español.

### Fixed
- **El workflow de dos modelos no se resolvía.** `SKILL.md` invocaba la herramienta
  Workflow con `name: fluidez-ia`, pero `workflow.js` seguía declarando
  `meta.name: 'ai-fluency'` (no se localizó en el fork). El Paso 2 no encontraba el
  workflow y la corrida caía al **fallback determinístico en silencio** — el análisis
  con IA (Sonnet explora, Opus evalúa), que es el corazón del producto, nunca corría.
  Ahora el frontmatter, la invocación y `meta.name` coinciden en `fluidez-ia`, con un
  test de regresión (`test_workflow_name_matches_skill_invocation`) que lo blinda.

### Changed
- Branding del motor y rutas de salida a fluidez-ia: el reporte se escribe en
  `reporte_fluidez_ia.html` y el archivo histórico en `~/.claude/fluidez-ia-archive`.

[1.0.0]: https://github.com/martinviretti/fluidez-ia/releases/tag/v1.0.0
