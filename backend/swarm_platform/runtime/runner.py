"""Esecuzione delle missioni, monitoraggio e registrazione nel thread del runner."""
from __future__ import annotations
from dataclasses import dataclass
import time
import traceback
from .monitor import Monitor, distance
from .results import Recorder, atomic_json, read_json, utc_now
from ..ros.adapter import RosSession


@dataclass
class Task:
    commands: list
    index: int = 0
    active: object = None
    future: object = None
    sent_wall: float = 0.0
    checkpoint_at: float = 0.0
    checkpoint_done: bool = False


class Cancelled(Exception):
    """Interruzione richiesta dall'utente, distinta da un errore tecnico."""


def execute(prepared, *, session_factory=RosSession, cancel=lambda: False,
            startup_timeout: float = 30.0, wall_timeout: float = 900.0,
            on_state=lambda state: None, live_hz: float = 20.0) -> dict:
    """Missioni e checkpoint seguono il tempo simulato; timeout e live il monotono."""
    if not 1 <= live_hz <= 60:
        raise ValueError("live_hz deve essere tra 1 e 60")

    paths = prepared.paths
    exp = prepared.experiment
    plan = prepared.plan
    monitor = Monitor(exp)
    base = read_json(paths.result_json, {})
    recorder = Recorder(paths)
    session = None
    result = {**base, "status": "starting", "passed": None, "started_at": utc_now()}
    atomic_json(paths.result_json, result)
    on_state({"run_id": paths.run_id, "status": "starting", "time": 0.0, "poses": {}})

    tasks = {d.id: Task([c for c in plan.commands if c.drone_id == d.id]) for d in exp.active_drones}
    origin = latest = None
    publish_at = 0.0
    started = time.monotonic()
    status, error = "error", None

    try:
        session = session_factory(exp, paths)
        session.start()
        recorder.event("simulator_started")

        while True:
            wall = time.monotonic()
            if cancel():
                raise Cancelled("Interruzione richiesta dall'utente")
            if wall - started > wall_timeout:
                raise RuntimeError("Timeout reale dell'esperimento")

            frames = session.poll(0.01)

            if origin is None:
                if frames:
                    latest = frames[-1]
                if session.ready() and latest is not None:
                    bad = [d.id for d in exp.active_drones
                           if distance(latest["poses"][d.id]["position"], d.initial_position.as_list()) > 0.01]
                    if bad:
                        raise RuntimeError("Spawn simulati non conformi al JSON: " + ", ".join(bad))
                    origin = latest["sim_time"]
                    result["status"] = "running"
                    atomic_json(paths.result_json, result)
                    recorder.event("mission_started", sim_origin=origin)
                    frames = [latest]
                elif wall - started > startup_timeout:
                    raise RuntimeError(
                        "Avvio non pronto: richiesti servizi, clock in avanzamento e TF completi. "
                        "Leggere crazyswarm2.log"
                    )
                else:
                    continue

            if wall - session.last_clock_wall > 3.0:
                raise RuntimeError("Clock simulato fermo da oltre 3 secondi reali")

            for frame in frames:
                if frame["sim_time"] < origin:
                    continue
                frame = {**frame, "time": frame["sim_time"] - origin}
                if monitor.last and frame["time"] <= monitor.last["time"]:
                    continue
                recorder.frame(frame)
                for event in monitor.observe(frame):
                    event = dict(event)
                    recorder.event(event.pop("event"), **event)
                latest = frame

            if latest is None:
                continue
            # Clock e TF arrivano da callback distinte: tolleriamo 50 ms di sfasamento.
            # Il monitor applica comunque max_sample_gap senza margini ai frame registrati.
            if session.clock - latest["sim_time"] > exp.settings.max_sample_gap + 0.05:
                raise RuntimeError("Telemetria incompleta o obsoleta rispetto al clock")

            now = session.clock
            for did, task in tasks.items():
                if task.future is not None:
                    if task.future.done():
                        response = task.future.result()
                        if response is None:
                            raise RuntimeError(f"Risposta ROS assente per {did}")
                        if hasattr(response, "success") and not response.success:
                            raise RuntimeError(f"Comando ROS rifiutato per {did}")
                        task.future = None
                        task.checkpoint_at = now + task.active.duration
                        recorder.event(
                            "command_response", drone=did, index=task.active.index,
                            time=now - origin,
                            note="Risposta del servizio, non conferma del raggiungimento del target"
                        )
                    elif wall - task.sent_wall > 5.0:
                        raise RuntimeError(f"Timeout risposta servizio {did}/{task.active.kind.value}")

                if task.active is not None and task.future is None:
                    if not task.checkpoint_done and latest["sim_time"] >= task.checkpoint_at:
                        checkpoint = monitor.checkpoint(task.active, latest)
                        recorder.event("checkpoint", **checkpoint)
                        task.checkpoint_done = True
                    if task.checkpoint_done and now >= task.checkpoint_at + task.active.hold:
                        task.index += 1
                        task.active = None

                if task.active is None and task.index < len(task.commands):
                    task.active = task.commands[task.index]
                    task.checkpoint_done = False
                    task.sent_wall = time.monotonic()
                    task.future = session.send(task.active)
                    recorder.event("command_sent", **task.active.to_dict(), actual_time=now - origin)

            if wall >= publish_at:
                on_state({
                    "run_id": paths.run_id,
                    "status": "running",
                    "sim_time": latest["sim_time"],
                    "time": latest["time"],
                    "planned_duration": plan.duration,
                    "poses": latest["poses"],
                    "frames": monitor.frames,
                    "checkpoints": len(monitor.checkpoints),
                    "violations": len(monitor.episodes),
                })
                publish_at = wall + 1.0 / live_hz

            if all(task.index == len(task.commands) for task in tasks.values()):
                status = "completed"
                break

    except Cancelled as exc:
        status, error = "cancelled", str(exc)
    except Exception as exc:
        status, error = "error", str(exc)
        paths.file("traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        if session is not None:
            try:
                session.close()
            except Exception as exc:
                if error is None:
                    status, error = "error", "Chiusura simulatore fallita: " + str(exc)

        metrics = monitor.report(len(plan.commands))
        result.update(
            status=status,
            passed=(status == "completed" and metrics["passed"]),
            ended_at=utc_now(),
            error=error,
            metrics=metrics,
            sim_origin=origin,
            observed_duration=(latest.get("time", 0.0) if latest else 0.0),
        )
        atomic_json(paths.result_json, result)
        recorder.event("run_finished", status=status, passed=result["passed"], error=error)
        recorder.close()
        on_state({
            "run_id": paths.run_id,
            "status": status,
            "time": result["observed_duration"],
            "poses": latest["poses"] if latest else {},
            "result": result,
            "error": error,
        })

    return result
