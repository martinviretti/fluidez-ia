export const meta = {
  name: 'fluidez-ia',
  description: 'Análisis de fluidez con IA en dos modelos: Sonnet 4.6 explora la evidencia, Opus 4.8 escribe un mapa de habilidades anclado en el framework de Fluidez con IA y después verifica que esté fundamentado en la evidencia.',
  whenToUse: 'Lo corre la skill /fluidez-ia después de que insight.py emite evidence.json. Args: {evidence, framework} rutas absolutas.',
  phases: [
    { title: 'Explore', detail: 'Sonnet 4.6 — un explorador por cada competencia 4D' },
    { title: 'Analyze', detail: 'Opus 4.8 — mapa de habilidades anclado en el framework' },
    { title: 'Verify', detail: 'verificar que el mapa esté fundamentado; reparar si no lo está' },
  ],
}

// Resolve inputs. The /ai-fluency skill passes absolute paths via args, but if they don't
// arrive the defaults MUST still point at the exact files the skill writes — never a bare
// relative path like '.insight/evidence.json', which an agent will "helpfully" resolve to a
// stale copy elsewhere on disk (e.g. an old ~/Dropbox/.../.insight/evidence.json), silently
// analyzing the wrong dataset.
const EV = (args && args.evidence) || '~/.claude/insight/evidence.json'
const FW = (args && args.framework) || '~/.claude/skills/ai-fluency/reference/ai-fluency-framework.md'

const COMPETENCIES = [
  { key: 'Delegation',  focus: 'Qué le entrega al agente vs qué retiene, y cómo reparte el trabajo: delegaciones end-to-end vs micro-pasos, sub-agentes / jobs en background / planificación, amplitud de herramientas (conciencia de plataforma y rutas). Señales: delegation_events, tool_usage, alcance de los prompts.' },
  { key: 'Description',  focus: 'Con cuánta concreción briefea al agente: ¿los prompts de acción nombran un archivo/error (artefacto), llevan una restricción y enuncian un porqué/test de aceptación? Descarga escueta vs briefs específicos cargados por adelantado. Señales: detalle de Instrucción (tasas de restricción/artefacto/intención) + prompts de muestra.' },
  { key: 'Discernment',  focus: 'Cómo evalúa los resultados: verificación después de ráfagas de ediciones (tests/build/run), anclar las ediciones en una lectura previa, corregir con precisión (síntoma + regla) vs rechazo vago. Señales: detalle de Verificación, Contexto, Iteración. OJO con la agencia: verificación/anclaje son en parte impulsados por Claude — acreditale al USUARIO con moderación.' },
  { key: 'Diligence',    focus: 'Responsabilidad: verificar antes de que las cosas salgan a producción, desarmar lo que se levantó, hacerse cargo del resultado en vez de publicar a ciegas. En un transcript de programación esto se solapa con Discernment — pesá el ángulo de responsabilidad. Señales: bonus por desarmado de verificación, ediciones ancladas.' },
]

const FINDING = {
  type: 'object', additionalProperties: false,
  required: ['competency', 'level_estimate', 'confidence', 'strengths', 'gaps', 'evidence_quotes'],
  properties: {
    competency: { type: 'string' },
    level_estimate: { type: 'integer', minimum: 1, maximum: 5 },
    confidence: { type: 'string', enum: ['low', 'medium', 'high'] },
    strengths: { type: 'array', items: { type: 'string' } },
    gaps: { type: 'array', items: { type: 'string' } },
    evidence_quotes: { type: 'array', items: { type: 'string' }, description: 'citas/observaciones reales de la evidencia' },
    notes: { type: 'string' },
  },
}

const SKILL_ENTRY = {
  type: 'object', additionalProperties: false,
  required: ['competency', 'level', 'level_label', 'summary', 'evidence', 'next_move'],
  properties: {
    competency: { type: 'string', enum: ['Delegation', 'Description', 'Discernment', 'Diligence'] },
    level: { type: 'integer', minimum: 1, maximum: 5 },
    level_label: { type: 'string', enum: ['Emerging', 'Developing', 'Proficient', 'Advanced', 'Expert'] },
    summary: { type: 'string' },
    evidence: { type: 'array', items: { type: 'string' }, minItems: 1 },
    next_move: { type: 'string' },
  },
}

const ANALYSIS = {
  type: 'object', additionalProperties: false,
  required: ['overall_read', 'skill_map', 'top_growth', 'strengths'],
  properties: {
    overall_read: { type: 'string' },
    skill_map: { type: 'array', items: SKILL_ENTRY, minItems: 4, maxItems: 4 },
    top_growth: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['title', 'why', 'how', 'example_before', 'example_after'],
        properties: {
          title: { type: 'string' }, why: { type: 'string' }, how: { type: 'string' },
          example_before: { type: 'string' }, example_after: { type: 'string' },
        },
      },
    },
    strengths: { type: 'array', items: { type: 'string' } },
  },
}

const VERDICT = {
  type: 'object', additionalProperties: false,
  required: ['is_grounded', 'ungrounded_claims'],
  properties: {
    is_grounded: { type: 'boolean' },
    ungrounded_claims: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
}

const READ = `Con tu herramienta Read, leé EXACTAMENTE estos dos archivos y usá ÚNICAMENTE esos — el framework en ` +
  `${FW} y el bundle de evidencia descontaminado (JSON) en ${EV}. ` +
  `NO busques, adivines ni sustituyas ninguna otra ruta: puede haber copias viejas de evidence.json ` +
  `en otro lugar del disco (archivos antiguos, carpetas de Dropbox/iCloud) — ignoralas por completo. Si falta ` +
  `cualquiera de los dos archivos, FRENÁ y reportalo en vez de leer otro distinto. (Un ~ al inicio significa tu ` +
  `directorio home — expandilo a $HOME antes de leer.) La evidencia es real y ` +
  `local; anclá todo en ella — citá prompts reales; nunca inventes.`

// ---- Explore: Sonnet 4.6, one thorough explorer per competency -------------
phase('Explore')
const findings = await parallel(COMPETENCIES.map(c => () =>
  agent(
    `${READ}\n\nSos un analista cuidadoso y minucioso que explora UNA competencia de fluidez con IA: ` +
    `**${c.key}**.\n${c.focus}\n\nUsá la rúbrica de niveles del framework. Estimá un nivel (1–5), ` +
    `fijá la confianza según cuánta evidencia exista (matizá cuando las señales son débiles) y listá fortalezas concretas, ` +
    `brechas y citas reales de la evidencia. Sé específico respecto de ESTA persona.`,
    { label: `explore:${c.key}`, phase: 'Explore', model: 'sonnet', schema: FINDING }
  ).then(f => f && { ...f, competency: f.competency || c.key })
)).then(r => r.filter(Boolean))

log(`Exploradas ${findings.length}/4 competencias (Sonnet 4.6)`)

// ---- Analyze: Opus 4.8 writes the grounded skill map -----------------------
phase('Analyze')
const findingsJson = JSON.stringify(findings, null, 2)
const analystPrompt =
  `${READ}\n\nSos el evaluador senior de fluidez con IA (escribí como un docente amable y exigente). ` +
  `Cuatro exploradores Sonnet produjeron estos hallazgos por competencia:\n\n${findingsJson}\n\n` +
  `Reconciliálos con los puntajes deterministas del bundle de evidencia y con la rúbrica de niveles ` +
  `del framework y su "cómo se ve lo bueno". Producí la evaluación final según el OUTPUT CONTRACT del framework: ` +
  `un overall_read, un skill_map con EXACTAMENTE las cuatro competencias (Delegation, Description, Discernment, ` +
  `Diligence) en ese orden, top_growth y strengths. ` +
  `\n\nLa sección top_growth es el corazón del informe — se renderiza como las tarjetas de "cómo crecer" ` +
  `de esta persona, así que DEBE ser totalmente a medida, nunca consejos genéricos. Producí 3 ítems (2 solo si los datos son escasos). ` +
  `Para cada uno: un título filoso y específico; un "why" que cite los números/patrones propios de ESTA persona (p. ej. su ` +
  `tasa de restricciones, un hábito que viste); un "how" concreto; y el antes/después donde example_before es un ` +
  `prompt REAL que efectivamente escribió (copialo TEXTUAL de los sample_prompts o weak_examples de la evidencia — ` +
  `no lo inventes ni lo parafrasees) y example_after es tu reescritura a medida de ESE prompt exacto, listo ` +
  `para pegar, que corrige la brecha específica. Cargalo de señal: nombrá sus archivos, herramientas, proyectos y forma de redactar. ` +
  `Si dos ítems de crecimiento fueran a compartir el mismo antes/después, reemplazá uno para que ningún ejemplo se repita. ` +
  `Respetá la agencia (descontá los hábitos impulsados por Claude) y la confianza (matizá las señales débiles). ` +
  `Toda afirmación — y todo example_before — tiene que estar fundamentada en la evidencia.`
let analysis = await agent(analystPrompt, { label: 'analyze', phase: 'Analyze', model: 'opus', schema: ANALYSIS })

// ---- Verify: is the map actually grounded? repair once if not --------------
phase('Verify')
const verdict = await agent(
  `${READ}\n\nChequeá de forma adversarial este mapa de habilidades de fluidez con IA contra la evidencia. Marcá toda afirmación que ` +
  `sea genérica, no fundamentada, inflada, o que ignore una confianza baja. Ante la duda, poné is_grounded=false.\n\n` +
  `SKILL MAP:\n${JSON.stringify(analysis, null, 2)}`,
  { label: 'verify', phase: 'Verify', model: 'opus', schema: VERDICT }
)
if (verdict && verdict.is_grounded === false && (verdict.ungrounded_claims || []).length) {
  log(`Reparando ${verdict.ungrounded_claims.length} afirmación(es) no fundamentada(s)`)
  analysis = await agent(
    `${READ}\n\nRevisá este mapa de habilidades para corregir estos problemas de fundamentación — reemplazá las ` +
    `afirmaciones genéricas/infladas/no fundamentadas por otras ancladas en la evidencia y matizadas como corresponde. Mantené la misma forma de JSON.\n\n` +
    `PROBLEMS:\n${(verdict.ungrounded_claims || []).map((c, i) => `${i + 1}. ${c}`).join('\n')}\n\n` +
    `CURRENT:\n${JSON.stringify(analysis, null, 2)}`,
    { label: 'repair', phase: 'Verify', model: 'opus', schema: ANALYSIS }
  )
}

return analysis
