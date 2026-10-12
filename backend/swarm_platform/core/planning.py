"""Piano nominale dei comandi di ciascun drone."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import Enum
from .model import ExperimentSpec, Vec3


class CommandKind(str, Enum):
    TAKEOFF = "takeoff"
    GO_TO = "go_to"
    LAND = "land"


@dataclass(frozen=True)
class PlannedCommand:
    drone_id: str
    index: int
    kind: CommandKind
    start_time: float
    duration: float
    target: tuple[float, float, float]
    yaw: float = 0.0
    hold: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["target"] = list(self.target)
        return d


@dataclass(frozen=True)
class ExperimentPlan:
    commands: tuple[PlannedCommand, ...]
    duration: float


def compile_plan(experiment: ExperimentSpec) -> ExperimentPlan:
    """Compila sequenze per drone; precondizione: esperimento valido."""
    active = {d.id: d for d in experiment.active_drones}
    out, ends = [], []
    for m in experiment.missions:
        if m.drone_id not in active:
            continue
        p = active[m.drone_id].initial_position.as_list()
        actions = [(CommandKind.TAKEOFF, (p[0], p[1], m.takeoff.height), 0., m.takeoff.duration, 0.)]
        for w in m.waypoints:
            p = w.position.as_list()
            actions.append((CommandKind.GO_TO, tuple(p), w.yaw, w.duration, w.hold))
        actions.append((CommandKind.LAND, (p[0], p[1], m.land.height), 0., m.land.duration, 0.))
        t = 0.
        for i, (kind, target, yaw, duration, hold) in enumerate(actions):
            c = PlannedCommand(m.drone_id, i, kind, t, duration, target, yaw, hold)
            out.append(c)
            t += duration + hold
        ends.append(t)
    out.sort(key=lambda c: (c.start_time, c.drone_id, c.index))
    return ExperimentPlan(tuple(out), max(ends, default=0.))
