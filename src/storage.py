import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any, Generator
from datetime import datetime


class StorageRepository:
    """
    Repositorio SQLite para historial de ofertas de LinkedIn.
    Estructura idéntica al bot USAL para consistencia entre proyectos.
    Agrega columna `url` para rastrear links de LinkedIn.
    """

    def __init__(self, db_path: str | Path = "data/job_history.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id        TEXT UNIQUE NOT NULL,
                    title         TEXT NOT NULL,
                    company       TEXT NOT NULL,
                    url           TEXT,
                    fit_score     INTEGER NOT NULL,
                    recommendation TEXT NOT NULL,
                    reason        TEXT,
                    status        TEXT NOT NULL,
                    evaluated_at  TEXT NOT NULL,
                    applied_at    TEXT
                );
            """)
            # Migración segura: agrega columna url si no existe (bases antiguas)
            try:
                cursor.execute("ALTER TABLE jobs ADD COLUMN url TEXT")
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def is_job_seen(self, job_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,))
            return cursor.fetchone() is not None

    def record_job_evaluation(
        self,
        job_id: str,
        title: str,
        company: str,
        score: int,
        recommendation: str,
        reason: str,
        url: Optional[str] = None,
    ) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO jobs
                (job_id, title, company, url, fit_score, recommendation, reason, status, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, title, company, url,
                score, recommendation, reason,
                "EVALUATED",
                datetime.now().isoformat()
            ))
            conn.commit()

    def mark_as_applied(self, job_id: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs
                SET status = 'APPLIED', applied_at = ?
                WHERE job_id = ?
            """, (datetime.now().isoformat(), job_id))
            conn.commit()

    def mark_as_failed(self, job_id: str, reason: str = "Error en formulario") -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs
                SET status = 'FAILED', reason = ?
                WHERE job_id = ?
            """, (reason, job_id))
            conn.commit()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def mark_as_saved(self, job_id: str, reason: str = "Guardada en LinkedIn para postulación externa") -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs
                SET status = 'SAVED', reason = ?
                WHERE job_id = ?
            """, (reason, job_id))
            conn.commit()

    def record_saved_job_to_csv(
        self,
        job_data: Dict[str, Any],
        filepath: str | Path = "data/empleos_guardados.csv"
    ) -> None:
        """
        Registra una oferta externa guardada en un archivo CSV formateado para Excel.
        Evita duplicados comprobando la URL.
        """
        import csv
        csv_path = Path(filepath)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        headers = ["Fecha", "Puesto", "Empresa", "Modalidad_Ubicacion", "Score", "Motivo", "URL_LinkedIn"]
        file_exists = csv_path.exists()

        # Evitar duplicar filas
        if file_exists:
            try:
                with open(csv_path, mode="r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("URL_LinkedIn") and row.get("URL_LinkedIn") == job_data.get("url"):
                            return
            except Exception:
                pass

        with open(csv_path, mode="a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Puesto": job_data.get("title", ""),
                "Empresa": job_data.get("company", ""),
                "Modalidad_Ubicacion": job_data.get("location", ""),
                "Score": job_data.get("score", 0),
                "Motivo": job_data.get("reason", ""),
                "URL_LinkedIn": job_data.get("url", ""),
            })

    def mark_as_skipped(self, job_id: str, reason: str = "Score insuficiente") -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs
                SET status = 'SKIPPED', reason = ?
                WHERE job_id = ?
            """, (reason, job_id))
            conn.commit()

    def get_applied_count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'APPLIED'")
            row = cursor.fetchone()
            return row[0] if row else 0

    def get_session_summary(self) -> Dict[str, int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status, COUNT(*) as cnt
                FROM jobs
                GROUP BY status
            """)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_all_jobs(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs ORDER BY id DESC")
            return [dict(row) for row in cursor.fetchall()]
