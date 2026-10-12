class_name BackendBridge
extends Node
## Comandi HTTP e polling dello stato del backend.

signal state_received(state: Dictionary)
signal disconnected(reason: String)

const POLL_INTERVAL: float = 0.05
const MAX_BODY: int = 1048576

var is_ready: bool = false
var _base_url: String = ""
var _elapsed: float = 0.0
var _polling: bool = false
var _generation: int = 0

func connect_backend(host: String, port: int) -> Dictionary:
	_disconnect("Nuova connessione", false)
	if (host != "localhost" and not host.is_valid_ip_address()) or ":" in host or port < 1 or port > 65535:
		return {"ok": false, "error": "Usare localhost o un indirizzo IPv4 e una porta valida"}
	_base_url = "http://%s:%d" % [host, port]
	var generation: int = _generation
	var reply: Dictionary = await _request("/api/health")
	if generation != _generation or not bool(reply.get("ok", false)):
		return reply
	if reply.data.get("application") != "crazyflie-platform" or reply.data.get("transport") != "http":
		return {"ok": false, "error": "Il servizio non è il backend HTTP Crazyflie Platform"}
	is_ready = true
	_elapsed = 0.0
	return reply

func run_experiment(document: Dictionary) -> Dictionary:
	return await _request("/api/run", HTTPClient.METHOD_POST, document)

func verify_geometry(document: Dictionary) -> Dictionary:
	return await _request("/api/verify_geometry", HTTPClient.METHOD_POST, document)

func stop_run() -> Dictionary:
	return await _request("/api/stop", HTTPClient.METHOD_POST)

func list_runs() -> Dictionary:
	return await _request("/api/runs")

func open_run(run_id: String) -> Dictionary:
	return await _request("/api/runs/" + run_id.uri_encode())

func get_replay(run_id: String, offset: int) -> Dictionary:
	return await _request("/api/runs/%s/replay?offset=%d&limit=200" % [run_id.uri_encode(), offset])

func get_logs(run_id: String) -> Dictionary:
	return await _request("/api/runs/%s/logs" % run_id.uri_encode())

func _request(path: String, method: HTTPClient.Method = HTTPClient.METHOD_GET, data: Dictionary = {}) -> Dictionary:
	if not is_ready and path != "/api/health":
		return {"ok": false, "error": "Backend non connesso"}
	var body: String = JSON.stringify(data) if method == HTTPClient.METHOD_POST else ""
	if body.to_utf8_buffer().size() > MAX_BODY:
		return {"ok": false, "error": "Richiesta oltre il limite di 1 MiB"}
	var generation: int = _generation
	# Richieste indipendenti: STOP non attende polling o replay.
	var http := HTTPRequest.new()
	http.timeout = 5.0
	http.body_size_limit = MAX_BODY
	add_child(http)
	var err: Error = http.request(_base_url + path, ["Content-Type: application/json"], method, body)
	if err != OK:
		http.queue_free()
		_disconnect(error_string(err))
		return {"ok": false, "error": error_string(err)}
	var completed: Array = await http.request_completed
	http.queue_free()
	# Le risposte di una connessione precedente non aggiornano la nuova sessione.
	if generation != _generation:
		return {"ok": false, "error": "Connessione cambiata; operazione non ripetuta"}
	if int(completed[0]) != HTTPRequest.RESULT_SUCCESS:
		var reason: String = "Backend non raggiungibile o risposta incompleta. Run non viene reinviato automaticamente"
		_disconnect(reason)
		return {"ok": false, "error": reason}
	var parser := JSON.new()
	var bytes: PackedByteArray = completed[3]
	if parser.parse(bytes.get_string_from_utf8()) != OK or not parser.data is Dictionary:
		_disconnect("Risposta JSON non valida")
		return {"ok": false, "error": "Risposta JSON non valida"}
	var reply: Dictionary = parser.data
	var success: bool = int(completed[1]) >= 200 and int(completed[1]) < 300
	if not reply.get("ok") is bool or bool(reply.ok) != success or (success and not reply.get("data") is Dictionary):
		_disconnect("Risposta HTTP non valida")
		return {"ok": false, "error": "Risposta HTTP non valida"}
	return reply

func _disconnect(reason: String, notify: bool = true) -> void:
	var was_ready: bool = is_ready
	is_ready = false
	_generation += 1
	_polling = false
	_elapsed = 0.0
	if notify and was_ready:
		disconnected.emit(reason)

func _process(delta: float) -> void:
	if not is_ready: return
	_elapsed += delta
	if _elapsed < POLL_INTERVAL: return
	_elapsed = fmod(_elapsed, POLL_INTERVAL)
	# Salta il tick se la lettura precedente è ancora in corso.
	if not _polling: _poll_state()

func _poll_state() -> void:
	_polling = true
	var generation: int = _generation
	var reply: Dictionary = await _request("/api/state")
	if generation != _generation: return
	_polling = false
	if bool(reply.get("ok", false)):
		state_received.emit(reply.data)
	else:
		_disconnect(str(reply.get("error", "Lettura dello stato fallita")))
