extends Control

# Modalità interne della UI, distinte dagli stati JSON del backend.
enum Mode { EDITOR, VERIFYING, LAUNCHING, LIVE, RESULT, REPLAY }


@onready var bridge: BackendBridge = %Bridge
@onready var scene_view: ExperimentSceneView = %SceneView
@onready var editor: ExperimentEditor = %Editor
@onready var host_field: LineEdit = %HostField
@onready var port_field: SpinBox = %PortField
@onready var status_label: Label = %StatusLabel
@onready var messages: RichTextLabel = %Messages
@onready var runs_list: ItemList = %RunsList
@onready var open_dialog: FileDialog = %OpenDialog
@onready var save_dialog: FileDialog = %SaveDialog
@onready var replay_slider: HSlider = %ReplaySlider
@onready var replay_time: Label = %ReplayTime
@onready var play_button: Button = %PlayButton
@onready var run_button: Button = %RunButton
@onready var verify_button: Button = %VerifyButton
@onready var geometry_status: Label = %GeometryStatus
@onready var stop_button: Button = %StopButton
@onready var edit_buttons: Array[Button] = [%NewButton, %OpenButton, %SaveButton]
var run_entries: Array = []
var connected: bool = false
var mode: Mode = Mode.EDITOR
var tracked_run: String = ""
var last_finished: String = ""
var view_document: Dictionary = {}
var replay_frames: Array = []
var playing: bool = false
var replay_loading: bool = false
var latest_state: Dictionary = {}
var loading_live: bool = false
var connecting_backend: bool = false

func _ready() -> void:
	# Layout e bridge sono già istanziati da main.tscn.
	bridge.state_received.connect(_state_received)
	bridge.disconnected.connect(_disconnected)
	var root_path: String = ProjectSettings.globalize_path("res://").trim_suffix("/").get_base_dir()
	var example_path: String = root_path.path_join("examples/three_drones.json")
	if FileAccess.file_exists(example_path): _open_file(example_path)
	else: _new_document()
	_set_mode(Mode.EDITOR)
	_message("Verifica ostacoli controlla il percorso programmato. Esegui simulazione avvia la prova dinamica separatamente.")

func _open_dialog() -> void:
	open_dialog.popup_centered_ratio(0.75)

func _save_dialog() -> void:
	save_dialog.current_file = "experiment.json"
	save_dialog.popup_centered_ratio(0.75)

func _focus_drone() -> void:
	scene_view.focus_drone(editor.selected_id)

func _toggle_envelopes(value: bool) -> void:
	scene_view.set_envelopes_visible(value)

func _message(value: String) -> void:
	messages.append_text(value + "\n")

func _new_document() -> void:
	if mode in [Mode.LAUNCHING, Mode.LIVE, Mode.VERIFYING]: return
	var data := {"name": "nuovo_esperimento", "scenario": {
		"bounds": {"min": [-2, -2, 0], "max": [2, 2, 2]}, "obstacles": []},
		"drones": [], "missions": {}, "metadata": {},
		"settings": {"target_tolerance": 0.10, "yaw_tolerance_degrees": 5.0, "min_separation": 0.25, "max_sample_gap": 0.25}}
	var reason: String = editor.set_document(data)
	if not reason.is_empty(): _message(reason)
	else:
		_set_mode(Mode.EDITOR)
		_document_changed(editor.document)

func _open_file(path: String) -> void:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		_message("Impossibile aprire " + path)
		return
	var parser := JSON.new()
	if parser.parse(file.get_as_text()) != OK or typeof(parser.data) != TYPE_DICTIONARY:
		_message("File JSON non valido: " + parser.get_error_message())
		return
	var reason: String = editor.set_document(parser.data)
	if not reason.is_empty():
		_message(reason)
		return
	_set_mode(Mode.EDITOR)
	_document_changed(editor.document)
	_message("Documento aperto: " + path)

func _save_file(path: String) -> void:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_message("Impossibile salvare " + path)
		return
	file.store_string(JSON.stringify(editor.document, "\t") + "\n")
	_message("Salvato: " + path + ". Il file contiene il documento attualmente applicato.")

func _document_changed(data: Dictionary) -> void:
	if mode != Mode.EDITOR: return
	geometry_status.text = "Verifica ostacoli: non eseguita sul documento corrente."
	view_document = data.duplicate(true)
	scene_view.display_document(view_document)

func _selected(kind: String, did: String, index: int) -> void:
	if mode == Mode.EDITOR: editor.select_item(kind, did, index)

func _moved(kind: String, did: String, index: int, p: Vector3) -> void:
	if mode == Mode.EDITOR: editor.move_item(kind, did, index, p)

func _set_mode(value: Mode) -> void:
	mode = value
	editor.set_locked(value != Mode.EDITOR)
	scene_view.editable = value == Mode.EDITOR
	run_button.disabled = not connected or value != Mode.EDITOR
	verify_button.disabled = not connected or value != Mode.EDITOR
	stop_button.disabled = value != Mode.LIVE
	for b in edit_buttons: b.disabled = value in [Mode.LAUNCHING, Mode.LIVE, Mode.VERIFYING]
	play_button.disabled = value != Mode.REPLAY
	replay_slider.editable = value == Mode.REPLAY

func _connect_backend() -> void:
	if connecting_backend: return
	connecting_backend = true
	latest_state = {}
	var response: Dictionary = await bridge.connect_backend(host_field.text.strip_edges(), int(port_field.value))
	connecting_backend = false
	connected = bool(response.get("ok", false))
	_set_mode(mode)
	if not _ok(response): return
	_message("Connesso via HTTP a " + str(response.data.version) + ". Archivio: " + str(response.data.data_directory))
	await _refresh_runs()
	# Alla riconnessione non si ripete Run: si recupera lo stato della prova attiva.
	if latest_state.is_empty():
		_state_received(response.data.get("state", {}))
	else:
		_state_received(latest_state)

func _disconnected(reason: String) -> void:
	connected = false
	latest_state = {}
	# La scena viene svuotata: alla riconnessione ricaricare anche lo snapshot.
	tracked_run = ""
	_set_mode(Mode.EDITOR)
	_document_changed(editor.document)
	status_label.text = reason
	_message(reason + ". Riconnetti prima di avviare un altro esperimento.")


func _ok(response: Dictionary) -> bool:
	if not bool(response.get("ok", false)):
		_message(str(response.get("error", "Errore sconosciuto")))
		return false
	return true


func _verify_geometry() -> void:
	if not connected or mode != Mode.EDITOR or replay_loading: return
	_set_mode(Mode.VERIFYING)
	geometry_status.text = "Verifica del percorso programmato in corso..."
	var response: Dictionary = await bridge.verify_geometry(editor.document.duplicate(true))
	if not connected: return
	_set_mode(Mode.EDITOR)
	if not _ok(response):
		geometry_status.text = "Verifica non eseguita: " + str(response.get("error", "Errore backend"))
	elif bool(response.data.get("passed", false)):
		geometry_status.text = "Verifica ostacoli superata: %d tratti controllati. Esito relativo al percorso programmato." % int(response.data.checked_segments)
		_message(geometry_status.text)
	else:
		geometry_status.text = "ERRORE GEOMETRICO: " + str(response.data.get("error", "Percorso in collisione"))
		_message(geometry_status.text)
	# Eventuali notifiche live arrivate durante la verifica restano recuperabili.
	_state_received(latest_state)

func _run() -> void:
	if not connected or mode != Mode.EDITOR or replay_loading: return
	view_document = editor.document.duplicate(true)
	scene_view.display_document(view_document)
	tracked_run = ""
	_set_mode(Mode.LAUNCHING)
	status_label.text = "Verifica dei dati e preparazione automatica dell'esecuzione..."
	var r: Dictionary = await bridge.run_experiment(view_document)
	if not _ok(r):
		_set_mode(Mode.EDITOR)
		status_label.text = "Avvio non riuscito. Correggi il problema indicato nel registro."
		return
	_set_mode(Mode.LIVE)
	tracked_run = r.data.run_id
	last_finished = ""
	if str(latest_state.get("run_id", "")) == tracked_run: _state_received(latest_state)
	_message("Avvio Crazyswarm2 per " + tracked_run + ". Il backend verifica clock, servizi e pose iniziali.")

func _stop() -> void:
	var r: Dictionary = await bridge.stop_run()
	if _ok(r): _message("Richiesto STOP della simulazione. I dati parziali verranno conservati.")

func _state_received(state: Dictionary) -> void:
	latest_state = state
	if not connected or mode in [Mode.REPLAY, Mode.LAUNCHING, Mode.VERIFYING] or replay_loading: return
	var state_name: String = str(state.get("status", "idle"))
	var rid: String = str(state.get("run_id", ""))
	if state_name in ["starting", "running"]:
		if rid != tracked_run:
			if loading_live: return
			loading_live = true
			var details: Dictionary = await bridge.open_run(rid)
			loading_live = false
			if not _ok(details): return
			# La richiesta dello snapshot può terminare dopo la notifica finale.
			# Non sostituire in quel caso il documento editoriale con uno snapshot.
			if not connected or mode == Mode.REPLAY: return
			if latest_state.get("status") not in ["starting", "running"] or str(latest_state.get("run_id", "")) != rid:
				_state_received(latest_state)
				if mode == Mode.EDITOR: _document_changed(editor.document)
				return
			view_document = details.data.experiment
			scene_view.display_document(view_document)
			tracked_run = rid
			state = latest_state
		_set_mode(Mode.LIVE)
		scene_view.update_live_poses(state.get("poses", {}), float(state.get("time", 0)))
		status_label.text = "%s | %.2f s simulati | %d campioni | %d violazioni" % [str(state.get("status")), float(state.get("time", 0)), int(state.get("frames", 0)), int(state.get("violations", 0))]
	elif state_name in ["completed", "error", "cancelled", "interrupted"]:
		if rid != last_finished:
			last_finished = rid
			var result: Dictionary = state.get("result", {})
			var outcome: String = "Successo" if bool(result.get("passed", false)) else "Fallimento dei criteri"
			if state_name == "cancelled": outcome = "Arresto volontario"
			elif state_name == "error": outcome = "Errore di esecuzione"
			elif state_name == "interrupted": outcome = "Esecuzione interrotta"
			elif result.get("metrics", {}).get("evaluation") == "inconclusive": outcome = "Non valutabile"
			status_label.text = "%s | %s | %s" % [state_name, outcome, rid]
			_message("Risultato: " + JSON.stringify(result, "  "))
			if mode == Mode.LIVE:
				scene_view.update_live_poses(state.get("poses", {}), float(state.get("time", 0)))
				# Conserva pose e tracce per il confronto finale. Il pulsante già
				# presente ripristina l'editor e cancella la traccia del run concluso.
				_set_mode(Mode.RESULT)
				_message("Percorso eseguito conservato nella vista. Torna all'editor per modificare o avviare una nuova prova.")
			await _refresh_runs()

func _refresh_runs() -> void:
	if not connected: return
	var r: Dictionary = await bridge.list_runs()
	if not _ok(r): return
	run_entries = r.data.runs
	runs_list.clear()
	for entry in run_entries:
		runs_list.add_item("%s · %s · %s" % [entry.run_id, entry.status, entry.name])
	if not run_entries.is_empty(): runs_list.select(0)

func _selected_run() -> String:
	var indices: PackedInt32Array = runs_list.get_selected_items()
	if indices.is_empty(): return ""
	return str(run_entries[indices[0]].run_id)

func _show_logs() -> void:
	var rid: String = _selected_run()
	if rid.is_empty(): return
	var r: Dictionary = await bridge.get_logs(rid)
	if _ok(r):
		for name in r.data: _message("\n" + str(name) + "\n" + str(r.data[name]))

func _load_replay() -> void:
	if mode in [Mode.LAUNCHING, Mode.LIVE, Mode.VERIFYING] or replay_loading:
		_message("Attendi la conclusione o interrompi il run prima di aprire un replay.")
		return
	var rid: String = _selected_run()
	if rid.is_empty(): return
	replay_loading = true
	var details: Dictionary = await bridge.open_run(rid)
	if not _ok(details):
		replay_loading = false
		return
	var frames: Array = []
	var offset: int = 0
	while true:
		var page: Dictionary = await bridge.get_replay(rid, offset)
		if not _ok(page):
			replay_loading = false
			return
		frames.append_array(page.data.frames)
		if page.data.next_offset == null: break
		offset = int(page.data.next_offset)
	replay_loading = false
	if frames.is_empty():
		_message("Il run non contiene pose: prepared o errore precedente all'acquisizione. Usa Mostra log.")
		return
	playing = false
	replay_frames = frames
	view_document = details.data.experiment
	scene_view.display_document(view_document)
	scene_view.prepare_replay_trails(replay_frames)
	_set_mode(Mode.REPLAY)
	replay_slider.max_value = float(frames[-1].time)
	replay_slider.value = 0.0
	_seek(0.0)
	status_label.text = "Replay " + rid + " | registrazione originale, nessuna riesecuzione ROS"
	_message("Replay caricato: %d campioni. Risultato: %s" % [frames.size(), JSON.stringify(details.data.result)])

func _play_pause() -> void:
	if mode != Mode.REPLAY: return
	if replay_slider.value >= replay_slider.max_value: replay_slider.value = 0.0
	playing = not playing

func _process(delta: float) -> void:
	if playing and mode == Mode.REPLAY:
		replay_slider.value = minf(replay_slider.value + delta, replay_slider.max_value)
		if replay_slider.value >= replay_slider.max_value: playing = false

func _seek(t: float) -> void:
	if mode != Mode.REPLAY or replay_frames.is_empty(): return
	var lo: int = 0
	var hi: int = replay_frames.size() - 1
	while lo < hi:
		var mid: int = int((lo + hi + 1) / 2)
		if float(replay_frames[mid].time) <= t: lo = mid
		else: hi = mid - 1
	var a: Dictionary = replay_frames[lo]
	var b: Dictionary = replay_frames[mini(lo + 1, replay_frames.size() - 1)]
	var dt: float = float(b.time) - float(a.time)
	var weight: float = clampf((t - float(a.time)) / dt, 0.0, 1.0) if dt > 0 else 0.0
	var poses: Dictionary = {}
	for did in a.poses:
		var p: Vector3 = RosCoordinates.vec(a.poses[did].position).lerp(RosCoordinates.vec(b.poses[did].position), weight)
		var av: Array = a.poses[did].orientation
		var bv: Array = b.poses[did].orientation
		var q: Quaternion = Quaternion(av[0], av[1], av[2], av[3]).slerp(Quaternion(bv[0], bv[1], bv[2], bv[3]), weight)
		poses[did] = {"position": [p.x, p.y, p.z], "orientation": [q.x, q.y, q.z, q.w]}
	scene_view.update_replay_poses(poses, t)
	replay_time.text = "%.2f / %.2f s" % [t, replay_slider.max_value]

func _return_editor() -> void:
	if mode in [Mode.LAUNCHING, Mode.LIVE, Mode.VERIFYING]:
		_message("Prima interrompi o termina la simulazione.")
		return
	playing = false
	_set_mode(Mode.EDITOR)
	_document_changed(editor.document)
	status_label.text = "Editor: documento originale ripristinato, indipendente dal replay."

func _open_guide() -> void:
	var root_path: String = ProjectSettings.globalize_path("res://").trim_suffix("/").get_base_dir()
	OS.shell_open(root_path.path_join("docs/GUIDA_USO.pdf"))
