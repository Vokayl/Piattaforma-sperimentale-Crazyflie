"""Parametri sim.params.yaml: infrastruttura fissa e robot dell'esperimento."""
from __future__ import annotations
from pathlib import Path
import yaml
from ..core.model import ExperimentSpec, WORLD_FRAME

ROBOT_TYPE = "cf21"
SIM_BACKEND = "np"
SIM_CONTROLLER = "mellinger"
SIM_DT = 0.0005


def simulator_parameters(experiment: ExperimentSpec) -> dict:
    """Genera i parametri del simulatore; assume un esperimento già validato."""
    params = {
        "fileversion": 3,
        "robots": {
            d.id: {
                "enabled": d.enabled,
                "uri": d.uri,
                "initial_position": d.initial_position.as_list(),
                "type": ROBOT_TYPE,
                "reference_frame": WORLD_FRAME,
            }
            for d in experiment.drones
        },
        "robot_types": {
            ROBOT_TYPE: {
                "connection": "crazyflie",
                "motion_capture": {
                    "tracking": "librigidbodytracker",
                    "marker": "default_single_marker",
                    "dynamics": "default",
                },
                "big_quad": False,
            },
        },
        "all": {
            "reference_frame": WORLD_FRAME,
            "firmware_logging": {"enabled": False},
            "firmware_params": {"commander": {"enHighLevel": 1}},
        },
        "robot_description": '<robot name="$NAME"><link name="base_link"/></robot>',
        # Il timer deve avanzare anche prima della pubblicazione di /clock.
        "use_sim_time": False,
        "sim": {
            "backend": SIM_BACKEND,
            "controller": SIM_CONTROLLER,
            "max_dt": SIM_DT,
            "visualizations": {"rviz": {"enabled": True}},
        },
    }
    return {"/**": {"ros__parameters": params}}


def write_yaml(config: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
