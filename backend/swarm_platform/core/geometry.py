"""Verifica segmento-box sul percorso programmato, con l'ingombro del drone.

Il controllo riguarda la polilinea dei waypoint, non la traiettoria simulata."""
from .model import ExperimentSpec
from .planning import compile_plan


def segment_hits_box(start, end, radius, center, size) -> bool:
    """Distanza minima segmento-box: contatto compreso, senza campionamento.

    Tra due attraversamenti delle facce del box la distanza al quadrato è una
    funzione quadratica del parametro t del segmento. Ne controlliamo il minimo
    in ogni intervallo: così non saltiamo ostacoli sottili o contatti tangenti.
    """
    lower = [c - s / 2 for c, s in zip(center, size)]
    upper = [c + s / 2 for c, s in zip(center, size)]
    delta = [b - a for a, b in zip(start, end)]
    cuts = {0.0, 1.0}
    for p, d, lo, hi in zip(start, delta, lower, upper):
        if d != 0:
            for face in (lo, hi):
                t = (face - p) / d
                if 0 < t < 1:
                    cuts.add(t)
    cuts = sorted(cuts)
    # Gli arrotondamenti sui decimali non devono escludere un contatto tangente.
    threshold = (radius + 1e-9) ** 2

    def squared_distance(t):
        return sum(max(lo - (p + t * d), 0.0, p + t * d - hi) ** 2
                   for p, d, lo, hi in zip(start, delta, lower, upper))

    for left, right in zip(cuts, cuts[1:]):
        if squared_distance(left) <= threshold or squared_distance(right) <= threshold:
            return True
        mid = (left + right) / 2
        quadratic = linear = 0.0
        for p, d, lo, hi in zip(start, delta, lower, upper):
            value = p + mid * d
            if lo <= value <= hi:
                continue
            bound = lo if value < lo else hi
            quadratic += d * d
            linear += d * (p - bound)
        if quadratic:
            minimum = max(left, min(right, -linear / quadratic))
            if squared_distance(minimum) <= threshold:
                return True
    return False


def verify_obstacles(experiment: ExperimentSpec) -> dict:
    """Restituisce il primo errore geometrico, senza creare o modificare run."""
    drones = {d.id: d for d in experiment.active_drones}
    positions = {d.id: d.initial_position.as_list() for d in drones.values()}
    checked = 0
    for command in compile_plan(experiment).commands:
        drone = drones[command.drone_id]
        start, end = positions[drone.id], command.target
        checked += 1
        for box in experiment.scenario.obstacles:
            if segment_hits_box(start, end, drone.radius, box.center.as_list(), box.size.as_list()):
                movement = {"takeoff": "decollo", "go_to": "waypoint", "land": "atterraggio"}[command.kind.value]
                return {
                    "passed": False,
                    "error": (f"{drone.id}: tratto {command.index + 1} ({movement}) in collisione "
                              f"con l'ostacolo {box.id}, considerando il raggio del drone."),
                    "collision": {"drone": drone.id, "obstacle": box.id,
                                  "command_index": command.index, "command": command.kind.value,
                                  "start": list(start), "end": list(end)},
                }
        positions[drone.id] = end
    return {"passed": True, "checked_segments": checked,
            "obstacle_count": len(experiment.scenario.obstacles)}
