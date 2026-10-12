class_name ExperimentEditor
extends TabContainer

signal changed(document: Dictionary)
signal error(message: String)
signal selection_changed(drone_id: String, waypoint_index: int)

# Percorsi relativi al documento o all'oggetto selezionato; i prefissi vettoriali
# (Spawn, Waypoint, BoundsMin...) collegano automaticamente i campi X, Y e Z.
const FIELD_GROUPS = {
	"document": {"ExperimentName": ["name"], "Separation": ["settings", "min_separation"],
		"Tolerance": ["settings", "target_tolerance"], "YawTolerance": ["settings", "yaw_tolerance_degrees"],
		"MaxGap": ["settings", "max_sample_gap"]},
	"drone": {"Spawn": ["initial_position"], "Radius": ["radius"], "Uri": ["uri"]},
	"mission": {"TakeoffHeight": ["takeoff", "height"], "TakeoffDuration": ["takeoff", "duration"],
		"LandHeight": ["land", "height"], "LandDuration": ["land", "duration"]},
	"waypoint": {"Waypoint": ["position"], "WaypointYaw": ["yaw"],
		"WaypointDuration": ["duration"], "WaypointHold": ["hold"]},
	"bounds": {"BoundsMin": ["min"], "BoundsMax": ["max"]},
	"obstacle": {"ObstacleId": ["id"], "ObstacleCenter": ["center"], "ObstacleSize": ["size"]}
}

var document: Dictionary = {}
var selected_id: String = ""
var selected_waypoint: int = -1
var selected_obstacle: int = -1
var _updating: bool = false
var _field_paths: Dictionary = {}
var _fields: Dictionary = {}
var _controls: Array[Control] = []
var locked: bool = false

func _number_value(value: Variant) -> bool:
	return (typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT) and is_finite(float(value))

func _v3(value: Variant) -> bool:
	return typeof(value) == TYPE_ARRAY and value.size() == 3 and _number_value(value[0]) and _number_value(value[1]) and _number_value(value[2])

func _has_fields(value: Variant, strings: Array = [], numbers: Array = [], vectors: Array = []) -> bool:
	if typeof(value) != TYPE_DICTIONARY: return false
	for key in strings:
		if typeof(value.get(key)) != TYPE_STRING: return false
	for key in numbers:
		if not _number_value(value.get(key)): return false
	for key in vectors:
		if not _v3(value.get(key)): return false
	return true

# Il frontend controlla la struttura; la validazione completa spetta al backend.
func set_document(value: Dictionary) -> String:
	var data: Dictionary = value.duplicate(true)
	if not _has_fields(data, ["name"]):
		return "Richiesto name (testo)"
	if typeof(data.get("drones")) != TYPE_ARRAY or typeof(data.get("missions")) != TYPE_DICTIONARY:
		return "Richiesti drones (lista) e missions (oggetto)"
	var ids: Array[String] = []
	for d: Variant in data.drones:
		if not _has_fields(d, ["id"], [], ["initial_position"]):
			return "Drone malformato: richiesti id e initial_position [x,y,z]"
		if d.id in ids: return "ID drone duplicato: " + d.id
		ids.append(d.id)
		d.get_or_add("uri", "radio://0/80/2M/E7E7E7E701")
		d.get_or_add("enabled", true)
		d.get_or_add("radius", 0.08)
		if not _has_fields(d, ["uri"], ["radius"]): return "URI o raggio drone malformati"
		if typeof(d.enabled) != TYPE_BOOL: return "enabled deve essere booleano"
		if not data.missions.has(d.id): return "Manca la missione per " + d.id
		var m: Variant = data.missions[d.id]
		if typeof(m) != TYPE_DICTIONARY or typeof(m.get("takeoff")) != TYPE_DICTIONARY:
			return "Missione malformata per " + d.id
		m.get_or_add("land", {"height": 0.04, "duration": 2.0})
		m.get_or_add("waypoints", [])
		if typeof(m.land) != TYPE_DICTIONARY or typeof(m.waypoints) != TYPE_ARRAY: return "land o waypoints non validi"
		for movement in [m.takeoff, m.land]:
			if not _has_fields(movement, [], ["height", "duration"]):
				return "takeoff/land richiedono height e duration numerici"
		for w in m.waypoints:
			if not _has_fields(w, [], ["duration"], ["position"]):
				return "Waypoint malformato"
			w.get_or_add("yaw", 0.0)
			w.get_or_add("hold", 0.0)
			if not _has_fields(w, [], ["yaw", "hold"]): return "yaw/hold devono essere numerici"
	data.get_or_add("scenario", {"obstacles": []})
	if typeof(data.scenario) != TYPE_DICTIONARY: return "scenario non valido"
	data.scenario.get_or_add("obstacles", [])
	if typeof(data.scenario.obstacles) != TYPE_ARRAY: return "obstacles non valido"
	if data.scenario.get("bounds") != null:
		if not _has_fields(data.scenario.bounds, [], [], ["min", "max"]):
			return "bounds richiede min/max tridimensionali"
	for box in data.scenario.obstacles:
		if not _has_fields(box, ["id"], [], ["center", "size"]):
			return "Ostacolo malformato"
	data.get_or_add("settings", {})
	if typeof(data.settings) != TYPE_DICTIONARY: return "settings deve essere un oggetto"
	data.get_or_add("metadata", {})
	if typeof(data.metadata) != TYPE_DICTIONARY: return "metadata deve essere un oggetto"
	data.settings.get_or_add("min_separation", 0.25)
	data.settings.get_or_add("max_sample_gap", 0.25)
	if not _has_fields(data.settings, [], ["target_tolerance", "yaw_tolerance_degrees", "min_separation", "max_sample_gap"]):
		return "settings richiede soglie numeriche"
	document = data
	if not selected_id in ids:
		selected_id = ids[0] if not ids.is_empty() else ""
	selected_waypoint = -1
	selected_obstacle = -1
	_refresh_fields()
	return ""

func _ready() -> void:
	for node in find_children("*", "Control", true, false):
		# L'input interno di uno SpinBox è già gestito dal controllo numerico.
		if node is LineEdit and node.get_parent() is SpinBox: continue
		if node is BaseButton or node is SpinBox or node is LineEdit:
			_controls.append(node)
		if node is LineEdit:
			_fields[str(node.name)] = node
			node.text_submitted.connect(_text_changed.bind(node))
			node.focus_exited.connect(_commit_text.bind(node))
		elif node is SpinBox:
			_fields[str(node.name)] = node
			# Mantiene visibili anche valori importati che il backend dovrà rifiutare.
			node.allow_lesser = true
			node.allow_greater = true
			node.value_changed.connect(_number_changed.bind(node))
	_refresh_fields()
	set_locked(locked)

func _get_path(path: Array) -> Variant:
	var value: Variant = document
	for key in path: value = value[key]
	return value

func _put(value: Variant, path: Array) -> void:
	var target: Variant = document
	for i in range(path.size() - 1): target = target[path[i]]
	target[path[-1]] = value
	_changed()

func _text_changed(value: String, field: LineEdit) -> void:
	if _updating or locked: return
	if field.name == "DroneId":
		if _drone_index(selected_id) >= 0: _rename_drone(value.strip_edges())
	elif _field_paths.has(str(field.name)):
		var path: Array = _field_paths[str(field.name)]
		if str(_get_path(path)) != value: _put(value, path)

func _commit_text(field: LineEdit) -> void:
	_text_changed(field.text, field)

func _number_changed(value: float, field: SpinBox) -> void:
	if _updating or locked or not _field_paths.has(str(field.name)): return
	_put(value, _field_paths[str(field.name)])

func _enabled_changed(value: bool) -> void:
	var i: int = _drone_index(selected_id)
	if not _updating and not locked and i >= 0:
		_put(value, ["drones", i, "enabled"])

func _bind_fields(group: String, base: Array = []) -> void:
	for node_name in FIELD_GROUPS[group]:
		var path: Array = base + FIELD_GROUPS[group][node_name]
		if _fields.has(node_name): _field_paths[node_name] = path
		else:
			for i in range(3): _field_paths[node_name + ["X", "Y", "Z"][i]] = path + [i]

func _changed(refresh_fields: bool = false) -> void:
	if refresh_fields: _refresh_fields()
	else: _refresh_lists()
	changed.emit(document)

func _refresh_lists() -> void:
	_fill_list(%DroneList, document.drones.map(func(d): return str(d.id) + ("" if d.enabled else " (disabilitato)")), _drone_index(selected_id))
	var points: Array = document.missions.get(selected_id, {}).get("waypoints", [])
	var labels: Array = []
	for i in range(points.size()): labels.append("Waypoint %d  %s" % [i + 1, str(points[i].position)])
	_fill_list(%WaypointList, labels, selected_waypoint)
	_fill_list(%ObstacleList, document.scenario.obstacles.map(func(box): return str(box.id)), selected_obstacle)

func _fill_list(list: ItemList, labels: Array, selected: int) -> void:
	list.clear()
	for label in labels: list.add_item(label)
	if selected >= 0 and selected < labels.size(): list.select(selected)

func _refresh_fields() -> void:
	if not is_node_ready() or document.is_empty(): return
	_updating = true
	_field_paths.clear()
	_bind_fields("document")
	var didx: int = _drone_index(selected_id)
	%DroneProperties.visible = didx >= 0
	%EmptyDrones.visible = didx < 0
	%MissionProperties.visible = didx >= 0
	%MissionTitle.text = "Drone selezionato: " + selected_id if didx >= 0 else "Aggiungi un drone dalla prima scheda."
	%WaypointProperties.visible = false
	if didx >= 0:
		%DroneId.text = selected_id
		%DroneEnabled.set_pressed_no_signal(document.drones[didx].enabled)
		_bind_fields("drone", ["drones", didx])
		var base: Array = ["missions", selected_id]
		_bind_fields("mission", base)
		var waypoints: Array = document.missions[selected_id].waypoints
		if selected_waypoint >= 0 and selected_waypoint < waypoints.size():
			%WaypointProperties.visible = true
			_bind_fields("waypoint", base + ["waypoints", selected_waypoint])
	var has_bounds: bool = document.scenario.get("bounds") != null
	%BoundsProperties.visible = has_bounds
	%AddBounds.visible = not has_bounds
	if has_bounds:
		_bind_fields("bounds", ["scenario", "bounds"])
	%ObstacleProperties.visible = selected_obstacle >= 0 and selected_obstacle < document.scenario.obstacles.size()
	if %ObstacleProperties.visible:
		_bind_fields("obstacle", ["scenario", "obstacles", selected_obstacle])
	for node_name in _field_paths:
		var field: Control = _fields[node_name]
		var value: Variant = _get_path(_field_paths[node_name])
		if field is SpinBox: field.set_value_no_signal(float(value))
		elif field is LineEdit: field.text = str(value)
	_refresh_lists()
	_updating = false

func _drone_index(did: String) -> int:
	for i in range(document.drones.size()):
		if document.drones[i].id == did: return i
	return -1

func _select_drone(index: int) -> void:
	select_item("drone", document.drones[index].id, -1)
	selection_changed.emit(selected_id, -1)

func _select_waypoint(index: int) -> void:
	select_item("waypoint", selected_id, index)
	selection_changed.emit(selected_id, index)

func select_item(kind: String, did: String, index: int) -> void:
	if kind == "obstacle":
		selected_obstacle = index
		_refresh_fields()
		current_tab = 2
		return
	selected_id = did
	selected_waypoint = index if kind == "waypoint" else -1
	_refresh_fields()
	current_tab = 1 if kind == "waypoint" else 0

func move_item(kind: String, did: String, index: int, p: Vector3) -> void:
	if locked: return
	if kind == "obstacle": document.scenario.obstacles[index].center = [p.x, p.y, p.z]
	elif kind == "waypoint": document.missions[did].waypoints[index].position = [p.x, p.y, p.z]
	else: document.drones[_drone_index(did)].initial_position = [p.x, p.y, p.z]
	_changed(true)

func _rename_drone(value: String) -> void:
	if value.is_empty() or (value != selected_id and _drone_index(value) >= 0):
		error.emit("Identificativo vuoto o già usato")
		return
	if value == selected_id: return
	var m: Dictionary = document.missions[selected_id]
	document.missions.erase(selected_id)
	document.missions[value] = m
	document.drones[_drone_index(selected_id)].id = value
	selected_id = value
	_changed(true)

func _add_drone() -> void:
	var i: int = 1
	while _drone_index("cf%d" % i) >= 0: i += 1
	selected_id = "cf%d" % i
	var x: float = -0.8 + document.drones.size() * 0.4
	document.drones.append({"id": selected_id, "uri": "radio://0/80/2M/E7E7E7%04X" % i,
		"initial_position": [x, -0.8, 0.0], "enabled": true, "radius": 0.08})
	document.missions[selected_id] = {"takeoff": {"height": 1.0, "duration": 2.0},
		"waypoints": [{"position": [x, 0.8, 1.0], "yaw": 0.0, "duration": 3.0, "hold": 0.5}],
		"land": {"height": 0.04, "duration": 2.0}}
	selected_waypoint = -1
	_changed(true)

func _remove_drone() -> void:
	var i: int = _drone_index(selected_id)
	if i < 0: return
	document.drones.remove_at(i)
	document.missions.erase(selected_id)
	selected_id = document.drones[0].id if not document.drones.is_empty() else ""
	selected_waypoint = -1
	_changed(true)

func _add_waypoint() -> void:
	if not document.missions.has(selected_id): return
	var points: Array = document.missions[selected_id].waypoints
	var pos: Array = document.drones[_drone_index(selected_id)].initial_position.duplicate()
	if not points.is_empty(): pos = points[-1].position.duplicate()
	pos[2] = float(document.missions[selected_id].takeoff.height)
	points.append({"position": pos, "yaw": 0.0, "duration": 2.0, "hold": 0.5})
	selected_waypoint = points.size() - 1
	_changed(true)

func _remove_waypoint() -> void:
	if selected_waypoint < 0: return
	document.missions[selected_id].waypoints.remove_at(selected_waypoint)
	selected_waypoint = -1
	_changed(true)

func _move_waypoint(direction: int) -> void:
	if selected_waypoint < 0: return
	var points: Array = document.missions[selected_id].waypoints
	var target: int = selected_waypoint + direction
	if target < 0 or target >= points.size(): return
	var value: Variant = points[selected_waypoint]
	points.remove_at(selected_waypoint)
	points.insert(target, value)
	selected_waypoint = target
	_changed(true)

func _select_obstacle(index: int) -> void:
	select_item("obstacle", "", index)

func _add_bounds() -> void:
	document.scenario.bounds = {"min": [-2, -2, 0], "max": [2, 2, 2]}
	_changed(true)

func _add_obstacle() -> void:
	var index: int = 1
	var used: Array = []
	for box in document.scenario.obstacles: used.append(str(box.id))
	while "box_%d" % index in used: index += 1
	document.scenario.obstacles.append({"id": "box_%d" % index, "center": [0, 0, 0.5], "size": [0.4, 0.4, 1.0]})
	selected_obstacle = document.scenario.obstacles.size() - 1
	_changed(true)

func _remove_obstacle() -> void:
	if selected_obstacle < 0: return
	document.scenario.obstacles.remove_at(selected_obstacle)
	selected_obstacle = -1
	_changed(true)

func _waypoint_up() -> void:
	_move_waypoint(-1)

func _waypoint_down() -> void:
	_move_waypoint(1)

func set_locked(value: bool) -> void:
	locked = value
	for control in _controls:
		if control is BaseButton: control.disabled = value
		else: control.editable = not value
