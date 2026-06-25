"""Tests para la skill /fluidez-ia de Claude Code y su instalador.

El layout de este repo es PLANO (SKILL.md, workflow.js, insight.py en la raíz):
el instalador los copia a ~/.claude/skills/fluidez-ia/ y ~/.claude/workflows/.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "SKILL.md"
WORKFLOW = REPO_ROOT / "workflow.js"
FRAMEWORK = REPO_ROOT / "reference" / "framework-fluidez-ia.md"
INSTALL = REPO_ROOT / "install.sh"


class SkillFilesTests(unittest.TestCase):
    def test_skill_pieces_exist(self):
        self.assertTrue(SKILL.exists(), "SKILL.md debe existir")
        self.assertTrue(WORKFLOW.exists(), "el workflow que invoca la skill debe existir")
        self.assertTrue(FRAMEWORK.exists(), "el framework que lee el workflow debe existir")
        self.assertTrue((REPO_ROOT / "insight.py").exists(), "el motor que corre la skill debe existir")

    def test_frontmatter_has_required_fields(self):
        text = SKILL.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", text, re.S)
        self.assertIsNotNone(match, "SKILL.md debe arrancar con un bloque de frontmatter YAML")
        fm = match.group(1)
        self.assertRegex(fm, r"(?m)^name:\s*fluidez-ia\s*$")
        self.assertRegex(fm, r"(?m)^description:\s*\S")
        # La skill debe invocar el motor y el workflow de dos modelos.
        self.assertIn("insight.py", text)
        self.assertIn("Workflow", text)


class WorkflowNameConsistencyTests(unittest.TestCase):
    """Regresión: el nombre que el workflow DECLARA (meta.name) tiene que ser el mismo
    que SKILL.md le PASA a la herramienta Workflow. Si difieren, el Paso 2 no encuentra
    el workflow y la corrida cae al fallback determinístico en silencio."""

    def _declared_workflow_name(self):
        wf = WORKFLOW.read_text(encoding="utf-8")
        m = re.search(r"name:\s*'([^']+)'", wf)
        self.assertIsNotNone(m, "workflow.js debe declarar meta.name")
        return m.group(1)

    def _name_skill_invokes(self):
        text = SKILL.read_text(encoding="utf-8")
        # El Paso 2 instruye: llamar a Workflow con `name`: `<nombre>`
        m = re.search(r"`name`:\s*`([^`]+)`", text)
        self.assertIsNotNone(m, "SKILL.md debe indicar qué `name` pasarle a Workflow")
        return m.group(1)

    def test_workflow_name_matches_skill_invocation(self):
        declared = self._declared_workflow_name()
        invoked = self._name_skill_invokes()
        self.assertEqual(
            declared, invoked,
            f"workflow.js declara meta.name='{declared}' pero SKILL.md invoca '{invoked}' "
            f"— deben coincidir o el workflow no se resuelve",
        )
        self.assertEqual(declared, "fluidez-ia")


class InstallerTests(unittest.TestCase):
    def test_installer_places_every_skill_piece(self):
        text = INSTALL.read_text(encoding="utf-8")
        for needed in ("insight.py", "framework-fluidez-ia.md", "SKILL.md", "workflow.js",
                       "fluidez-ia.js", ".claude/skills/fluidez-ia", ".claude/workflows"):
            self.assertIn(needed, text, f"el instalador debería referenciar {needed}")


if __name__ == "__main__":
    unittest.main()
