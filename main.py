"""
main.py
=======
Orquestador principal del LinkedIn Easy Apply Bot.

Flujo de ejecución:
  1. Cargar configuración (.env, profile.json, criteria.json, search_queries.json)
  2. Conectar a Chrome ya logueado en LinkedIn (vía CDP)
  3. Por cada query de búsqueda configurada:
     a. Navegar a LinkedIn Jobs con filtro Easy Apply
     b. Scrapear tarjetas del panel izquierdo
     c. Para cada oferta no vista:
        - Pre-filtro rápido por título
        - Evaluación con Gemini (fit_score)
        - Si APPLY y score >= umbral: ejecutar EasyApplyFiller
        - Registrar resultado en SQLite
        - Delay humano entre postulaciones
  4. Mostrar resumen final de sesión

Modos:
  --auto       : Postula automáticamente sin confirmación (por defecto)
  --dry-run    : Evalúa y abre modales sin enviar
  --interactive: Pregunta antes de cada postulación
"""

import argparse
import asyncio
import json
import os
import re
import sys
import random
from pathlib import Path
from dotenv import load_dotenv

from src.browser import LinkedInBrowser
from src.linkedin_scraper import LinkedInScraper, JobListing
from src.form_filler import EasyApplyFiller
from src.evaluator import JobEvaluator
from src.storage import StorageRepository
from src.ui import (
    console,
    print_welcome,
    print_search_start,
    print_job_card,
    print_apply_start,
    print_apply_result,
    print_skip,
    print_session_summary,
    print_already_applied,
    print_saved_job,
)


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        description="LinkedIn Easy Apply Bot — Postulación autónoma e inteligente"
    )
    parser.add_argument(
        "--auto",
        action="store_const",
        const="auto",
        dest="mode",
        help="Modo 100%% automático (por defecto)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_const",
        const="dry-run",
        dest="mode",
        help="Auditoría: evalúa y abre modales pero NO envía postulaciones",
    )
    parser.add_argument(
        "--interactive",
        action="store_const",
        const="interactive",
        dest="mode",
        help="Pregunta confirmación antes de cada postulación",
    )
    parser.add_argument(
        "--cdp-url",
        default=None,
        help="URL del puerto CDP de Chrome (default: env CDP_URL o http://localhost:9222)",
    )
    parser.add_argument(
        "--max-apps",
        type=int,
        default=None,
        help="Máximo de postulaciones en esta ejecución",
    )
    parser.add_argument(
        "--schedule",
        choices=["part-time", "full-time", "all"],
        default=None,
        help="Tipo de jornada: part-time (media jornada + prácticas), full-time, all (todas)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Máximo de ofertas a analizar por búsqueda (default: 40)",
    )
    parser.set_defaults(mode=None)
    return parser.parse_args(args)


async def main_async():
    load_dotenv()
    args = parse_args(sys.argv[1:])
    print_welcome()

    # ─── Cargar configuración ─────────────────────────────────────────────────
    base_dir = Path(__file__).parent
    profile_path    = base_dir / "config" / "profile.json"
    criteria_path   = base_dir / "config" / "criteria.json"
    queries_path    = base_dir / "config" / "search_queries.json"

    if not profile_path.exists():
        example_path = base_dir / "config" / "profile.example.json"
        if example_path.exists():
            console.print(
                "[bold yellow]AVISO:[/bold yellow] No se encontró config/profile.json\n"
                "[cyan]Copiá config/profile.example.json a config/profile.json y completá tus datos personales.[/cyan]"
            )
        else:
            console.print(f"[bold red]ERROR:[/bold red] Archivo no encontrado: {profile_path}")
        return

    for path in (criteria_path, queries_path):
        if not path.exists():
            console.print(f"[bold red]ERROR:[/bold red] Archivo no encontrado: {path}")
            console.print(
                "[yellow]Asegurate de que existan los archivos en la carpeta config/[/yellow]"
            )
            return

    with open(profile_path, "r", encoding="utf-8") as f:
        profile = json.load(f)
    with open(criteria_path, "r", encoding="utf-8") as f:
        criteria = json.load(f)
    with open(queries_path, "r", encoding="utf-8") as f:
        search_config = json.load(f)

    # ─── Validar API Key ──────────────────────────────────────────────────────
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "tu_api_key_aqui":
        console.print(
            "[bold red]ERROR:[/bold red] GEMINI_API_KEY no está configurada en .env\n"
            "[yellow]Copiá .env.example a .env y completá tu clave.[/yellow]"
        )
        return

    # ─── Validar perfil personal ──────────────────────────────────────────────
    if profile.get("full_name", "").startswith("TU "):
        console.print(
            "[bold yellow]⚠ AVISO:[/bold yellow] Completá tus datos personales en config/profile.json\n"
            "[dim](full_name, email, phone, linkedin_url, etc.)[/dim]"
        )

    # ─── Parámetros de ejecución ──────────────────────────────────────────────
    mode = args.mode or os.getenv("DEFAULT_MODE", "auto")
    cdp_url = args.cdp_url or os.getenv("CDP_URL", "http://localhost:9222")
    min_score = int(os.getenv("MIN_FIT_SCORE", criteria.get("min_fit_score", 65)))
    max_apps = args.max_apps or int(
        os.getenv("MAX_APPLICATIONS_PER_RUN", criteria.get("max_applications_per_run", 20))
    )
    dry_run = mode == "dry-run"

    queries = search_config.get("queries", [])
    location = search_config.get("location", "Buenos Aires, Argentina")
    easy_apply_only = search_config.get("easy_apply_only", True)
    schedule = args.schedule or os.getenv("JOB_SCHEDULE", search_config.get("schedule", "part-time"))
    max_per_query = args.max_results or int(
        os.getenv("MAX_RESULTS_PER_QUERY", search_config.get("max_results_per_query", 40))
    )

    console.print(
        f"[dim]Modo:[/dim] [bold]{mode.upper()}[/bold]  "
        f"[dim]Jornada:[/dim] [bold]{schedule.upper()}[/bold]  "
        f"[dim]Score mínimo:[/dim] [bold]{min_score}[/bold]  "
        f"[dim]Máx. postulaciones:[/dim] [bold]{max_apps}[/bold]  "
        f"[dim]Queries:[/dim] [bold]{len(queries)}[/bold]"
    )

    # ─── Inicializar componentes ──────────────────────────────────────────────
    storage = StorageRepository(base_dir / "data" / "job_history.db")
    storage.init_db()

    evaluator = JobEvaluator(
        api_key=api_key,
        profile=profile,
        criteria=criteria,
        model_name=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    )
    scraper   = LinkedInScraper()
    browser   = LinkedInBrowser(cdp_url=cdp_url)

    applied_count   = 0
    evaluated_count = 0

    try:
        console.print(f"\n[cyan]Conectando a Chrome en {cdp_url}...[/cyan]")
        page = await browser.connect()
        title = await page.title() if hasattr(page, "title") else "Sin título"
        console.print(f"[green]✓ Conectado:[/green] {title}\n")

        filler = EasyApplyFiller(
            browser=browser,
            evaluator=evaluator,
            profile=profile,
            dry_run=dry_run,
        )

        # ── Iterar sobre cada query de búsqueda ───────────────────────────────
        for query_idx, query in enumerate(queries, 1):
            if applied_count >= max_apps:
                console.print(
                    f"\n[bold yellow]Límite de {max_apps} postulaciones alcanzado. "
                    "Sesión finalizada.[/bold yellow]"
                )
                break

            console.print(f"\n[bold]Query {query_idx}/{len(queries)}[/bold]")
            print_search_start(query, location, max_per_query)

            # Navegar a LinkedIn Jobs con filtros
            await browser.navigate_to_jobs(
                query=query,
                location=location,
                easy_apply=easy_apply_only,
                schedule=schedule,
            )
            await browser.human_delay(2.0, 3.5)

            # Verificar que estamos en la página correcta
            if "linkedin.com/jobs" not in page.url:
                console.print("[yellow]No se pudo navegar a LinkedIn Jobs. Saltando query...[/yellow]")
                continue

            # Contar resultados
            result_count = await scraper.count_results(page)
            if result_count == 0:
                console.print(f"[dim]Sin resultados para '{query}'. Continuando...[/dim]")
                continue

            result_count = min(result_count, max_per_query)
            console.print(f"[dim]Se encontraron {result_count} tarjetas visibles.[/dim]")

            card_selector = await scraper.get_current_card_selector(page)

            # ── Procesar cada tarjeta ─────────────────────────────────────────
            for card_idx in range(result_count):
                if applied_count >= max_apps:
                    break

                global_idx = card_idx + 1
                total_str  = str(result_count)

                # Chequeo previo: intentar extraer el ID de la tarjeta antes de hacer clic
                cards = page.locator(card_selector)
                if card_idx >= await cards.count():
                    break
                current_card = cards.nth(card_idx)
                card_job_id = await scraper.get_card_job_id(current_card)

                if card_job_id and storage.is_job_seen(card_job_id):
                    print_skip(f"Oferta ya evaluada previamente en BD ({card_job_id})", global_idx, result_count)
                    continue

                # Hacer clic en la tarjeta para cargar el panel de detalles
                loaded = await scraper.click_card_and_load_details(page, card_idx, card_selector)
                if not loaded:
                    continue

                await browser.human_delay(1.0, 2.0)

                # Extraer datos del panel de detalles
                (
                    title_det, company, location_det,
                    description, is_easy_apply, already_applied
                ) = await scraper.extract_detail_panel(page)

                if not title_det:
                    continue

                # Obtener URL actual y generar ID determinista y estable
                current_url = page.url
                job_id = card_job_id or scraper._generate_id(current_url, title_det, company)

                # ── Oferta ya vista en DB ──────────────────────────────────────
                if storage.is_job_seen(job_id):
                    print_skip(f"Ya vista: {title_det} @ {company}", global_idx, result_count)
                    await browser.human_delay(0.5, 1.0)
                    continue

                # ── Ya postulada en LinkedIn ──────────────────────────────────
                if already_applied:
                    print_already_applied(title_det, company, global_idx, result_count)
                    storage.record_job_evaluation(
                        job_id=job_id, title=title_det, company=company,
                        score=100, recommendation="APPLY",
                        reason="Postulación ya enviada detectada en LinkedIn",
                        url=current_url,
                    )
                    storage.mark_as_applied(job_id)
                    continue

                # ── Pre-filtro rápido por título y ubicación ─────────────────
                prefilter = evaluator.should_prefilter_skip(title_det, location_det)
                if prefilter:
                    print_skip(f"{prefilter} — {title_det}", global_idx, result_count)
                    storage.record_job_evaluation(
                        job_id=job_id, title=title_det, company=company,
                        score=15, recommendation="SKIP", reason=prefilter,
                        url=current_url,
                    )
                    storage.mark_as_skipped(job_id, prefilter)
                    await browser.human_delay(0.5, 1.0)
                    continue

                # ── Si NO tiene Solicitud Sencilla (oferta externa) ─────────────
                # Si no tiene Easy Apply pero pasa el prefiltro, la evaluamos con Gemini.
                # Si resulta ser un gran match (APPLY y score >= min_score), la guardamos
                # en el perfil de LinkedIn (botón Guardar), en SQLite y en data/empleos_guardados.csv.
                if not is_easy_apply:
                    console.print(
                        f"[cyan]⚙ Evaluando puesto externo con Gemini ({global_idx}/{total_str}): "
                        f"[bold]{title_det}[/bold] @ {company}...[/cyan]"
                    )
                    try:
                        evaluation = evaluator.evaluate_job(title_det, company, description)
                    except Exception as e:
                        console.print(f"[red]Error al evaluar con Gemini: {e}[/red]")
                        continue

                    evaluated_count += 1
                    storage.record_job_evaluation(
                        job_id=job_id,
                        title=evaluation.job_title or title_det,
                        company=evaluation.company or company,
                        score=evaluation.fit_score,
                        recommendation=evaluation.recommendation,
                        reason=evaluation.summary_reason,
                        url=current_url,
                    )
                    print_job_card(evaluation, global_idx, result_count)

                    if (
                        evaluation.recommendation == "APPLY"
                        and evaluation.fit_score >= min_score
                    ):
                        saved_on_li = await scraper.save_job_in_linkedin(page)
                        storage.mark_as_saved(
                            job_id,
                            f"Guardada externa (Score {evaluation.fit_score}): {evaluation.summary_reason}"
                        )
                        storage.record_saved_job_to_csv({
                            "title": evaluation.job_title or title_det,
                            "company": evaluation.company or company,
                            "location": location_det,
                            "score": evaluation.fit_score,
                            "reason": evaluation.summary_reason,
                            "url": current_url,
                        })
                        print_saved_job(title_det, company, evaluation.fit_score, saved_on_li)
                    else:
                        storage.mark_as_skipped(
                            job_id,
                            f"No es Easy Apply y no alcanza score suficiente ({evaluation.fit_score}): {evaluation.summary_reason}"
                        )

                    await browser.human_delay(1.0, 2.0)
                    continue

                # ── Evaluación con Gemini para ofertas Easy Apply ─────────────
                console.print(
                    f"[cyan]⚙ Evaluando con Gemini ({global_idx}/{total_str}): "
                    f"[bold]{title_det}[/bold] @ {company}...[/cyan]"
                )
                try:
                    evaluation = evaluator.evaluate_job(title_det, company, description)
                except Exception as e:
                    console.print(f"[red]Error al evaluar con Gemini: {e}[/red]")
                    continue

                evaluated_count += 1

                storage.record_job_evaluation(
                    job_id=job_id,
                    title=evaluation.job_title or title_det,
                    company=evaluation.company or company,
                    score=evaluation.fit_score,
                    recommendation=evaluation.recommendation,
                    reason=evaluation.summary_reason,
                    url=current_url,
                )

                print_job_card(evaluation, global_idx, result_count)

                # ── Decidir si postular ───────────────────────────────────────
                should_apply = False

                if (
                    evaluation.recommendation == "APPLY"
                    and evaluation.fit_score >= min_score
                ):
                    if mode == "auto":
                        should_apply = True
                    elif mode == "dry-run":
                        should_apply = True   # abre modal pero no envía
                    elif mode == "interactive":
                        console.print("\n[bold yellow]¿Postularse a esta oferta?[/bold yellow]")
                        choice = input("  [S] Sí / [n] No / [q] Salir: ").strip().lower()
                        if choice == "q":
                            console.print("[yellow]Ejecución detenida por el usuario.[/yellow]")
                            break
                        should_apply = choice in ("s", "", "y", "si", "sí")
                        if not should_apply:
                            storage.mark_as_skipped(job_id, "Rechazado por usuario en modo interactivo")

                if should_apply:
                    print_apply_start(title_det, company)

                    # Hacer clic en "Solicitud sencilla"
                    clicked = await scraper.click_easy_apply_button(page)
                    if not clicked:
                        print_apply_result(False, "No se encontró el botón 'Solicitud sencilla'.")
                        storage.mark_as_failed(job_id, "Botón Easy Apply no encontrado")
                        await browser.human_delay(2.0, 3.5)
                        continue

                    await browser.human_delay(1.5, 2.5)

                    # Rellenar formulario
                    success, msg = await filler.apply(page, title_det, company, description)
                    print_apply_result(success, msg)

                    if success and not dry_run:
                        storage.mark_as_applied(job_id)
                        applied_count += 1
                    elif not success:
                        storage.mark_as_failed(job_id, msg)

                    # Asegurar que la "X" del modal se presione y no quede bloqueando la pantalla
                    await filler.click_modal_x(page)

                    # Delay anti-detección entre postulaciones
                    delay_range = criteria.get("delay_between_applications_seconds", [20, 45])
                    delay = random.uniform(delay_range[0], delay_range[1])
                    console.print(f"  [dim]⏳ Pausa de {delay:.0f}s antes de la siguiente...[/dim]")
                    await asyncio.sleep(delay)

                else:
                    if evaluation.recommendation == "SKIP" or evaluation.fit_score < min_score:
                        storage.mark_as_skipped(job_id, evaluation.summary_reason)

                await browser.human_delay(1.5, 3.0)

                # Si estamos cerca del final de las tarjetas visibles y aún no alcanzamos max_per_query, cargar más
                if card_idx >= result_count - 3 and result_count < max_per_query:
                    await browser.scroll_job_list(page, 500)
                    new_count = await scraper.count_results(page)
                    if new_count > result_count:
                        result_count = min(new_count, max_per_query)

            # Scroll para cargar más resultados (paginación LinkedIn)
            await browser.scroll_job_list(page, 600)
            await browser.human_delay(1.5, 2.5)

    except ConnectionError as e:
        console.print(f"\n[bold red]{e}[/bold red]")
        console.print(
            "[yellow]Asegurate de ejecutar launch_chrome.bat primero "
            "y que Chrome esté abierto con LinkedIn logueado.[/yellow]"
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Ejecución interrumpida por el usuario.[/yellow]")
    finally:
        await browser.close()
        summary = storage.get_session_summary()
        print_session_summary(summary, applied_count, evaluated_count)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
