import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app import main
from backend.app.main import cors_origins_from_environment, database_url_from_environment

client = TestClient(main.app)


def test_postgres_url_normalization_preserves_encoded_credentials_and_options(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://student%40uiu:p%2Fss%3Aword@db.example:5432/sections?sslmode=require&application_name=uiu",
    )

    url = database_url_from_environment()

    assert url.drivername == "postgresql+psycopg"
    assert url.username == "student@uiu"
    assert url.password == "p/ss:word"
    assert url.query == {"sslmode": "require", "application_name": "uiu"}


def test_sqlite_url_remains_supported(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./local.db")

    assert database_url_from_environment().drivername == "sqlite"


def test_health_endpoint_checks_database_connectivity():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["database"] == "connected"


def test_cors_origins_are_trimmed_deduplicated_and_have_no_trailing_slash(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " https://uiu.vercel.app/,http://localhost:5173,https://uiu.vercel.app ")

    assert cors_origins_from_environment() == ["https://uiu.vercel.app", "http://localhost:5173"]


def test_catalog_initialization_adds_missing_rows_without_overwriting_data_or_routines(monkeypatch):
    test_engine = create_engine("sqlite:///:memory:")
    main.Base.metadata.create_all(test_engine)
    catalog = json.loads((main.DATA_DIR / "fall_2026_sections.json").read_text(encoding="utf-8"))
    first_section = catalog["sections"][0]
    original_name = first_section["course_name"]
    monkeypatch.setattr(main, "engine", test_engine)
    with Session(test_engine) as db:
        db.add(main.SectionRecord(**{**first_section, "course_name": "Preserved existing record"}))
        db.add(main.RoutineRecord(name="Preserved user routine", section_ids=[], preferences={}))
        db.commit()

    main.initialize_catalog()

    with Session(test_engine) as db:
        section = db.scalar(select(main.SectionRecord).where(main.SectionRecord.source_serial == first_section["source_serial"]))
        routine = db.scalar(select(main.RoutineRecord).where(main.RoutineRecord.name == "Preserved user routine"))
        assert section is not None and section.course_name == "Preserved existing record"
        assert original_name != section.course_name
        assert routine is not None
        assert db.scalar(select(main.SectionRecord.id).where(main.SectionRecord.source_serial == catalog["sections"][1]["source_serial"])) is not None
    test_engine.dispose()
