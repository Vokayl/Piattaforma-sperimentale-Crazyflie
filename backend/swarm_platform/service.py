"""Coordinamento della missione e stato condiviso con i gestori HTTP.

L'accesso allo stato è protetto da lock; una sola missione può essere attiva."""
from __future__ import annotations
from copy import deepcopy
import os
from pathlib import Path
import sys
import threading
import traceback
from . import __version__
from .core.model import experiment_from_dict
from .core.geometry import verify_obstacles
from .runtime.flow import prepare_experiment
from .runtime.results import atomic_json, read_json, resolve_run, utc_now, frame_page
from .runtime.runner import execute

DEFAULT_DATA = Path(os.getenv("CFP_DATA_DIR", str(Path.home() / ".crazyflie_platform")))
TERMINAL = {"completed", "error", "cancelled", "interrupted"}


class BusyError(RuntimeError):
    """Il backend supporta una sola missione attiva per volta."""


class PlatformService:
    def __init__(self, data: Path = DEFAULT_DATA,
                 *, live_hz: float = 20.0, execute_fn=execute):
        self.data = Path(data).resolve()
        self.runs = self.data / "runs"
        self.runs.mkdir(parents=True, exist_ok=True)
        if not 1 <= live_hz <= 60:
            raise ValueError("live_hz deve essere tra 1 e 60")
        self.live_hz, self.execute_fn = live_hz, execute_fn
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self.current = None
        self._state = {"status": "idle", "run_id": None, "poses": {}}
        self._revision = 0
        self._closed = False

    def busy(self) -> bool:
        """True finché il thread della missione non ha completato anche il cleanup."""
        with self.lock:
            return self.thread is not None and self.thread.is_alive()

    def health(self) -> dict:
        return {
            "application": "crazyflie-platform",
            "version": __version__,
            "transport": "http",
            "mode": "simulation_only",
            "data_directory": str(self.data),
            "python": sys.executable,
            "busy": self.busy(),
            "live_hz": self.live_hz,
        }

    def _publish(self, state: dict) -> None:
        with self.lock:
            self._state = deepcopy(state)
            self._revision += 1

    def snapshot(self, after_revision: int | None = None) -> tuple[int, dict | None]:
        """Restituisce lo stato soltanto quando la revisione è cambiata."""
        with self.lock:
            if after_revision == self._revision:
                return self._revision, None
            return self._revision, deepcopy(self._state)

    def state(self) -> dict:
        return self.snapshot()[1]

    def start(self, data: dict) -> dict:
        """Valida, prepara e avvia la missione nel thread dedicato."""
        with self.lock:
            if self._closed:
                raise RuntimeError("Backend in chiusura")
            if self.busy():
                raise BusyError("Un esperimento è già in esecuzione")

            spec = experiment_from_dict(data)
            paths = None
            try:
                prepared = prepare_experiment(spec, runs_dir=self.runs)
                paths = prepared.paths
                self.current = paths
                self.cancel.clear()
                initial = read_json(paths.result_json, {})
                initial.update(status="starting", requested_at=utc_now())
                atomic_json(paths.result_json, initial)
                self._publish({"run_id": paths.run_id, "status": "starting", "time": 0.0, "poses": {}})
                self.thread = threading.Thread(
                    target=self._execute,
                    args=(prepared,),
                    name="experiment-runner",
                    daemon=False,
                )
                self.thread.start()
            except Exception as exc:
                self.thread = None
                if paths is not None:
                    self._failure(paths, exc)
                raise
            return {"run_id": paths.run_id, "status": "starting"}

    def verify_geometry(self, data: dict) -> dict:
        """Verifica il documento corrente senza ROS, file o stato di esecuzione."""
        return verify_obstacles(experiment_from_dict(data))

    def _failure(self, paths, exc) -> None:
        """Archivia anche gli errori avvenuti dopo la creazione del run."""
        result = read_json(paths.result_json, {})
        result.update(status="error", passed=False, error=str(exc), ended_at=utc_now())
        paths.file("traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        atomic_json(paths.result_json, result)
        self._publish({
            "run_id": paths.run_id,
            "status": "error",
            "poses": {},
            "error": str(exc),
            "result": result,
        })

    def _execute(self, prepared) -> None:
        try:
            result = self.execute_fn(
                prepared,
                cancel=self.cancel.is_set,
                on_state=self._publish,
                live_hz=self.live_hz,
            )
            state = self.state()
            state.update(
                run_id=prepared.paths.run_id,
                status=result["status"],
                result=result,
                error=result.get("error"),
            )
            self._publish(state)
        except Exception as exc:
            self._failure(prepared.paths, exc)

    def stop(self) -> dict:
        """Richiede l'annullamento cooperativo al thread della missione."""
        with self.lock:
            active = self.busy()
            if active:
                self.cancel.set()
            return {"stopping": active, "run_id": self.current.run_id if self.current else None}

    def list_runs(self) -> dict:
        entries = []
        for path in sorted(self.runs.iterdir(), reverse=True):
            if not path.is_dir() or path.is_symlink():
                continue
            result = read_json(path / "result.json")
            if result:
                exp = read_json(path / "experiment.json", {})
                entries.append({
                    "run_id": path.name,
                    "name": exp.get("name", ""),
                    **{key: result.get(key) for key in
                       ("status", "passed", "error", "created_at")},
                })
            if len(entries) >= 100:
                break
        return {"runs": entries, "limit": 100}

    def get_run(self, rid: str) -> dict:
        paths = resolve_run(self.runs, rid)
        return {
            "run_id": rid,
            "experiment": read_json(paths.file("experiment.json")),
            "result": read_json(paths.result_json),
            "path": str(paths.root),
        }

    def replay(self, rid: str, offset: int = 0, limit: int = 200) -> dict:
        return frame_page(resolve_run(self.runs, rid), offset, limit, max_bytes=196_608)

    def logs(self, rid: str) -> dict:
        paths = resolve_run(self.runs, rid)
        out = {}
        for name in ("crazyswarm2.log", "traceback.log"):
            p = paths.file(name)
            if p.exists():
                with p.open("rb") as stream:
                    stream.seek(max(0, p.stat().st_size - 16000))
                    out[name] = stream.read().decode("utf-8", errors="replace")
        return out

    def close(self, timeout: float = 15.0) -> None:
        """Ferma cooperativamente la missione e attende il thread."""
        with self.lock:
            self._closed = True
        self.stop()
        thread = self.thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise RuntimeError("Thread ROS ancora attivo: arrestare il backend se il runtime nativo è bloccato")
