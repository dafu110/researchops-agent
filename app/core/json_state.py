import json
import os
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TypeVar


T = TypeVar("T")


def load_json_or_default(path: Path, default: T) -> T:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup_path = path.with_suffix(f"{path.suffix}.corrupt")
        shutil.copyfile(path, backup_path)
        return default


def atomic_json_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)
