from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml


COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def test_compose_postgres_credentials_are_consistent() -> None:
    compose = _load_compose()
    services = compose["services"]

    postgres_environment = services["postgres"]["environment"]
    expected_user = postgres_environment["POSTGRES_USER"]
    expected_password = postgres_environment["POSTGRES_PASSWORD"]
    expected_database = postgres_environment["POSTGRES_DB"]

    assert expected_password

    for service_name in ("migrate", "api"):
        database_url = services[service_name]["environment"]["DATABASE_URL"]
        parsed = urlparse(database_url)

        assert parsed.scheme == "postgresql"
        assert parsed.username == expected_user
        assert parsed.password is not None
        assert unquote(parsed.password) == expected_password
        assert parsed.hostname == "postgres"
        assert parsed.port == 5432
        assert parsed.path == f"/{expected_database}"


def test_compose_keeps_legacy_volume_names_stable() -> None:
    compose = _load_compose()

    assert compose["volumes"] == {
        "postgres_data": {"name": "mlproject_postgres_data"},
        "qdrant_data": {"name": "mlproject_qdrant_data"},
        "uploads_data": {"name": "mlproject_uploads_data"},
        "huggingface_cache": {"name": "mlproject_huggingface_cache"},
    }
