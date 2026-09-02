"""Pure snapping math for the kitbash editor (server-side, unit-testable)."""

import math


def _unit(v):
    length = math.sqrt(sum(c * c for c in v))
    if length < 1e-12:
        raise ValueError("zero-length vector")
    return tuple(c / length for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def align_rotation_deg(normal, mount_axis=(0.0, 0.0, 1.0)):
    """Euler XYZ degrees (Blender order) rotating mount_axis onto normal."""
    a = _unit(mount_axis)
    n = _unit(normal)
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, n))))
    if dot > 1 - 1e-9:
        return (0.0, 0.0, 0.0)
    if dot < -1 + 1e-9:  # opposite: 180° about any perpendicular axis
        ref = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
        axis = _unit(_cross(a, ref))
        angle = math.pi
    else:
        axis = _unit(_cross(a, n))
        angle = math.acos(dot)
    # axis-angle -> quaternion -> Euler XYZ (Blender order)
    s = math.sin(angle / 2)
    qx, qy, qz = (axis[i] * s for i in range(3))
    qw = math.cos(angle / 2)
    # rotation matrix from quaternion
    r00 = 1 - 2 * (qy * qy + qz * qz); r01 = 2 * (qx * qy - qz * qw); r02 = 2 * (qx * qz + qy * qw)
    r10 = 2 * (qx * qy + qz * qw);     r11 = 1 - 2 * (qx * qx + qz * qz); r12 = 2 * (qy * qz - qx * qw)
    r20 = 2 * (qx * qz - qy * qw);     r21 = 2 * (qy * qz + qx * qw);     r22 = 1 - 2 * (qx * qx + qy * qy)
    # R = Rz @ Ry @ Rx  (Blender XYZ)
    ry = math.asin(max(-1.0, min(1.0, -r20)))
    if abs(r20) < 1 - 1e-9:
        rx = math.atan2(r21, r22)
        rz = math.atan2(r10, r00)
    else:  # gimbal lock
        rx = math.atan2(-r12, r11)
        rz = 0.0
    return tuple(round(math.degrees(a), 6) for a in (rx, ry, rz))


def snap_position(candidates, point, radius):
    """Closest (position, normal) candidate within radius of point, else None."""
    best = None
    best_d2 = radius * radius
    for pos, normal in candidates:
        d2 = sum((p - q) ** 2 for p, q in zip(pos, point))
        if d2 <= best_d2:
            best_d2 = d2
            best = (pos, normal)
    return best
