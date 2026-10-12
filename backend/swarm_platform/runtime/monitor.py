"""Valutazione della telemetria: separazione, limiti, qualità e target.

Gli ostacoli sono verificati separatamente sul piano da core.geometry.
"""
from __future__ import annotations
from itertools import combinations
import math
from ..core.model import ExperimentSpec
from ..core.planning import PlannedCommand, CommandKind


def distance(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class Monitor:
    def __init__(self, experiment: ExperimentSpec):
        self.exp = experiment
        self.drones = {d.id: d for d in experiment.active_drones}
        self.frames = 0
        self.last = None
        self.min_distance = None
        self.lengths = {i: 0.0 for i in self.drones}
        self.episodes: list[dict] = []
        self.active: dict[str, dict] = {}
        self.checkpoints: list[dict] = []
        self.quality: list[str] = []
        self.max_gap = 0.0

    def observe(self, frame: dict) -> list[dict]:
        t, poses = frame["time"], frame["poses"]
        if set(poses) != set(self.drones):
            raise ValueError("Frame incompleto: tutti i droni attivi devono avere lo stesso timestamp")
        if self.last is not None:
            gap = t - self.last["time"]
            if gap <= 0:
                raise ValueError("Timestamp non strettamente crescente")
            self.max_gap = max(self.max_gap, gap)
            if gap > self.exp.settings.max_sample_gap and "sample_gap" not in self.quality:
                self.quality.append("sample_gap")
            for did in poses:
                self.lengths[did] += distance(poses[did]["position"], self.last["poses"][did]["position"])
        self.frames += 1
        present: dict[str, dict] = {}
        for a, b in combinations(sorted(poses), 2):
            d = distance(poses[a]["position"], poses[b]["position"])
            self.min_distance = d if self.min_distance is None else min(self.min_distance, d)
            required = max(self.exp.settings.min_separation, self.drones[a].radius + self.drones[b].radius)
            if d < required:
                present[f"separation:{a}:{b}"] = {"kind": "separation", "drones": [a, b], "threshold": required}
        bounds = self.exp.scenario.bounds
        for did, pose in poses.items():
            p = pose["position"]
            # I confini includono i centri sul piano di decollo.
            if bounds and any(v < lo or v > hi for v, lo, hi in
                              zip(p, bounds.minimum.as_list(), bounds.maximum.as_list())):
                present[f"bounds:{did}"] = {"kind": "bounds", "drones": [did]}
        events = []
        for key in list(self.active):
            if key not in present:
                record = self.active.pop(key)
                record["end"] = t
                events.append({"event": "violation_end", **record})
        for key, desc in present.items():
            if key not in self.active:
                record = {"key": key, "start": t, "last_observed": t, "end": None, **desc}
                self.active[key] = record
                self.episodes.append(record)
                events.append({"event": "violation_start", **record})
            else:
                self.active[key]["last_observed"] = t
        self.last = frame
        return events

    def checkpoint(self, command: PlannedCommand, frame: dict) -> dict:
        """Confronta il target con una posa osservata; non assume il completamento dal servizio."""
        p = frame["poses"][command.drone_id]["position"]
        error = distance(p, command.target)
        record = {"drone": command.drone_id, "index": command.index, "command": command.kind.value,
                  "time": frame["time"], "target": list(command.target), "observed": p,
                  "position_error": error, "position_passed": error <= self.exp.settings.target_tolerance,
                  "yaw_target": None, "yaw_observed": None, "yaw_error_degrees": None, "yaw_passed": None}
        if command.kind == CommandKind.GO_TO:
            x, y, z, w = frame["poses"][command.drone_id]["orientation"]
            yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
            delta = yaw - command.yaw
            yaw_error = abs(math.degrees(math.atan2(math.sin(delta), math.cos(delta))))
            record.update(yaw_target=command.yaw, yaw_observed=yaw, yaw_error_degrees=yaw_error,
                          yaw_passed=yaw_error <= self.exp.settings.yaw_tolerance_degrees)
        record["passed"] = record["position_passed"] and record["yaw_passed"] is not False
        self.checkpoints.append(record)
        return record

    def report(self, expected: int) -> dict:
        """Produce l'esito dei criteri, distinto dallo stato tecnico del runner."""
        complete = len(self.checkpoints) == expected and self.frames > 0
        if self.episodes or any(not c["passed"] for c in self.checkpoints):
            evaluation = "failed"
        elif not complete or self.quality:
            evaluation = "inconclusive"
        else:
            evaluation = "passed"
        return {"passed": evaluation == "passed", "evaluation": evaluation, "frames": self.frames,
                "criteria": {"target_tolerance": self.exp.settings.target_tolerance,
                             "yaw_tolerance_degrees": self.exp.settings.yaw_tolerance_degrees,
                             "min_separation": self.exp.settings.min_separation,
                             "max_sample_gap": self.exp.settings.max_sample_gap},
                "min_center_distance": self.min_distance, "path_length": self.lengths,
                "checkpoints_expected": expected, "checkpoints_observed": len(self.checkpoints),
                "checkpoints": self.checkpoints, "violations": self.episodes,
                "data_quality": self.quality, "max_sample_gap": self.max_gap,
                "scope": "sampled_separation_centers_bounds_position_and_go_to_yaw_checkpoints"}
