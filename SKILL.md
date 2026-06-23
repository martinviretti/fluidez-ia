---
name: fluidez-ia
description: Analiza cómo colaborás con Claude Code y produce un mapa de "fluidez con IA" en español — puntaje general, arquetipo, las cuatro competencias (Delegación, Instrucción/Descripción, Discernimiento, Diligencia), las cinco dimensiones medidas, y dirección clara de qué/dónde/cómo mejorar. Usala cuando el usuario pida analizar su uso de Claude Code, su fluidez con IA, su perfil de builder, su estilo de prompting, o "cómo uso Claude / la IA", o cuando corra /fluidez-ia. Versión localizada al español (detección bilingüe de señales) del motor de AI fluency.
argument-hint: "[RUTA | --no-open]"
allowed-tools: Bash(python3 *), Read, Write, Workflow
---

# Análisis de Fluidez con IA — un comando, corrida completa (ES)

Producís un **mapa de fluidez con IA** confiable para este desarrollador a partir de sus
transcripts reales de Claude Code. Una corrida, tres partes:

1. **Medir (determinístico).** `insight.py` parsea los transcripts, los de-contamina y
   limpia, y computa los números — basados en tasas, con hedging por confianza, respaldados
   por un archivo persistente para ver **más allá de la ventana de 30 días** de Claude Code.
   La detección de señales es **bilingüe** (español + inglés), así no penaliza prompts en
   español rioplatense.
2. **Explorar (Sonnet 4.6).** Exploradores en paralelo leen la evidencia, uno por competencia.
3. **Analizar (Opus 4.8).** Un evaluador senior escribe el mapa, **anclado en el framework
   de fluidez incluido**, y después verifica que esté anclado en la evidencia.

La skill es autocontenida: el motor y el framework viven al lado de este archivo en
`~/.claude/skills/fluidez-ia/`, y todos los archivos de trabajo caen en `~/.claude/fluidez-ia/`.

## Paso 1 — Medir + emitir evidencia

Estos archivos de trabajo viven en rutas fijas y reutilizadas, así que primero borrá
cualquier sobrante de una corrida anterior (o de otra persona en una máquina compartida):

```bash
rm -f ~/.claude/fluidez-ia/evidence.json ~/.claude/fluidez-ia/analysis.json
```

Después medí (usá `--quiet` para que el puntaje NO se muestre todavía — esta es una corrida
que debe terminar en un único reporte final, no un puntaje ahora y un reporte después).
El fix de UTF-8 ya está dentro de `insight.py`, así que `python` directo no rompe en Windows:

```bash
python3 ~/.claude/skills/fluidez-ia/insight.py --evidence ~/.claude/fluidez-ia/evidence.json --no-open --quiet --no-archive -o ~/.claude/fluidez-ia/reporte_fluidez_ia.html $ARGUMENTS
```

Esto computa el bundle de evidencia de-contaminado y escribe un reporte determinístico de
fallback. **No le reportes el puntaje, arquetipo ni ningún resultado al usuario todavía** —
seguí a los Pasos 2–3 y presentá solo el reporte final personalizado por IA. Si reporta que
no hay transcripts, decile al usuario que pase su directorio de transcripts como `$ARGUMENTS`
(default `~/.claude/projects`). El bundle lleva un `meta.run_fingerprint` que ata cualquier
análisis construido a partir de él a esta corrida exacta.

## Paso 2 — Correr el workflow de análisis de dos modelos

Imprimí las rutas absolutas que el workflow necesita (las lee con su propia herramienta Read):

```bash
python3 -c "import os; print(os.path.expanduser('~/.claude/fluidez-ia/evidence.json')); print(os.path.expanduser('~/.claude/skills/fluidez-ia/reference/framework-fluidez-ia.md'))"
```

Después llamá a la herramienta **Workflow** con:
- `name`: `fluidez-ia`
- `args`: `{ "evidence": "<primera línea de arriba>", "framework": "<segunda línea de arriba>" }`

El workflow devuelve el análisis como un objeto JSON (overall_read, skill_map de las cuatro
competencias, top_growth, strengths). **Sonnet 4.6** explora, **Opus 4.8** analiza + verifica.

> Si la capability **Workflow** no está disponible en este entorno, saltá los Pasos 2–3: el
> reporte determinístico del Paso 1 es completo por sí solo. Re-corré el Paso 1 sin `--quiet`
> (o leé `~/.claude/fluidez-ia/evidence.json`) para narrar los números, y abrí el reporte.

## Paso 3 — Renderizar el reporte final

Solo hacé esto si el Paso 2 efectivamente devolvió un análisis. Escribí el JSON devuelto a
`~/.claude/fluidez-ia/analysis.json`, después mergealo — pasando el bundle de evidencia del
que se construyó para que el motor confirme que el análisis pertenece a esta corrida exacta:

```bash
python3 ~/.claude/skills/fluidez-ia/insight.py --analysis ~/.claude/fluidez-ia/analysis.json --analysis-evidence ~/.claude/fluidez-ia/evidence.json --no-archive -o ~/.claude/fluidez-ia/reporte_fluidez_ia.html $ARGUMENTS
```

Esta corrida del Paso 3 es la PRIMERA vez que se imprime el puntaje (el Paso 1 fue `--quiet`).
El motor fingerprintea los datos de esta corrida y los compara con el `run_fingerprint` del
bundle; si no coinciden (un análisis viejo o ajeno), imprime una nota y renderiza el reporte
determinístico en su lugar. Señalá al usuario `~/.claude/fluidez-ia/reporte_fluidez_ia.html`.

## Paso 4 — Narrar (no re-derivar)

Recién ahora, con el reporte final ya hecho, dale una lectura corta y alentadora en el chat:
el **puntaje + banda + arquetipo** en una oración, la **palanca de mejora de mayor impacto**
anclada en uno de sus prompts reales, y su **competencia más fuerte** como base. Un párrafo o
dos; el reporte tiene la profundidad.

## Notas

- Los transcripts originales nunca se modifican. Por **default esta skill NO archiva**
  (corre con `--no-archive`) para no duplicar cientos de MB. Si querés acumular historia
  más allá de la limpieza de 30 días de Claude Code, sacá `--no-archive` de los comandos
  de arriba: se copiarán a `~/.claude/fluidez-ia-archive`.
- Los puntajes miden comportamiento observable, no intención; las señales finas se marcan
  como "poca data" y se hedgean — no sobre-afirmes sobre esas.
- La detección de señales es bilingüe (ES+EN): prompts en español rioplatense puntúan justo
  en Instrucción e Iteración (en el motor original, en inglés, quedaban subvaluados).
