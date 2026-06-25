# fluidez-ia

[![tests](https://github.com/martinviretti/fluidez-ia/actions/workflows/tests.yml/badge.svg)](https://github.com/martinviretti/fluidez-ia/actions/workflows/tests.yml)

Versión **en español rioplatense** del motor de *AI fluency* (análisis de cómo colaborás
con Claude Code). Fork localizado de [Feloguarin/claude-insight](https://github.com/Feloguarin/claude-insight)
— el original mide señales con regex en inglés y subvalúa a quien prompea en español.

## ⚡ Instalación (un comando)

```bash
curl -fsSL https://raw.githubusercontent.com/martinviretti/fluidez-ia/main/install.sh | bash
```

Detecta tu Python (3.8+) automáticamente y deja la skill en `~/.claude/skills/fluidez-ia/`.
Después, abrí Claude Code en cualquier carpeta y corré **`/fluidez-ia`**.

> **¿Preferís mirar antes de correr?** (recomendado con cualquier `curl | bash`)
> ```bash
> git clone https://github.com/martinviretti/fluidez-ia
> cat fluidez-ia/install.sh   # revisás el script
> bash fluidez-ia/install.sh  # y lo corrés
> ```

Requiere **Python 3.8+** y Claude Code.

## Qué hace

Lee tus transcripts locales de Claude Code (`~/.claude/projects/**/*.jsonl`), los limpia de
ruido (resultados de tools, inyecciones, pastes), y computa un **puntaje de fluidez 0–100**,
un **arquetipo de builder** y un mapa de **5 dimensiones**:

| Dimensión | Peso | Qué mide | ¿Depende del idioma? |
|---|---|---|---|
| Instrucción (Direction) | 0.24 | Qué tan bien briefeás (objetivo + archivo/restricción/intención) | **Sí** → bilingüe |
| Verificación | 0.22 | Si se corren tests/build/lint tras editar | No (mira comandos) |
| Contexto | 0.22 | Si se lee el archivo antes de editarlo | No (mira tool calls) |
| Iteración | 0.18 | Correcciones precisas vs vagas | **Sí** → bilingüe |
| Herramientas (Toolcraft) | 0.14 | Variedad de tools + delegación | No |

Toda la salida (terminal, reporte HTML, CLI) está en español.

## Documentación

Presentación que explica el sistema de punta a punta — metodología, fórmulas de
cada dimensión, umbrales de saturación, bandas, arquetipos, el framework 4D y los
parámetros del motor:

- **[`presentacion-fluidez-ia.html`](presentacion-fluidez-ia.html)** — presentación
  (con índice navegable y descarga a PDF).

> GitHub no renderiza HTML inline; descargá el archivo y abrilo en el navegador,
> o usá el sitio de GitHub Pages si está activo.

## Qué cambia respecto del original

1. **Detección bilingüe (ES+EN)** en los 5 detectores de señales (constraint, intent, action,
   corrección, elogio, verificación). Mantiene el inglés y suma el español, así no pierde los
   términos técnicos en inglés que se usan mezclados.
2. **Fix de UTF-8 para Windows** embebido en `insight.py` — no rompe por emojis/acentos sin
   necesidad de `PYTHONUTF8`.
3. **Todo el texto visible traducido**: bandas, arquetipos, contenido docente, reporte HTML,
   framework y prompts del workflow Sonnet/Opus.
4. **Bugfix**: las rutas de consejo por arquetipo (`ARCH_PATHS`) no matcheaban en el original
   y caían siempre al texto genérico; acá están alineadas.
5. **No archiva por default** (la skill corre con `--no-archive`) para no duplicar cientos de MB.

## Uso

Como skill de Claude Code (ya instalada en `~/.claude/skills/fluidez-ia/`):

```
/fluidez-ia
```

O directo por CLI:

```bash
# todo tu uso de Claude Code
python3 insight.py

# un proyecto puntual
python3 insight.py "C:/ruta/al/proyecto-o-sesion.jsonl"

# acumular historia más allá de 30 días (copia transcripts al archive)
python3 insight.py            # sin --no-archive

# opciones útiles
python3 insight.py --no-open  # no abrir el navegador
python3 insight.py --json     # métricas crudas a stdout
```

Requiere **Python 3.8+**. El reporte se escribe en `~/.claude/fluidez-ia/reporte_fluidez_ia.html`.

## Estructura

```
fluidez-ia/
├── insight.py                       # motor determinístico (medición + render HTML)
├── SKILL.md                         # definición de la skill /fluidez-ia
├── workflow.js                      # orquestación Sonnet 4.6 + Opus 4.8 (solo si hay capability Workflow)
├── install.sh                       # instalador (detecta Python, copia la skill)
├── presentacion-fluidez-ia.html     # presentación (metodología + fórmulas)
├── reference/
│   └── framework-fluidez-ia.md      # framework 4D que lee Opus para el skill map
└── tests/                           # 39 tests (stdlib) — corren en CI sobre 3.8/3.10/3.12
```

La skill instalada vive en `~/.claude/skills/fluidez-ia/` (+ `~/.claude/workflows/fluidez-ia.js`).
Esta carpeta es la **fuente de verdad**: editás acá y copiás a la skill instalada.

## Notas

- El stage de IA (Sonnet explora + Opus escribe el skill map con reescrituras de tus prompts)
  solo corre donde la capability **Workflow** de Claude Code está disponible. Si no, el reporte
  determinístico es completo por sí solo.
- Los puntajes miden comportamiento observable, no intención. Con poca data las dimensiones se
  hedgean hacia 50 y se marcan como "pocos datos".

## Desarrollo

La suite es stdlib puro — sin dependencias, sin paso de install:

```bash
python -m unittest discover -s tests -v
```

CI corre estos 39 tests en cada push a `main` y cada PR, sobre Python 3.8 / 3.10 / 3.12.
Si tocás señales o scoring, sumá un test; si tocás strings de salida (terminal o HTML),
actualizá las aserciones en `tests/`.

## Licencia

MIT — ver [`LICENSE`](LICENSE). fluidez-ia es un fork localizado de
[Claude Insight](https://github.com/Feloguarin/claude-insight) (también MIT); se retiene
la atribución al autor original.
