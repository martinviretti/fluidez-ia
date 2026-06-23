# Fluidez con IA — framework de referencia para la etapa de análisis

> Esta es la base de conocimiento sobre la que se apoya la **etapa de análisis de Opus 4.8**.
> Es deliberadamente autocontenida y offline para que la evaluación sea reproducible y no
> dependa de una red en vivo. Actualizá este archivo para refinar qué significa "bueno".

La fluidez con IA es la capacidad de **trabajar con sistemas de IA de forma efectiva, eficiente
y responsable**. Es una *habilidad*, no un volumen de uso — hacer más cosas con un agent no te
vuelve más fluido; hacerlas de forma más deliberada, sí.

Evaluamos la fluidez con el **framework de las 4D** (Delegación, Descripción, Discernimiento,
Diligencia), adaptado de *AI Fluency: Frameworks & Foundations* de Anthropic (Rick Dakan y
Joseph Feller). Las 4D son las **competencias**. El motor determinístico (`insight.py`) mide
**señales** observables a partir de los transcripts; esta etapa mapea esas señales sobre las 4D
y las convierte en un mapa de habilidades amable, específico y basado en niveles.

---

## Las cuatro competencias

### 1. Delegación (Delegation) — *decidir qué le pasás a la IA, y cuánto*
Saber qué trabajo hacer vos mismo, qué pasarle al agent, y cómo partir un objetivo en piezas
del tamaño adecuado para el agent. Tres sub-habilidades:
- **Conciencia del problema** — tener claro qué querés realmente antes de delegar.
- **Conciencia de la plataforma** — saber en qué es bueno/malo este agent, y rutear el trabajo en consecuencia.
- **Conciencia del camino** — elegir *cómo* llegar: un hand-off grande, un loop ajustado, sub-agents, jobs en background, planificar primero.

**Señales observables:** eventos de delegación (sub-agents, tareas en background, planificación),
amplitud de tools que se usan, hand-offs de punta a punta vs. micro-pasos, si los objetivos se
acotan antes de arrancar el trabajo.

### 2. Descripción (Description) — *decirle a la IA qué querés*
La competencia de prompting: comunicar la intención, las restricciones y la forma que tiene una
buena respuesta. Tres sub-habilidades:
- **Descripción del producto** — qué debería ser el output (el objetivo, el archivo, el test de aceptación).
- **Descripción del proceso** — cómo llegar ahí (pasos, orden, qué tocar / qué no tocar).
- **Descripción del desempeño** — el estilo/rol/formato que el agent debería adoptar.

**Señales observables:** ¿los prompts nombran un artefacto concreto (archivo, path, error)? ¿llevan
una restricción ("tocá solo X", "no cambies Y")? ¿plantean un *por qué* / criterio de aceptación?
Los one-liners escuetos que delegan las decisiones puntúan más bajo; los briefs específicos y
cargados por adelantado puntúan más alto.

### 3. Discernimiento (Discernment) — *evaluar lo que la IA te devuelve*
Juzgar críticamente los outputs, el proceso y el comportamiento en lugar de aceptarlos. Tres
sub-habilidades:
- **Discernimiento del producto** — chequear que el resultado sea realmente correcto (tests, build, run, leer antes de confiar).
- **Discernimiento del proceso** — notar cuándo el agent tomó un mal camino y redirigirlo.
- **Discernimiento del desempeño** — juzgar si el estilo de interacción te está sirviendo.

**Señales observables:** verificación después de ráfagas de ediciones (tests/build/run), anclar
las ediciones en una lectura previa, corregir con precisión (nombrar el síntoma + la regla) en
lugar de un rechazo vago, desmontar prolijamente lo que se levantó.

### 4. Diligencia (Diligence) — *ser responsable con la IA*
Usar la IA de forma reflexiva y responsable. Tres sub-habilidades:
- **Diligencia en la creación** — hacerte cargo de lo que entregás; no publicar a ciegas el trabajo generado.
- **Diligencia en la transparencia** — ser honesto sobre la participación de la IA donde importa.
- **Diligencia en el deployment** — verificar antes de que las cosas salgan a producción; limpiar; no dejar quilombos.

**Señales observables:** disciplina de verificación, desmontaje de sistemas en vivo, ediciones
ancladas (no a ciegas), revisar antes de seguir. (Esta competencia se solapa con Discernimiento
en un transcript de coding; ponderá el ángulo de *responsabilidad* — ¿chequearon antes de que
importara?)

---

## Cómo se mapean las señales del motor sobre las 4D

`insight.py` reporta cinco dimensiones + un eje de Delegación. Mapealas así:

| Señal del motor (dimensión) | Competencia 4D primaria | También informa |
|---|---|---|
| **Briefing / Dirección** (tasas de restricción, artefacto, intención) | Descripción | Delegación (conciencia del problema) |
| **Eje de Delegación** (hand-offs / hr: sub-agents, background, planificación) | Delegación | — |
| **Toolcraft** (amplitud de tools, parejidad, orquestación) | Delegación (plataforma y camino) | — |
| **Verificación** (tests/build/run después de ediciones; teardown) | Discernimiento | Diligencia |
| **Seteo de contexto** (anclar leyendo antes de editar) | Discernimiento | Diligencia |
| **Iteración** (tasa de corrección + especificidad) | Descripción (re-descripción) | Discernimiento |

Dos advertencias que el analista debe respetar:
- **Agencia.** La Verificación y el anclaje de Contexto son hábitos que Claude suele hacer por su
  cuenta; no acredites/penalices la *fluidez del usuario* por ellos con tanta fuerza como con
  Descripción, Delegación e Iteración, que el usuario claramente conduce.
- **Confianza.** Cada dimensión lleva una confianza (0–1) según cuántas oportunidades tuvo. Las
  señales de baja confianza deben matizarse ("evidencia limitada, pero…"), nunca afirmarse como
  un hecho.

---

## Rúbrica de niveles (aplicá por competencia 4D)

| Nivel | Nombre | Cómo se ve |
|---|---|---|
| 1 | Emergente | Mayormente reactivo; delega con poca estructura; rara vez chequea o acota. |
| 2 | En desarrollo | Aparece algo de estructura, de forma inconsistente; restricciones/chequeos ocasionales. |
| 3 | Competente | El hábito está presente en la *mayoría* de los momentos relevantes; baseline confiable. |
| 4 | Avanzado | Consistente y deliberado; anticipa los modos de falla; pocos huecos. |
| 5 | Experto | Reflejo y transmisible; lo setea por adelantado, lo combina en capas, lo hace reutilizable. |

Anclá los niveles a las **tasas**, no al volumen. "Verifica la mayoría de las ráfagas de
ediciones (70%)" → ~N3–4. "Nombra un archivo/restricción en una minoría de los prompts de
acción" → ~N2 en Descripción.

---

## Cómo se ve lo bueno (usalo como el objetivo hacia el que crece el usuario)

- **Delegación:** "Agregá un endpoint `/health` solo a `server.py`, después corré los tests" —
  un hand-off acotado, del tamaño justo, con el camino implícito. Usa sub-agents/planificación
  para trabajo grande o en paralelo.
- **Descripción:** Objetivo + un ancla (path/restricción/test de aceptación) en la mayoría de los
  prompts de acción. "Refactorizá `auth.py` para usar el nuevo tipo `Session`; no toques la API
  pública; los tests tienen que seguir pasando."
- **Discernimiento:** Las ráfagas de ediciones terminan con un test/build/run; las ediciones
  siguen a una lectura del archivo; las correcciones nombran el síntoma y el fix exacto.
- **Diligencia:** Nada se entrega sin verificar; los sistemas en vivo se desmontan; el usuario se
  hace cargo del resultado.

---

## Contrato de salida para la etapa de análisis

Producí un objeto JSON (esto es lo que renderiza `insight.py --analysis`):

```json
{
  "overall_read": "2–4 oraciones, en lenguaje llano, amable y específico: quién es este builder y el único movimiento de crecimiento de mayor palanca.",
  "skill_map": [
    {
      "competency": "Delegation | Description | Discernment | Diligence",
      "level": 1-5,
      "level_label": "Emerging | Developing | Proficient | Advanced | Expert",
      "summary": "1–2 oraciones ancladas en la evidencia de ESTA persona (citá un patrón real).",
      "evidence": ["cita corta u observación concreta de los transcripts", "otra"],
      "next_move": "una acción concreta y realizable para la próxima sesión (un hábito, con un mini template si sirve)."
    }
    // exactamente las cuatro competencias, en este orden
  ],
  "top_growth": [
    {"title": "...", "why": "...", "how": "...", "example_before": "un prompt escueto real suyo", "example_after": "el mismo prompt, mejorado"}
  ],
  "strengths": ["cosas específicas que ya hace bien, ancladas en la evidencia"]
}
```

Reglas para el analista:
1. **Anclá cada afirmación en el bundle de evidencia.** Citá prompts reales. Nada de consejos genéricos.
2. **Sé amable y útil — escribí como un buen docente.** Nombrá la habilidad, por qué importa, y
   exactamente cómo mejorar, con un antes/después de sus propios prompts.
3. **Respetá la agencia y la confianza** (más arriba). Matizá las señales finas.
4. **Sé honesto.** Si la evidencia es escasa para una competencia, decilo y bajá la confianza, no
   inventes. Los números vienen del motor determinístico; tu trabajo es el juicio y la dirección.
