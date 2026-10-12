"""Assemblaggio dei TF con lo stesso timestamp in un frame completo."""
from __future__ import annotations
import math
from ..core.model import WORLD_FRAME


class FrameAssembler:
    def __init__(self, ids):
        self.ids = set(ids)
        self.pending: dict[int, dict] = {}
        self.last_ns = -1
        self.discarded = 0

    def add(self, stamp_ns: int, child: str, parent: str, position, orientation) -> dict | None:
        """Accetta una trasformazione e restituisce un frame solo se tutti i droni sono presenti."""
        if child not in self.ids:
            return None
        if parent.lstrip("/") != WORLD_FRAME:
            raise ValueError(f"Frame inatteso per {child}: {parent!r}, richiesto {WORLD_FRAME!r}")
        if len(position) != 3 or len(orientation) != 4 or not all(math.isfinite(v) for v in [*position, *orientation]):
            raise ValueError(f"Posa non finita o malformata di {child}")
        norm = math.hypot(*orientation)
        if norm == 0:
            raise ValueError(f"Quaternione nullo per {child}")
        if not math.isfinite(norm):
            raise ValueError(f"Quaternione non normalizzabile per {child}")
        if stamp_ns <= self.last_ns:
            return None
        p = self.pending.setdefault(stamp_ns, {})
        if child in p:
            if p[child]["position"] != list(position):
                raise ValueError(f"Due pose diverse per {child} allo stesso timestamp")
            return None
        p[child] = {"position": list(position), "orientation": [v / norm for v in orientation]}
        if set(p) == self.ids:
            out = {"sim_time": stamp_ns / 1e9, "poses": p}
            self.discarded += sum(1 for t in self.pending if t < stamp_ns)
            self.pending = {t: v for t, v in self.pending.items() if t > stamp_ns}
            self.last_ns = stamp_ns
            return out
        if len(self.pending) > 100:
            del self.pending[min(self.pending)]
            self.discarded += 1
        return None
