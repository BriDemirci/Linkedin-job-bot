import json
import time
import re
import warnings
from typing import List, Literal, Dict, Any, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

warnings.filterwarnings("ignore", category=UserWarning)


class JobEvaluation(BaseModel):
    job_title: str
    company: str
    fit_score: int = Field(ge=0, le=100, description="Puntaje 0-100 de compatibilidad")
    recommendation: Literal["APPLY", "SKIP"]
    matching_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    summary_reason: str


class ScreeningAnswer(BaseModel):
    """Respuesta a una pregunta de screening del formulario Easy Apply."""
    answer: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    reasoning: str


class JobEvaluator:
    """
    Evaluador de ofertas de LinkedIn usando Gemini.
    Extiende el bot USAL con:
      - generate_answer(): responde preguntas dinámicas de formularios Easy Apply
      - generate_cover_letter(): genera carta de presentación personalizada
    """

    def __init__(
        self,
        api_key: str,
        profile: Dict[str, Any],
        criteria: Dict[str, Any],
        model_name: str = "gemini-3.5-flash-lite",
    ):
        self.api_key = api_key
        self.profile = profile
        self.criteria = criteria
        self.model_name = model_name
        self.client = genai.Client(api_key=self.api_key)

    # ─── Pre-filtro rápido ────────────────────────────────────────────────────

    def should_prefilter_skip(self, title: str, location: str = "") -> Optional[str]:
        """
        Descarta ofertas por título o ubicación sin gastar tokens de Gemini.
        Retorna el motivo si debe omitirse, None si pasa el filtro.
        """
        title_lower = title.lower()
        loc_lower = location.lower() if location else ""

        # Disciplinas no afines
        for disc in self.criteria.get("excluded_disciplines", []):
            if re.search(rf"\b{re.escape(disc.lower())}", title_lower):
                return f"Disciplina no afín: '{disc}'"

        # Niveles de experiencia descartables
        reject_terms = self.criteria.get("experience_requirements", {}).get("reject_if_contains", [])
        for term in reject_terms:
            if term.lower() in title_lower:
                return f"Requiere experiencia no compatible: '{term}'"

        # Filtro de ubicación geográfica para ofertas presenciales / híbridas
        if loc_lower:
            is_remote = any(r in loc_lower for r in ["remoto", "remote", "teletrabajo"])
            if not is_remote:
                rejected_zones = self.criteria.get("location_filter", {}).get("rejected_zones", [])
                for zone in rejected_zones:
                    if zone.lower() in loc_lower:
                        return f"Ubicación lejana no compatible: '{zone}'"

        return None

    # ─── Evaluación con Gemini ────────────────────────────────────────────────

    def _build_evaluation_prompt(self, title: str, company: str, description: str) -> str:
        return f"""
Actúa como un asesor de carreras y reclutador técnico experto.
Analizá la siguiente oferta de LinkedIn y determiná si el candidato debe postularse.

--- PERFIL DEL CANDIDATO ---
{json.dumps(self.profile, indent=2, ensure_ascii=False)}

--- CRITERIOS Y PREFERENCIAS ---
{json.dumps(self.criteria, indent=2, ensure_ascii=False)}

--- OFERTA DE EMPLEO A EVALUAR (LinkedIn) ---
Puesto: {title}
Empresa: {company}
Descripción completa:
{description}

--- INSTRUCCIONES DE EVALUACIÓN ---
1. REGLA CLAVE: El candidato BUSCA SU PRIMER EMPLEO O PASANTÍA (SIN EXPERIENCIA PREVIA).
   - Pasantías, trainee, junior inicial, estudiantes universitarios → puntaje ELEVADO (≥ 75).
   - "Sin experiencia", "estudiante", "hasta 1 año" con tareas alcanzables → recomendar APPLY.
   - Solo recomendar SKIP si exige 2+ años comprobables, o niveles Semi-Senior/Senior/Lead.
2. ABANICO AMPLIO: Sé flexible con denominaciones: Desarrollador (cualquier stack), Soporte,
   QA, Analista Funcional Jr, Analista de Datos, Operador IT, Consultor Jr, etc. Todos son afines.
3. JORNADA Y TIPO DE EMPLEO: Se priorizan pasantías universitarias y jornadas part-time (media jornada).
4. UBICACIÓN Y TRASLADO (LÍMITE GEOGRÁFICO):
   - Si es 100% Remoto: ACEPTAR sin importar dónde esté radicada la empresa.
   - Si es Presencial o Híbrido: SOLO ACEPTAR si es en CABA o Zona Norte de GBA (hasta Pilar / Escobar / Tigre / San Isidro / Vicente López).
   - Rechazar (SKIP) si es presencial o híbrido en Zona Sur (Quilmes, Lanús, La Plata, etc.), Zona Oeste (Morón, Moreno, Merlo, La Matanza, etc.) o provincias alejadas (Córdoba, Rosario, etc.).
5. IDIOMA (INGLÉS C1 AVANZADO): El candidato tiene nivel de inglés avanzado C1 (certificado por EF Oxford). Las ofertas redactadas en INGLÉS o que exijan inglés fluido son 100% AFINES y deben evaluarse positivamente (APPLY si cumple perfil de pasantía / trainee / junior inicial).
6. HABILIDADES TÉCNICAS DEL CV: Brian domina Python, C++, C#, .NET, Java, JavaScript, SQL (SQL Server, MySQL, SQLite), HTML/CSS, y tiene experiencia en gestión y resolución de problemas por su emprendimiento Brint It 3D.
7. NO penalices herramientas propietarias que puede aprender rápido.
8. Score ≥ {self.criteria.get('min_fit_score', 65)} y oportunidad razonable → APPLY; si no → SKIP.
9. Extrae skills coincidentes, faltantes, pros, contras y resumen de 1-2 oraciones.
Respondé estrictamente en formato JSON según el esquema.
"""

    def evaluate_job(
        self, title: str, company: str, description: str, max_retries: int = 3
    ) -> JobEvaluation:
        prompt = self._build_evaluation_prompt(title, company, description)
        for attempt in range(1, max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=JobEvaluation,
                        temperature=0.2,
                    ),
                )
                data = json.loads(response.text)
                return JobEvaluation(**data)
            except Exception as e:
                err_str = str(e).lower()
                is_rate = "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str
                if is_rate and attempt < max_retries:
                    wait = 20 * attempt
                    print(f"\n[Cuota] Límite alcanzado. Pausando {wait}s (intento {attempt}/{max_retries})...")
                    time.sleep(wait)
                else:
                    raise

    # ─── Respuesta de preguntas de formulario ─────────────────────────────────

    def generate_answer(
        self,
        question: str,
        field_type: str,
        options: Optional[List[str]] = None,
        job_context: str = "",
    ) -> ScreeningAnswer:
        """
        Usa Gemini para responder preguntas dinámicas del formulario Easy Apply.
        `field_type`: 'text', 'number', 'select', 'radio', 'textarea', 'checkbox'
        `options`: lista de opciones disponibles (para select/radio)
        """
        options_str = ""
        if options:
            options_str = f"\nOpciones disponibles: {json.dumps(options, ensure_ascii=False)}"

        prompt = f"""
Sos un asistente que está completando un formulario de postulación en LinkedIn en nombre del candidato.

--- PERFIL DEL CANDIDATO ---
{json.dumps(self.profile, indent=2, ensure_ascii=False)}

--- PREGUNTA DEL FORMULARIO ---
Pregunta: "{question}"
Tipo de campo: {field_type}{options_str}
Contexto de la oferta: {job_context or "No especificado"}

--- INSTRUCCIONES ---
1. Respondé con el valor más adecuado para el candidato según su perfil.
2. Si la pregunta es sobre años de experiencia en algo específico, revisá `years_of_experience_by_skill`.
   Si no está en el mapa, usá 0 para habilidades técnicas específicas o 1 para generales.
3. Si es un select/radio, la respuesta DEBE ser EXACTAMENTE una de las opciones disponibles.
4. Si es número, respondé SOLO con el número (sin texto).
5. Para preguntas de autorización de trabajo, visas, etc., usá los valores del perfil.
6. Si la pregunta es sobre pretensión salarial / remuneración:
   - Si el campo pide un número (field_type == 'number'): colocá un valor numérico competitivo de mercado para pasantía / trainee en Argentina (ej. 650000 para ARS, o 600 si es en USD).
   - Si es select o radio, elegí el rango inicial / trainee o 'A convenir'.
   - Si permite texto abierto, respondé 'A convenir'.
7. Si no estás seguro, indicá confidence = "LOW".
Respondé en formato JSON según el esquema.
"""
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ScreeningAnswer,
                    temperature=0.1,
                ),
            )
            data = json.loads(response.text)
            return ScreeningAnswer(**data)
        except Exception as e:
            # Fallback seguro si Gemini falla
            return ScreeningAnswer(
                answer="0" if field_type == "number" else "No especificado",
                confidence="LOW",
                reasoning=f"Fallback por error de API: {e}",
            )

    # ─── Carta de presentación ────────────────────────────────────────────────

    def generate_cover_letter(
        self, job_title: str, company: str, description: str
    ) -> str:
        """Genera una carta de presentación personalizada (en inglés o español según la oferta) usando Gemini."""
        text = f"{job_title} {description}".lower()
        en_markers = [
            "looking for", "requirements", "responsibilities", "skills",
            "experience", "bachelor", "degree", "internship", "developer",
            "we are", "join our", "must have", "nice to have"
        ]
        is_english = sum(1 for m in en_markers if m in text) >= 2

        if is_english:
            prompt = f"""
Write a concise, professional cover letter (max 150 words) in English for an Information Systems student applying to a tech position.

Position: {job_title}
Company: {company}
Description: {description[:500]}

Candidate Profile:
- Advanced Information Systems student at Universidad del Salvador (USAL).
- Certified C1 Advanced English (EF Oxford).
- Technical skills: Python, C++, C#, .NET, Java, JavaScript, SQL (SQL Server, MySQL, SQLite).
- Operations management, process optimization, and customer service experience through 3D printing venture (Brint It 3D).
- Eager to learn, proactive, highly adaptable, seeking first tech role or internship.

Instructions:
- Professional, confident yet approachable tone.
- Explicitly mention the company name.
- Highlight fast-learning ability, problem-solving, and motivation.
- Close stating availability for an interview.
- Maximum 150 words.
- Return ONLY the cover letter text, no subject line, no placeholders.
"""
            fallback = (
                f"Dear {company} Hiring Team,\n\n"
                f"I am writing to express my strong interest in the {job_title} position. "
                f"I am an advanced Information Systems student at Universidad del Salvador (USAL) "
                f"with certified C1 Advanced English (EF Oxford). I have a solid foundation in "
                f"programming (Python, C++, C#, .NET, Java, SQL) and practical experience in "
                f"operations and problem-solving through my 3D printing venture.\n\n"
                f"I am eager to contribute to your team and continue growing professionally. "
                f"I am available for an interview at your earliest convenience.\n\n"
                f"Best regards,\n{self.profile.get('full_name', '')}"
            )
        else:
            template = self.profile.get("cover_letter_template", "")
            if template and "{" in template:
                try:
                    return template.format(
                        company=company,
                        job_title=job_title,
                        full_name=self.profile.get("full_name", ""),
                    )
                except KeyError:
                    pass

            prompt = f"""
Escribí una carta de presentación concisa (máx. 150 palabras) en español para un candidato estudiante de Sistemas.

Puesto: {job_title}
Empresa: {company}
Descripción: {description[:500]}

Perfil del candidato:
- {self.profile.get('cv_summary', '')}
- Habilidades: {', '.join(self.profile.get('skills', [])[:8])}
- Idiomas: Inglés C1 Avanzado (EF Oxford), Español nativo.

Instrucciones:
- Tono profesional pero cercano
- Mencionar la empresa por nombre
- Destacar disposición de aprendizaje y motivación
- Cerrar con disponibilidad para entrevista
- Máximo 150 palabras
- Solo el texto de la carta, sin asunto ni encabezado formal
"""
            fallback = (
                f"Estimado equipo de {company},\n\n"
                f"Me postulo con entusiasmo para el rol de {job_title}. "
                f"Soy estudiante de Lic. en Sistemas de la Información en la USAL, con inglés C1 y conocimientos en "
                f"Python, C++, C#, SQL y bases de datos, y gran disposición para aprender y aportar valor desde el primer día.\n\n"
                f"Quedo a su entera disposición para una entrevista.\n\n"
                f"Saludos cordiales,\n{self.profile.get('full_name', '')}"
            )

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.4),
            )
            return response.text.strip()
        except Exception:
            return fallback
