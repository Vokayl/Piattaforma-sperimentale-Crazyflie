"""Processo Crazyswarm2 con un proprio contesto ROS.

La funzione di ingresso è a livello di modulo per consentire l'avvio con spawn."""
from __future__ import annotations
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.signals import SignalHandlerOptions
from crazyflie_sim.crazyflie_server import CrazyflieServer
from .namespaces import run_namespace
from .config import SIM_BACKEND, SIM_CONTROLLER


def _run_server(params_path: str, run_id: str, stop_event) -> None:
    namespace = run_namespace(run_id)
    ros_args = ["--ros-args", "--params-file", params_path, "-r", "__ns:=" + namespace]
    for topic in ("tf", "tf_static", "clock"):
        for source in (topic, "/" + topic):
            ros_args += ["-r", source + ":=" + namespace + "/" + topic]

    rclpy.init(args=ros_args, signal_handler_options=SignalHandlerOptions.NO)
    node = None
    executor = None
    try:
        node = CrazyflieServer()
        backend = node._ros_parameters["sim"]["backend"]
        controller = node._ros_parameters["sim"]["controller"]
        if backend != SIM_BACKEND or controller != SIM_CONTROLLER:
            raise RuntimeError("Configurazione del simulatore non coerente con la piattaforma")

        # Inizializza il riferimento di ogni controllore nella posa di spawn.
        for cf in node.cfs.values():
            cf.cmdFullState(
                cf.initialPosition,
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                0.0,
                [0.0, 0.0, 0.0],
            )

        executor = SingleThreadedExecutor()
        executor.add_node(node)
        print(f"CF_PLATFORM_SIM_READY namespace={namespace} backend={backend} controller={controller} dt={node.backend.dt}", flush=True)
        while rclpy.ok() and not stop_event.is_set():
            executor.spin_once(timeout_sec=0.1)
    finally:
        if executor is not None:
            try:
                executor.shutdown(timeout_sec=2.0)
            except Exception:
                pass
        if node is not None:
            try:
                node.on_shutdown_callback()
            except Exception:
                pass
            try:
                node.destroy_node()
            except Exception:
                pass
        if rclpy.ok():
            rclpy.shutdown()


def run_simulator_process(params_path: str, run_id: str, log_path: str, stop_event) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", buffering=1) as log, \
         redirect_stdout(log), redirect_stderr(log):
        _run_server(params_path, run_id, stop_event)
