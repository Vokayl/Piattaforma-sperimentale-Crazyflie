"""Verifiche dell'archivio senza avviare ROS o il simulatore."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from swarm_platform.runtime import results

TEST_DIRECTORY = Path(__file__).resolve().parent


class ResultsTests(unittest.TestCase):

    def test_invalid_identifiers_and_traversal_are_rejected(self):
        with TemporaryDirectory(dir=TEST_DIRECTORY) as directory:
            for rid in ("../outside", "/outside", "20261012T134512Z",
                        "20261012T134512Z_abcdef1234", "20261012T134512987Z/child"):
                with self.subTest(rid=rid), self.assertRaises(ValueError):
                    results.resolve_run(Path(directory), rid)
            with self.assertRaises(FileNotFoundError):
                results.resolve_run(Path(directory), "20261012T134512987Z")


    def test_replay_pagination_works_with_timestamp_identifiers(self):
        with TemporaryDirectory(dir=TEST_DIRECTORY) as directory:
            paths = results.create_run_directory(Path(directory))
            recorder = results.Recorder(paths)
            frames = [{"time": i * 0.1, "poses": {"cf1": {"position": [i, 0, 1]}}}
                      for i in range(3)]
            try:
                for frame in frames:
                    recorder.frame(frame)
                recorder.event("mission_finished")
            finally:
                recorder.close()
            resolved = results.resolve_run(Path(directory), paths.run_id)
            page = results.frame_page(resolved, offset=0, limit=2)
            self.assertEqual(page, {"frames": frames[:2], "next_offset": 2})
            self.assertEqual(results.frame_page(resolved, offset=2, limit=2),
                             {"frames": frames[2:], "next_offset": None})


if __name__ == "__main__":
    unittest.main()
