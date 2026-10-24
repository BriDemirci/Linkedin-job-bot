import re
import hashlib
from typing import List, Optional, Tuple
from pydantic import BaseModel
from playwright.async_api import Page


class JobListing(BaseModel):
    job_id: str
    title: str
    company: str
    location: str = "No especificada"
    modality: str = ""          # Presencial / Remoto / Híbrido
    posted_date: str = ""
    applicants: str = ""
    url: str = ""
    summary: str = ""
    full_description: str = ""
    is_easy_apply: bool = False
    already_applied: bool = False


class LinkedInScraper:
    """
    Scraper de ofertas Easy Apply de LinkedIn Jobs.
    Estrategia:
      1. Navegar a la página de resultados con filtro Easy Apply activo
      2. Iterar sobre las tarjetas del panel izquierdo
      3. Hacer clic en cada tarjeta para cargar el panel de detalles derecho
      4. Extraer descripción completa del panel derecho
      5. Verificar badge "Solicitud sencilla" y "Postulación enviada"
    """

    # ─── Selectores de tarjetas ───────────────────────────────────────────────

    CARD_LIST_SELECTORS = [
        ".jobs-search-results__list-item",
        ".job-search-card",
        "li.jobs-search-results__list-item",
        "[data-occludable-job-id]",
    ]

    TITLE_SELECTORS = [
        ".job-card-list__title",
        ".job-card-container__link",
        "a.job-card-list__title--link",
        ".artdeco-entity-lockup__title a",
        "strong",
    ]

    COMPANY_SELECTORS = [
        ".job-card-container__primary-description",
        ".artdeco-entity-lockup__subtitle span",
        ".job-card-container__company-name",
        ".job-card-list__company-name",
    ]

    # ─── Selectores del panel de detalles ─────────────────────────────────────

    DETAIL_TITLE_SELECTORS = [
        ".job-details-jobs-unified-top-card__job-title h1",
        ".jobs-unified-top-card__job-title h1",
        ".t-24.t-bold",
        "h1.jobs-unified-top-card__job-title",
    ]

    DETAIL_COMPANY_SELECTORS = [
        ".job-details-jobs-unified-top-card__company-name a",
        ".jobs-unified-top-card__company-name a",
        ".jobs-unified-top-card__subtitle-primary-grouping a",
    ]

    DETAIL_LOCATION_SELECTORS = [
        ".job-details-jobs-unified-top-card__bullet",
        ".jobs-unified-top-card__bullet",
        ".jobs-unified-top-card__workplace-type",
    ]

    DESCRIPTION_SELECTORS = [
        ".jobs-description__content",
        ".jobs-description-content__text",
        "#job-details",
        ".jobs-box__html-content",
        "article.jobs-description",
    ]

    EASY_APPLY_BTN_SELECTORS = [
        "button.jobs-apply-button:has-text('Solicitud sencilla')",
        "button[aria-label*='Solicitud sencilla']",
        "button.jobs-apply-button:has-text('Easy Apply')",
        "button[aria-label*='Easy Apply']",
        ".jobs-apply-button--top-card",
    ]

    ALREADY_APPLIED_SELECTORS = [
        ".artdeco-inline-feedback:has-text('Postulación enviada')",
        ".jobs-applied-badge",
        "span:has-text('Postulación enviada')",
        "button:has-text('Postulación enviada')",
        ".jobs-details-top-card__apply-error",
    ]

    SAVE_BTN_SELECTORS = [
        "button.jobs-save-button",
        "button[data-control-name='save_job']",
        "button[aria-label*='Guardar']",
        "button[aria-label*='Save']",
        "button:has-text('Guardar')",
        "button:has-text('Save')",
    ]

    def _generate_id(self, url: str, title: str, company: str) -> str:
        """Genera ID estable desde la URL de LinkedIn o título+empresa."""
        # Intentar extraer ID numérico de LinkedIn de la URL (/jobs/view/123 o currentJobId=123)
        match = re.search(r"(?:/jobs/view/|currentJobId=)(\d+)", url)
        if match:
            return f"li-{match.group(1)}"
        text = f"{title.strip().lower()}_{company.strip().lower()}"
        return f"li-{hashlib.md5(text.encode()).hexdigest()[:12]}"

    async def get_card_job_id(self, card) -> Optional[str]:
        """Extrae el job_id numérico de una tarjeta del panel izquierdo sin hacer clic."""
        try:
            job_id_attr = await card.get_attribute("data-occludable-job-id")
            if not job_id_attr:
                job_id_attr = await card.get_attribute("data-job-id")
            if job_id_attr and job_id_attr.isdigit():
                return f"li-{job_id_attr}"

            link = card.locator("a[href*='/jobs/view/'], a[href*='currentJobId=']")
            if await link.count() > 0:
                href = await link.first.get_attribute("href")
                if href:
                    m = re.search(r"(?:/jobs/view/|currentJobId=)(\d+)", href)
                    if m:
                        return f"li-{m.group(1)}"
        except Exception:
            pass
        return None

    async def get_job_cards(self, page: Page) -> List[JobListing]:
        """
        Devuelve las tarjetas de ofertas visibles en el panel izquierdo.
        No extrae descripción completa (eso se hace al hacer clic en cada tarjeta).
        """
        jobs: List[JobListing] = []

        for card_sel in self.CARD_LIST_SELECTORS:
            cards = page.locator(card_sel)
            count = await cards.count()
            if count > 0:
                for i in range(count):
                    card = cards.nth(i)
                    try:
                        job = await self._extract_card_data(card, page)
                        if job:
                            jobs.append(job)
                    except Exception:
                        continue
                if jobs:
                    return jobs

        return jobs

    async def _extract_card_data(self, card, page: Page) -> Optional[JobListing]:
        """Extrae datos básicos de una tarjeta del panel izquierdo."""
        # Título
        title = ""
        for sel in self.TITLE_SELECTORS:
            loc = card.locator(sel)
            if await loc.count() > 0:
                title = (await loc.first.inner_text()).strip()
                break
        if not title:
            return None

        # Empresa
        company = "Empresa no identificada"
        for sel in self.COMPANY_SELECTORS:
            loc = card.locator(sel)
            if await loc.count() > 0:
                company = (await loc.first.inner_text()).strip()
                break

        # URL del job desde el atributo data-occludable-job-id o href del link
        url = ""
        job_id_attr = await card.get_attribute("data-occludable-job-id")
        if job_id_attr:
            url = f"https://www.linkedin.com/jobs/view/{job_id_attr}/"

        if not url:
            link = card.locator("a[href*='/jobs/view/']")
            if await link.count() > 0:
                href = await link.first.get_attribute("href")
                url = href if href else ""

        job_id = self._generate_id(url, title, company)

        # Badge Easy Apply en la tarjeta
        easy_apply_badge = card.locator(
            "li-icon[type='linkedin-bug'],"
            ".job-card-container__apply-method"
        )
        is_easy = await easy_apply_badge.count() > 0

        # Ya postulado
        applied_badge = card.locator(
            ".job-card-container__footer-job-state:has-text('Postulación enviada'),"
            ".artdeco-inline-feedback--success"
        )
        already_applied = await applied_badge.count() > 0

        return JobListing(
            job_id=job_id,
            title=title,
            company=company,
            url=url,
            is_easy_apply=is_easy,
            already_applied=already_applied,
        )

    async def click_card_and_load_details(
        self, page: Page, card_index: int, card_selector: str
    ) -> bool:
        """
        Hace clic en la tarjeta N del panel izquierdo y espera que cargue el panel derecho.
        Retorna True si el panel cargó correctamente.
        """
        cards = page.locator(card_selector)
        if card_index >= await cards.count():
            return False
        card = cards.nth(card_index)
        try:
            await card.scroll_into_view_if_needed()
            await card.click()
            # Esperar a que cargue el panel de detalles
            await page.wait_for_selector(
                ".jobs-description__content, #job-details, .jobs-description-content__text",
                timeout=8000,
            )
            return True
        except Exception:
            return False

    async def extract_detail_panel(self, page: Page) -> Tuple[str, str, str, str, bool, bool]:
        """
        Extrae datos del panel de detalles derecho después de hacer clic en una tarjeta.
        Retorna: (title, company, location, full_description, is_easy_apply, already_applied)
        """
        # Título
        title = ""
        for sel in self.DETAIL_TITLE_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0:
                title = (await loc.first.inner_text()).strip()
                break

        # Empresa
        company = ""
        for sel in self.DETAIL_COMPANY_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0:
                company = (await loc.first.inner_text()).strip()
                break

        # Ubicación / modalidad
        location = ""
        for sel in self.DETAIL_LOCATION_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0:
                location = (await loc.first.inner_text()).strip()
                break

        # Descripción completa
        description = ""
        for sel in self.DESCRIPTION_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                description = (await loc.first.inner_text()).strip()
                if len(description) > 50:
                    break

        # Easy Apply button presente en el panel
        is_easy_apply = False
        for sel in self.EASY_APPLY_BTN_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                is_easy_apply = True
                break

        # Ya postulado
        already_applied = False
        for sel in self.ALREADY_APPLIED_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0:
                already_applied = True
                break

        return title, company, location, description, is_easy_apply, already_applied

    async def get_current_card_selector(self, page: Page) -> str:
        """Devuelve el selector de tarjetas activo en la página actual."""
        for sel in self.CARD_LIST_SELECTORS:
            if await page.locator(sel).count() > 0:
                return sel
        return self.CARD_LIST_SELECTORS[0]

    async def count_results(self, page: Page) -> int:
        """Cuenta las tarjetas visibles en el panel izquierdo."""
        for sel in self.CARD_LIST_SELECTORS:
            count = await page.locator(sel).count()
            if count > 0:
                return count
        return 0

    async def click_easy_apply_button(self, page: Page) -> bool:
        """Hace clic en el botón 'Solicitud sencilla' del panel de detalles."""
        for sel in self.EASY_APPLY_BTN_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                await loc.first.scroll_into_view_if_needed()
                await loc.first.click()
                await page.wait_for_timeout(2000)
                return True
        return False

    async def save_job_in_linkedin(self, page: Page) -> bool:
        """
        Hace clic en el botón 'Guardar' / 'Save' en el panel de detalles para guardar la oferta en el perfil de LinkedIn.
        Retorna True si se guardó con éxito o ya estaba guardada.
        """
        # Verificar si ya está guardada
        already_saved_selectors = [
            "button.jobs-save-button[aria-label*='Eliminar']",
            "button.jobs-save-button[aria-label*='Unsave']",
            "button:has-text('Guardado')",
            "button:has-text('Saved')",
        ]
        for sel in already_saved_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                return True

        # Buscar y hacer clic en el botón de guardar
        for sel in self.SAVE_BTN_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                try:
                    await loc.first.scroll_into_view_if_needed()
                    await loc.first.click()
                    await page.wait_for_timeout(1500)
                    return True
                except Exception:
                    continue
        return False
