#!/usr/bin/env bash
set -euo pipefail

# Fluidez con IA — instala la skill /fluidez-ia en Claude Code.
# Uso:  curl -fsSL https://raw.githubusercontent.com/martinviretti/fluidez-ia/main/install.sh | bash
#
# Después, abrí Claude Code en cualquier carpeta y corré:  /fluidez-ia

REPO="martinviretti/fluidez-ia"
SKILL_DIR="${HOME}/.claude/skills/fluidez-ia"
WF_DIR="${HOME}/.claude/workflows"

echo "🔍 Instalando la skill /fluidez-ia"
echo "===================================="

# --- Detectar un Python 3.8+ que REALMENTE corra -------------------------------
# (en Windows, 'python3' suele ser un alias del Store que no ejecuta nada: por eso
#  validamos corriéndolo, no solo con 'command -v'.)
PY=""
for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' >/dev/null 2>&1; then
      PY="$c"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "❌ Necesitás Python 3.8+ y no encontré uno que funcione. Instalalo y reintentá."
  exit 1
fi
echo "✅ Python detectado: $PY"

# --- Resolver el último release tagueado (fallback a main) ---------------------
REF="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null \
  | grep '"tag_name"' | head -1 | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
if [ -n "${REF:-}" ]; then
  echo "📦 Release: ${REF}"
  URL="https://github.com/${REPO}/archive/refs/tags/${REF}.tar.gz"
  DIRNAME="fluidez-ia-${REF#v}"
else
  echo "ℹ️  Sin releases — uso main."
  URL="https://github.com/${REPO}/archive/refs/heads/main.tar.gz"
  DIRNAME="fluidez-ia-main"
fi

# --- Descargar el repo a un temp y copiar los 4 archivos -----------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "📥 Descargando…"
if ! curl -fsSL "$URL" | tar -xz -C "$TMP"; then
  echo "❌ Falló la descarga. Revisá tu conexión y reintentá."
  exit 1
fi
SRC="${TMP}/${DIRNAME}"

mkdir -p "$SKILL_DIR/reference" "$WF_DIR"
cp "$SRC/insight.py"                          "$SKILL_DIR/insight.py"
cp "$SRC/reference/framework-fluidez-ia.md"   "$SKILL_DIR/reference/framework-fluidez-ia.md"
cp "$SRC/workflow.js"                          "$WF_DIR/fluidez-ia.js"
# La SKILL.md usa 'python3'; lo reemplazamos por el intérprete detectado en ESTA máquina.
sed "s/python3/${PY}/g" "$SRC/SKILL.md" > "$SKILL_DIR/SKILL.md"

echo "✅ Instalado:"
echo "   • skill    → $SKILL_DIR"
echo "   • workflow → $WF_DIR/fluidez-ia.js"
echo ""
echo "🎉 Listo. Abrí Claude Code en cualquier carpeta y corré:"
echo ""
echo "      /fluidez-ia"
echo ""
echo "   El reporte queda en ~/.claude/fluidez-ia/reporte_fluidez_ia.html"
