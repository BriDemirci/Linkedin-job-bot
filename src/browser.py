import asyncio
import random
from typing import List, Optional
from playwright.async_api import async_playwright, Browser, Page, Locator


class LinkedInBrowser:
    """
    Conector CDP para Chrome ya logueado en LinkedIn.
    Extiende el patrón del bot USAL con:
      - Detección automática de pestaña de LinkedIn
      - human_type: escritura char-a-char para evadir detección
      - human_scroll: scroll orgánico
      - Headers anti-detección
    """

    LINKEDIN_KEYWORDS = ["linkedin.com", "linkedin", "jobs"]

    def __init__(self, cdp_url: str = "http://localhost:9222"):
        self.cdp_url = cdp_url
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.active_page: Optional[Page] = None

    # ─── Conexión ────────────────────────────────────────────────────────────

    async def connect(self) -> Page:
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(self.cdp_url)
        except Exception as e:
            raise ConnectionError(
                f"No se pudo conectar a Chrome en {self.cdp_url}. "
                "Ejecutá launch_chrome.bat y asegurate de que Chrome esté abierto "
                "con el puerto 9222 y con LinkedIn ya logueado."
            ) from e

        page = await self._find_linkedin_tab()
        if page is None:
            # No había pestaña de LinkedIn abierta; abrimos una nueva
            if self.browser.contexts:
                page = await self.browser.contexts[0].new_page()
            else:
                raise ConnectionError("Chrome conectado pero sin contextos disponibles.")

        self.active_page = page
        await self._inject_stealth_headers(page)
        return page

    async def _find_linkedin_tab(self) -> Optional[Page]:
        """Busca una pestaña que ya tenga LinkedIn abierto."""
        if not self.browser:
            return None
        for context in self.browser.contexts:
            for page in context.pages:
                url_lower = page.url.lower()
                if any(kw in url_lower for kw in self.LINKEDIN_KEYWORDS):
                    await page.bring_to_front()
                    self.active_page = page
                    return page
        return None

    async def _inject_stealth_headers(self, page: Page) -> None:
        """Inyecta headers para reducir señales de detección de bot."""
        await page.set_extra_http_headers({
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
        })

    # ─── Navegación ──────────────────────────────────────────────────────────

    async def navigate_to_jobs(
        self,
        query: str,
        location: str,
        easy_apply: bool = True,
        schedule: str = "part-time",
        experience_levels: str = "1,2",
    ) -> None:
        """
        Navega a LinkedIn Jobs con los filtros configurados:
          - keywords: texto de búsqueda
          - location: ubicación base
          - easy_apply: f_LF=f_AL (Solicitud sencilla)
          - experience_levels: f_E=1,2 (1: Prácticas, 2: Sin experiencia / Entry level)
          - schedule: f_JT=P,I para Part-time / Prácticas, f_JT=F para Full-time, o sin filtro para all
          - fecha: Cualquier momento (f_TPR omitido a pedido del usuario)
          - orden: Más recientes (sortBy=DD)
        """
        if not self.active_page:
            raise RuntimeError("Browser no conectado.")

        params = [
            f"keywords={query.replace(' ', '%20')}",
            f"location={location.replace(' ', '%20').replace(',', '%2C')}",
            "sortBy=DD",
        ]

        if easy_apply:
            params.append("f_AL=true")

        # Nivel de experiencia: 1 = Prácticas, 2 = Sin experiencia
        if experience_levels:
            exp_encoded = experience_levels.replace(",", "%2C")
            params.append(f"f_E={exp_encoded}")

        # Tipo de empleo / Jornada
        if schedule == "part-time":
            params.append("f_JT=P%2CI")  # P: Part-time, I: Prácticas
        elif schedule == "full-time":
            params.append("f_JT=F")       # F: Full-time
        # Si schedule == "all", no agregamos filtro f_JT para abarcar todas

        query_string = "&".join(params)
        url = f"https://www.linkedin.com/jobs/search/?{query_string}"

        await self.active_page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await self.human_delay(2.0, 4.0)

        # Asegurar en UI que el botón de filtro 'Solicitud sencilla' esté activado
        if easy_apply:
            await self._ensure_easy_apply_filter_active()

    async def _ensure_easy_apply_filter_active(self) -> None:
        """Verifica en la UI que el botón de filtro Solicitud sencilla esté activo; si no, le hace clic."""
        if not self.active_page:
            return

        filter_buttons = [
            "button[aria-label*='Solicitud sencilla']",
            "button[aria-label*='Easy Apply']",
            "button.artdeco-pill:has-text('Solicitud sencilla')",
            "button.artdeco-pill:has-text('Easy Apply')",
            ".search-reusables__filter-pill-button:has-text('Solicitud sencilla')",
            ".search-reusables__filter-pill-button:has-text('Easy Apply')",
            "#searchFilter_applyWithLinkedin",
            "button:has-text('Solicitud sencilla')",
            "button:has-text('Easy Apply')",
        ]
        for sel in filter_buttons:
            loc = self.active_page.locator(sel)
            try:
                if await loc.count() > 0 and await loc.first.is_visible():
                    pressed = await loc.first.get_attribute("aria-pressed")
                    checked = await loc.first.get_attribute("aria-checked")
                    if pressed != "true" and checked != "true":
                        await loc.first.click()
                        await self.human_delay(1.5, 2.5)
                        return
            except Exception:
                continue

    async def scroll_job_list(self, page: Page, amount: int = 500) -> None:
        """Hace scroll dentro del contenedor de la lista de empleos del panel izquierdo."""
        containers = [
            ".jobs-search-results-list",
            ".scaffold-layout__list",
            "div.jobs-search-results-list",
        ]
        for sel in containers:
            loc = page.locator(sel)
            if await loc.count() > 0:
                try:
                    await loc.first.evaluate(f"el => el.scrollBy({{top: {amount}, behavior: 'smooth'}})")
                    await self.human_delay(0.5, 1.0)
                    return
                except Exception:
                    pass
        # Fallback mouse wheel
        await page.mouse.wheel(0, amount)
        await self.human_delay(0.5, 1.0)

    # ─── Interacción humana ───────────────────────────────────────────────────

    async def human_delay(self, min_s: float = 1.0, max_s: float = 2.5) -> None:
        """Pausa aleatoria entre acciones para simular comportamiento humano."""
        delay = random.uniform(min_s, max_s)
        await asyncio.sleep(delay)

    async def human_type(self, locator: Locator, text: str) -> None:
        """
        Escribe texto carácter a carácter con delays variables.
        Mucho más difícil de detectar que page.fill() directo.
        """
        await locator.click()
        await self.human_delay(0.2, 0.5)
        # Limpiar campo primero
        await locator.press("Control+a")
        await self.human_delay(0.1, 0.2)
        await locator.press("Delete")
        await self.human_delay(0.1, 0.3)

        for char in text:
            await locator.press(char) if len(char) == 1 else await locator.type(char)
            # Velocidad de tipeo variable: 40-180ms por carácter
            await asyncio.sleep(random.uniform(0.04, 0.18))

        await self.human_delay(0.2, 0.4)

    async def human_scroll(self, direction: str = "down", amount: int = 300) -> None:
        """Scroll suave para simular lectura humana."""
        if not self.active_page:
            return
        delta = amount if direction == "down" else -amount
        await self.active_page.mouse.wheel(0, delta)
        await self.human_delay(0.3, 0.8)

    async def safe_click(self, target: Locator | str) -> bool:
        """Clic seguro con scroll previo para visibilidad."""
        if not self.active_page:
            return False
        locator = self.active_page.locator(target) if isinstance(target, str) else target
        if await locator.count() > 0:
            try:
                await locator.first.scroll_into_view_if_needed()
                await self.human_delay(0.3, 0.7)
                await locator.first.click()
                await self.human_delay(0.4, 0.9)
                return True
            except Exception:
                return False
        return False

    async def find_and_click(self, selectors: List[str], timeout_ms: int = 5000) -> bool:
        """
        Intenta una lista de selectores y hace clic en el primero visible.
        Útil para botones con texto variable (Sí/No, Siguiente/Next).
        """
        if not self.active_page:
            return False
        for sel in selectors:
            loc = self.active_page.locator(sel)
            try:
                if await loc.count() > 0 and await loc.first.is_visible():
                    await loc.first.scroll_into_view_if_needed()
                    await self.human_delay(0.2, 0.5)
                    await loc.first.click()
                    await self.human_delay(0.5, 1.0)
                    return True
            except Exception:
                continue
        return False

    # ─── Cierre ──────────────────────────────────────────────────────────────

    async def close(self) -> None:
        if self.playwright:
            await self.playwright.stop()
