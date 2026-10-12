"""API HTTP/JSON per comandi, stato e archivio, con un thread per richiesta."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
import threading
from urllib.parse import parse_qs, urlsplit
from ..service import BusyError, PlatformService

LOG = logging.getLogger(__name__)
MAX_BODY = 1_048_576


def result_summary(result: dict) -> dict:
    """Lo stato live resta leggero; i dettagli rimangono nell'archivio."""
    summary = {k: v for k, v in result.items() if k != "metrics"}
    summary["metrics"] = {k: v for k, v in result.get("metrics", {}).items()
                          if k not in {"violations", "checkpoints"}}
    summary["metrics"]["violation_count"] = len(result.get("metrics", {}).get("violations", []))
    return summary


def live_snapshot(state: dict) -> dict:
    output = dict(state)
    if "result" in output:
        output["result"] = result_summary(output["result"])
    return output


def json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def reject_constant(value: str):
    raise ValueError("Numero JSON non valido: " + value)


class RequestError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        # Il polling a 20 Hz non deve riempire il log del backend.
        pass

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _body(self) -> dict:
        if self.headers.get("Transfer-Encoding"):
            raise RequestError(400, "Usare Content-Length, non Transfer-Encoding")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            raise RequestError(400, "Content-Length non valido")
        size = int(lengths[0])
        if size > MAX_BODY:
            raise RequestError(413, "Richiesta oltre il limite di 1 MiB")
        if self.headers.get_content_type() != "application/json":
            raise RequestError(415, "Il corpo deve essere application/json")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise RequestError(400, "Corpo della richiesta incompleto")
        body = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
        if not isinstance(body, dict):
            raise RequestError(400, "Il corpo JSON deve essere un oggetto")
        return body

    def _dispatch(self) -> dict:
        service = self.server.service
        url = urlsplit(self.path)
        path = url.path
        if self.command == "POST":
            data = self._body()
            if path == "/api/run":
                return service.start(data)
            if path == "/api/stop":
                return service.stop()
            if path == "/api/verify_geometry":
                return service.verify_geometry(data)
        else:
            if path == "/api/health":
                return {**service.health(), "state": live_snapshot(service.state())}
            if path == "/api/state":
                return live_snapshot(service.state())
            if path == "/api/runs":
                return service.list_runs()
            parts = path.strip("/").split("/")
            if len(parts) in (3, 4) and parts[:2] == ["api", "runs"]:
                rid = parts[2]
                if len(parts) == 3:
                    detail = {**service.get_run(rid), "result_summarized": False}
                    if len(json_bytes({"ok": True, "data": detail})) > MAX_BODY:
                        detail["result"] = result_summary(detail.get("result") or {})
                        detail["result_summarized"] = True
                    return detail
                if parts[3] == "logs":
                    return service.logs(rid)
                if parts[3] == "replay":
                    query = parse_qs(url.query, keep_blank_values=True, max_num_fields=2)
                    if set(query) - {"offset", "limit"} or any(len(v) != 1 for v in query.values()):
                        raise ValueError("Parametri replay non validi")
                    offset = int(query.get("offset", ["0"])[0])
                    limit = int(query.get("limit", ["200"])[0])
                    if offset < 0 or not 1 <= limit <= 200:
                        raise ValueError("offset deve essere >= 0 e limit tra 1 e 200")
                    return service.replay(rid, offset, limit)
        raise RequestError(404, "Risorsa o metodo non disponibile")

    def _handle(self):
        try:
            response = {"ok": True, "data": self._dispatch()}
            status = 200
            body = json_bytes(response)
            if len(body) > MAX_BODY:
                raise RequestError(413, "Risposta troppo grande: usare le pagine del replay")
        except (ValueError, FileNotFoundError, BusyError, TimeoutError) as exc:
            status = (exc.status if isinstance(exc, RequestError) else
                      409 if isinstance(exc, BusyError) else
                      404 if isinstance(exc, FileNotFoundError) else
                      408 if isinstance(exc, TimeoutError) else 400)
            body = json_bytes({"ok": False, "error": str(exc)})
        except Exception:
            LOG.exception("Errore nella richiesta HTTP")
            status, body = 500, json_bytes({"ok": False, "error": "Errore interno del backend"})
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            # Una risposta persa non annulla né ripete l'operazione eseguita.
            pass
        self.close_connection = True


class BridgeServer(ThreadingHTTPServer):
    def __init__(self, service: PlatformService, host="127.0.0.1", port=8870):
        address = ipaddress.IPv4Address(host)
        if address.is_multicast:
            raise ValueError("L'indirizzo di ascolto non può essere multicast")
        self.service = service
        self.stopped = threading.Event()
        super().__init__((host, port), Handler)
        self.address = self.server_address
        self.timeout = .2

    def run(self):
        # Il timeout permette anche al signal handler del main di fermare il loop.
        while not self.stopped.is_set():
            self.handle_request()

    def close(self):
        self.stopped.set()
        self.server_close()
