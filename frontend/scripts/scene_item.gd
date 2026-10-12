class_name ExperimentVisualItem
extends Node3D
## Comportamenti condivisi dagli oggetti della scena.

func _tint(node: GeometryInstance3D, color: Color) -> void:
	var material := node.material_override as StandardMaterial3D
	if material != null:
		material.albedo_color = color

func configure_drone(id: String, color: Color, radius: float, show_envelope: bool) -> void:
	$Label.text = id
	$Label.modulate = color
	_tint($Heading, color)
	$Envelope.scale = Vector3.ONE * radius
	$Envelope.visible = show_envelope
	_tint($Envelope, Color(color, 0.12))

func configure_waypoint(id: String, color: Color) -> void:
	$Label.text = id
	$Label.modulate = color
	_tint($Visual, color)

func configure_obstacle(id: String, dimensions: Vector3) -> void:
	$Label.text = id
	$Visual.scale = dimensions
	$Label.position.y = dimensions.y / 2.0 + 0.08

func configure_segment(from: Vector3, to: Vector3, color: Color) -> void:
	var length: float = from.distance_to(to)
	visible = length > 0.000001
	if not visible: return
	position = (from + to) * 0.5
	var direction: Vector3 = (to - from).normalized()
	look_at(to, Vector3.RIGHT if absf(direction.dot(Vector3.UP)) > 0.99 else Vector3.UP)
	$Visual.scale.z = length
	_tint($Visual, color)
