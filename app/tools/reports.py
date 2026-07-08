from pathlib import Path
from time import time

from app.core.config import settings


class ReportWriter:
    def write_markdown(self, title: str, body: str) -> str:
        reports_dir = Path(settings.data_dir) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        filename = f"report-{int(time())}.md"
        path = reports_dir / filename
        path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        return str(path)


report_writer = ReportWriter()
