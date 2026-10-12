"""Dati e criteri degli esperimenti, senza dipendenze ROS/Godot."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import json
import math
from pathlib import Path
import re
from typing import Any

WORLD_FRAME = "world"


class ValidationError(ValueError):
    """Errore leggibile nella descrizione dell'esperimento."""


def _pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValidationError(f"Chiave JSON duplicata: {k}")
        out[k] = v
    return out


def decode_json(text: str) -> Any:
    """Legge JSON rigoroso senza valori speciali NaN o Infinity."""
    return json.loads(text, object_pairs_hook=_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValidationError(f"Numero non finito: {x}")))


def obj(v: Any, label: str, keys: set[str] | None = None) -> dict:
    if not isinstance(v, dict) or (keys is not None and set(v) - keys):
        raise ValidationError(f"{label}: oggetto non valido")
    return v


def number(v: Any, label: str, minimum: float | None = None) -> float:
    """Accetta solo numeri finiti: bool non è un valore numerico del modello."""
    if (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            or (minimum is not None and v < minimum)):
        raise ValidationError(f"{label}: numero non valido")
    return float(v)


def text(v: Any, label: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValidationError(f"{label}: testo non valido")
    return v


def identifier(v: Any, label: str) -> str:
    s = text(v, label)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,47}", s) or s in {"all", "crazyflie_server"}:
        raise ValidationError(f"{label}: identificativo non valido")
    return s


def boolean(v: Any, label: str) -> bool:
    if not isinstance(v, bool):
        raise ValidationError(f"{label}: atteso booleano")
    return v


def array(v: Any, label: str, maximum: int = 1000) -> list:
    if not isinstance(v, list) or len(v) > maximum:
        raise ValidationError(f"{label}: lista non valida")
    return v


@dataclass(frozen=True)
class Vec3:
    """Posizione in metri nel riferimento ROS."""
    x: float
    y: float
    z: float

    @classmethod
    def from_value(cls, v: Any, label: str) -> Vec3:
        if not isinstance(v, list) or len(v) != 3:
            raise ValidationError(f"{label}: attesa terna [x,y,z]")
        return cls(*(number(n, label) for n in v))

    def as_list(self) -> list[float]:
        return [self.x, self.y, self.z]


@dataclass(frozen=True)
class Bounds3D:
    """Limiti dello scenario, applicati ai centri dei droni."""
    minimum: Vec3
    maximum: Vec3


@dataclass(frozen=True)
class ObstacleBox:
    """Box allineato agli assi ROS, non corpo dinamico del simulatore."""
    id: str
    center: Vec3
    size: Vec3


@dataclass(frozen=True)
class ScenarioSpec:
    bounds: Bounds3D | None = None
    obstacles: tuple[ObstacleBox, ...] = ()


@dataclass(frozen=True)
class DroneSpec:
    """Identità e condizioni iniziali; radius è l'ingombro del monitor."""
    id: str
    uri: str
    initial_position: Vec3
    enabled: bool = True
    radius: float = 0.08


@dataclass(frozen=True)
class Waypoint:
    """Target assoluto, yaw in radianti, durata del trasferimento e sosta."""
    position: Vec3
    yaw: float
    duration: float
    hold: float = 0.0


@dataclass(frozen=True)
class TakeoffSpec:
    height: float
    duration: float


@dataclass(frozen=True)
class LandSpec:
    height: float = 0.04
    duration: float = 2.0


@dataclass(frozen=True)
class MissionSpec:
    drone_id: str
    takeoff: TakeoffSpec
    waypoints: tuple[Waypoint, ...]
    land: LandSpec


@dataclass(frozen=True)
class Settings:
    target_tolerance: float = 0.10  # metri, checkpoint di posizione
    yaw_tolerance_degrees: float = 5.0  # gradi, solo checkpoint go_to
    min_separation: float = 0.25   # metri, distanza minima tra i centri
    max_sample_gap: float = 0.25  # secondi di tempo simulato


@dataclass(frozen=True)
class ExperimentSpec:
    """Documento canonico normalizzato, indipendente da ROS e Godot."""
    name: str
    scenario: ScenarioSpec
    drones: tuple[DroneSpec, ...]
    missions: tuple[MissionSpec, ...]
    metadata: dict = field(default_factory=dict)
    settings: Settings = field(default_factory=Settings)

    @property
    def active_drones(self) -> tuple[DroneSpec, ...]:
        return tuple(d for d in self.drones if d.enabled)

    def validate(self) -> None:
        """Verifica anche istanze create direttamente in Python."""
        names = [m.drone_id for m in self.missions]
        if len(names) != len(set(names)):
            raise ValidationError("Due missioni associate allo stesso drone")
        experiment_from_dict(self.to_dict())

    def to_dict(self) -> dict:
        scenario = {"obstacles": [{"id": o.id, "center": o.center.as_list(), "size": o.size.as_list()}
                                  for o in self.scenario.obstacles]}
        if self.scenario.bounds is not None:
            scenario["bounds"] = {"min": self.scenario.bounds.minimum.as_list(),
                                  "max": self.scenario.bounds.maximum.as_list()}
        return {"name": self.name,
                "scenario": scenario,
                "drones": [{"id": d.id, "uri": d.uri, "initial_position": d.initial_position.as_list(),
                            "enabled": d.enabled, "radius": d.radius} for d in self.drones],
                "missions": {m.drone_id: {"takeoff": asdict(m.takeoff),
                    "waypoints": [{"position": w.position.as_list(), "yaw": w.yaw,
                                   "duration": w.duration, "hold": w.hold} for w in m.waypoints],
                    "land": asdict(m.land)} for m in self.missions},
                "settings": asdict(self.settings), "metadata": self.metadata}


def experiment_from_dict(data: dict) -> ExperimentSpec:
    try:
        obj(data, "esperimento", {"name", "scenario", "drones", "missions", "settings", "metadata"})
        s = obj(data.get("scenario", {}), "scenario", {"bounds", "obstacles"})
        bounds = None
        if s.get("bounds") is not None:
            b = obj(s["bounds"], "bounds", {"min", "max"})
            bounds = Bounds3D(Vec3.from_value(b["min"], "bounds.min"), Vec3.from_value(b["max"], "bounds.max"))
            if any(a >= b for a, b in zip(bounds.minimum.as_list(), bounds.maximum.as_list())):
                raise ValidationError("bounds: min deve essere < max su ogni asse")
        obstacles, obstacle_ids = [], set()
        for o in array(s.get("obstacles", []), "obstacles", 100):
            obj(o, "obstacle", {"id", "center", "size"})
            oid = identifier(o["id"], "obstacle.id")
            if oid in obstacle_ids:
                raise ValidationError(f"Ostacolo duplicato: {oid}")
            obstacle_ids.add(oid)
            size = Vec3.from_value(o["size"], "obstacle.size")
            if min(size.as_list()) <= 0:
                raise ValidationError("Le dimensioni degli ostacoli devono essere > 0")
            obstacles.append(ObstacleBox(oid, Vec3.from_value(o["center"], "obstacle.center"), size))
        drones, ids, uris = [], set(), set()
        for d in array(data["drones"], "drones", 32):
            obj(d, "drone", {"id", "uri", "initial_position", "enabled", "radius"})
            did = identifier(d["id"], "drone.id")
            if did == WORLD_FRAME:
                raise ValidationError("Il frame del drone non può coincidere con il riferimento world")
            if did in ids:
                raise ValidationError(f"Drone duplicato: {did}")
            ids.add(did)
            enabled = boolean(d.get("enabled", True), "enabled")
            uri = text(d["uri"], "uri")
            if enabled and uri in uris:
                raise ValidationError(f"URI duplicata per i droni abilitati: {uri}")
            if enabled:
                uris.add(uri)
            drones.append(DroneSpec(did, uri, Vec3.from_value(d["initial_position"], "initial_position"),
                          enabled, number(d.get("radius", 0.08), "radius", 0.001)))
        if not any(d.enabled for d in drones):
            raise ValidationError("È richiesto almeno un drone abilitato")
        ms = obj(data["missions"], "missions")
        missions = []
        for did, m in ms.items():
            if did not in ids:
                raise ValidationError(f"Missione per un drone inesistente: {did}")
            obj(m, f"missione {did}", {"takeoff", "waypoints", "land"})
            to = obj(m["takeoff"], "takeoff", {"height", "duration"})
            ld = obj(m.get("land", {}), "land", {"height", "duration"})
            wp = []
            for w in array(m.get("waypoints", []), "waypoints", 200):
                obj(w, "waypoint", {"position", "yaw", "duration", "hold"})
                wp.append(Waypoint(Vec3.from_value(w["position"], "waypoint.position"),
                                   number(w.get("yaw", 0), "yaw"),
                                   number(w["duration"], "waypoint.duration", 0.1),
                                   number(w.get("hold", 0), "hold", 0)))
            missions.append(MissionSpec(did,
                TakeoffSpec(number(to["height"], "takeoff.height", 0.001), number(to["duration"], "takeoff.duration", 0.1)),
                tuple(wp), LandSpec(number(ld.get("height", 0.04), "land.height", 0),
                                   number(ld.get("duration", 2), "land.duration", 0.1))))
        for d in drones:
            if d.enabled and d.id not in ms:
                raise ValidationError(f"Manca la missione per {d.id}")
        st = obj(data["settings"], "settings", set(Settings.__dataclass_fields__))
        for key in ("target_tolerance", "yaw_tolerance_degrees"):
            if key not in st:
                raise ValidationError(f"Campo obbligatorio mancante: settings.{key}")
        defaults = asdict(Settings())
        defaults.update(st)
        settings = Settings(**{k: number(v, f"settings.{k}", 0.04 if k == "max_sample_gap" else 0)
                              for k, v in defaults.items()})
        if settings.yaw_tolerance_degrees > 180:
            raise ValidationError("settings.yaw_tolerance_degrees deve essere <= 180")
        metadata = obj(data.get("metadata", {}), "metadata")
        json.dumps(metadata, allow_nan=False)  # rifiuta metadati non serializzabili
        return ExperimentSpec(text(data["name"], "name"), ScenarioSpec(bounds, tuple(obstacles)),
                              tuple(drones), tuple(missions), metadata, settings)
    except KeyError as exc:
        raise ValidationError(f"Campo obbligatorio mancante: {exc.args[0]}") from exc
    except (TypeError, OverflowError) as exc:
        raise ValidationError("Documento non valido") from exc


def load_experiment(path: str | Path) -> ExperimentSpec:
    return experiment_from_dict(decode_json(Path(path).read_text(encoding="utf-8-sig")))
