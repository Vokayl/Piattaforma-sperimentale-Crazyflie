"""Avvio del backend HTTP e gestione dei segnali di arresto."""
from __future__ import annotations
import os
import signal
from pathlib import Path
from .service import PlatformService, DEFAULT_DATA
from .transport.bridge import BridgeServer


def main() -> int:
    host = os.getenv("CFP_HOST", "127.0.0.1")
    port = int(os.getenv("CFP_PORT", "8870"))
    live_hz = float(os.getenv("CFP_LIVE_HZ", "20"))
    data = Path(os.getenv("CFP_DATA_DIR", str(DEFAULT_DATA)))

    service = PlatformService(data, live_hz=live_hz)
    bridge = BridgeServer(service, host, port)
    previous = {}

    def stop(*_):
        service.stop()
        bridge.stopped.set()

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, stop)
        print(
            f"Crazyflie Platform HTTP http://{bridge.address[0]}:{bridge.address[1]} | archivio {service.runs}",
            flush=True,
        )
        bridge.run()
        return 0
    finally:
        bridge.close()
        service.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
