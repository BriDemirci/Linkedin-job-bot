"""
tests/test_config.py
====================
Valida que los archivos de configuración sean correctos y completos
antes de ejecutar el bot.
"""

import json
import os
import pytest
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
PROFILE_PATH = BASE_DIR / "config" / "profile.json"
CRITERIA_PATH = BASE_DIR / "config" / "criteria.json"
QUERIES_PATH = BASE_DIR / "config" / "search_queries.json"
ENV_PATH = BASE_DIR / ".env"


class TestProfileConfig:
    def setup_method(self):
        target = PROFILE_PATH if PROFILE_PATH.exists() else (BASE_DIR / "config" / "profile.example.json")
        with open(target, "r", encoding="utf-8") as f:
            self.profile = json.load(f)

    def test_profile_file_exists(self):
        assert PROFILE_PATH.exists() or (BASE_DIR / "config" / "profile.example.json").exists(), (
            "No se encontró ni config/profile.json ni config/profile.example.json"
        )

    def test_required_fields_present(self):
        required_fields = [
            "full_name", "first_name", "last_name",
            "email", "phone",
            "career", "skills", "languages",
            "years_of_experience_general",
            "authorized_to_work_in_argentina",
            "cover_letter_template",
        ]
        for field in required_fields:
            assert field in self.profile, f"Campo requerido faltante en profile.json: '{field}'"

    def test_personal_data_not_placeholder(self):
        """Verifica que el usuario haya completado sus datos personales."""
        full_name = self.profile.get("full_name", "")
        if full_name.startswith("TU "):
            pytest.skip("profile.json aún tiene datos placeholder — completar antes de ejecutar.")

    def test_skills_not_empty(self):
        assert len(self.profile.get("skills", [])) > 0, "El perfil no tiene skills definidas"

    def test_education_present(self):
        edu = self.profile.get("education", [])
        assert len(edu) > 0, "El perfil no tiene educación definida"

    def test_languages_have_level(self):
        for lang in self.profile.get("languages", []):
            assert "language" in lang and "level" in lang, \
                f"Idioma mal formateado: {lang}"


class TestCriteriaConfig:
    def setup_method(self):
        with open(CRITERIA_PATH, "r", encoding="utf-8") as f:
            self.criteria = json.load(f)

    def test_criteria_file_exists(self):
        assert CRITERIA_PATH.exists()

    def test_min_fit_score_valid(self):
        score = self.criteria.get("min_fit_score", 0)
        assert 0 <= score <= 100, f"min_fit_score debe estar entre 0 y 100, es {score}"

    def test_excluded_disciplines_is_list(self):
        assert isinstance(self.criteria.get("excluded_disciplines", []), list)

    def test_max_applications_positive(self):
        max_apps = self.criteria.get("max_applications_per_run", 0)
        assert max_apps > 0, "max_applications_per_run debe ser > 0"


class TestSearchQueriesConfig:
    def setup_method(self):
        with open(QUERIES_PATH, "r", encoding="utf-8") as f:
            self.config = json.load(f)

    def test_queries_file_exists(self):
        assert QUERIES_PATH.exists()

    def test_queries_not_empty(self):
        queries = self.config.get("queries", [])
        assert len(queries) > 0, "No hay queries de búsqueda configuradas"

    def test_location_defined(self):
        assert self.config.get("location"), "No se definió la ubicación de búsqueda"

    def test_max_results_positive(self):
        max_r = self.config.get("max_results_per_query", 0)
        assert max_r > 0, "max_results_per_query debe ser > 0"


class TestEnvConfig:
    def test_env_file_exists(self):
        if not ENV_PATH.exists():
            pytest.skip(".env no existe (se crea a partir de .env.example).")

    def test_gemini_api_key_set(self):
        if not ENV_PATH.exists():
            pytest.skip(".env no existe.")
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
        key = os.getenv("GEMINI_API_KEY", "")
        if not key or key == "tu_api_key_aqui":
            pytest.skip("GEMINI_API_KEY no está configurada aún en .env")
