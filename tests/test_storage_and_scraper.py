import sys
import tempfile
from pathlib import Path
import csv

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.storage import StorageRepository
from src.linkedin_scraper import LinkedInScraper


def test_scraper_generate_id_url():
    scraper = LinkedInScraper()
    # Format 1: /jobs/view/123456789/
    id1 = scraper._generate_id("https://www.linkedin.com/jobs/view/123456789/?refId=abc", "Dev", "Comp")
    assert id1 == "li-123456789"

    # Format 2: ?currentJobId=987654321&keywords=python
    id2 = scraper._generate_id("https://www.linkedin.com/jobs/search/?currentJobId=987654321&geoId=100", "Dev", "Comp")
    assert id2 == "li-987654321"

    # Format 3: Deterministic MD5 fallback
    id3a = scraper._generate_id("https://example.com/invalid", "Python Developer", "TechCorp")
    id3b = scraper._generate_id("https://example.com/invalid", "Python Developer", "TechCorp")
    assert id3a == id3b
    assert id3a.startswith("li-")


def test_storage_repository_flow():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        csv_path = Path(tmp_dir) / "test_saved.csv"

        storage = StorageRepository(db_path)
        storage.init_db()

        # Job evaluation
        job_id = "li-12345"
        assert not storage.is_job_seen(job_id)

        storage.record_job_evaluation(
            job_id=job_id,
            title="Junior Python Dev",
            company="Startup Inc",
            score=85,
            recommendation="APPLY",
            reason="Gran afinidad con perfil",
            url="https://www.linkedin.com/jobs/view/12345/",
        )

        assert storage.is_job_seen(job_id)

        # Mark as saved (oferta externa destacada)
        storage.mark_as_saved(job_id, "Guardada en LinkedIn y CSV")
        job_record = storage.get_job(job_id)
        assert job_record is not None
        assert job_record["status"] == "SAVED"

        # Record to CSV
        job_data = {
            "title": "Junior Python Dev",
            "company": "Startup Inc",
            "location": "CABA (Híbrido)",
            "score": 85,
            "reason": "Gran afinidad con perfil",
            "url": "https://www.linkedin.com/jobs/view/12345/",
        }
        storage.record_saved_job_to_csv(job_data, filepath=csv_path)

        # Verify CSV contents and encoding
        assert csv_path.exists()
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
            assert len(rows) == 1
            assert rows[0]["Puesto"] == "Junior Python Dev"
            assert rows[0]["Empresa"] == "Startup Inc"
            assert rows[0]["Score"] == "85"
            assert rows[0]["URL_LinkedIn"] == "https://www.linkedin.com/jobs/view/12345/"

        # Ensure deduplication in CSV
        storage.record_saved_job_to_csv(job_data, filepath=csv_path)
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
            assert len(rows) == 1  # Did not duplicate
