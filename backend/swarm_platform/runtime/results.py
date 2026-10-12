"""Archivio dei run: documenti JSON atomici e registrazioni JSONL progressive."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Lock

_atomic_replace_lock = Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, data: dict) -> None:
    """Scrive prima un file temporaneo, poi sostituisce atomicamente il documento."""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".tmp.", delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        with _atomic_replace_lock:
            os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def read_json(path: Path, default=None):
    """Legge un artefatto opzionale; restituisce il default su assenza o JSON incompleto."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    root: Path

    def file(self, name: str) -> Path:
        return self.root / name

    @property
    def result_json(self):
        return self.file("result.json")


def create_run_directory(base: Path) -> RunPaths:
    """Identifica il run con data e ora UTC, incluse le cifre dei millisecondi."""
    created = datetime.now(timezone.utc)
    rid = created.strftime("%Y%m%dT%H%M%S") + f"{created.microsecond // 1000:03d}Z"
    p = Path(base).resolve() / rid
    p.mkdir(parents=True, exist_ok=False)
    return RunPaths(rid, p)


def resolve_run(base: Path, rid: str) -> RunPaths:
    """Rifiuta traversal e directory estranee all'archivio."""
    if not re.fullmatch(r"[0-9]{8}T[0-9]{9}Z", rid):
        raise ValueError("Identificativo run non valido")
    root = (base / rid).resolve()
    if root.parent != base.resolve() or not root.is_dir():
        raise FileNotFoundError(rid)
    return RunPaths(rid, root)


class Recorder:
    """Scrittura progressiva di ogni frame completo e degli eventi sperimentali."""
    def __init__(self, paths: RunPaths):
        self.frames = paths.file("frames.jsonl").open("w", encoding="utf-8", buffering=1)
        self.events = paths.file("events.jsonl").open("w", encoding="utf-8", buffering=1)

    def frame(self, data: dict) -> None:
        self.frames.write(json.dumps(data, allow_nan=False) + "\n")

    def event(self, event_name: str, **data) -> None:
        self.events.write(json.dumps({"event": event_name, "wall_time": utc_now(), **data}, allow_nan=False) + "\n")

    def close(self) -> None:
        self.frames.close()
        self.events.close()


def frame_page(paths: RunPaths, offset: int = 0, limit: int = 1000, *, max_bytes: int = 196_608) -> dict:
    """Legge una pagina di frame con limiti di righe e byte; offset conta le righe."""
    if offset < 0 or not 1 <= limit <= 2000:
        raise ValueError("offset >= 0; limit tra 1 e 2000")
    result = []
    used_bytes = 0
    next_offset = None
    p = paths.file("frames.jsonl")
    if p.exists():
        with p.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if len(result) == limit or (result and used_bytes + len(line.encode("utf-8")) > max_bytes):
                    next_offset = i
                    break
                try:
                    if len(line.encode("utf-8")) > max_bytes:
                        raise ValueError("Un singolo frame supera il limite della pagina")
                    result.append(json.loads(line))
                    used_bytes += len(line.encode("utf-8"))
                except json.JSONDecodeError:
                    # Un'ultima riga interrotta non cancella quelle già complete.
                    break
    return {"frames": result, "next_offset": next_offset}
