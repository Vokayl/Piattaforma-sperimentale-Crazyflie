"""Sessione ROS del run e gestione del processo simulatore.

Il metodo spawn evita che il figlio erediti il runtime DDS del backend."""
from __future__ import annotations
from collections import deque
import multiprocessing
import time
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.signals import SignalHandlerOptions
from rclpy.context import Context
from tf2_msgs.msg import TFMessage
from rosgraph_msgs.msg import Clock
from crazyflie_interfaces.srv import Takeoff, GoTo, Land
from .namespaces import run_namespace, drone_service
from .simulator import run_simulator_process
from ..runtime.telemetry import FrameAssembler


def stop_process(process, stop_event) -> None:
    """Arresta cooperativamente il processo Crazyswarm2 con fallback forzato."""
    if process is None:
        return
    stop_event.set()
    process.join(3.0)
    if process.is_alive():
        process.terminate()
        process.join(2.0)
    if process.is_alive():
        process.kill()
        process.join(2.0)


class RosSession:
    def __init__(self, experiment, paths):
        self.exp, self.paths = experiment, paths
        self.namespace = run_namespace(paths.run_id)
        self.clock = None
        self.clock_changes = 0
        self.last_clock_wall = time.monotonic()
        self.frames = deque()
        self.assembler = FrameAssembler([d.id for d in experiment.active_drones])
        self.error = None
        self.node = self.executor = self.context = None
        self.clients = {}
        self.process = None
        self.mp_context = multiprocessing.get_context("spawn")
        self.simulator_stop = self.mp_context.Event()

    def start(self):

        self.types = {"takeoff": Takeoff, "go_to": GoTo, "land": Land}
        self.context = Context()
        rclpy.init(args=[], context=self.context, signal_handler_options=SignalHandlerOptions.NO)
        self.node = rclpy.create_node(
            "experiment_observer",
            namespace=self.namespace,
            context=self.context,
        )
        self.executor = SingleThreadedExecutor(context=self.context)
        self.executor.add_node(self.node)

        qos = QoSProfile(
            depth=200,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.node.create_subscription(TFMessage, self.namespace + "/tf", self._tf, qos)
        self.node.create_subscription(Clock, self.namespace + "/clock", self._clock, qos)

        for drone in self.exp.active_drones:
            for operation, interface in self.types.items():
                self.clients[drone.id, operation] = self.node.create_client(
                    interface,
                    drone_service(drone.id, operation, self.namespace),
                )

        params_path = str(self.paths.file("sim.params.yaml"))
        log_path = str(self.paths.file("crazyswarm2.log"))
        self.process = self.mp_context.Process(
            target=run_simulator_process,
            args=(params_path, self.paths.run_id, log_path, self.simulator_stop),
            name=f"crazyflie-sim-{self.paths.run_id}",
            daemon=False,
        )
        self.process.start()

    def _clock(self, msg):
        """Osserva il clock simulato e rileva regressioni temporali."""
        t = msg.clock.sec + msg.clock.nanosec / 1e9
        if self.clock is not None and t < self.clock:
            self.error = RuntimeError("Il clock simulato è tornato indietro")
        if self.clock is None or t > self.clock:
            self.last_clock_wall = time.monotonic()
            self.clock_changes += 1
        self.clock = t

    def _tf(self, msg):
        """Raggruppa TF coerenti; una coda satura interrompe l'acquisizione."""
        try:
            for transform in msg.transforms:
                p = transform.transform.translation
                q = transform.transform.rotation
                stamp = transform.header.stamp.sec * 1_000_000_000 + transform.header.stamp.nanosec
                frame = self.assembler.add(
                    stamp,
                    transform.child_frame_id,
                    transform.header.frame_id,
                    [p.x, p.y, p.z],
                    [q.x, q.y, q.z, q.w],
                )
                if frame is not None:
                    if len(self.frames) >= 1000:
                        raise RuntimeError("Coda di telemetria satura")
                    self.frames.append(frame)
        except Exception as exc:
            self.error = exc

    def poll(self, timeout: float = 0.01) -> list[dict]:
        """Elabora callback ROS sul thread della missione e restituisce i nuovi frame."""
        if self.process is not None and not self.process.is_alive():
            raise RuntimeError(
                f"crazyflie_sim terminato con codice {self.process.exitcode}; leggere crazyswarm2.log"
            )
        self.executor.spin_once(timeout_sec=timeout)
        if self.error:
            raise self.error
        out = list(self.frames)
        self.frames.clear()
        return out

    def ready(self) -> bool:
        return all(client.service_is_ready() for client in self.clients.values()) and self.clock_changes >= 2

    def send(self, command):
        request = self.types[command.kind.value].Request()
        request.group_mask = 0
        ns = round(command.duration * 1_000_000_000)
        request.duration.sec, request.duration.nanosec = divmod(ns, 1_000_000_000)
        if command.kind.value == "go_to":
            request.goal.x, request.goal.y, request.goal.z = command.target
            request.yaw = command.yaw
            request.relative = False
        else:
            request.height = command.target[2]
        return self.clients[command.drone_id, command.kind.value].call_async(request)

    def close(self):
        errors = []
        actions = [lambda: stop_process(self.process, self.simulator_stop)]
        if self.executor:
            actions.append(lambda: self.executor.shutdown(timeout_sec=2))
        if self.node:
            actions.append(self.node.destroy_node)
        if self.context is not None:
            actions.append(self.context.try_shutdown)
        for action in actions:
            try:
                action()
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("; ".join(errors))
