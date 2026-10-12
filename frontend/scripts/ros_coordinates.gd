class_name RosCoordinates
extends RefCounted

# Cambio di base da ROS (Z verticale) a Godot (Y verticale).
static func position_to_godot(p: Vector3) -> Vector3:
	return Vector3(p.x, p.z, -p.y)

static func position_to_ros(p: Vector3) -> Vector3:
	return Vector3(p.x, -p.z, p.y)

# Q_G = C Q_R C^-1; per i quaternioni basta ruotare la parte vettoriale.
static func orientation_to_godot(q: Quaternion) -> Quaternion:
	return Quaternion(q.x, q.z, -q.y, q.w).normalized()

static func orientation_to_ros(q: Quaternion) -> Quaternion:
	return Quaternion(q.x, -q.z, q.y, q.w).normalized()

static func vec(values: Array) -> Vector3:
	return Vector3(float(values[0]), float(values[1]), float(values[2]))
