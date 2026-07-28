from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
TEST_COMPOSE = ROOT / "host-compose/postgres/test/docker-compose.yml"
PROD_COMPOSE = ROOT / "host-compose/postgres/prod/docker-compose.yml"


def _postgres_service(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document["services"]["postgres"]


def test_shared_test_postgres_has_explicit_connection_capacity() -> None:
    service = _postgres_service(TEST_COMPOSE)

    assert service["command"] == [
        "postgres",
        "-c",
        "max_connections=200",
    ]


def test_test_capacity_override_does_not_change_production() -> None:
    service = _postgres_service(PROD_COMPOSE)

    assert service.get("command") != [
        "postgres",
        "-c",
        "max_connections=200",
    ]
