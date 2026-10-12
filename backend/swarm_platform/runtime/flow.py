"""Preparazione del piano e degli input persistenti del simulatore."""
from dataclasses import dataclass
from pathlib import Path
from ..core.model import ExperimentSpec
from ..core.planning import ExperimentPlan, compile_plan
from ..ros.config import simulator_parameters, write_yaml, SIM_BACKEND, SIM_CONTROLLER
from .results import RunPaths, create_run_directory, atomic_json, utc_now


@dataclass(frozen=True)
class PreparedExperiment:
    experiment: ExperimentSpec
    plan: ExperimentPlan
    paths: RunPaths


def prepare_experiment(experiment: ExperimentSpec, *, runs_dir: str | Path) -> PreparedExperiment:
    """Compila il piano e salva experiment.json, sim.params.yaml e result.json."""
    experiment.validate()
    plan = compile_plan(experiment)
    if plan.duration > 600:
        raise ValueError("La versione minimale limita il piano nominale a 600 secondi")
    paths = create_run_directory(Path(runs_dir))
    try:
        atomic_json(paths.file("experiment.json"), experiment.to_dict())
        write_yaml(simulator_parameters(experiment), paths.file("sim.params.yaml"))
        atomic_json(paths.result_json, {"run_id": paths.run_id, "status": "prepared", "passed": None,
            "state_source": f"crazyswarm2_{SIM_BACKEND}_tf",
            "simulation": {"backend": SIM_BACKEND, "controller": SIM_CONTROLLER},
            "planned_duration": plan.duration,
            "commands": len(plan.commands), "created_at": utc_now()})
    except Exception as exc:
        atomic_json(paths.result_json, {"run_id": paths.run_id, "status": "error", "passed": False, "error": str(exc)})
        raise
    return PreparedExperiment(experiment, plan, paths)
