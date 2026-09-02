import math

from orchestrator.snap import align_rotation_deg, snap_position


def _apply_euler_xyz(v, deg):
    """Rotate v by Blender-XYZ euler (degrees) — pure-python reference."""
    rx, ry, rz = (math.radians(a) for a in deg)
    def rot_x(p):
        x, y, z = p
        c, s = math.cos(rx), math.sin(rx)
        return (x, y * c - z * s, y * s + z * c)
    def rot_y(p):
        x, y, z = p
        c, s = math.cos(ry), math.sin(ry)
        return (x * c + z * s, y, -x * s + z * c)
    def rot_z(p):
        x, y, z = p
        c, s = math.cos(rz), math.sin(rz)
        return (x * c - y * s, x * s + y * c, z)
    return rot_z(rot_y(rot_x(v)))


def test_align_rotation_identity():
    assert align_rotation_deg((0, 0, 1)) == (0.0, 0.0, 0.0)


def test_align_rotation_to_plus_x():
    r = align_rotation_deg((1, 0, 0))
    out = _apply_euler_xyz((0, 0, 1), r)
    assert all(abs(a - b) < 1e-6 for a, b in zip(out, (1, 0, 0)))


def test_align_rotation_arbitrary_normal():
    n = (0.267, 0.535, 0.802)
    r = align_rotation_deg(n)
    out = _apply_euler_xyz((0, 0, 1), r)
    got = (out[0] / 1, out[1], out[2])
    exp = (n[0] / math.sqrt(sum(c * c for c in n)),
           n[1] / math.sqrt(sum(c * c for c in n)),
           n[2] / math.sqrt(sum(c * c for c in n)))
    assert all(abs(a - b) < 1e-4 for a, b in zip(got, exp))


def test_snap_position_picks_closest_within_radius():
    candidates = [([10, 0, 0], [0, 0, 1]), ([2, 0, 0], [0, 1, 0])]
    hit = snap_position(candidates, (2.4, 0.1, 0), radius=1.0)
    assert hit == ([2, 0, 0], [0, 1, 0])


def test_snap_position_none_outside_radius():
    assert snap_position([([10, 0, 0], [0, 0, 1])], (0, 0, 0), 1.0) is None
