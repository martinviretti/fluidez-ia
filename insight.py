#!/usr/bin/env python3
"""
Fluidez con IA — analizador de fluidez con IA en un comando (fork ES de Claude Insight).

    python3 insight.py

Reads your local Claude Code transcripts (~/.claude/projects/**/*.jsonl),
estimates how skillfully you drive an AI coding agent, and writes a single
self-contained HTML report (./reporte_fluidez_ia.html) that opens in your browser.

Design principles (see README "Methodology"):
  * It measures SKILL, not activity. Every score input is a per-prompt or
    per-opportunity RATE pushed through a saturating curve, so using the agent
    MORE can never raise your score — only using it BETTER can.
  * It only looks at YOUR real typed prompts and Claude's real tool actions.
    Tool-results, subagent turns, slash-command stubs, injected system text and
    pasted walls of text are filtered out before anything is scored.
  * Every number is auditable: baselines are recomputed from your corpus at
    runtime, formulas are documented, and thin signals are flagged "low data"
    and pulled toward a neutral 50 instead of faking confidence.

Pure Python standard library — no pip, no Ollama, no API key. One command runs the
whole pass: de-contaminate and scrub your transcripts, score them, and (as
`/fluidez-ia` in Claude Code) write a Sonnet+Opus skill map grounded in the AI
Fluency framework on top. The only thing it writes is
the HTML report and a local copy of your transcripts in an archive
(~/.claude/fluidez-ia-archive) so history survives Claude Code's 30-day cleanup —
pass --no-archive to skip that and read your transcripts without copying them.
"""

import argparse
import glob
import hashlib
import html
import json
import math
import os
import re
import shutil
import statistics
import sys
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime

# Windows: la consola por defecto usa cp1252 y revienta con UnicodeEncodeError al
# imprimir emojis/acentos. Forzamos UTF-8 en stdout/stderr para que el resumen no
# falle, sin depender de PYTHONUTF8/PYTHONIOENCODING externos.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# --------------------------------------------------------------------------- #
# Constants & tunables (documented; shown in the report's methodology appendix)
# --------------------------------------------------------------------------- #

DEFAULT_DIRS = ["~/.claude/projects", "~/.claude/sessions"]

# Claude Code deletes transcripts older than its `cleanupPeriodDays` setting (default 30),
# so by default only ~30 days of history is ever on disk. We mirror each run's transcripts
# into this persistent archive so history accumulates indefinitely and survives the cleanup.
# Keep this on a PRIVATE, per-person path. A single archive folder shared between different
# people or computers (e.g. a synced team Dropbox) merges everyone's transcripts into one
# analysis — so each person must point --archive at their own location, not a shared one.
DEFAULT_ARCHIVE_DIR = "~/.claude/fluidez-ia-archive"

GAP_CAP_SECONDS = 300          # idle gaps longer than this are NOT counted as active time
MAX_HUMAN_PROMPT_CHARS = 6000  # anything longer is treated as a paste/injection, not a typed prompt
PROVISIONAL_MIN_PROMPTS = 30   # below this the headline score is shown as a hedged range

EDIT_TOOLS = {"edit", "write", "multiedit", "notebookedit"}
READ_TOOLS = {"read", "grep", "glob"}

# Text that marks a "user"-role record as injected/system rather than typed by the human.
INJECTION_MARKERS = (
    "<task-notification>", "<command-name>", "<command-message>", "<command-args>",
    "<local-command-caveat>", "<local-command-stdout>", "<system-reminder>",
    "<bash-input>", "<bash-stdout>", "caveat: the messages below",
    "[request interrupted", "base directory for this skill", "<user-prompt-submit-hook>",
    "<user-memory-input>", "this session is being continued",
)

# Subagent system prompts get stored as plain user-role text with no other marker.
# They almost always open with "You are <role>…". This catches the back-door inflation.
_INJECTED_HEAD = re.compile(
    r"^\s*(you are\b|sos un\b|sos una\b|eres un\b|eres una\b|act[uú]as como\b|"
    r"actu[aá]s como\b|<[a-z][\w-]*>|base directory for this skill)", re.I
)

# Broad, project-extensible verification matcher (matched against real Bash commands).
VERIFY_RE = re.compile(
    r"\b("
    r"pytest|unittest|jest|vitest|mocha|go test|cargo (test|build|check)|"
    r"npm (run )?(test|build|lint)|yarn (test|build|lint)|pnpm (test|build|lint)|"
    r"ruff|eslint|flake8|mypy|tsc\b|make (test|lint|build|check)|playwright|"
    r"python\d? -m \w|\.venv/bin/python|lsof -ti|curl .*(localhost|127\.0\.0\.1)|"
    r"docker compose|docker-compose|pre-commit|"
    r"py -m pytest|py -m unittest|invoke-pester|pester"  # variantes Windows/PowerShell
    r")",
    re.I,
)
# Clean-teardown of a live system (small bonus, folded into Verification).
TEARDOWN_RE = re.compile(r"(lsof -ti.*kill|pkill|kill -9|docker compose down|docker-compose down)", re.I)

# Direction (prompt-quality) cues.
ARTIFACT_RE = re.compile(
    r"([\w./\-]+\.(py|js|ts|tsx|jsx|html|css|md|json|sh|ya?ml|toml|rs|go|java|cpp|c|rb|sql))"
    r"|((?:/[\w.\-]+){2,})"        # multi-segment paths (not bare /word or </tag>)
    r"|(`[^`]+`)"                  # inline code / quoted token
    r"|(\b\w+\(\))",               # function() reference
    re.I,
)
CONSTRAINT_CUE = re.compile(
    r"\b(only|must|should|shouldn't|don't|do not|never|always|keep|ensure|instead of|"
    r"at most|at least|exactly|without|except|make sure|no more than|leave .* as is|"
    # --- español ---
    r"solo|sólo|solamente|únicamente|unicamente|debe|deb[eé]s|deber[ií]a|ten[eé]s que|"
    r"hay que|nunca|siempre|mantené|mantene|manten[eé]|asegur[aá]|asegurate|asegúrate|"
    r"en vez de|en lugar de|como máximo|como maximo|al menos|por lo menos|exactamente|"
    r"sin |excepto|salvo|no más de|no mas de|no toques|no rompas|no modifiques|"
    r"no cambies|dej[aá] .* como est[aá]|que no )\b", re.I
)
INTENT_CUE = re.compile(
    r"\b(so that|because|the goal is|in order to|for the demo|for my|for the|so i can|so we can|"
    r"so it|i need|i want .* so|"
    # --- español ---
    r"para que|porque|el objetivo es|la idea es|así |asi |para poder|para el|para la|"
    r"para mi|para mí|necesito|de modo que|de manera que|con el fin de|a fin de|"
    r"quiero .* para|me sirve para|así puedo|asi puedo)\b", re.I
)
ACTION_VERB = re.compile(
    r"\b(add|create|build|make|implement|write|fix|change|update|refactor|remove|delete|run|"
    r"generate|set up|setup|install|deploy|edit|rename|move|clean|stitch|speed up|merge|split|"
    # --- español (imperativo voseo/tuteo + infinitivo) ---
    r"agreg[aá]|agregar|cre[aá]|crear|arm[aá]|armar|hac[eé]|hacer|implement[aá]|implementar|"
    r"escrib[ií]|escribir|arregl[aá]|arreglar|corregí|corrige|corregir|cambi[aá]|cambiar|"
    r"actualiz[aá]|actualizar|refactoriz[aá]|refactorizar|elimin[aá]|eliminar|borr[aá]|borrar|"
    r"sac[aá]|sacar|quit[aá]|quitar|corr[eé]|correr|ejecut[aá]|ejecutar|gener[aá]|generar|"
    r"configur[aá]|configurar|instal[aá]|instalar|despleg[aá]|desplegar|edit[aá]|editar|"
    r"renombr[aá]|renombrar|mov[eé]|mover|limpi[aá]|limpiar|un[ií]|unir|separ[aá]|separar|"
    r"divid[ií]|dividir|acelerar|optimiz[aá]|optimizar|migr[aá]|migrar|valid[aá]|validar)\b", re.I
)

# Iteration cues.
CORRECTION_CUE = re.compile(
    r"\b(no|nope|wrong|not quite|that's not|thats not|actually|instead|revert|undo|redo|try again|"
    r"too (aggressive|agressive|much|many|slow|fast|big|small)|still (broken|failing|wrong|not)|"
    r"doesn't work|does not work|not working|unteligible|unteliggeble|"
    # --- español ---
    r"nop|mal|incorrecto|eso no|no es eso|no era|en realidad|en vez|en lugar|"
    r"revert[ií]|revierte|deshac[eé]|deshace|de nuevo|otra vez|prob[aá] de nuevo|"
    r"demasiado (agresivo|lento|r[aá]pido|grande|chico|peque[ñn]o)|"
    r"sigue (roto|fallando|mal|sin)|todav[ií]a (no|falla|est[aá])|no funciona|"
    r"no anda|no sirve|no va|est[aá] mal|esto no)\b", re.I
)
PRAISE_CUE = re.compile(
    r"\b(great|perfect|love it|nice|awesome|excellent|beautiful|exactly|"
    r"genial|perfecto|me encanta|buen[ií]simo|b[aá]rbaro|excelente|hermoso|exacto|"
    r"joya|de diez|as[ií] est[aá] bien|impecable|listo|dale)\b", re.I)
CORRECTION_RATE_CEILING = 0.35   # a "high" correction rate; lower is better

# Delegation / planning tool signals.
DELEGATION_TOOLS = {"agent", "task", "workflow", "exitplanmode", "enterplanmode"}

# Dimension weights (sum to 1.0).
WEIGHTS = {
    "Direction": 0.24,
    "Verification": 0.22,
    "Context": 0.22,
    "Iteration": 0.18,
    "Toolcraft": 0.14,
}
# Opportunity-count targets for per-dimension confidence shrinkage.
TARGET_N = {"Direction": 60, "Verification": 15, "Context": 25, "Iteration": 12, "Toolcraft": 40}

# Etiquetas visibles para el usuario. La clave interna "Direction" se muestra como
# "Instrucción" (mide qué tan bien briefeás), distinta del arquetipo de delegación.
DISPLAY_NAMES = {"Direction": "Instrucción", "Verification": "Verificación",
                 "Context": "Contexto", "Iteration": "Iteración", "Toolcraft": "Herramientas"}

def disp(name):
    return DISPLAY_NAMES.get(name, name)

# Contenido docente de cada competencia (cálido, en lenguaje llano, con ejemplos antes/después
# y una práctica). Hace que el reporte explique qué mejorar y exactamente cómo.
SKILL_TEACH = {
    "Direction": {
        "what_it_is": "Decirle al agente qué querés y darle algo a lo que apuntar: un objetivo más un archivo, una restricción, o una forma de saber que funcionó.",
        "why_it_matters": "Cuando tu objetivo y tus límites están claros desde el arranque, el agente lo hace bien a la primera en vez de adivinar y arrastrarte a rondas de arreglos.",
        "how_to_improve": "Antes de apretar enter, sumale un ancla a tu objetivo: el archivo a tocar, una regla que no debe romper, o una línea de 'listo cuando…'. Con una línea alcanza.",
        "examples": [
            {"before": "arreglá el bug de login", "after": "Los usuarios quedan deslogueados después de una contraseña correcta en Safari. El chequeo vive en src/auth/session.ts. Arreglalo para que un login válido setee la cookie de sesión, y mantené los tests actuales en verde."},
            {"before": "agregá caché a la API", "after": "Cachéa las respuestas de GET /products en api/products.py por 60s para aliviar la DB en lecturas repetidas. No cachées requests autenticados, y agregá un test de que una segunda llamada dentro de los 60s no toca la DB."},
        ],
        "practice": "Antes de mandar un prompt, sumale un ancla a tu objetivo: un path de archivo, una restricción, o una línea de 'listo cuando…'.",
        "good_looks_like": "Cada pedido dice qué querés más dónde trabajar o cómo se juzga el éxito, así el agente actúa en vez de adivinar.",
    },
    "Verification": {
        "what_it_is": "Que el agente pruebe su propio trabajo — corra los tests, el build, el lint, o levante la app — antes de decirte que está listo.",
        "why_it_matters": "El código que parece correcto pero nunca se corrió es donde se esconden la mayoría de los bugs de IA; chequearlo convierte el «probablemente anda» en «lo vi andar».",
        "how_to_improve": "En el mismo prompt que pide el cambio, nombrá el comando exacto que lo prueba (un test, build, lint o curl) y decile al agente que lo corra y te muestre la salida antes de frenar.",
        "examples": [
            {"before": "Arreglá el off-by-one en el helper de paginación.", "after": "Arreglá el off-by-one en el helper de paginación, después corré `pytest tests/test_pagination.py -x` y pegá la salida. No lo des por arreglado hasta que ese test pase."},
            {"before": "Agregá un endpoint /health al server FastAPI.", "after": "Agregá un endpoint /health al server FastAPI. Levantalo en el puerto 8000, hacé curl a `localhost:8000/health` y mostrame la respuesta. Corré `ruff check` también y confirmá que está limpio antes de terminar."},
        ],
        "practice": "Antes de aceptar cualquier cambio, preguntá: «¿Cómo verificaste esto? Correlo y mostrame la salida.»",
        "good_looks_like": "Cada cambio termina con una prueba — un test que pasa, un build verde, una respuesta real — pegada de vuelta, no solo una afirmación.",
    },
    "Context": {
        "what_it_is": "Apuntar al agente al código real — un archivo, una función, una zona de líneas — y que lo lea antes de cambiar nada.",
        "why_it_matters": "Cuando el agente ve el código actual real primero, sus ediciones encajan con lo que realmente hay en vez de una suposición, así aplican limpio a la primera.",
        "how_to_improve": "Antes de cualquier edición, nombrá el archivo exacto (y la función o zona si podés) y decile al agente que lo lea primero. Que mire antes de saltar.",
        "examples": [
            {"before": "Agregá lógica de reintento al cliente de API.", "after": "Leé src/api/client.ts primero, después agregá retry-con-backoff al método request(). Mostrame el cambio antes de aplicarlo."},
            {"before": "Arreglá el bug de timezone en el formateador de fechas.", "after": "Abrí src/utils/date.ts y buscá formatDate(). Leé cómo maneja timezones ahora, después arreglá el off-by-one para que las entradas UTC se rendericen en la zona local del usuario."},
        ],
        "practice": "Arrancá tu próximo pedido de edición con «Leé <archivo> primero, después…» para que el agente se ancle antes de tocar nada.",
        "good_looks_like": "Cada edición cae sobre código que el agente recién leyó, así los diffs aplican limpio sin romper lo de alrededor.",
    },
    "Iteration": {
        "what_it_is": "Cuando el agente agarra para el lado equivocado, encarrilarlo con una corrección precisa — nombrando qué se rompió y la regla a seguir — en vez de solo «no» o «probá de nuevo».",
        "why_it_matters": "Una corrección precisa clava el arreglo en una ronda; un «no» vago hace que el agente vuelva a adivinar, y quemás turnos mientras el código se desvía más.",
        "how_to_improve": "Cuando un resultado está mal, decí tres cosas en un mensaje: el síntoma que viste, la regla que rompió, y qué hacer en su lugar. Después dejalo correr.",
        "examples": [
            {"before": "no, eso no está bien, probá de nuevo", "after": "El loop de reintento captura la excepción pero nunca la re-lanza después del último intento, así que las fallas parecen éxitos. Re-lanzá el error original cuando se agoten los reintentos, y mantené el backoff existente."},
            {"before": "esto está mal, arreglá el test", "after": "El test pasa porque mockeaste la función bajo prueba en vez de la llamada de red. No mockees get_user — mockeá requests.get adentro, y verificá que se llamó con la URL real."},
        ],
        "practice": "Antes de mandar una corrección, fijate que nombre el síntoma y la regla. Si solo dice «no», agregale la mitad que falta.",
        "good_looks_like": "Una corrección filosa — síntoma, regla y el arreglo — y el agente lo clava al siguiente intento.",
    },
    "Toolcraft": {
        "what_it_is": "Dejar que el agente use la herramienta correcta para cada paso — buscar en el código, correr comandos, levantar la app, trabajar en background — en vez de forzar todo por el chat.",
        "why_it_matters": "El agente trabaja más rápido y confiable cuando busca y corre cosas de verdad, en vez de razonar sobre el código de memoria.",
        "how_to_improve": "Decile al agente qué acción tomar primero — buscar en el codebase, correr la suite, levantar el server — para que junte hechos y chequee su trabajo con la herramienta hecha para cada paso.",
        "examples": [
            {"before": "¿Cómo funciona el login en esta app?", "after": "Buscá en el codebase el flujo de login (grep de auth, session, login), leé los archivos que encuentres, después explicame cómo va un request desde el submit del form hasta una sesión logueada."},
            {"before": "Agregá un retry al cliente de API, y asegurate de que los tests sigan pasando.", "after": "Agregá retry-con-backoff al cliente de API. Después corré la suite en background; si algo falla, leé la falla, arreglala, y avisame cuando esté en verde."},
        ],
        "practice": "Sumá una línea a tu próxima tarea diciéndole al agente qué acción tomar primero: «buscá…», «corré los tests», o «levantá el server y chequeá».",
        "good_looks_like": "Le pasás un trabajo entero y el agente busca, edita, corre y verifica solo — cada paso usando la herramienta hecha para él.",
    },
}

BANDS = [
    ("Operador", 0, 39, "Usás al agente como manos rápidas. Los prompts son cortos y poco "
     "especificados, las ediciones suelen ocurrir sin leer el archivo primero, y los cambios "
     "rara vez se verifican. Las mejoras más rápidas están justo acá: enunciá un objetivo más "
     "una restricción, y dejá que el agente lea antes de editar."),
    ("En desarrollo", 40, 54, "Empieza a aparecer ida y vuelta real y uno o dos hábitos ya son "
     "sólidos. Algunos prompts llevan un path o una restricción; la verificación pasa de vez en "
     "cuando. La brecha al siguiente nivel es la consistencia: hacer lo correcto por defecto, no "
     "solo a veces."),
    ("Competente", 55, 69, "Conducís al agente de forma deliberada. La mayoría de tus prompts son "
     "específicos, las ediciones suelen seguir a una lectura del mismo archivo, y verificás más "
     "seguido que no. Ingeniería asistida por IA sólida y confiable. Lo que queda por ganar es "
     "altitud (decir el porqué) y orquestación."),
    ("Avanzado", 70, 84, "Orquestás en vez de operar. Tus prompts codifican objetivos, restricciones "
     "y criterios de aceptación; leer antes de editar ya es un hábito; la verificación es casi "
     "automática; usás planificación y delegación con fluidez. Briefeás al agente como a un "
     "compañero senior."),
    ("Experto", 85, 100, "Tratás al agente como un sistema de ingeniería gestionado: prompts "
     "consistentemente de alto contexto con criterios de éxito explícitos, loops disciplinados de "
     "leer→editar→verificar, delegación deliberada y casi ningún ciclo de corrección desperdiciado."),
]

# Archetype axes and prototypes.
# The archetype describes YOUR DRIVING STYLE, so it is built only from signals you
# control and DISCOUNTS the habits Claude does on its own. Verification and Context
# (read-before-edit, running tests) are largely the agent's defaults, so they carry
# low "agency" weight; how you brief (Direction), correct (Iteration), reach for tools
# (Toolcraft) and hand off work (Delegation) carry full weight.
ARCHETYPE_AXES = ["Direction", "Verification", "Context", "Iteration", "Toolcraft", "Delegation"]
AGENCY = {"Direction": 1.0, "Verification": 0.35, "Context": 0.15,
          "Iteration": 1.0, "Toolcraft": 0.8, "Delegation": 1.0}

# Prototype vectors over ARCHETYPE_AXES (0-100). Delegation is the axis that separates
# a hands-off delegator from a hands-on builder. These are the five explicit, recognizable
# builder archetypes; the classifier picks the nearest one from your AGENCY-WEIGHTED vector.
PROTOTYPES = {
    "Agente Autónomo": {"emoji": "🤖", "vec": [58, 65, 62, 62, 85, 96],
        "blurb": "Delegás trabajos enteros, de punta a punta, y confiás en que el agente los corra — definís el resultado y dejás que Claude elija los pasos."},
    "Arquitecto":      {"emoji": "🏗️", "vec": [80, 66, 88, 65, 60, 48],
        "blurb": "Planificás y explorás antes de construir — leés y diseñás primero, así los cambios caen sobre una estructura clara."},
    "Depurador":       {"emoji": "🐛", "vec": [62, 88, 82, 85, 60, 28],
        "blurb": "Cazás problemas de forma metódica — leés para diagnosticar, cambiás, verificás y repetís hasta que está realmente arreglado."},
    "Colaborador":     {"emoji": "🤝", "vec": [66, 62, 66, 80, 55, 38],
        "blurb": "Trabajás con el agente como con un compañero — pedís opciones, das feedback y conducís hacia el alineamiento."},
    "Velocista":       {"emoji": "⚡", "vec": [45, 38, 52, 46, 62, 30],
        "blurb": "Te movés rápido y directo — prompts escuetos, turnos veloces, poca ceremonia. Gran velocidad; el briefing y la verificación son tus bordes de mejora."},
}
ARCHETYPE_MARGIN = 0.06   # cosine-similarity margin below which we emit a blended label


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def _parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _text_of(content):
    """Concatenate the text blocks of a message content (str or list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _is_tool_result(content):
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def _looks_injected(text):
    head = text[:200].lstrip()
    if len(text) > MAX_HUMAN_PROMPT_CHARS:
        return True
    if _INJECTED_HEAD.match(head):
        return True
    low = text.lower()
    return any(m in low for m in INJECTION_MARKERS)


def _denamespace_tool(name):
    """mcp__<hash>__slack_read_thread -> slack_read_thread; keep core names as-is."""
    if name.startswith("mcp__"):
        parts = name.split("__")
        return parts[-1] if parts else name
    return name


# Redact machine-identifying home paths from free text before it is shown in the report or
# written to the evidence bundle. Applied only at PRESENTATION, never to the scored corpus,
# so scores stay byte-identical.
_HOME_PATH_RE = re.compile(r"(?:/Users/|/home/)[^/\s]+")
_WIN_HOME_RE = re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+")


def _scrub_paths(text):
    """/Users/<name>/x -> ~/x ; bare /Users/<name> -> ~ ; same for /home/<name> and Windows."""
    if not isinstance(text, str):
        return text
    text = _HOME_PATH_RE.sub("~", text)
    text = _WIN_HOME_RE.sub("~", text)
    return text


class Corpus:
    """Everything we measured from the transcripts, cleanly separated from scoring."""

    def __init__(self):
        self.files = 0
        self.projects = set()
        self.total_bytes = 0
        self.user_records = 0
        self.filtered = Counter()       # why user records were not counted as prompts
        self.real_prompts = []          # list of dicts: text, project, session, idx
        self.tool_usage = Counter()     # de-namespaced tool name -> count
        self.total_tool_calls = 0
        self.delegation_events = 0
        self.first_ts = None
        self.last_ts = None
        self.active_seconds = 0.0
        # Per-session ordered timelines of {"kind": "prompt"|"tool", ...}
        self.sessions = {}              # session_id -> {"project","timeline":[...]}


# Agent-to-agent transcripts (Claude Code subagents, Workflow runs) live under a
# ".../subagents/..." path. They are NOT the user's own prompts — counting them would
# contaminate the assessment and inflate counts every time a workflow is run — so they
# are excluded from discovery (an explicitly named single file is still honored).
_SUBAGENT_RE = re.compile(r"[/\\]subagents[/\\]")


def _filter_transcripts(paths):
    return [p for p in paths if not _SUBAGENT_RE.search(p)]


def discover_files(explicit):
    if explicit:
        p = os.path.expanduser(explicit)
        if os.path.isfile(p) and p.endswith(".jsonl"):
            return [p]
        if os.path.isdir(p):
            return _filter_transcripts(sorted(glob.glob(os.path.join(p, "**", "*.jsonl"), recursive=True)))
        return []
    env = os.environ.get("CLAUDE_PROJECTS_DIR")
    roots = [env] if env else DEFAULT_DIRS
    files = []
    for r in roots:
        rp = os.path.expanduser(r)
        if os.path.isdir(rp):
            files.extend(glob.glob(os.path.join(rp, "**", "*.jsonl"), recursive=True))
    return _filter_transcripts(sorted(set(files)))


def _dedupe_sessions(files):
    """When the same session shows up in more than one root (the live ~/.claude/projects dir
    AND the persistent archive — possibly under a since-renamed project folder, a different-case
    path, or a synced copy from another machine), keep a single copy of it: the largest one,
    since transcripts only ever grow, so the biggest file is the most complete. Claude Code
    session filenames are globally-unique IDs, so the filename alone identifies the session —
    keying on it (not the parent folder) is what makes the dedupe robust to all of the above."""
    best = {}
    for path in files:
        key = os.path.basename(path)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = -1
        cur = best.get(key)
        if cur is None or size > cur[0]:
            best[key] = (size, path)
    return sorted(p for _, p in best.values())


def archive_transcripts(live_files, archive_dir):
    """Copy live transcripts into a persistent archive so they survive Claude Code's
    `cleanupPeriodDays` deletion. Each file is mirrored to
    <archive>/<project folder>/<session>.jsonl. We copy only when the archived copy is
    missing or strictly smaller than the live one (transcripts only grow, so a >= archive copy
    is the more complete one and must never be overwritten with a smaller/equal one). We write
    via a temp file + atomic replace, re-checking the archive size just before the swap so a
    concurrent run can't clobber a larger copy, and always clean up the temp file.
    Returns (n_new, n_updated); a stderr note is printed if any file could not be archived."""
    arch_root = os.path.expanduser(archive_dir)
    new = updated = failed = 0
    for path in live_files:
        project = os.path.basename(os.path.dirname(path)) or "default"
        dest_dir = os.path.join(arch_root, project)
        dest = os.path.join(dest_dir, os.path.basename(path))
        try:
            live_size = os.path.getsize(path)
        except OSError:
            continue
        arch_size = os.path.getsize(dest) if os.path.exists(dest) else -1
        if arch_size >= live_size:
            continue  # already archived an equal-or-more-complete copy
        tmp = dest + ".tmp"
        try:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copyfile(path, tmp)
            # Another run may have grown the archive while we were copying — don't shrink it.
            current = os.path.getsize(dest) if os.path.exists(dest) else -1
            if current >= live_size:
                continue
            os.replace(tmp, dest)  # atomic; never leaves a half-written archive copy
        except OSError:
            failed += 1
            continue
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        if arch_size < 0:
            new += 1
        else:
            updated += 1
    if failed:
        print(f"  Nota: {failed} transcript(s) no se pudieron archivar en {archive_dir} "
              f"(revisá permisos / espacio en disco). Igual se analizaron desde el disco.",
              file=sys.stderr)
    return new, updated


def parse(files):
    c = Corpus()
    c.files = len(files)
    for path in files:
        project = os.path.basename(os.path.dirname(path)) or "default"
        c.projects.add(project)
        try:
            c.total_bytes += os.path.getsize(path)
        except OSError:
            pass
        session_id = os.path.splitext(os.path.basename(path))[0]
        timeline = []
        ts_in_file = []
        prompt_idx = 0
        try:
            fh = open(path, encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_ts(e.get("timestamp"))
                if ts:
                    ts_in_file.append(ts)
                    c.first_ts = ts if c.first_ts is None or ts < c.first_ts else c.first_ts
                    c.last_ts = ts if c.last_ts is None or ts > c.last_ts else c.last_ts
                msg = e.get("message") if isinstance(e.get("message"), dict) else {}
                role = e.get("role") or msg.get("role") or e.get("type")
                content = msg.get("content", e.get("content"))

                if role == "assistant":
                    if isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                raw = b.get("name", "unknown")
                                name = _denamespace_tool(raw)
                                c.tool_usage[name] += 1
                                c.total_tool_calls += 1
                                inp = b.get("input", {}) if isinstance(b.get("input"), dict) else {}
                                if name.lower() in DELEGATION_TOOLS:
                                    c.delegation_events += 1
                                if name.lower() == "bash" and inp.get("run_in_background"):
                                    c.delegation_events += 1
                                fpath = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
                                cmd = inp.get("command") if name.lower() == "bash" else None
                                timeline.append({
                                    "kind": "tool", "name": name.lower(),
                                    "file": fpath, "cmd": cmd,
                                })
                    continue

                if role != "user":
                    continue
                c.user_records += 1
                if _is_tool_result(content):
                    c.filtered["salidas de herramientas"] += 1
                    continue
                if e.get("isSidechain") is True:
                    c.filtered["turnos de subagentes"] += 1
                    continue
                if e.get("isMeta") is True:
                    c.filtered["meta-inyectados"] += 1
                    continue
                text = _text_of(content).strip()
                if not text:
                    c.filtered["vacíos"] += 1
                    continue
                if _looks_injected(text):
                    c.filtered["inyectados / pegados"] += 1
                    continue
                # A genuine, human-typed prompt.
                prompt_idx += 1
                rec = {"text": text, "project": project, "session": session_id, "idx": prompt_idx}
                c.real_prompts.append(rec)
                timeline.append({"kind": "prompt", "text": text, "rec": rec})

        if len(ts_in_file) >= 2:
            ts_in_file.sort()
            c.active_seconds += sum(
                min((ts_in_file[i + 1] - ts_in_file[i]).total_seconds(), GAP_CAP_SECONDS)
                for i in range(len(ts_in_file) - 1)
            )
        if timeline:
            c.sessions[session_id] = {"project": project, "timeline": timeline}
    return c


# --------------------------------------------------------------------------- #
# Scoring helpers
# --------------------------------------------------------------------------- #

def squash(x, target):
    """Saturating curve: hitting `target` maxes the signal; exceeding adds nothing."""
    if target <= 0:
        return 0.0
    return max(0.0, min(1.0, x / target))


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _run_fingerprint(corpus):
    """A stable hash of THIS run's de-contaminated prompt set. It binds an AI analysis
    (the Opus-stage skill map) to the exact data it was written from, so a stale or
    foreign ``analysis.json`` — e.g. left over from a previous run or another person on a
    machine that reuses the fixed ``~/.claude/insight/`` paths — carries a different
    fingerprint and is refused at merge time. This is what stops one person's written
    verdict from ever rendering inside someone else's report."""
    h = hashlib.sha256()
    for p in sorted(corpus.real_prompts, key=lambda r: (r["session"], r["idx"])):
        h.update(f"{p['session']}\x1f{p['idx']}\x1f{p['text']}\x1e".encode("utf-8"))
    h.update(f"|n={len(corpus.real_prompts)}".encode("utf-8"))
    return h.hexdigest()[:16]


def _is_action_prompt(text):
    return bool(ACTION_VERB.search(text))


# --------------------------------------------------------------------------- #
# The five dimensions — each returns (score_0_100, detail_dict, evidence_list)
# --------------------------------------------------------------------------- #

def score_direction(corpus):
    prompts = corpus.real_prompts
    n = len(prompts)
    if n == 0:
        return 0.0, {"n": 0}, []
    constraint = artifact = intent = 0
    weak_examples = []
    for p in prompts:
        t = p["text"]
        has_artifact = bool(ARTIFACT_RE.search(t))
        has_constraint = bool(CONSTRAINT_CUE.search(t) and ACTION_VERB.search(t))
        has_intent = bool(INTENT_CUE.search(t))
        artifact += 1 if has_artifact else 0
        constraint += 1 if has_constraint else 0
        intent += 1 if has_intent else 0
        if _is_action_prompt(t) and not (has_artifact or has_constraint or has_intent) and len(t) < 120:
            weak_examples.append(p)
    constraint_rate = constraint / n
    artifact_rate = artifact / n
    intent_rate = intent / n
    # front-loading: penalize rules first revealed via a high-info correction
    corr = _find_corrections(corpus)
    new_rule_corrections = sum(1 for x in corr if x["high_info"])
    action_prompts = max(1, sum(1 for p in prompts if _is_action_prompt(p["text"])))
    front_loading = 1 - clamp(new_rule_corrections / action_prompts, 0, 1)
    score = 100 * (
        0.30 * squash(constraint_rate, 0.45)
        + 0.20 * squash(artifact_rate, 0.45)
        + 0.25 * squash(intent_rate, 0.30)
        + 0.25 * front_loading
    )
    detail = {
        "n": n, "constraint_rate": constraint_rate, "artifact_rate": artifact_rate,
        "intent_rate": intent_rate, "front_loading": front_loading,
    }
    return score, detail, weak_examples[:6]


def _iter_sessions(corpus):
    for sid, s in corpus.sessions.items():
        yield sid, s["project"], s["timeline"]


def _find_corrections(corpus):
    """Correction turns: short rejections that follow an assistant action, praise-guarded."""
    out = []
    for sid, project, timeline in _iter_sessions(corpus):
        saw_tool = False
        for ev in timeline:
            if ev["kind"] == "tool":
                saw_tool = True
                continue
            t = ev["text"]
            head = t[:160]
            if CORRECTION_CUE.search(head) and not PRAISE_CUE.search(head) and saw_tool:
                high_info = bool(
                    re.search(r"\d", t) or ARTIFACT_RE.search(t) or len(t.split()) >= 8
                    or INTENT_CUE.search(t)
                )
                out.append({"session": sid, "project": project, "text": t, "high_info": high_info})
            saw_tool = False  # reset: correction must directly follow an action turn
    return out


def score_iteration(corpus):
    prompts = corpus.real_prompts
    n = len(prompts)
    corr = _find_corrections(corpus)
    k = len(corr)
    if n == 0:
        return 50.0, {"n": 0, "corrections": 0}, []
    rate = k / n
    specificity = (sum(1 for x in corr if x["high_info"]) / k) if k else 1.0
    score = 100 * (0.6 * (1 - clamp(rate / CORRECTION_RATE_CEILING, 0, 1)) + 0.4 * specificity)
    low_info = [x for x in corr if not x["high_info"]]
    # Confidence is keyed on prompt count n (the opportunity count), NOT correction count k:
    # a user with many clean prompts and zero corrections has STRONG evidence of good iteration,
    # so it must not be shrunk toward 50 as if it were "no data".
    detail = {"n": n, "corrections": k, "correction_rate": rate, "specificity": specificity}
    return score, detail, low_info[:4]


def score_context(corpus):
    total_edits = 0
    grounded = 0
    blind_examples = []
    for sid, project, timeline in _iter_sessions(corpus):
        read_paths = set()
        edited_paths = set()
        written_paths = set()   # files the agent authored this session (grounded to edit)
        for ev in timeline:
            if ev["kind"] != "tool":
                continue
            name, fpath = ev["name"], ev.get("file")
            if name in READ_TOOLS and fpath:
                read_paths.add(fpath)
            elif name in EDIT_TOOLS:
                total_edits += 1
                if not fpath:
                    grounded += 1  # can't attribute; don't penalize
                    continue
                is_new_write = (name == "write" and fpath not in read_paths and fpath not in edited_paths)
                # grounded if it was read, OR authored earlier this session, OR is being created now
                if fpath in read_paths or fpath in written_paths or is_new_write:
                    grounded += 1
                else:
                    blind_examples.append({"session": sid, "project": project, "file": fpath})
                if name == "write":
                    written_paths.add(fpath)
                edited_paths.add(fpath)
    if total_edits == 0:
        return 50.0, {"n": 0, "grounded": 0, "total_edits": 0, "rate": None}, []
    rate = grounded / total_edits
    score = 100 * squash(rate, 0.85)
    return score, {"n": total_edits, "grounded": grounded, "total_edits": total_edits, "rate": rate}, blind_examples[:4]


def score_verification(corpus):
    episodes = 0
    verified = 0
    teardown_bonus = 0
    unverified_examples = []
    for sid, project, timeline in _iter_sessions(corpus):
        open_ep = False
        ep_files = []
        for ev in timeline:
            if ev["kind"] == "prompt":
                # a "run it / does it work / confirm" prompt verifies an open episode
                if open_ep and re.search(
                        r"\b(run it|does it work|confirm|check (it|that)|verify|did it work|"
                        r"corr[eé]lo|corr[eé]la|corr[eé] (el|la|los|las)?|funciona|anda|"
                        r"confirm[aá]|verific[aá]|prob[aá]|chequ[eé][aá]|fij[aá]te|"
                        r"compil[aá]|test[eé][aá])\b",
                        ev["text"], re.I):
                    verified += 1
                    open_ep = False
                continue
            name = ev["name"]
            cmd = ev.get("cmd") or ""
            if name in EDIT_TOOLS:
                if not open_ep:
                    open_ep = True
                    episodes += 1
                    ep_files = []
                if ev.get("file"):
                    ep_files.append(os.path.basename(ev["file"]))
            elif name == "bash":
                if TEARDOWN_RE.search(cmd):
                    teardown_bonus = 5
                if open_ep and VERIFY_RE.search(cmd):
                    verified += 1
                    open_ep = False
            elif name in READ_TOOLS and open_ep and ev.get("file") and os.path.basename(ev["file"]) in ep_files:
                # re-reading the just-edited file is a (weak) check
                verified += 1
                open_ep = False
        if open_ep:
            unverified_examples.append({"session": sid, "project": project,
                                        "files": ", ".join(sorted(set(ep_files))[:3]) or "files"})
    if episodes == 0:
        return 50.0, {"n": 0, "episodes": 0, "verified": 0, "rate": None}, []
    rate = verified / episodes
    score = min(100, 100 * squash(rate, 0.60) + teardown_bonus)
    return score, {"n": episodes, "episodes": episodes, "verified": verified, "rate": rate,
                   "teardown_bonus": teardown_bonus}, unverified_examples[:4]


def score_toolcraft(corpus):
    total = corpus.total_tool_calls
    if total == 0:
        return 0.0, {"n": 0, "distinct": 0, "evenness": 0.0, "delegation_events": 0}, []
    # Collapse case-variant duplicates (e.g. "Bash" vs "bash") for an honest distinct count.
    merged = Counter()
    for name, cnt in corpus.tool_usage.items():
        merged[name.lower()] += cnt
    distinct = len(merged)
    breadth = squash(distinct / 20, 1.0)
    # Shannon evenness of the usage distribution.
    counts = list(merged.values())
    H = -sum((x / total) * math.log(x / total) for x in counts if x > 0)
    evenness = (H / math.log(distinct)) if distinct > 1 else 0.0
    active_hours = max(corpus.active_seconds / 3600, 0.5)
    delegation = squash(corpus.delegation_events / active_hours, 2.0)
    score = 100 * (0.45 * breadth + 0.30 * evenness + 0.25 * delegation)
    detail = {"n": total, "distinct": distinct, "evenness": evenness,
              "delegation_events": corpus.delegation_events}
    return score, detail, []


# --------------------------------------------------------------------------- #
# Aggregate: confidence shrinkage, overall score, band, archetype
# --------------------------------------------------------------------------- #

def shrink(score, n, target_n):
    c = min(1.0, n / target_n) if target_n else 1.0
    return 50 + (score - 50) * c, c


def band_for(score):
    for name, lo, hi, meaning in BANDS:
        if lo <= score <= hi:
            return name, meaning
    return BANDS[-1][0], BANDS[-1][3]


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def classify_archetype(dim_scores, delegation_score):
    """Nearest-prototype over your DRIVING-STYLE vector, with a margin guard.

    The vector adds a Delegation axis and is AGENCY-WEIGHTED: axes you control
    (Direction, Iteration, Toolcraft, Delegation) count fully, while axes the agent
    mostly drives on its own (Verification, Context) are heavily discounted — so the
    archetype reflects how *you* drive, not Claude's built-in habits.
    """
    scores = dict(dim_scores)
    scores["Delegation"] = delegation_score
    V = [scores[ax] for ax in ARCHETYPE_AXES]
    names = list(PROTOTYPES.keys())
    mat = [PROTOTYPES[n]["vec"] for n in names]
    # z-score each axis across prototypes + the user vector, then apply agency weights
    cols = list(zip(*(mat + [V])))
    means = [statistics.mean(col) for col in cols]
    stds = [statistics.pstdev(col) or 1.0 for col in cols]
    w = [AGENCY[ax] for ax in ARCHETYPE_AXES]

    def zw(vec):
        return [w[i] * (v - means[i]) / stds[i] for i, v in enumerate(vec)]

    vz = zw(V)
    sims = sorted(((round(_cosine(vz, zw(PROTOTYPES[n]["vec"])), 3), n) for n in names), reverse=True)
    top_sim, top = sims[0]
    second_sim, second = sims[1]
    blended = (top_sim - second_sim) < ARCHETYPE_MARGIN
    second_short = second.replace("The ", "")
    article = "an" if second_short[:1] in "AEIOU" else "a"
    return {
        "primary": top, "primary_sim": top_sim, "secondary": second, "secondary_sim": second_sim,
        "blended": blended, "all": sims, "delegation_score": round(delegation_score),
        "label": f"{PROTOTYPES[top]['emoji']} {top}" + (f", con una veta de {second_short}" if blended else ""),
        "blurb": PROTOTYPES[top]["blurb"],
    }


# --------------------------------------------------------------------------- #
# Analysis orchestration
# --------------------------------------------------------------------------- #

def analyze(corpus):
    raw, detail, evidence = {}, {}, {}
    for name, fn in (("Direction", score_direction), ("Verification", score_verification),
                     ("Context", score_context), ("Iteration", score_iteration),
                     ("Toolcraft", score_toolcraft)):
        s, d, ev = fn(corpus)
        raw[name], detail[name], evidence[name] = s, d, ev

    shrunk, conf = {}, {}
    for name in raw:
        shrunk[name], conf[name] = shrink(raw[name], detail[name].get("n", 0), TARGET_N[name])

    overall_raw = round(sum(WEIGHTS[n] * raw[n] for n in WEIGHTS))
    overall = round(sum(WEIGHTS[n] * shrunk[n] for n in WEIGHTS))
    band, band_meaning = band_for(overall)
    # Delegation is a user-driven archetype axis (handoffs per active hour).
    active_hours = max(corpus.active_seconds / 3600, 0.5)
    delegation_score = 100 * squash(corpus.delegation_events / active_hours, 2.0)
    archetype = classify_archetype(shrunk, delegation_score)

    # length distribution of real prompts (context only)
    lens = [len(p["text"]) for p in corpus.real_prompts]
    words = [len(p["text"].split()) for p in corpus.real_prompts]
    dist = {}
    if lens:
        dist = {
            "median_chars": int(statistics.median(lens)),
            "mean_chars": int(statistics.mean(lens)),
            "median_words": int(statistics.median(words)),
            "under_80_pct": round(100 * sum(1 for L in lens if L < 80) / len(lens)),
        }

    return {
        "raw": raw, "shrunk": shrunk, "conf": conf, "detail": detail, "evidence": evidence,
        "overall_raw": overall_raw, "overall": overall, "band": band, "band_meaning": band_meaning,
        "archetype": archetype, "dist": dist, "fingerprint": _run_fingerprint(corpus),
    }


def build_action_plan(corpus, result):
    """Growth cards ranked by impact = (target - score) * weight. The teaching copy
    comes from SKILL_TEACH; user-specific evidence comes from result['evidence']."""
    TARGET = 85
    cards = []
    for name in WEIGHTS:
        score = result["shrunk"][name]
        impact = (TARGET - score) * WEIGHTS[name]
        cards.append({"dim": name, "score": round(score), "impact": impact,
                      "weak": result["evidence"].get(name, []),
                      "detail": result["detail"][name]})
    cards.sort(key=lambda c: c["impact"], reverse=True)
    # strength callout = highest shrunk score
    strength = max(WEIGHTS, key=lambda n: result["shrunk"][n])
    return cards, strength


def _shortest_action_prompt(corpus):
    cands = [p["text"] for p in corpus.real_prompts if _is_action_prompt(p["text"]) and len(p["text"]) < 40]
    return min(cands, key=len) if cands else None


def build_evidence(corpus, result, cards, archive_info=None):
    """Serialize a de-contaminated EVIDENCE bundle for the two-model analysis pipeline
    (Sonnet 4.6 explores it; Opus 4.8 analyzes it against the bundled AI-fluency
    framework). It contains your real prompts/behavior with home paths scrubbed, and is
    git-ignored. Deterministic (no randomness) so runs are reproducible."""
    prompts = corpus.real_prompts
    sample, seen = [], set()

    def add(p):
        k = (p["session"], p["idx"])
        if k in seen:
            return
        seen.add(k)
        sample.append({"text": _scrub_paths(p["text"][:600]), "project": _project_label(p["project"]),
                       "chars": len(p["text"])})

    by_len = sorted(prompts, key=lambda p: len(p["text"]))
    for p in by_len[:6]:                 # the terse nudges
        add(p)
    for p in by_len[-14:]:               # the rich, intent-carrying prompts
        add(p)
    stride = max(1, len(prompts) // 20)  # an even spread through the timeline
    for p in prompts[::stride]:
        if len(sample) >= 50:
            break
        add(p)

    def clean_ex(items):
        out = []
        for e in items or []:
            if not isinstance(e, dict):
                continue
            c = {}
            if e.get("text"):
                c["text"] = _scrub_paths(str(e["text"])[:300])
            if e.get("file"):
                c["file"] = os.path.basename(str(e["file"]))
            if e.get("files"):
                c["files"] = str(e["files"])
            if e.get("project"):
                c["project"] = _project_label(e["project"])
            if c:
                out.append(c)
        return out

    span_days = (corpus.last_ts - corpus.first_ts).days if corpus.first_ts and corpus.last_ts else 0
    a = result["archetype"]
    return {
        "schema": "claude-insight-evidence/1",
        "meta": {
            "sessions": corpus.files, "projects": len(corpus.projects),
            "real_prompts": len(prompts), "user_records": corpus.user_records,
            "filtered_noise": dict(corpus.filtered),
            "span_days": span_days,
            "active_hours": round(corpus.active_seconds / 3600, 1),
            "archive": archive_info,
            "prompt_distribution": result["dist"],
            # Binds any analysis produced from this bundle back to this exact run; the
            # analysis stage must echo it so a stale/foreign analysis can be refused.
            "run_fingerprint": result.get("fingerprint"),
        },
        "scores": {
            "overall": result["overall"], "overall_raw": result["overall_raw"],
            "band": result["band"], "weights": WEIGHTS,
            "dimensions_raw": {k: round(v) for k, v in result["raw"].items()},
            "dimensions_adjusted": {k: round(v) for k, v in result["shrunk"].items()},
            "confidence": {k: round(v, 2) for k, v in result["conf"].items()},
            "dimension_names": DISPLAY_NAMES,
        },
        "dimension_detail": result["detail"],
        "archetype": {"primary": a["primary"], "secondary": a["secondary"],
                      "blended": a.get("blended")},
        "behavior": {
            "sample_prompts": sample,
            "weak_examples": {c["dim"]: clean_ex(c["weak"]) for c in cards},
            "tool_usage": dict(corpus.tool_usage),
            "delegation_events": corpus.delegation_events,
        },
    }


def _analysis_section_html(analysis):
    """Render the AI-authored skill map (produced by the Opus analysis stage,
    grounded in reference/framework-fluidez-ia.md). Falls back to nothing if absent."""
    if not analysis or not isinstance(analysis, dict):
        return ""
    parts = ['<section><h3>Mapa de habilidades — analizado contra el framework de AI Fluency</h3>']
    read = analysis.get("overall_read") or analysis.get("summary")
    if read:
        parts.append(f'<p class="assess">{_esc(read)}</p>')
    for s in analysis.get("skill_map") or []:
        if not isinstance(s, dict):
            continue
        comp = _esc(s.get("competency", "?"))
        lvl = s.get("level", "?")
        label = _esc(s.get("level_label", ""))
        summ = _esc(s.get("summary", ""))
        nxt = _esc(s.get("next_move", ""))
        ev = "".join(f"<li>“{_esc(str(x)[:200])}”</li>" for x in (s.get("evidence") or [])[:3])
        parts.append(
            f'<div class="dim"><div class="dim-h"><b>{comp}</b>'
            f'<span class="pill">Nivel {_esc(lvl)}/5 · {label}</span></div>'
            f'<p>{summ}</p>'
            + (f'<ul class="ev">{ev}</ul>' if ev else "")
            + (f'<p class="next"><b>Tu próximo paso:</b> {nxt}</p>' if nxt else "")
            + '</div>')
    strengths = analysis.get("strengths") or []
    if strengths:
        items = "".join(f"<li>{_esc(s)}</li>" for s in strengths[:5])
        parts.append(f'<p style="margin-top:14px"><b>Lo que ya hacés bien:</b></p><ul class="facts">{items}</ul>')
    parts.append('<p style="color:var(--mut);font-size:13px;margin-top:10px">'
                 'Esta sección la escribe Claude Opus 4.8 a partir de tu evidencia descontaminada '
                 '(explorada por Claude Sonnet 4.6), anclada en el framework de AI Fluency incluido. '
                 'Los números de arriba se computan de forma determinística e independiente.</p>')
    parts.append('</section>')
    return "".join(parts)


def _growth_cards_html(analysis):
    """The 'how to grow' cards, written FOR THIS PERSON by the Opus analysis stage:
    each item names the habit, why it matters, how to grow it, and a before/after where
    the 'before' is one of THEIR real prompts and the 'after' is Opus's tailored rewrite.
    Returns '' when there is no analysis (the caller then falls back to the generic
    teaching examples), so the report only ever shows canned examples when no AI ran."""
    if not analysis or not isinstance(analysis, dict):
        return ""
    items = [g for g in (analysis.get("top_growth") or []) if isinstance(g, dict)]
    if not items:
        return ""
    out = []
    for i, g in enumerate(items[:3]):
        title = _esc(g.get("title", "Tu próximo paso de mejora"))
        why = _esc(g.get("why", ""))
        how = _esc(g.get("how", ""))
        before = g.get("example_before")
        after = g.get("example_after")
        ba = ""
        if before and after:
            ba = (f'<div class="ba"><div class="before"><span>Un prompt que escribiste</span>'
                  f'“{_esc(str(before)[:400])}”</div>'
                  f'<div class="after"><span>Reescritura a tu medida</span>'
                  f'“{_esc(str(after)[:600])}”</div></div>')
        out.append(
            f'<div class="card prio"><div class="ph">Prioridad {i + 1} · escrito para vos</div>'
            f'<h4>{title}</h4>'
            + (f'<p class="why"><b>Por qué importa.</b> {why}</p>' if why else "")
            + (f'<div class="wwh"><span class="lab">Cómo mejorarlo</span>'
               + (f'<p class="how">{how}</p>' if how else "") + f'{ba}</div>'
               if (how or ba) else "")
            + '</div>')
    return "".join(out)


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #

def _project_label(name):
    """Claude encodes an absolute path with '-' for '/', so we can't perfectly
    recover hyphenated names. Drop the home/boilerplate prefix and show the rest.
    '-Users-me-Dropbox-AI-platzi-executive-assistant' -> 'AI platzi executive assistant'."""
    s = re.sub(r"^-?(?:Users|home)-[^-]+(?:-|$)", "", name)  # strip -Users-/-home-<user>- (mac & linux)
    s = re.sub(r"^Dropbox-", "", s)                          # strip a common cloud-folder prefix
    s = s.replace("-", " ").strip()
    # Nothing left -> the session ran in $HOME itself; never echo the raw name (it holds the username).
    if not s:
        return "home" if re.match(r"^-?(?:Users|home)-", name) else name
    return s


def terminal_summary(corpus, result):
    a = result["archetype"]
    lines = [
        "",
        f"  Puntaje de Fluidez IA: {result['overall']}/100  ({result['band']})",
        f"  Arquetipo: {a['label']}",
        f"  Basado en {len(corpus.real_prompts)} prompts reales en {len(corpus.projects)} proyectos, "
        f"{corpus.files} sesiones ({corpus.total_bytes/1e6:.1f} MB).",
        "",
    ]
    return "\n".join(lines)


def _esc(s):
    return html.escape(str(s))


# Each archetype's encouraging "next gain" — frames the top growth lever as a natural
# progression for that style rather than a deficit.
ARCH_PATHS = {
    "Agente Autónomo": "Ya delegás trabajos enteros bien — sumá una frase filosa de intención por cada hand-off y mucho más va a salir bien a la primera, con menos ida y vuelta.",
    "Arquitecto": "Tu planificación es una fortaleza real — combinala con un chequeo rápido después de cada cambio para que tus diseños salgan probados, no solo dibujados.",
    "Depurador": "Tu disciplina diagnóstica es excelente — capturá cada arreglo como una pequeña regla reutilizable para que el mismo bug nunca te cueste dos veces.",
    "Colaborador": "Tu ida y vuelta mantiene todo alineado — front-loadear una restricción o dos te va a llevar ahí en menos rondas.",
    "Velocista": "Tu velocidad es real — un brief de una línea más un test rápido evitan que esa velocidad se convierta en retrabajo.",
}

_SIG_DESC = {
    "Delegation": "cuánto delegás — le pasás a Claude trabajos enteros y confiás en que los corra de punta a punta",
    "Toolcraft": "el rango de herramientas que ponés en juego — vas más allá de la shell para agarrar el instrumento justo",
    "Iteration": "qué tan limpio cambiás de rumbo — tus correcciones tienden a nombrar el arreglo, no solo a rechazar",
    "Briefing": "qué tan concreto encuadrás los pedidos cuando importa",
}

# La línea específica, anclada en evidencia, que explica cada dimensión como borde de mejora.
_GROWTH_LINE = {
    "Direction": "Los {s} ganan en qué tan filoso encuadran el trabajo que delegan — y ahora los tuyos suelen ser de una línea como “{ex}”, así que Claude rellena huecos que podrías haber decidido vos.",
    "Verification": "Ahora los cambios suelen avanzar sin un test, build o corrida que los confirme — la confiabilidad más barata que podés recuperar.",
    "Context": "Ahora algunas ediciones caen antes de que el archivo se haya leído en esa sesión — un riesgo fácil de edición a ciegas para eliminar.",
    "Iteration": "Ahora las correcciones tiran a rechazos breves; nombrar el síntoma y la regla exacta resuelve los loops en menos turnos.",
    "Toolcraft": "Ahora la mayoría del trabajo se canaliza por una sola herramienta — buscar, planificar y delegar amplía lo que podés encarar.",
}


def build_assessment(corpus, result, cards):
    """A coherent, professional written read — synthesizes the numbers into one story
    and explicitly resolves the archetype-vs-weakest-dimension tension."""
    a = result["archetype"]
    arch = a["primary"]
    short = arch.replace("The ", "")
    art = "an" if short[:1] in "AEIOU" else "a"
    deleg = a["delegation_score"]
    n_deleg = corpus.delegation_events
    median = result["dist"].get("median_chars", "?")

    # signature strength = your strongest USER-driven signal (not Claude's defaults)
    user_signals = {
        "Briefing": result["shrunk"]["Direction"], "Iteration": result["shrunk"]["Iteration"],
        "Toolcraft": result["shrunk"]["Toolcraft"], "Delegation": float(deleg),
    }
    sig = max(user_signals, key=user_signals.get)

    growth = cards[0]["dim"]
    growth_disp = disp(growth)
    example = _shortest_action_prompt(corpus) or "corré esto"
    path_why = ARCH_PATHS.get(arch, "Seguí construyendo los hábitos de abajo y tu próxima corrida va a mostrar la mejora.")

    p1 = (f"Conducís a Claude como <b>{_esc(a['label'])}</b>. {_esc(a['blurb'])} "
          f"La señal más clara es tu tasa de delegación — <b>{deleg}/100</b>, de {n_deleg} hand-offs a "
          f"subagentes, jobs en background y planificación — combinada con prompts rápidos y escuetos (mediana "
          f"{median} caracteres).")

    # Solo se acredita el loop leer→editar→verificar cuando los datos realmente lo muestran; si no, esta
    # cláusula afirmaba una disciplina que el propio reporte de algunos usuarios contradice (0% verificado / anclado).
    loop_ok = result["shrunk"]["Context"] >= 55 and result["shrunk"]["Verification"] >= 55
    p2_mid = ("Eso, sumado al disciplinado loop leer→editar→verificar que muestran tus sesiones, es"
              if loop_ok else "Eso es")
    p2 = (f"Tu hábito <i>autoconducido</i> más fuerte es {_esc(_SIG_DESC.get(sig, sig.lower()))}. "
          f"{p2_mid} por lo que tu puntaje general queda en <b>{result['overall']}/100 ({_esc(result['band'])})</b>.")

    gline = _GROWTH_LINE.get(growth, "").format(s=_esc(short), ex=_esc(example))
    p3 = (f"Y la tensión aparente, resuelta: tu dimensión más baja es <b>{_esc(growth_disp)}</b> — pero para "
          f"un {_esc(short)} eso no es una contradicción, es el borde de mejora que te <i>define</i>. {gline} "
          f"{_esc(path_why)}")

    return (f'<p class="assess">{p1}</p><p class="assess">{p2}</p><p class="assess">{p3}</p>')


def build_html(corpus, result, cards, strength, archive_info=None, analysis=None, analysis_note=None):
    a = result["archetype"]
    d = result["dist"]
    analysis_section = _analysis_section_html(analysis)
    # When an AI analysis was expected but couldn't be used (no-op'd, empty, or from a
    # different run), say so plainly instead of letting the template-only report pass as
    # the full thing. Silent on a plain deterministic run (no --analysis was attempted).
    analysis_status_html = ""
    if not analysis_section and analysis_note:
        analysis_status_html = (
            '<section><div class="prov">ℹ️ <b>Solo reporte determinístico.</b> '
            f'{_esc(analysis_note)} — no se sumó arriba el mapa de habilidades de Sonnet&nbsp;+&nbsp;Opus. '
            'El puntaje, el arquetipo y las dimensiones de abajo igual se computan por completo desde tus datos; '
            'para sumar el mapa de habilidades escrito por la IA, volvé a correr <code>/fluidez-ia</code> dentro de Claude Code.'
            '</div></section>')
    days = (corpus.last_ts - corpus.first_ts).days if corpus.first_ts and corpus.last_ts else 0
    active_h = corpus.active_seconds / 3600
    filtered_total = sum(corpus.filtered.values())
    provisional = len(corpus.real_prompts) < PROVISIONAL_MIN_PROMPTS

    DIM_BLURB = {
        "Direction": "Qué tan claro le decís al agente qué querés antes de que actúe.",
        "Verification": "Si los cambios se chequean (tests / build / app) antes de seguir.",
        "Context": "Leer un archivo antes de editarlo — cambios anclados, no a ciegas.",
        "Iteration": "Corregir con precisión en vez de patalear con rechazos vagos.",
        "Toolcraft": "Usar un rango sano de herramientas — sin forzar todo por una sola.",
    }

    def dim_rate_line(name):
        det = result["detail"][name]
        if name == "Verification" and det.get("rate") is not None:
            return f"{det['verified']} de {det['episodes']} ráfagas de edición verificadas ({det['rate']*100:.0f}%)"
        if name == "Context" and det.get("rate") is not None:
            return f"{det['grounded']} de {det['total_edits']} ediciones quedaron ancladas en una lectura previa ({det['rate']*100:.0f}%)"
        if name == "Direction":
            return (f"{det['constraint_rate']*100:.0f}% llevan una restricción · "
                    f"{det['artifact_rate']*100:.0f}% nombran un archivo/error · {det['intent_rate']*100:.0f}% dicen un porqué")
        if name == "Iteration":
            return f"{det['corrections']} turnos de corrección ({det['correction_rate']*100:.0f}% de los prompts); {det['specificity']*100:.0f}% fueron específicos"
        if name == "Toolcraft":
            return f"{det.get('distinct', 0)} herramientas distintas, uniformidad {det.get('evenness', 0.0):.2f}, {det.get('delegation_events', 0)} delegaciones"
        return ""

    # dimension bars
    dim_html = ""
    order = sorted(WEIGHTS, key=lambda n: result["shrunk"][n], reverse=True)
    for name in order:
        sc = round(result["shrunk"][name])
        raw_sc = round(result["raw"][name])
        c = result["conf"][name]
        lowdata = c < 0.75
        tag = ""
        if name == strength:
            tag = '<span class="tag s">Fortaleza</span>'
        elif name == cards[0]["dim"]:
            tag = '<span class="tag w">Mayor palanca de mejora</span>'
        ld = '<span class="tag ld">pocos datos</span>' if lowdata else ""
        dim_html += f"""
      <div class="dim">
        <div class="top"><span class="name">{_esc(disp(name))} {tag}{ld}</span><span class="sval">{sc}<span class="hint">/100</span></span></div>
        <div class="bar"><i style="width:{sc}%"></i></div>
        <p class="def">{_esc(DIM_BLURB[name])}</p>
        <p class="rate">{_esc(dim_rate_line(name))}<span class="wt"> · peso {int(WEIGHTS[name]*100)}%</span></p>
      </div>"""

    # archetype affinity
    aff = ""
    for sim, nm in a["all"]:
        pct = max(0, round((sim + 1) / 2 * 100))
        aff += f"""<div class="bar-item"><div class="bl">{PROTOTYPES[nm]['emoji']} {_esc(nm)}</div>
          <div class="bt"><i style="width:{pct}%"></i></div><div class="bv">{sim:+.2f}</div></div>"""

    # data-ingested filter breakdown
    filt = "".join(
        f"<li><b>{v:,}</b> {_esc(k)}</li>" for k, v in corpus.filtered.most_common()
    )

    # Archive stat tile + the "why ~30 days / how to see more" callout.
    archive_tile = retention_note = ""
    arch_dir_disp = _esc(archive_info["dir"]) if archive_info else _esc(DEFAULT_ARCHIVE_DIR)
    if archive_info:
        archive_tile = (f'<div class="ing"><div class="n">{archive_info["archived_sessions"]:,}</div>'
                        f'<div class="l">sesiones en tu archivo</div></div>')
    # Mostramos la explicación cuando el historial visible es corto — es la limpieza de 30 días pegando.
    if days <= 32:
        grew = ""
        if archive_info and archive_info.get("enabled"):
            grew = (f' Esta corrida preservó <b>{archive_info["new"]:,}</b> sesión(es) nueva(s) en tu '
                    f'archivo (<code>{arch_dir_disp}</code>), así que de acá en más tu historial sigue creciendo '
                    f'más allá de la pared de los 30 días. Mantené este archivo privado para vos — compartir una carpeta '
                    f'entre personas mezclaría los transcripts de todos en un único reporte.')
        retention_note = (
            '<div class="honesty" style="margin-top:14px">'
            f'<b>¿Por qué solo ~{days} días?</b> Claude Code borra los transcripts más viejos que tu '
            'setting <code>cleanupPeriodDays</code> (default <b>30</b>), así que eso es todo lo que '
            'quedó en disco para leer — no es un límite de esta herramienta. Para analizar más historial: '
            '<b>(1)</b> subí <code>cleanupPeriodDays</code> en <code>~/.claude/settings.json</code> '
            '(ej. <code>"cleanupPeriodDays": 365</code>) para frenar el borrado; '
            f'<b>(2)</b> seguí corriendo Claude Insight.{grew}'
            '</div>')

    # action cards (what/where/how)
    def evidence_html(card):
        name = card["dim"]
        ev = card["weak"]
        if not ev:
            return '<p class="ev-none">No hay ejemplos claros en tus transcripts — esto ya es un hábito. ✓</p>'
        items = ""
        # guarda de muestra chica por proyecto
        proj_counts = Counter(p["project"] for p in corpus.real_prompts)
        for e in ev[:3]:
            if name == "Direction" or name == "Iteration":
                proj = e["project"]; txt = _scrub_paths(e["text"])
                small = " <em>(ilustrativo, muestra chica)</em>" if proj_counts.get(proj, 0) < 10 else ""
                items += f'<li>“{_esc(txt[:140])}” <span class="loc">— {_esc(_project_label(proj))}{small}</span></li>'
            elif name == "Context":
                small = " <em>(ilustrativo)</em>" if proj_counts.get(e["project"], 0) < 10 else ""
                items += f'<li>Editó <code>{_esc(os.path.basename(e["file"]))}</code> sin leerlo primero <span class="loc">— {_esc(_project_label(e["project"]))}{small}</span></li>'
            elif name == "Verification":
                small = " <em>(ilustrativo)</em>" if proj_counts.get(e["project"], 0) < 10 else ""
                items += f'<li>Una ráfaga de ediciones a <code>{_esc(e["files"])}</code> sin correr nada después <span class="loc">— {_esc(_project_label(e["project"]))}{small}</span></li>'
        return f"<ul class='ev'>{items}</ul>"

    cards_html = ""
    for i, card in enumerate(cards[:2]):
        name = card["dim"]
        t = SKILL_TEACH[name]
        # These before/after pairs are a fixed teaching library, identical for every user
        # with this weak dimension — they are NOT drawn from this person's transcripts.
        # Label them as such so they can never be mistaken for a personalized rewrite (the
        # personalized signal is the "Where this shows up in your sessions" block above).
        ex_html = "".join(
            f'<div class="ba"><div class="before"><span>En vez de</span>“{_esc(e["before"])}”</div>'
            f'<div class="after"><span>Más fuerte</span>“{_esc(e["after"])}”</div></div>'
            for e in t["examples"]
        )
        cards_html += f"""
      <div class="card prio">
        <div class="ph">Prioridad {i+1} · {_esc(disp(name))} <span class="pscore">ahora {card['score']}/100</span></div>
        <h4>{_esc(t['what_it_is'])}</h4>
        <p class="why"><b>Por qué importa.</b> {_esc(t['why_it_matters'])}</p>
        <div class="wwh"><span class="lab">Dónde aparece esto en tus sesiones</span>{evidence_html(card)}</div>
        <div class="wwh"><span class="lab">Cómo mejorarlo</span><p class="how">{_esc(t['how_to_improve'])}</p>
          <p class="exgen">Ilustraciones genéricas del hábito — <b>no</b> de tus sesiones:</p>
          {ex_html}
        </div>
        <p class="tgt">🎯 Probá esto la próxima sesión: {_esc(t['practice'])}</p>
      </div>"""

    # strength callout — lead with the user's signature (self-driven) strength.
    # Floor the praise: if even the best dimension is weak, frame it as "relatively
    # strongest" rather than asserting a mastered habit the rate-line would contradict.
    s_det = dim_rate_line(strength)
    strong_score = round(result["shrunk"][strength])
    if strong_score >= 55:
        strength_head = "Seguí haciendo esto"
        strength_body = (f"{_esc(SKILL_TEACH[strength]['good_looks_like'])} La evidencia en tus "
                         f"sesiones: {_esc(s_det)}. Esta es tu base — construí sobre ella.")
    else:
        strength_head = "Tu área relativamente más fuerte"
        strength_body = (f"Incluso tu dimensión más fuerte tiene margen para crecer ({strong_score}/100), pero este "
                         f"es el lugar más natural para empezar a construir. La evidencia en tus sesiones: "
                         f"{_esc(s_det)}.")
    strength_html = f"""
      <div class="card keep">
        <div class="ph">{strength_head} · {_esc(disp(strength))} <span class="pscore">{strong_score}/100</span></div>
        <p>{strength_body}</p>
      </div>"""

    # skill map (levels)
    skill_levels = _skill_levels(result)
    skill_html = ""
    for sk in skill_levels:
        dots = "".join(
            f'<span class="dot {"on" if i < sk["level"] else ""}"></span>' for i in range(5)
        )
        skill_html += f"""<div class="skill">
          <div class="sk-top"><span class="sk-name">{_esc(sk['name'])} <span class="lvl">Nivel {sk['level']}/5</span></span><span class="sk-dots">{dots}</span></div>
          <p class="sk-what">{_esc(sk['what'])}</p>
          <p class="sk-now"><b>Estás acá:</b> {_esc(sk['now'])}</p>
          <p class="sk-next"><b>Próximo paso:</b> {_esc(sk['next'])}</p></div>"""

    prov_banner = ""
    if provisional:
        prov_banner = (f'<div class="prov">⚠️ Provisional: solo se encontraron {len(corpus.real_prompts)} prompts reales — '
                       f'tomá el puntaje como un rango aproximado (±10). Se afina a medida que usás más Claude Code.</div>')
    # Con pocos datos el arquetipo es la señal menos estable (un vector casi neutro cae en
    # el prototipo más cercano por una nimiedad), así que lo matizamos explícitamente en vez de afirmarlo.
    arch_hedge = ""
    if provisional:
        arch_hedge = ('<p style="margin-top:8px;font-size:12.5px;color:var(--warn)">Provisional — basado en solo '
                      f'{len(corpus.real_prompts)} prompt(s); el arquetipo puede moverse a medida que se acumula más historial.</p>')

    # datos al pasar
    facts = [
        f"{len(corpus.real_prompts)} prompts que realmente tipeaste (de {corpus.user_records:,} registros de usuario — el resto eran salida de herramientas, turnos de subagentes o texto de sistema)",
        f"el prompt mediano tiene {d.get('median_chars','?')} caracteres ({d.get('median_words','?')} palabras); {d.get('under_80_pct','?')}% están bajo los 80 chars",
        f"{active_h:.0f} horas de tiempo activo manos a la obra (se excluyen los gaps de inactividad de más de 5 min)",
        f"{result['detail']['Toolcraft']['distinct']} herramientas distintas usadas; {corpus.total_tool_calls:,} llamadas a herramientas en total",
        f"herramienta más usada: {corpus.tool_usage.most_common(1)[0][0] if corpus.tool_usage else 'n/a'}",
        f"{corpus.delegation_events} delegaciones (subagentes / jobs en background / planificación)",
    ]
    facts_html = "".join(f"<li>{_esc(f)}</li>" for f in facts)
    assessment_html = build_assessment(corpus, result, cards)

    # "What to improve": prefer the Opus analysis's tailored growth cards (grounded in this
    # person's real prompts). Only fall back to the generic teaching examples when no AI
    # analysis ran — so a finished report is personalized, not a library of stock examples.
    growth_cards = _growth_cards_html(analysis)
    if growth_cards:
        improve_cards = growth_cards
        improve_intro = ('<p class="exgen" style="margin-bottom:14px">Escrito para vos por Claude '
                         'Opus&nbsp;4.8 a partir de tus prompts reales — tus movimientos de mayor palanca, cada '
                         'uno con uno de tus prompts reescrito.</p>')
    else:
        improve_cards = cards_html
        improve_intro = ""

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tu reporte de Fluidez con IA</title>
<style>
:root{{--bg:#0c0d18;--p:#15172a;--p2:#1d2040;--ink:#eef0ff;--mut:#a4a8cc;--line:#2a2d52;
--ac:#7c5cff;--ac2:#3ad6c9;--good:#3ad68a;--warn:#ffb454;--bad:#ff6b8b;}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:radial-gradient(1100px 640px at 72% -12%,#262a55 0%,var(--bg) 55%);color:var(--ink);
font:16px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;padding-bottom:80px}}
.wrap{{max-width:880px;margin:0 auto;padding:0 22px}}
header{{text-align:center;padding:60px 0 12px}}
.kick{{letter-spacing:.22em;text-transform:uppercase;font-size:12px;color:var(--mut)}}
h1{{font-size:34px;margin:10px 0 4px}}
.sub{{color:var(--mut);max-width:620px;margin:6px auto 0;font-size:15px}}
.hero{{margin:30px auto 0;display:flex;gap:22px;align-items:stretch;flex-wrap:wrap;justify-content:center}}
.score-card{{background:linear-gradient(135deg,var(--p2),var(--p));border:1px solid var(--line);border-radius:22px;
padding:26px 30px;text-align:center;min-width:240px;box-shadow:0 18px 50px rgba(0,0,0,.4)}}
.ring{{position:relative;width:170px;height:170px;margin:0 auto}}
.ring .n{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}}
.ring .n b{{font-size:50px;line-height:1}}
.ring .n s{{text-decoration:none;color:var(--mut);font-size:13px}}
.band{{margin-top:12px;font-size:19px;font-weight:700;color:var(--ac2)}}
.rawnote{{color:var(--mut);font-size:12px;margin-top:4px}}
.arch{{flex:1;min-width:260px;background:var(--p);border:1px solid var(--line);border-radius:22px;padding:24px 26px;text-align:left}}
.arch .emoji{{font-size:40px}}
.arch h2{{font-size:23px;margin:6px 0}}
.arch p{{color:var(--mut);font-size:15px}}
.prov{{background:rgba(255,180,84,.1);border:1px solid rgba(255,180,84,.35);color:#ffe6c2;border-radius:12px;padding:12px 16px;margin:22px 0 0;font-size:14px}}
section{{margin:42px 0}}
h3{{font-size:13px;letter-spacing:.16em;text-transform:uppercase;color:var(--mut);border-bottom:1px solid var(--line);padding-bottom:10px;margin-bottom:18px}}
.band-meaning{{background:var(--p);border:1px solid var(--line);border-left:4px solid var(--ac);border-radius:12px;padding:16px 20px;color:#dfe2ff}}
.assess{{background:var(--p);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin-bottom:12px;font-size:15.5px;line-height:1.7;color:#e8eaff}}
.assess b{{color:#fff}}
.ingest{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.ing{{background:var(--p);border:1px solid var(--line);border-radius:14px;padding:14px 16px}}
.ing .n{{font-size:24px;font-weight:700;color:var(--ac2)}}
.ing .l{{color:var(--mut);font-size:13px;margin-top:2px}}
.honesty{{margin-top:16px;background:var(--p);border:1px solid var(--line);border-radius:14px;padding:16px 20px}}
.honesty b{{color:var(--ink)}}
.honesty ul{{list-style:none;display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:8px}}
.honesty li{{color:var(--mut);font-size:14px}}
.dim{{background:var(--p);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin-bottom:12px}}
.dim .top{{display:flex;justify-content:space-between;align-items:baseline}}
.dim .name{{font-weight:700;font-size:17px}}
.dim .sval{{font-size:22px;font-weight:800}} .dim .hint{{color:var(--mut);font-size:12px;font-weight:400}}
.dim-h{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:6px}}
.dim-h b{{font-size:17px}}
.pill{{font-size:12px;font-weight:700;color:var(--ink);background:var(--p2);border:1px solid var(--line);border-radius:99px;padding:3px 11px;white-space:nowrap}}
.ev{{margin:8px 0 0 0;padding-left:18px}} .ev li{{color:var(--mut);font-size:14px;margin:3px 0}}
.next{{margin-top:8px;font-size:14.5px}} .next b{{color:#fff}}
.bar{{height:9px;background:#23264a;border-radius:99px;overflow:hidden;margin:11px 0 9px}}
.bar>i{{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--ac),var(--ac2))}}
.def{{color:var(--ink);font-size:14.5px}} .rate{{color:var(--mut);font-size:13px;margin-top:3px}} .wt{{opacity:.7}}
.tag{{font-size:10.5px;padding:2px 8px;border-radius:99px;font-weight:700;margin-left:6px;vertical-align:middle}}
.tag.s{{background:rgba(58,214,138,.16);color:var(--good)}} .tag.w{{background:rgba(255,107,139,.16);color:var(--bad)}}
.tag.ld{{background:rgba(164,168,204,.16);color:var(--mut)}}
.bar-item{{display:flex;align-items:center;gap:12px;margin:7px 0}}
.bl{{min-width:160px;font-size:14px}} .bt{{flex:1;height:7px;background:#23264a;border-radius:99px;overflow:hidden}}
.bt>i{{display:block;height:100%;background:linear-gradient(90deg,var(--ac),var(--ac2))}} .bv{{min-width:46px;text-align:right;color:var(--mut);font-size:13px}}
.card{{background:var(--p);border:1px solid var(--line);border-radius:16px;padding:18px 22px;margin-bottom:14px}}
.prio{{border-left:4px solid var(--warn)}} .keep{{border-left:4px solid var(--good)}}
.ph{{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--mut)}}
.pscore{{float:right;color:var(--ac2);letter-spacing:0}}
.card h4{{font-size:18px;margin:8px 0 12px}}
.wwh{{margin:12px 0}} .wwh .lab{{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin-bottom:6px}}
ul.ev{{list-style:none}} ul.ev li{{background:var(--p2);border-radius:9px;padding:9px 12px;margin-bottom:7px;font-size:14px}}
.loc{{color:var(--mut);font-size:12.5px}} .ev-none{{color:var(--good);font-size:14px}}
.ba{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px}}
.why{{color:var(--mut);font-size:14px;margin:2px 0 4px}} .why b{{color:var(--ink)}}
.how{{font-size:14.5px;margin:0 0 4px}}
.exgen{{font-size:12px;color:var(--mut);margin:8px 0 2px;font-style:italic}}
.sk-what{{color:var(--ink);font-size:13.5px;margin-top:5px}}
.lvl{{font-size:11px;color:var(--ac2);font-weight:600;margin-left:6px}}
.before,.after{{border-radius:10px;padding:10px 13px;font-size:14px}}
.before{{background:rgba(255,107,139,.08);color:#ffd0da}} .after{{background:rgba(58,214,138,.08);color:#cfeede}}
.before span,.after span{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.08em;opacity:.7;margin-bottom:3px}}
.tgt{{margin-top:10px;color:var(--ac2);font-size:14px}}
.skill{{background:var(--p);border:1px solid var(--line);border-radius:14px;padding:14px 18px;margin-bottom:10px}}
.sk-top{{display:flex;justify-content:space-between;align-items:center}} .sk-name{{font-weight:700}}
.dot{{display:inline-block;width:11px;height:11px;border-radius:50%;background:#2a2d52;margin-left:4px}}
.dot.on{{background:linear-gradient(135deg,var(--ac),var(--ac2))}}
.sk-now{{color:var(--mut);font-size:13.5px;margin-top:6px}} .sk-next{{font-size:13.5px;margin-top:3px}}
.facts{{list-style:none}} .facts li{{background:var(--p);border:1px solid var(--line);border-radius:10px;padding:11px 15px;margin-bottom:8px;font-size:14.5px}}
.facts li::before{{content:"›";color:var(--ac2);font-weight:800;margin-right:9px}}
details{{background:var(--p);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin-top:14px}}
summary{{cursor:pointer;color:var(--mut);font-size:14px}} details p,details li{{color:var(--mut);font-size:13px;margin-top:8px}}
footer{{text-align:center;color:var(--mut);font-size:13px;margin-top:46px}}
code{{background:#23264a;padding:1px 6px;border-radius:5px;font-size:13px}}
@media(max-width:640px){{.ba{{grid-template-columns:1fr}}.bl{{min-width:120px}}}}
</style></head><body><div class="wrap">

<header>
  <div class="kick">Claude Insight · Reporte de Fluidez con IA</div>
  <h1>Qué tan hábilmente construís con IA</h1>
  <p class="sub">Una lectura de cómo conducís realmente Claude Code — medida a partir de tus prompts reales y las acciones reales de Claude, analizada por completo en tu máquina.</p>
</header>

{prov_banner}

<div class="hero">
  <div class="score-card">
    <div class="ring">
      <svg width="170" height="170" style="transform:rotate(-90deg)">
        <circle cx="85" cy="85" r="74" fill="none" stroke="#23264a" stroke-width="12"/>
        <circle cx="85" cy="85" r="74" fill="none" stroke="url(#g)" stroke-width="12" stroke-linecap="round"
          stroke-dasharray="{2*math.pi*74*result['overall']/100:.0f} 999"/>
        <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="#3ad6c9"/></linearGradient></defs>
      </svg>
      <div class="n"><b>{result['overall']}</b><s>/ 100</s></div>
    </div>
    <div class="band">{_esc(result['band'])}</div>
    <div class="rawnote">crudo {result['overall_raw']} · ajustado por confianza {result['overall']}</div>
  </div>
  <div class="arch">
    <div class="emoji">{PROTOTYPES[a['primary']]['emoji']}</div>
    <h2>{_esc(a['label'])}</h2>
    <p>{_esc(a['blurb'])}</p>
    <p style="margin-top:10px;font-size:13px">Coincidencia más cercana {a['primary_sim']:+.2f}, el siguiente es {_esc(a['secondary'].replace('The ',''))} {a['secondary_sim']:+.2f}{' — cerca, así que esto es una mezcla' if a['blended'] else ''}. Construido a partir de cómo conducís <b>vos</b> — tus briefs, correcciones, elecciones de herramientas y cuánto delegás ({a['delegation_score']}/100 de delegación) — y descuenta deliberadamente los hábitos de leer-antes-de-editar y correr-los-tests que Claude hace por su cuenta, así que te refleja a vos, no al agente.</p>
    <p style="margin-top:8px;font-size:12.5px;color:var(--mut)">Tu <b>puntaje</b> mide la calidad de la colaboración (vos + Claude); tu <b>arquetipo</b> mide tu estilo de conducción solo — así que pueden diferir a propósito.</p>
    {arch_hedge}
  </div>
</div>

<section>
  <h3>Evaluación profesional</h3>
  {assessment_html}
</section>

<section>
  <h3>Qué significa tu puntaje</h3>
  <div class="band-meaning"><b>{_esc(result['band'])} ({result['overall']}/100).</b> {_esc(result['band_meaning'])}</div>
</section>

<section>
  <h3>En cuántos datos se basa esto</h3>
  <div class="ingest">
    <div class="ing"><div class="n">{corpus.files}</div><div class="l">sesiones escaneadas</div></div>
    <div class="ing"><div class="n">{len(corpus.projects)}</div><div class="l">proyectos</div></div>
    <div class="ing"><div class="n">{corpus.total_bytes/1e6:.1f} MB</div><div class="l">datos de transcripts parseados</div></div>
    <div class="ing"><div class="n">{days} días</div><div class="l">período de actividad</div></div>
    <div class="ing"><div class="n">{len(corpus.real_prompts)}</div><div class="l">prompts reales que tipeaste</div></div>
    <div class="ing"><div class="n">{active_h:.0f} h</div><div class="l">tiempo activo manos a la obra</div></div>
    {archive_tile}
  </div>
  {retention_note}
  <div class="honesty">
    <b>La parte honesta:</b> encontramos {corpus.user_records:,} registros “de usuario” pero solo <b>{len(corpus.real_prompts)}</b> son prompts que tipeaste <b>vos</b>. Filtramos {filtered_total:,} que la herramienta vieja contaba mal:
    <ul>{filt}</ul>
    <p style="color:var(--mut);font-size:13px;margin-top:10px">Tus prompts reales: mediana {d.get('median_chars','?')} chars · {d.get('under_80_pct','?')}% bajo los 80 chars · {active_h:.0f} h de tiempo activo manos a la obra (los gaps de inactividad de más de 5 min se excluyen — no es tiempo de reloj crudo).</p>
  </div>
</section>

{analysis_section}
{analysis_status_html}

<section>
  <h3>Las cinco dimensiones</h3>
  {dim_html}
</section>

<section>
  <h3>Qué mejorar — y exactamente cómo</h3>
  {improve_intro}
  {improve_cards}
  {strength_html}
</section>

<section>
  <h3>Tu mapa de habilidades</h3>
  {skill_html}
</section>

<section>
  <h3>Afinidad de arquetipo</h3>
  {aff}
</section>

<section>
  <h3>Números honestos al pasar</h3>
  <ul class="facts">{facts_html}</ul>
</section>

<section>
  <h3>Metodología y honestidad</h3>
  <details><summary>Cómo se computó cada número (clic para expandir)</summary>
    <p><b>Solo se puntúan los prompts reales.</b> Un registro “de usuario” cuenta como prompt solo si no es una salida de herramienta, ni un turno de subagente (sidechain), ni meta/inyectado, ni un stub de slash-command, ni un pegado/system-prompt de más de {MAX_HUMAN_PROMPT_CHARS:,} chars o que abre con “Sos un …”. Esto saca la contaminación que hacía que la herramienta vieja reportara un promedio de {d.get('mean_chars','?')} contra el real.</p>
    <p><b>Todo es una tasa, después aplastada.</b> Cada dimensión es una tasa por-prompt o por-oportunidad pasada por min(1, tasa/objetivo), así que hacer más trabajo nunca sube el puntaje — solo hacerlo mejor lo sube. Pesos: Instrucción 24%, Verificación 22%, Contexto 22%, Iteración 18%, Herramientas 14%.</p>
    <p><b>Las señales finitas se matizan, no se inventan.</b> Cada dimensión se tira hacia un 50 neutro en proporción a cuántas oportunidades tuvo (ej. Iteración tuvo solo {result['detail']['Iteration']['corrections']} correcciones, así que se marca “pocos datos”). Se muestran tanto el puntaje crudo como el ajustado por confianza.</p>
    <p>El <b>arquetipo</b> describe tu <b>estilo de conducción</b>, no la calidad de la colaboración, así que se construye sobre un vector aparte <b>ponderado por agencia</b>: Instrucción, Iteración, Herramientas y Delegación (hand-offs a subagentes/jobs en background/planificación) cuentan por completo, mientras que Verificación y Contexto — hábitos que Claude hace mayormente por su cuenta — se descuentan ({int(AGENCY['Verification']*100)}% y {int(AGENCY['Context']*100)}% de peso). Es el prototipo más cercano por coseno sobre valores en z-score; si los dos primeros están dentro de {ARCHETYPE_MARGIN} mostramos una mezcla. El <b>tiempo activo</b> tope a los gaps de inactividad en {GAP_CAP_SECONDS//60} min. <b>Arreglos vs v1:</b> mal conteo de prompts, inflación de longitud, sobreconteo de tiempo inactivo, arquetipo random, diversidad de herramientas sin tope, y falsos positivos por la palabra “error”.</p>
    <p><b>Límites:</b> esto mide comportamiento observable, no intención; los detectores son heurísticos y sesgados al inglés; es una única foto, no una tendencia. Los prompts escuetos que arrastran intención del turno anterior pueden subpuntuar Instrucción.</p>
  </details>
</section>

<footer>Generado localmente por Claude Insight v2 · tus transcripts nunca salieron de esta máquina.</footer>
</div></body></html>"""


def _skill_levels(result):
    """Map dimension scores to L1-L5 skill levels with now/next text."""
    def lvl(score):
        return max(1, min(5, int(score // 20) + 1))
    s = result["shrunk"]
    defs = [
        ("Instrucción y especificidad", "Direction",
         "nombrar un objetivo + un ancla (path, restricción o test de aceptación) en la mayoría de los prompts de acción",
         {1: "Mayormente empujones cortos con poco contexto.", 2: "Contexto ocasional; a veces una restricción.",
          3: "La mayoría de los prompts llevan un objetivo + un ancla.", 4: "Objetivo + restricción + criterio son comunes.",
          5: "Consistentemente de alto contexto con reglas front-loadeadas."}),
        ("Disciplina de verificación", "Verification",
         "cerrar las ráfagas de edición corriendo los tests / la app antes de seguir",
         {1: "Ediciones aceptadas a ciegas, casi sin chequeos.", 2: "Verifica de vez en cuando.",
          3: "Verifica la mayoría de las ráfagas de ediciones.", 4: "Verifica casi todos los cambios.",
          5: "Verificar es un reflejo — enunciado de entrada y por capas."}),
        ("Anclaje de contexto (leer→editar)", "Context",
         "hacer que el agente lea el archivo objetivo antes de cambiarlo",
         {1: "Suele editar archivos que nunca leyó.", 2: "Lee antes de editar la mitad de las veces.",
          3: "Suele apuntar al agente al lugar correcto primero.", 4: "Rutinariamente lee el objetivo + deps antes de cambiar.",
          5: "Exploración deliberada antes de cambios no triviales."}),
        ("Iteración y recuperación", "Iteration",
         "lograr que las correcciones nombren un síntoma + la regla exacta, en una línea",
         {1: "Rechazos de poca info, loops largos.", 2: "Corrige pero vagamente.",
          3: "Mezcla correcciones precisas y peladas.", 4: "Baja tasa de corrección, mayormente específica.",
          5: "Feedback quirúrgico; convierte los errores en reglas reutilizables."}),
        ("Herramientas y orquestación", "Toolcraft",
         "ir más allá de la shell — búsqueda, planificación, delegación para los trabajos justos",
         {1: "Efectivamente una sola herramienta.", 2: "El trío central (Bash/Read/Edit).",
          3: "Suma búsqueda/web y algo de planificación.", 4: "Cómodo con MCP + reparto equilibrado.",
          5: "20+ herramientas usadas apropiadamente, baja concentración."}),
    ]
    out = []
    for name, dim, nxt, rub in defs:
        L = lvl(s[dim])
        out.append({"name": name, "dim": dim, "level": L, "now": rub[L],
                    "what": SKILL_TEACH[dim]["what_it_is"],
                    "next": nxt if L < 5 else "mantené esto — es una fortaleza real."})
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude Insight v2 — analizador de fluidez con IA (un comando, cero instalación).")
    ap.add_argument("path", nargs="?", help="directorio de transcripts o archivo .jsonl (default: ~/.claude/projects)")
    ap.add_argument("-o", "--out", default="reporte_fluidez_ia.html", help="path de salida del HTML")
    ap.add_argument("--json", action="store_true", help="imprimir las métricas crudas como JSON y salir")
    ap.add_argument("--no-open", action="store_true", help="no abrir el reporte automáticamente en el browser")
    ap.add_argument("--archive", default=os.environ.get("CLAUDE_INSIGHT_ARCHIVE", DEFAULT_ARCHIVE_DIR),
                    metavar="DIR",
                    help="archivo persistente que preserva los transcripts más allá de la limpieza de "
                         "30 días de Claude Code para que el historial se acumule (default ~/.claude/insight-archive; "
                         "mantenelo privado para vos — una carpeta compartida entre personas mezcla sus datos)")
    ap.add_argument("--no-archive", action="store_true",
                    help="no copiar los transcripts de esta corrida al archivo (igual lee uno existente)")
    ap.add_argument("--evidence", metavar="PATH",
                    help="escribir el bundle de evidencia descontaminada (JSON) para el pipeline de "
                         "análisis de dos modelos en PATH ('-' para stdout), después continuar")
    ap.add_argument("--analysis", metavar="PATH",
                    help="fusionar un análisis de IA (JSON de la etapa Opus) en el mapa de habilidades del reporte")
    ap.add_argument("--analysis-evidence", metavar="PATH", dest="analysis_evidence",
                    help="el bundle de evidencia del que se produjo el --analysis; su run_fingerprint "
                         "se chequea contra esta corrida para que no se pueda fusionar un análisis viejo/ajeno")
    ap.add_argument("--quiet", action="store_true",
                    help="suprimir el resumen de terminal (la pasada de medición interna de la skill lo usa "
                         "para que el puntaje no se muestre antes de que el reporte completo de IA esté listo)")
    args = ap.parse_args(argv)

    files = discover_files(args.path)

    # Default mode: maintain + read the persistent archive so we can analyze more than the
    # ~30 days Claude Code keeps on disk. Skipped when an explicit path is given.
    archive_info = None
    if not args.path:
        archive_dir = os.path.expanduser(args.archive)
        new = updated = 0
        if not args.no_archive:
            new, updated = archive_transcripts(files, archive_dir)
        arch_files = _filter_transcripts(glob.glob(os.path.join(archive_dir, "**", "*.jsonl"), recursive=True))
        merged = _dedupe_sessions(files + arch_files)
        archive_info = {
            "dir": args.archive, "enabled": not args.no_archive,
            "live_sessions": len(files), "archived_sessions": len(arch_files),
            "merged_sessions": len(merged), "new": new, "updated": updated,
        }
        files = merged
        # If most of what we're analyzing comes only from the archive (not this machine's
        # live transcripts), a shared/synced archive could be feeding in someone else's data.
        archive_only = archive_info["merged_sessions"] - archive_info["live_sessions"]
        if archive_only > max(25, 2 * archive_info["live_sessions"]):
            print(f"  Nota: {archive_only} de {archive_info['merged_sessions']} sesiones analizadas existen "
                  f"solo en el archivo ({args.archive}), no en tus transcripts vivos. Si ese archivo "
                  f"está compartido o sincronizado entre personas/máquinas, este reporte puede mezclar datos que no "
                  f"son tuyos — apuntá --archive a un path privado, por persona.", file=sys.stderr)

    if not files:
        where = args.path or "~/.claude/projects"
        print(f"No se encontraron transcripts de Claude Code en {where}.\n"
              f"Apuntá a tus transcripts con:  python3 insight.py /ruta/al/directorio", file=sys.stderr)
        return 1

    corpus = parse(files)
    if not corpus.real_prompts:
        print("Se encontraron transcripts pero no hay prompts reales tipeados por una persona para analizar.", file=sys.stderr)
        return 1

    result = analyze(corpus)
    cards, strength = build_action_plan(corpus, result)

    if args.evidence:
        bundle = build_evidence(corpus, result, cards, archive_info)
        text = json.dumps(bundle, indent=2)
        if args.evidence == "-":
            print(text)
        else:
            ep = os.path.abspath(args.evidence)
            os.makedirs(os.path.dirname(ep) or ".", exist_ok=True)
            with open(ep, "w", encoding="utf-8") as f:
                f.write(text)
            if not args.quiet:
                print(f"  Evidencia: {ep}", file=sys.stderr)

    analysis = None
    analysis_note = None
    if args.analysis:
        try:
            with open(os.path.expanduser(args.analysis), encoding="utf-8") as f:
                analysis = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"No se pudo leer --analysis {args.analysis}: {e}", file=sys.stderr)
            return 1
        # Don't blindly trust the analysis file: it lives at a fixed, reused path, so it
        # may be empty (the AI stage no-op'd) or left over from a different run/person.
        # Validate shape + provenance; on any failure render the deterministic report
        # only, and say so, rather than pasting someone else's verdict into this report.
        current_fp = result.get("fingerprint")
        if not isinstance(analysis, dict) or not analysis.get("skill_map"):
            print("  Nota: --analysis no tenía un mapa de habilidades usable (puede que la etapa de IA no haya corrido); "
                  "renderizando solo el reporte determinístico.", file=sys.stderr)
            analysis_note = "la etapa de mapa de habilidades de IA no devolvió salida usable"
            analysis = None
        elif args.analysis_evidence:
            # Deterministic provenance gate: the analysis is valid for this run only if the
            # evidence it was built from fingerprints to THIS run's data. insight.py wrote
            # that fingerprint, so this check never depends on the model copying anything.
            evidence_fp = None
            try:
                with open(os.path.expanduser(args.analysis_evidence), encoding="utf-8") as f:
                    evidence_fp = (json.load(f).get("meta") or {}).get("run_fingerprint")
            except (OSError, json.JSONDecodeError):
                evidence_fp = None
            if evidence_fp != current_fp:
                print(f"  Nota: el --analysis no coincide con esta corrida (su fingerprint de evidencia "
                      f"{evidence_fp} != {current_fp}). Lo ignoramos para que no se filtre en este "
                      f"reporte; renderizando solo el reporte determinístico.", file=sys.stderr)
                analysis_note = ("el análisis de IA guardado se produjo a partir de otra corrida / "
                                 "dataset, así que no se usó")
                analysis = None
        else:
            # Manual --analysis with no evidence binding: if the file itself happens to carry a
            # run_fingerprint, honor it; otherwise merge (back-compat with hand-written analyses).
            supplied_fp = analysis.get("run_fingerprint")
            if supplied_fp and current_fp and supplied_fp != current_fp:
                print(f"  Nota: el --analysis provisto se produjo a partir de OTRA corrida "
                      f"(fingerprint {supplied_fp} != {current_fp}). Lo ignoramos para que no se "
                      f"filtre en este reporte; renderizando solo el reporte determinístico.",
                      file=sys.stderr)
                analysis_note = ("el análisis de IA guardado se produjo a partir de otra corrida / "
                                 "dataset, así que no se usó")
                analysis = None

    if args.json:
        payload = {
            "overall": result["overall"], "overall_raw": result["overall_raw"],
            "band": result["band"], "archetype": result["archetype"]["label"],
            "dimensions_raw": result["raw"], "dimensions_adjusted": result["shrunk"],
            "confidence": result["conf"], "detail": result["detail"],
            "data_ingested": {
                "files": corpus.files, "projects": len(corpus.projects),
                "bytes": corpus.total_bytes, "user_records": corpus.user_records,
                "real_prompts": len(corpus.real_prompts), "filtered": dict(corpus.filtered),
                "active_hours": round(corpus.active_seconds / 3600, 1),
                "prompt_distribution": result["dist"],
                "archive": archive_info,
            },
        }
        print(json.dumps(payload, indent=2))
        return 0

    # Render fully before touching the file, so a render error can't leave a 0-byte report.
    html_doc = build_html(corpus, result, cards, strength, archive_info, analysis, analysis_note)
    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    if not args.quiet:
        print(terminal_summary(corpus, result))
        if archive_info and archive_info["enabled"]:
            print(f"  Archivo: {archive_info['merged_sessions']} sesiones preservadas en "
                  f"{archive_info['dir']} ({archive_info['new']} nuevas, {archive_info['updated']} actualizadas esta corrida).")
        print(f"  Reporte: {out_path}\n")
    if not args.no_open:
        try:
            webbrowser.open(f"file://{out_path}")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
