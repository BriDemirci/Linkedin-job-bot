from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import List, Dict, Any

from src.evaluator import JobEvaluation

console = Console()


def print_welcome():
    console.print(Panel.fit(
        "[bold cyan]LinkedIn Easy Apply Bot[/bold cyan]\n"
        "[dim]Postulación autónoma e inteligente en LinkedIn[/dim]\n"
        "[dim]Powered by Gemini · Playwright · Python[/dim]",
        border_style="bright_blue",
        padding=(1, 4),
    ))


def print_search_start(query: str, location: str, max_results: int):
    console.print(
        f"\n[bold cyan]🔍 Buscando:[/bold cyan] [white]{query}[/white] "
        f"[dim]en {location} (max {max_results} resultados)[/dim]"
    )


def print_job_card(eval_res: JobEvaluation, index: int, total: int):
    score = eval_res.fit_score
    if score >= 80:
        score_color = "bright_green"
        score_icon = "🟢"
    elif score >= 65:
        score_color = "yellow"
        score_icon = "🟡"
    else:
        score_color = "red"
        score_icon = "🔴"

    rec_color = "bright_green" if eval_res.recommendation == "APPLY" else "red"

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_row("[bold]🏢 Empresa:[/bold]", eval_res.company)
    table.add_row(
        "[bold]📊 Score:[/bold]",
        f"[{score_color}]{score_icon} {score}/100[/{score_color}]"
    )
    table.add_row(
        "[bold]✅ Decisión:[/bold]",
        f"[bold {rec_color}]{eval_res.recommendation}[/bold {rec_color}]"
    )
    if eval_res.matching_skills:
        table.add_row(
            "[bold]💡 Skills match:[/bold]",
            f"[green]{', '.join(eval_res.matching_skills[:5])}[/green]"
        )
    if eval_res.missing_skills:
        table.add_row(
            "[bold]⚠️ Faltantes:[/bold]",
            f"[dim]{', '.join(eval_res.missing_skills[:3])}[/dim]"
        )
    table.add_row("[bold]📝 Motivo:[/bold]", f"[dim]{eval_res.summary_reason}[/dim]")

    console.print(Panel(
        table,
        title=f"[bold]Oferta {index}/{total} · {eval_res.job_title}[/bold]",
        border_style=score_color,
    ))


def print_apply_start(job_title: str, company: str):
    console.print(
        f"  [cyan]📨 Iniciando Easy Apply:[/cyan] "
        f"[bold white]{job_title}[/bold white] [dim]@ {company}[/dim]"
    )


def print_apply_result(success: bool, message: str):
    if success:
        console.print(f"  [bold bright_green]✓ {message}[/bold bright_green]")
    else:
        console.print(f"  [bold red]✗ {message}[/bold red]")


def print_skip(reason: str, index: int, total: int):
    console.print(f"[dim]↷ Omitiendo ({index}/{total}): {reason}[/dim]")


def print_saved_job(job_title: str, company: str, score: int, saved_in_linkedin: bool):
    status_str = "Guardada en tu perfil de LinkedIn y Excel (CSV)" if saved_in_linkedin else "Registrada en Excel (CSV)"
    console.print(Panel(
        f"[bold bright_yellow]⭐ PUESTO DESTACADO (Sin Solicitud Sencilla)[/bold bright_yellow]\n"
        f"[white]Puesto:[/white] [bold]{job_title}[/bold] @ [bold]{company}[/bold]\n"
        f"[white]Score:[/white] [bold yellow]{score}/100[/bold yellow]\n"
        f"[green]✓ {status_str}[/green]",
        title="[bold yellow]⭐ Oferta Guardada para Revisión[/bold yellow]",
        border_style="yellow",
    ))


def print_session_summary(summary: Dict[str, int], applied: int, evaluated: int):
    table = Table(
        title="[bold cyan]📊 Resumen de Sesión[/bold cyan]",
        border_style="cyan",
        show_header=True,
    )
    table.add_column("Estado", style="bold")
    table.add_column("Cantidad", justify="right", style="bold white")

    status_labels = {
        "APPLIED":   ("✅ Postuladas",         "bright_green"),
        "SAVED":     ("⭐ Guardadas externas",  "bright_yellow"),
        "SKIPPED":   ("⏭️  Omitidas",          "yellow"),
        "FAILED":    ("❌ Fallidas",           "red"),
        "EVALUATED": ("🔍 Evaluadas",         "cyan"),
    }

    for status, (label, color) in status_labels.items():
        count = summary.get(status, 0)
        if count > 0:
            table.add_row(f"[{color}]{label}[/{color}]", str(count))

    console.print("\n")
    console.print(table)
    console.print(
        f"\n[bold green]✓ Sesión finalizada.[/bold green] "
        f"Se postularon [bold]{applied}[/bold] ofertas de [bold]{evaluated}[/bold] evaluadas."
    )
    console.print("[bold cyan]Historial guardado en data/job_history.db[/bold cyan]\n")


def print_already_applied(job_title: str, company: str, index: int, total: int):
    console.print(
        f"[dim green]✓ Ya postulado ({index}/{total}):[/dim green] "
        f"[dim]{job_title} @ {company}[/dim]"
    )


def print_rate_limit_wait(seconds: int):
    console.print(
        f"[yellow]⏳ Límite de API alcanzado. Esperando {seconds}s...[/yellow]"
    )
