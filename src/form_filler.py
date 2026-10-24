"""
form_filler.py
==============
Maneja el flujo completo de postulación por formulario multi-paso de LinkedIn Easy Apply.

Flujo:
  1. Detectar y abrir el modal "Solicitud sencilla"
  2. Paso "Información de contacto" → verificar/completar datos personales
  3. Paso "Currículum vitae" → usar CV ya guardado en LinkedIn (clic Next)
  4. Paso "Preguntas adicionales" → detectar campos y responderlos inteligentemente
  5. Paso "Carta de presentación" → generar con Gemini si el campo existe
  6. Paso "Revisión" → confirmar datos
  7. "Enviar solicitud" → confirmar éxito

Estrategia de respuesta a preguntas:
  - Reglas deterministas para preguntas comunes (experiencia=0, autorizado=Sí, etc.)
  - Gemini como fallback para preguntas ambiguas o desconocidas
  - El candidato es perfilado como "sin experiencia, primer empleo, estudiante"
"""

import asyncio
import re
from typing import Dict, Any, List, Optional, Tuple
from playwright.async_api import Page, Locator

from src.browser import LinkedInBrowser
from src.evaluator import JobEvaluator


# ─── Selectores del modal Easy Apply ─────────────────────────────────────────

MODAL_SELECTORS = [
    "div[data-test-modal]",
    ".jobs-easy-apply-modal",
    ".artdeco-modal--layer-default",
    "[aria-label='Solicitud sencilla']",
    "[aria-label='Easy Apply']",
]

NEXT_BUTTON_SELECTORS = [
    "button[aria-label='Continuar con el siguiente paso']",
    "button[aria-label='Continue to next step']",
    "footer button:has-text('Siguiente')",
    "footer button:has-text('Next')",
    "footer button:has-text('Continuar')",
    "footer button:has-text('Continue')",
    ".jobs-easy-apply-modal footer button.artdeco-button--primary",
]

SUBMIT_BUTTON_SELECTORS = [
    "button[aria-label='Enviar solicitud']",
    "button[aria-label='Submit application']",
    "footer button:has-text('Enviar solicitud')",
    "footer button:has-text('Submit application')",
    "footer button:has-text('Enviar')",
]

REVIEW_BUTTON_SELECTORS = [
    "button[aria-label='Revisar tu solicitud']",
    "button[aria-label='Review your application']",
    "footer button:has-text('Revisar')",
    "footer button:has-text('Review')",
]

CLOSE_BUTTON_SELECTORS = [
    "button[aria-label='Descartar']",
    "button[aria-label='Dismiss']",
    ".artdeco-modal__dismiss",
]

DISCARD_CONFIRM_SELECTORS = [
    "button[data-control-name='discard_application_confirm_btn']",
    "button:has-text('Descartar')",
    "button:has-text('Discard')",
]

SUCCESS_SELECTORS = [
    ".jobs-easy-apply-modal:has-text('Solicitud enviada')",
    ".jobs-easy-apply-modal:has-text('Application submitted')",
    "h2:has-text('Solicitud enviada')",
    "h2:has-text('Application submitted')",
    ".artdeco-modal:has-text('Solicitud enviada')",
]

# ─── Preguntas comunes con respuestas deterministas ────────────────────────────

DETERMINISTIC_PATTERNS = [
    # (pattern_regex, answer_func)
    # Experiencia en años
    (r"años?\s+de\s+experiencia|years?\s+of\s+experience",
     lambda profile, opts: _experience_answer(profile, opts)),
    # Autorización de trabajo
    (r"autorizado|autorizada|legal.*trabajar|legally.*work|work.*authorization",
     lambda profile, opts: "Sí" if not opts else _pick_option(opts, ["sí", "si", "yes"])),
    # Visa / patrocinio
    (r"visa|patrocinio|sponsorship",
     lambda profile, opts: "No" if not opts else _pick_option(opts, ["no"])),
    # Salario
    (r"salario|sueldo|salary|remuneración|pretensión",
     lambda profile, opts: profile.get("salary_expectation_ars", "A convenir")),
    # Disponibilidad
    (r"disponibilidad|disponible|cuando.*empezar|start.*date|fecha.*inicio",
     lambda profile, opts: profile.get("availability", "Inmediata")),
    # Reclutamiento presencial
    (r"dispuesto.*trabajar.*presencial|willing.*onsite|trabajo.*presencial",
     lambda profile, opts: "Sí" if not opts else _pick_option(opts, ["sí", "si", "yes"])),
    # Trabajo remoto
    (r"trabajo.*remoto|remote.*work",
     lambda profile, opts: "Sí" if not opts else _pick_option(opts, ["sí", "si", "yes"])),
    # LinkedIn
    (r"perfil.*linkedin|linkedin.*profile|url.*linkedin",
     lambda profile, opts: profile.get("linkedin_url", "")),
    # GitHub
    (r"github|repositorio",
     lambda profile, opts: profile.get("common_screening_answers", {}).get("github", "")),
    # Universidad
    (r"universidad|institution|school|educación",
     lambda profile, opts: "Universidad del Salvador (USAL)" if not opts
     else _pick_option(opts, ["usal", "universidad del salvador"])),
    # Carrera/título
    (r"carrera|título|degree|major|campo.*estudio",
     lambda profile, opts: "Licenciatura en Sistemas" if not opts
     else _pick_option(opts, ["sistemas", "informática", "computación"])),
    # Año de graduación
    (r"graduación|graduation|año.*finalización|end.*year",
     lambda profile, opts: str(profile.get("common_screening_answers", {}).get("graduation_year", "2027"))),
    # Nivel de inglés (C1 Avanzado - EF Oxford)
    (r"inglés|english|nivel.*idioma|language.*proficiency",
     lambda profile, opts: "Avanzado / C1" if not opts
     else _pick_option(opts, ["c1", "avanzado", "advanced", "proficient", "fluent", "full professional", "b2"])),
    # Relocate
    (r"reubicación|relocate|mudarte|mudarse",
     lambda profile, opts: "No" if not opts else _pick_option(opts, ["no"])),
    # Gender (skip if optional, answer if required)
    (r"género|gender",
     lambda profile, opts: _pick_option(opts, ["prefiero no decir", "prefer not", "no especificar"]) if opts else ""),
    # Discapacidad
    (r"discapacidad|disability",
     lambda profile, opts: _pick_option(opts, ["no", "ninguna", "none"]) if opts else "No"),
]


def _pick_option(options: List[str], keywords: List[str]) -> str:
    """Elige la primera opción que contenga alguna de las keywords (case-insensitive)."""
    for kw in keywords:
        for opt in options:
            if kw.lower() in opt.lower():
                return opt
    return options[0] if options else ""


def _experience_answer(profile: Dict[str, Any], options: Optional[List[str]]) -> str:
    """
    Para preguntas de años de experiencia: siempre 0 para candidatos sin experiencia.
    Si el campo es un select, busca la opción "Menos de 1", "0-1", "Sin experiencia", etc.
    """
    if not options:
        return "0"
    return _pick_option(options, [
        "sin experiencia", "menos de 1", "0-1", "0 a 1",
        "primer empleo", "no tengo", "ninguna", "0"
    ])


class EasyApplyFiller:
    """
    Rellena el formulario multi-paso de LinkedIn Easy Apply de forma autónoma.
    """

    def __init__(
        self,
        browser: LinkedInBrowser,
        evaluator: JobEvaluator,
        profile: Dict[str, Any],
        dry_run: bool = False,
    ):
        self.browser = browser
        self.evaluator = evaluator
        self.profile = profile
        self.dry_run = dry_run

    # ─── Entry point ──────────────────────────────────────────────────────────

    async def apply(
        self,
        page: Page,
        job_title: str,
        company: str,
        description: str,
    ) -> Tuple[bool, str]:
        """
        Ejecuta el flujo completo de Easy Apply.
        Retorna (success: bool, message: str).
        """
        modal = await self._get_modal(page)
        if modal is None:
            return False, "No se pudo localizar el modal de Easy Apply."

        if self.dry_run:
            await self._close_modal(page)
            return True, "[DRY-RUN] Modal detectado. No se envió la postulación."

        max_steps = 12  # límite de seguridad para evitar loops infinitos
        step = 0

        while step < max_steps:
            step += 1
            await self.browser.human_delay(0.8, 1.5)

            step_result = await self._handle_current_step(
                page, modal, job_title, company, description
            )

            if step_result == "submitted":
                await self.click_modal_x(page)
                return True, "✓ Postulación enviada exitosamente en LinkedIn."
            elif step_result == "error":
                await self._close_modal(page)
                return False, "Error al procesar un paso del formulario."
            elif step_result == "next":
                continue
            else:
                break

        await self._close_modal(page)
        return False, f"El formulario no se completó tras {max_steps} pasos."

    # ─── Manejo de pasos ──────────────────────────────────────────────────────

    async def _handle_current_step(
        self,
        page: Page,
        modal: Locator,
        job_title: str,
        company: str,
        description: str,
    ) -> str:
        """
        Detecta el estado del modal y actúa en consecuencia.
        Retorna: 'submitted' | 'next' | 'error' | 'done'
        """
        # ¿Ya se envió exitosamente?
        for sel in SUCCESS_SELECTORS:
            if await page.locator(sel).count() > 0:
                return "submitted"

        # ¿Botón de Enviar visible? → click y confirmar
        submit = await self._find_visible(page, SUBMIT_BUTTON_SELECTORS)
        if submit:
            await submit.scroll_into_view_if_needed()
            await self.browser.human_delay(0.5, 1.0)
            await submit.click()
            await self.browser.human_delay(1.5, 2.5)
            # Clic directo en la "X" del pop-up de postulación enviada
            await self.click_modal_x(page)
            return "submitted"

        # ¿Botón de Revisar visible? → click
        review = await self._find_visible(page, REVIEW_BUTTON_SELECTORS)
        if review:
            await review.click()
            await self.browser.human_delay(1.0, 2.0)
            return "next"

        # Rellenar campos del paso actual
        await self._fill_current_step_fields(page, modal, job_title, company, description)

        # Avanzar al siguiente paso
        next_btn = await self._find_visible(page, NEXT_BUTTON_SELECTORS)
        if next_btn:
            await next_btn.click()
            await self.browser.human_delay(1.5, 2.5)
            return "next"

        return "error"

    async def _fill_current_step_fields(
        self,
        page: Page,
        modal: Locator,
        job_title: str,
        company: str,
        description: str,
    ) -> None:
        """
        Detecta y rellena todos los campos del paso actual del formulario.
        """
        # ── Carta de presentación (textarea grande) ─────────────────────────
        cover_letter_selectors = [
            "textarea[name*='coverLetter']",
            "textarea[id*='cover-letter']",
            "textarea[aria-label*='carta']",
            "textarea[aria-label*='cover']",
        ]
        for sel in cover_letter_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                current_val = await loc.first.input_value()
                if not current_val.strip():
                    cover = self.evaluator.generate_cover_letter(
                        job_title, company, description
                    )
                    await self.browser.human_type(loc.first, cover)
                break

        # ── Selección de Currículum (Español vs Inglés según el puesto) ──────
        is_english = self._is_english_job(job_title, description)
        await self._select_resume_by_language(page, is_english)

        # ── Campos del formulario agrupados por label ───────────────────────
        # Estrategia: buscar todos los grupos de campo dentro del modal
        form_groups = page.locator(
            ".jobs-easy-apply-form-section__grouping,"
            ".fb-form-element,"
            ".jobs-easy-apply-form__element"
        )
        group_count = await form_groups.count()

        for i in range(group_count):
            group = form_groups.nth(i)
            await self._fill_field_group(page, group, job_title, company, description)

        # ── Fallback: inputs directos sin agrupar ───────────────────────────
        if group_count == 0:
            await self._fill_orphan_fields(page, job_title, company, description)

    async def _fill_field_group(
        self,
        page: Page,
        group: Locator,
        job_title: str,
        company: str,
        description: str,
    ) -> None:
        """Rellena un grupo campo+label dentro del formulario."""
        # Obtener la etiqueta/pregunta del campo
        label_loc = group.locator("label, legend, .fb-form-element-label, h3")
        label_text = ""
        if await label_loc.count() > 0:
            label_text = (await label_loc.first.inner_text()).strip()

        if not label_text:
            return

        # ── Textarea ────────────────────────────────────────────────────────
        textarea = group.locator("textarea")
        if await textarea.count() > 0 and await textarea.first.is_visible():
            current = await textarea.first.input_value()
            if not current.strip():
                answer = await self._resolve_answer(
                    label_text, "textarea", [], job_title, company, description
                )
                if answer:
                    await self.browser.human_type(textarea.first, answer)
            return

        # ── Select / dropdown ───────────────────────────────────────────────
        select = group.locator("select")
        if await select.count() > 0 and await select.first.is_visible():
            # Obtener opciones disponibles
            options = await select.first.evaluate("""
                el => Array.from(el.options)
                    .filter(o => o.value !== '')
                    .map(o => o.text.trim())
            """)
            current = await select.first.input_value()
            if not current or current == "":
                answer = await self._resolve_answer(
                    label_text, "select", options, job_title, company, description
                )
                if answer:
                    # Seleccionar por texto visible
                    try:
                        await select.first.select_option(label=answer)
                    except Exception:
                        # Fallback: seleccionar por valor parcial
                        for opt in options:
                            if answer.lower() in opt.lower():
                                try:
                                    await select.first.select_option(label=opt)
                                    break
                                except Exception:
                                    pass
                    await self.browser.human_delay(0.3, 0.6)
            return

        # ── Radio buttons ───────────────────────────────────────────────────
        radios = group.locator("input[type='radio']")
        radio_count = await radios.count()
        if radio_count > 0:
            options = []
            for r in range(radio_count):
                radio = radios.nth(r)
                radio_id = await radio.get_attribute("id")
                radio_label = group.locator(f"label[for='{radio_id}']")
                if await radio_label.count() > 0:
                    options.append(await radio_label.first.inner_text())

            # Verificar si ya hay uno seleccionado
            already_checked = False
            for r in range(radio_count):
                if await radios.nth(r).is_checked():
                    already_checked = True
                    break

            if not already_checked and options:
                answer = await self._resolve_answer(
                    label_text, "radio", options, job_title, company, description
                )
                for r in range(radio_count):
                    radio = radios.nth(r)
                    radio_id = await radio.get_attribute("id")
                    radio_label = group.locator(f"label[for='{radio_id}']")
                    label_val = ""
                    if await radio_label.count() > 0:
                        label_val = await radio_label.first.inner_text()
                    if answer.lower() in label_val.lower():
                        await radio.click()
                        await self.browser.human_delay(0.2, 0.4)
                        break
            return

        # ── Checkbox ────────────────────────────────────────────────────────
        checkbox = group.locator("input[type='checkbox']")
        if await checkbox.count() > 0:
            # Generalmente para "Acepto términos" → siempre marcar
            if not await checkbox.first.is_checked():
                # Solo marcar si es requerido o si la label indica términos/consentimiento
                if any(kw in label_text.lower() for kw in [
                    "acepto", "acuerdo", "términos", "condiciones", "confirm", "agree"
                ]):
                    await checkbox.first.click()
                    await self.browser.human_delay(0.2, 0.4)
            return

        # ── Input text / number ─────────────────────────────────────────────
        text_input = group.locator("input[type='text'], input[type='number'], input:not([type])")
        if await text_input.count() > 0 and await text_input.first.is_visible():
            current = await text_input.first.input_value()
            if not current.strip():
                field_type = await text_input.first.get_attribute("type") or "text"
                answer = await self._resolve_answer(
                    label_text, field_type, [], job_title, company, description
                )
                if answer:
                    await self.browser.human_type(text_input.first, answer)
            return

    async def _fill_orphan_fields(
        self, page: Page, job_title: str, company: str, description: str
    ) -> None:
        """Fallback: rellena inputs sin estructura de grupo definida."""
        # Nombre / Apellido
        for fname_sel in ["input[name*='firstName'], input[autocomplete='given-name']"]:
            loc = page.locator(fname_sel)
            if await loc.count() > 0 and not (await loc.first.input_value()).strip():
                await self.browser.human_type(loc.first, self.profile.get("first_name", ""))

        for lname_sel in ["input[name*='lastName'], input[autocomplete='family-name']"]:
            loc = page.locator(lname_sel)
            if await loc.count() > 0 and not (await loc.first.input_value()).strip():
                await self.browser.human_type(loc.first, self.profile.get("last_name", ""))

        # Teléfono
        for phone_sel in ["input[name*='phone'], input[autocomplete='tel'], input[type='tel']"]:
            loc = page.locator(phone_sel)
            if await loc.count() > 0 and not (await loc.first.input_value()).strip():
                await self.browser.human_type(loc.first, self.profile.get("phone", ""))

    # ─── Resolución de respuestas ─────────────────────────────────────────────

    async def _resolve_answer(
        self,
        question: str,
        field_type: str,
        options: List[str],
        job_title: str,
        company: str,
        description: str,
    ) -> str:
        """
        Estrategia de dos capas:
          1. Reglas deterministas para preguntas comunes (sin costo de API)
          2. Gemini para preguntas ambiguas o desconocidas
        """
        q_lower = question.lower()

        # ── Capa 1: Reglas deterministas ─────────────────────────────────────
        for pattern, answer_func in DETERMINISTIC_PATTERNS:
            if re.search(pattern, q_lower, re.IGNORECASE):
                # Si es pregunta de salario y el campo pide número o select estricto:
                if re.search(r"salario|sueldo|salary|remuneración|pretensión", q_lower, re.IGNORECASE):
                    if field_type == "number" or (options and not any("convenir" in o.lower() for o in options)):
                        continue  # Dejar que Gemini (Capa 3) calcule un valor numérico coherente
                result = answer_func(self.profile, options if options else None)
                if result is not None and str(result).strip():
                    return str(result).strip()

        # ── Capa 2: Campos de datos personales directos ───────────────────────
        personal_map = {
            r"nombre|first.*name|nombre.*pila": self.profile.get("first_name", ""),
            r"apellido|last.*name|surname":     self.profile.get("last_name", ""),
            r"email|correo|e-mail":             self.profile.get("email", ""),
            r"teléfono|telefono|phone|celular":  self.profile.get("phone", ""),
            r"ciudad|city":                     self.profile.get("location_city", "Buenos Aires"),
            r"país|country|pais":               self.profile.get("location_country", "Argentina"),
        }
        for pattern, value in personal_map.items():
            if re.search(pattern, q_lower, re.IGNORECASE) and value:
                return value

        # ── Capa 3: Gemini para preguntas desconocidas ────────────────────────
        job_context = f"Puesto: {job_title} en {company}. {description[:300]}"
        screening = self.evaluator.generate_answer(
            question=question,
            field_type=field_type,
            options=options or None,
            job_context=job_context,
        )
        return screening.answer

    # ─── Utilidades del modal ─────────────────────────────────────────────────

    async def _get_modal(self, page: Page) -> Optional[Locator]:
        """Verifica que el modal de Easy Apply esté abierto."""
        for sel in MODAL_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                return loc.first
        return None

    async def _find_visible(self, page: Page, selectors: List[str]) -> Optional[Locator]:
        """Retorna el primer locator visible de la lista de selectores."""
        for sel in selectors:
            loc = page.locator(sel)
            try:
                if await loc.count() > 0 and await loc.first.is_visible():
                    return loc.first
            except Exception:
                continue
        return None

    def _is_english_job(self, title: str, description: str) -> bool:
        """Detecta si la oferta de empleo está en inglés."""
        text = f"{title} {description}".lower()
        en_markers = [
            "looking for", "requirements", "responsibilities", "skills",
            "experience", "bachelor", "degree", "internship", "developer",
            "we are", "join our", "must have", "nice to have", "plus",
            "fluent in english", "english", "remote work", "full-time", "part-time"
        ]
        hits = sum(1 for m in en_markers if m in text)
        return hits >= 2

    async def _select_resume_by_language(self, page: Page, is_english: bool) -> None:
        """
        En el paso de CV, selecciona la versión en inglés o español según el idioma del puesto.
        """
        radios = page.locator("input[type='radio']")
        radio_count = await radios.count()
        if radio_count == 0:
            return

        target_keywords = (
            ["english", "ingles", "inglés", "en", "_en", "-en", "oxford"]
            if is_english
            else ["spanish", "español", "espanol", "es", "_es", "-es"]
        )

        for i in range(radio_count):
            radio = radios.nth(i)
            radio_id = await radio.get_attribute("id")
            label_text = ""
            if radio_id:
                label_loc = page.locator(f"label[for='{radio_id}']")
                if await label_loc.count() > 0:
                    label_text = (await label_loc.first.inner_text()).lower()
            if not label_text:
                try:
                    parent = radio.locator("..")
                    label_text = (await parent.inner_text()).lower()
                except Exception:
                    pass

            if any(kw in label_text for kw in target_keywords):
                try:
                    if not await radio.is_checked():
                        await radio.click(force=True)
                        await self.browser.human_delay(0.5, 0.8)
                except Exception:
                    pass
                return

    async def click_modal_x(self, page: Page) -> bool:
        """
        Cierra el modal de LinkedIn haciendo clic en la 'X' (botón de cerrar/descartar).
        Garantiza que el pop-up de 'Solicitud enviada' se cierre para continuar sin trabas.
        """
        await self.browser.human_delay(1.0, 2.0)

        # Selectores prioritarios para la "X" del modal
        x_selectors = [
            "button.artdeco-modal__dismiss",
            ".artdeco-modal__dismiss",
            "button[aria-label='Dismiss']",
            "button[aria-label='Descartar']",
            "button[aria-label='Cerrar']",
            "button[aria-label='Close']",
            "button[data-test-modal-close-btn]",
            ".artdeco-modal button[aria-label*='Dismiss']",
            ".artdeco-modal button[aria-label*='Descartar']",
            ".artdeco-modal button[aria-label*='Cerrar']",
            "button:has(svg[data-test-icon='close-small'])",
            "button:has(li-icon[type='cancel-icon'])",
            ".artdeco-modal button.artdeco-button--circle",
            "div[role='dialog'] button[aria-label]",
            ".artdeco-modal button:has-text('Listo')",
            ".artdeco-modal button:has-text('Done')",
            ".artdeco-modal button:has-text('Entendido')",
            ".artdeco-modal button:has-text('Continuar')",
            "button:has-text('Listo')",
            "button:has-text('Done')",
        ]

        for attempt in range(3):
            # 1. Intentar hacer clic en la "X"
            for sel in x_selectors:
                locs = page.locator(sel)
                count = await locs.count()
                for i in range(count):
                    btn = locs.nth(i)
                    try:
                        if await btn.is_visible():
                            await btn.click(force=True, timeout=2000)
                            await self.browser.human_delay(0.8, 1.5)
                            break
                    except Exception:
                        continue

            # 2. Si aparece diálogo de confirmación de descarte ("¿Descartar postulación?"):
            discard = await self._find_visible(page, DISCARD_CONFIRM_SELECTORS)
            if discard:
                try:
                    await discard.click(force=True)
                    await self.browser.human_delay(0.5, 1.0)
                except Exception:
                    pass

            # 3. Presionar Escape por si el modal intercepta teclado
            try:
                await page.keyboard.press("Escape")
                await self.browser.human_delay(0.5, 0.8)
            except Exception:
                pass

            # 4. Verificar si desapareció el modal
            if await page.locator(".artdeco-modal, .jobs-easy-apply-modal, .artdeco-modal-overlay").count() == 0:
                return True

        return True

    async def _close_modal(self, page: Page) -> None:
        """Cierra el modal descartando la solicitud."""
        await self.click_modal_x(page)


