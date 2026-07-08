import sqlite3
from pathlib import Path

from app.core.config import settings


class ReadOnlySQLTool:
    def __init__(self) -> None:
        self.db_path = Path(settings.data_dir) / "tools.db"
        self._ensure_db()

    def query(self, sql: str) -> str:
        lowered = f" {sql.strip().lower()} "
        if not lowered.strip().startswith("select"):
            raise ValueError("Only SELECT queries are allowed.")
        if any(token in lowered for token in (" insert ", " update ", " delete ", " drop ", " alter ")):
            raise ValueError("Mutating SQL is not allowed.")
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(sql).fetchmany(20)
        if not rows:
            return "no rows"
        return "\n".join(str(dict(row)) for row in rows)

    def _ensure_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sample_metrics "
                "(name TEXT PRIMARY KEY, value REAL NOT NULL, unit TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO sample_metrics VALUES "
                "('citation_coverage', 1.0, 'ratio'), "
                "('default_top_k', 5, 'chunks')"
            )


sql_tool = ReadOnlySQLTool()
