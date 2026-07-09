from pathlib import Path
from types import ModuleType

from app.core.config import settings


def psycopg_url(url: str | None = None) -> str:
    raw_url = url or settings.database_url
    return raw_url.replace("postgresql+psycopg://", "postgresql://", 1)


def load_psycopg() -> ModuleType:
    import psycopg

    return psycopg


def init_schema(psycopg: ModuleType, database_url: str | None = None) -> None:
    schema = _schema_path().read_text(encoding="utf-8")
    with psycopg.connect(psycopg_url(database_url)) as connection:
        connection.execute(schema)


def wants_postgres() -> bool:
    return settings.store_backend in {"auto", "postgres"}


def should_raise_postgres_errors() -> bool:
    return settings.store_backend == "postgres"


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "db" / "schema.sql"
