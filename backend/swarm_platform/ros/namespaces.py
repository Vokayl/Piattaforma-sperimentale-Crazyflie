"""Nomi delle interfacce ROS: prefisso per run e identificativo del drone."""
import re


def run_namespace(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", run_id):
        raise ValueError("run_id non valido")
    return "/cfp_" + run_id


def drone_service(drone_id: str, operation: str, root: str) -> str:
    return f"{root.rstrip('/')}/{drone_id}/{operation}"
