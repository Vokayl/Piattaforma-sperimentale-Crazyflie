class_name FlightTrail
extends MultiMeshInstance3D
## Traccia delle pose osservate di un drone.

# Distanza minima tra punti grafici; non cambia i frame registrati.
const MIN_POINT_DISTANCE: float = 0.01
var points := PackedVector3Array()
var times := PackedFloat64Array()
@onready var tip: MeshInstance3D = $Tip

func configure(color: Color) -> void:
	(material_override as StandardMaterial3D).albedo_color = color

func append_sample(point: Vector3, time: float) -> void:
	if not point.is_finite() or not is_finite(time): return
	if not points.is_empty():
		if time <= times[-1] or point.distance_to(points[-1]) < MIN_POINT_DISTANCE: return
	var segment_count: int = points.size()
	if segment_count > multimesh.instance_count:
		# instance_count azzera i trasformi: ripristiniamo quelli già memorizzati.
		multimesh.instance_count = maxi(64, multimesh.instance_count * 2)
		for i in range(1, points.size()):
			multimesh.set_instance_transform(i - 1, _segment_transform(points[i - 1], points[i]))
	if not points.is_empty():
		multimesh.set_instance_transform(segment_count - 1, _segment_transform(points[-1], point))
	# Limiti effettivi, anche quando un drone esce dal volume programmato.
	var margin := Vector3.ONE * 0.02
	var bounds := AABB(point - margin, margin * 2.0)
	multimesh.custom_aabb = bounds if points.is_empty() else multimesh.custom_aabb.merge(bounds)
	points.append(point)
	times.append(time)

func show_until(time: float, current_position: Vector3) -> void:
	tip.visible = false
	multimesh.visible_instance_count = 0
	if times.is_empty() or time < times[0]: return
	# Nel replay si riutilizza la mesh variando i segmenti visibili.
	var lo: int = 0
	var hi: int = times.size() - 1
	while lo < hi:
		var mid: int = int((lo + hi + 1) / 2)
		if times[mid] <= time: lo = mid
		else: hi = mid - 1
	multimesh.visible_instance_count = lo
	if current_position.is_finite() and points[lo].distance_squared_to(current_position) > 0.00000001:
		tip.transform = _segment_transform(points[lo], current_position)
		tip.visible = true

func _segment_transform(a: Vector3, b: Vector3) -> Transform3D:
	var direction: Vector3 = b - a
	var up: Vector3 = Vector3.RIGHT if absf(direction.normalized().dot(Vector3.UP)) > 0.99 else Vector3.UP
	var rotation: Basis = Basis.looking_at(direction, up)
	rotation.z *= direction.length()
	return Transform3D(rotation, (a + b) * 0.5)
