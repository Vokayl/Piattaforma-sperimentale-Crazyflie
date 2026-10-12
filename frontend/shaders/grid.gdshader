shader_type spatial;
render_mode unshaded, cull_disabled, blend_mix;

uniform float extent_m = 4.0;
uniform float minor_step = 0.1;
uniform float major_step = 1.0;
uniform vec4 minor_color : source_color = vec4(0.18, 0.22, 0.27, 0.55);
uniform vec4 major_color : source_color = vec4(0.34, 0.40, 0.48, 0.85);

float grid_line(vec2 position_m, float step_m) {
	vec2 coord = position_m / step_m;
	vec2 distance_to_line = abs(fract(coord - 0.5) - 0.5) / max(fwidth(coord), vec2(1e-5));
	return 1.0 - min(min(distance_to_line.x, distance_to_line.y), 1.0);
}

void fragment() {
	vec2 position_m = (UV - vec2(0.5)) * extent_m;
	float minor = grid_line(position_m, minor_step);
	float major = grid_line(position_m, major_step);
	float alpha = max(minor * minor_color.a, major * major_color.a);
	vec3 color = mix(minor_color.rgb, major_color.rgb, major);
	ALBEDO = color;
	ALPHA = alpha;
}
