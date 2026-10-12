class_name ExperimentSceneView
extends SubViewportContainer

signal selected(kind: String, drone_id: String, index: int)
signal moved(kind: String, drone_id: String, index: int, ros_position: Vector3)

const DRONE = preload("res://scenes/objects/drone.tscn")
const WAYPOINT = preload("res://scenes/objects/waypoint.tscn")
const OBSTACLE = preload("res://scenes/objects/obstacle.tscn")
const SEGMENT = preload("res://scenes/objects/route_segment.tscn")
const BOUNDS = preload("res://scenes/objects/flight_bounds.tscn")
const TRAIL = preload("res://scenes/objects/flight_trail.tscn")

@export var palette: Array[Color] = [Color(0.2, 0.75, 1.0), Color(1.0, 0.66, 0.25), Color(0.5, 0.9, 0.55), Color(0.9, 0.45, 0.8)]
@export var orbit_target := Vector3(0.0, 0.6, 0.0)
@export var orbit_yaw: float = 0.7
@export var orbit_pitch: float = 0.55
@export var distance: float = 5.0
@onready var viewport_3d: SubViewport = $Viewport
@onready var world: Node3D = $Viewport/World
@onready var content: Node3D = $Viewport/World/ExperimentContent
@onready var camera: Camera3D = $Viewport/World/Camera
var drones: Dictionary = {}
var trails: Dictionary = {}
var picks: Array[Dictionary] = []
var editable: bool = true
var drag_item: Dictionary = {}
var rotating: bool = false
var panning: bool = false
var show_envelopes: bool = false

func _ready() -> void:
	_update_camera()

func _instance(scene: PackedScene) -> Node3D:
	var item: Node3D = scene.instantiate() as Node3D
	content.add_child(item)
	return item

func _segment(a: Vector3, b: Vector3, color: Color) -> void:
	var item := _instance(SEGMENT) as ExperimentVisualItem
	item.configure_segment(a, b, color.darkened(0.5))

func set_envelopes_visible(value: bool) -> void:
	show_envelopes = value
	for actor in drones.values(): actor.get_node("Envelope").visible = value

func display_document(doc: Dictionary, reset_camera: bool = false) -> void:
	drag_item = {}
	for child in content.get_children():
		content.remove_child(child)
		child.queue_free()
	drones.clear()
	trails.clear()
	picks.clear()
	var scenario: Dictionary = doc.get("scenario", {})
	if scenario.get("bounds") != null:
		var a: Vector3 = RosCoordinates.position_to_godot(RosCoordinates.vec(scenario.bounds.min))
		var b: Vector3 = RosCoordinates.position_to_godot(RosCoordinates.vec(scenario.bounds.max))
		var bounds: Node3D = _instance(BOUNDS)
		bounds.position = (a + b) * 0.5
		bounds.scale = (b - a).abs()
	var obstacles: Array = scenario.get("obstacles", [])
	for i in range(obstacles.size()):
		var box: Dictionary = obstacles[i]
		var item := _instance(OBSTACLE) as ExperimentVisualItem
		var dimensions: Vector3 = RosCoordinates.vec(box.size)
		item.position = RosCoordinates.position_to_godot(RosCoordinates.vec(box.center))
		item.configure_obstacle(str(box.id), Vector3(dimensions.x, dimensions.z, dimensions.y).abs())
		picks.append({"kind": "obstacle", "id": str(box.id), "index": i, "node": item})
	var color_index: int = 0
	for drone: Dictionary in doc.get("drones", []):
		var did: String = str(drone.id)
		var color: Color = palette[color_index % palette.size()] if not palette.is_empty() else Color.WHITE
		color_index += 1
		if not bool(drone.get("enabled", true)): color = Color(0.5, 0.5, 0.5)
		var actor := _instance(DRONE) as ExperimentVisualItem
		actor.position = RosCoordinates.position_to_godot(RosCoordinates.vec(drone.initial_position))
		actor.configure_drone(did, color, float(drone.get("radius", 0.08)), show_envelopes)
		drones[did] = actor
		var trail := _instance(TRAIL) as FlightTrail
		trail.configure(color)
		trails[did] = trail
		picks.append({"kind": "drone", "id": did, "index": -1, "node": actor})
		var mission: Dictionary = doc.get("missions", {}).get(did, {})
		var previous: Vector3 = actor.position
		if mission.has("takeoff"):
			previous.y = float(mission.takeoff.height)
			_segment(actor.position, previous, color)
		for i in range(mission.get("waypoints", []).size()):
			var waypoint: Dictionary = mission.waypoints[i]
			var p: Vector3 = RosCoordinates.position_to_godot(RosCoordinates.vec(waypoint.position))
			var marker := _instance(WAYPOINT) as ExperimentVisualItem
			marker.position = p
			marker.configure_waypoint("%s · %d" % [did, i + 1], color)
			picks.append({"kind": "waypoint", "id": did, "index": i, "node": marker})
			_segment(previous, p, color)
			previous = p
	if reset_camera:
		orbit_target = Vector3(0, 0.6, 0)
		distance = 5.0
		_update_camera()

func update_poses(poses: Dictionary) -> void:
	for did in poses:
		if not drones.has(did): continue
		var pose: Dictionary = poses[did]
		var actor: Node3D = drones[did]
		actor.position = RosCoordinates.position_to_godot(RosCoordinates.vec(pose.position))
		var q: Array = pose.get("orientation", [0, 0, 0, 1])
		actor.quaternion = RosCoordinates.orientation_to_godot(Quaternion(q[0], q[1], q[2], q[3]))

func update_live_poses(poses: Dictionary, time: float) -> void:
	update_poses(poses)
	for did in poses:
		if not trails.has(did): continue
		var p: Vector3 = drones[did].position
		trails[did].append_sample(p, time)
		trails[did].show_until(time, p)

func prepare_replay_trails(frames: Array) -> void:
	for frame: Dictionary in frames:
		for did in frame.poses:
			if trails.has(did):
				trails[did].append_sample(RosCoordinates.position_to_godot(RosCoordinates.vec(frame.poses[did].position)), float(frame.time))

func update_replay_poses(poses: Dictionary, time: float) -> void:
	update_poses(poses)
	for did in trails:
		trails[did].show_until(time, drones[did].position)

func focus_drone(did: String) -> void:
	if drones.has(did):
		orbit_target = drones[did].position
		distance = 0.75
		_update_camera()

func _update_camera() -> void:
	camera.position = orbit_target + distance * Vector3(sin(orbit_yaw) * cos(orbit_pitch), sin(orbit_pitch), cos(orbit_yaw) * cos(orbit_pitch))
	camera.look_at(orbit_target, Vector3.UP)

func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
			distance = maxf(0.15, distance * 0.88)
			_update_camera()
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
			distance = minf(150.0, distance / 0.88)
			_update_camera()
		elif event.button_index == MOUSE_BUTTON_RIGHT:
			rotating = event.pressed
		elif event.button_index == MOUSE_BUTTON_LEFT:
			if event.pressed:
				panning = false
				var best: float = 22.0
				var pick: Dictionary = {}
				for item in picks:
					var p: Vector3 = item.node.global_position
					if camera.is_position_behind(p): continue
					var d: float = camera.unproject_position(p).distance_to(event.position)
					if d < best:
						best = d
						pick = item
				if not pick.is_empty():
					selected.emit(pick.kind, pick.id, pick.index)
					if editable: drag_item = pick
				else:
					panning = true
			else:
				if not drag_item.is_empty() and is_instance_valid(drag_item.node):
					var p: Vector3 = RosCoordinates.position_to_ros(drag_item.node.position)
					moved.emit(drag_item.kind, drag_item.id, drag_item.index, p)
				drag_item = {}
				panning = false
	elif event is InputEventMouseMotion:
		if rotating:
			orbit_yaw -= event.relative.x * 0.008
			orbit_pitch = clampf(orbit_pitch + event.relative.y * 0.008, -1.3, 1.45)
			_update_camera()
		elif panning and event.button_mask & MOUSE_BUTTON_MASK_LEFT:
			orbit_target += (-camera.global_basis.x * event.relative.x + camera.global_basis.y * event.relative.y) * distance * 0.0015
			_update_camera()
		elif editable and not drag_item.is_empty() and is_instance_valid(drag_item.node):
			var plane := Plane(Vector3.UP, drag_item.node.position.y)
			var hit: Variant = plane.intersects_ray(camera.project_ray_origin(event.position), camera.project_ray_normal(event.position))
			if hit != null:
				var p: Vector3 = hit
				if event.ctrl_pressed:
					p.x = snappedf(p.x, 0.1)
					p.z = snappedf(p.z, 0.1)
				drag_item.node.position = p
