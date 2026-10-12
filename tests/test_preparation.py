"""Preparazione degli input del simulatore senza avviare ROS."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import yaml

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "backend"))

from swarm_platform.core.model import experiment_from_dict, load_experiment
from swarm_platform.runtime.flow import prepare_experiment


class PreparationTests(unittest.TestCase):
    def test_examples_produce_only_the_inputs_used_by_the_simulator_and_archive(self):
        for name, commands in (("single_drone", 6), ("single_drone_fast", 6),
                               ("three_drones", 18), ("negative_obstacle", 18)):
            with self.subTest(experiment=name), TemporaryDirectory(dir=PROJECT / "tests") as directory:
                spec = load_experiment(PROJECT / "examples" / (name + ".json"))
                prepared = prepare_experiment(spec, runs_dir=directory)
                paths = prepared.paths
                self.assertEqual({p.name for p in paths.root.iterdir()},
                                 {"experiment.json", "sim.params.yaml", "result.json"})
                snapshot = json.loads(paths.file("experiment.json").read_text(encoding="utf-8"))
                self.assertEqual(experiment_from_dict(snapshot), spec)
                self.assertEqual(len(prepared.plan.commands), commands)
                params = yaml.safe_load(paths.file("sim.params.yaml").read_text(encoding="utf-8"))
                robots = params["/**"]["ros__parameters"]["robots"]
                self.assertEqual(set(robots), {d.id for d in spec.drones})
                result = json.loads(paths.result_json.read_text(encoding="utf-8"))
                self.assertEqual(result["status"], "prepared")
                self.assertEqual(result["commands"], commands)
                self.assertEqual(result["planned_duration"], prepared.plan.duration)


if __name__ == "__main__":
    unittest.main()
