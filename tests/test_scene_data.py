"""plot_vector_data and import_scene_data: drawing precomputed data."""
import json
import math

import bpy
import numpy as np
import pytest


def _rot_z(deg):
    a = math.radians(deg)
    return [[math.cos(a), -math.sin(a), 0.0], [math.sin(a), math.cos(a), 0.0], [0.0, 0.0, 1.0]]


def _two_boxes():
    return {
        "collection": "Magnets",
        "boxes": [
            {"name": "m0", "half_extents": [0.35, 0.25, 0.15], "center": [1.05, 0, -0.375],
             "rotation": _rot_z(0), "direction": [0, 0, 1]},
            {"name": "m1", "half_extents": [0.35, 0.25, 0.15], "center": [0, 1.05, 0.375],
             "rotation": _rot_z(90), "direction": [0.7071, 0, 0.7071], "status": "estimate"},
        ],
    }


def _alpha(mat):
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    return bsdf.inputs["Alpha"].default_value


def test_boxes_get_their_pose(server):
    r = server.import_scene_data(data=_two_boxes())
    assert r["boxes"] == 2 and r["collection"] == "Magnets"
    assert r["pose_readback_max_error"] < 1e-6  # float32 transforms
    m1 = np.array(bpy.data.objects["m1"].matrix_world)
    assert m1[:3, :3] == pytest.approx(np.array(_rot_z(90)), abs=1e-6)
    assert m1[:3, 3] == pytest.approx([0, 1.05, 0.375], abs=1e-6)
    dims = bpy.data.objects["m0"].dimensions
    assert tuple(dims) == pytest.approx((0.7, 0.5, 0.3), abs=1e-6)


def test_faces_colored_by_direction(server):
    server.import_scene_data(data=_two_boxes())
    mesh = bpy.data.objects["m0"].data
    by_normal = {tuple(round(c) for c in p.normal): mesh.materials[p.material_index].name
                 for p in mesh.polygons}
    assert by_normal[(0, 0, 1)] == "Magnets_pole_out"
    assert by_normal[(0, 0, -1)] == "Magnets_pole_in"
    assert by_normal[(1, 0, 0)] == "Magnets_side"
    arrow = bpy.data.objects["m0_dir"]
    assert arrow.parent.name == "m0"
    tip = max((arrow.matrix_world @ v.co for v in arrow.data.vertices), key=lambda v: v.z)
    assert tip.z > -0.375 + 0.15  # arrow points along +z, out of the top face


def test_estimate_status_is_translucent(server):
    server.import_scene_data(data=_two_boxes())
    checked = bpy.data.objects["m0"].data.materials[0]
    estimate = bpy.data.objects["m1"].data.materials[0]
    assert _alpha(checked) == 1.0
    assert _alpha(estimate) == pytest.approx(0.35)
    assert estimate.name.endswith("_estimate")
    assert bpy.data.objects["m1"]["status"] == "estimate"


def test_animation_keyframes_poses(server, scene):
    data = _two_boxes()
    data["animation"] = {"frame_start": 1, "frames": [
        {"m1": {"center": [0, 1.05, 0.375], "rotation": _rot_z(90 + 6 * k)}} for k in range(5)]}
    r = server.import_scene_data(data=data)
    assert r["animation"] == {"frame_start": 1, "frame_end": 5, "interpolation": "LINEAR"}
    scene.frame_set(4)
    m1 = np.array(bpy.data.objects["m1"].matrix_world)
    assert m1[:3, :3] == pytest.approx(np.array(_rot_z(108)), abs=1e-6)


def test_animation_unknown_box(server):
    data = _two_boxes()
    data["animation"] = {"frames": [{"nope": {"center": [0, 0, 0]}}]}
    with pytest.raises(ValueError, match="unknown box"):
        server.import_scene_data(data=data)


def test_invalid_rotation(server):
    data = {"boxes": [{"name": "b", "half_extents": [1, 1, 1], "rotation": [[2, 0, 0], [0, 1, 0], [0, 0, 1]]}]}
    with pytest.raises(ValueError, match="rotation"):
        server.import_scene_data(data=data)


def test_per_frame_labels_show_on_their_frame(server, scene):
    data = {"collection": "L", "labels": [
        {"name": "U", "frames": ["U = 1", "U = 2", "U = 3"], "frame_start": 1, "location": [0, 0, 1]},
        {"name": "units", "text": "mu0/4pi = 1", "status": "estimate"}]}
    r = server.import_scene_data(data=data)
    assert r["labels"] == 4
    for frame in (1, 2, 3):
        scene.frame_set(frame)
        shown = [n for n in ("U_1", "U_2", "U_3") if not bpy.data.objects[n].hide_render]
        assert shown == [f"U_{frame}"]
    assert bpy.data.objects["U_2"].data.body == "U = 2"
    scene.frame_set(10)
    assert not bpy.data.objects["U_3"].hide_render  # last text holds after the range


def test_markers_and_polylines(server, scene):
    data = {"collection": "P",
            "markers": [{"name": "min", "frame": 16}, {"name": "max", "frame": 46}],
            "polylines": [{"name": "loop", "lines": [[[0, 0, 0], [1, 0, 0], [1, 1, 0]],
                                                      [[0, 0, 1], [0, 1, 1]]], "status": "estimate"}]}
    r = server.import_scene_data(data=data)
    assert {m.name: m.frame for m in scene.timeline_markers} == {"min": 16, "max": 46}
    assert r["polylines"] == [{"name": "loop", "lines": 2}]
    assert "P" in [c.name for c in bpy.data.objects["loop"].users_collection]
    server.import_scene_data(data=data)  # markers are replaced, not duplicated
    assert len(scene.timeline_markers) == 2


def test_replace_removes_old_objects_and_data(server):
    server.import_scene_data(data=_two_boxes())
    meshes = len(bpy.data.meshes)
    server.import_scene_data(data=_two_boxes())
    assert len(bpy.data.meshes) == meshes
    assert sorted(o.name for o in bpy.data.collections["Magnets"].objects) == ["m0", "m0_dir", "m1", "m1_dir"]
    with pytest.raises(ValueError, match="replace"):
        server.import_scene_data(data=_two_boxes(), replace=False)


def test_import_from_json_file(server, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(json.dumps(_two_boxes()))
    assert server.import_scene_data(filepath=str(path))["boxes"] == 2


def test_vector_data_inline(server):
    pts = [[x, y, 0] for x in range(4) for y in range(4)]
    vec = [[1, 0, 0]] * 15 + [[1000, 0, 0]]
    r = server.plot_vector_data("F", points=pts, vectors=vec, clamp_percentile=90)
    assert r["arrows"] == 16 and r["clamped"]["count"] == 1
    assert r["arrow_length"] == pytest.approx(0.8 * (9 / 16) ** 0.5)
    assert "log" in r["color"]


def test_vector_data_skips_zero_and_nonfinite(server):
    r = server.plot_vector_data("F", points=[[0, 0, 0], [1, 0, 0], [2, 0, 0]],
                                vectors=[[0, 0, 0], [float("nan"), 0, 0], [0, 1, 0]])
    assert r["arrows"] == 1 and r["skipped"] == 2


def test_vector_data_from_npz_and_estimate(server, tmp_path):
    path = tmp_path / "field.npz"
    np.savez(path, points=np.random.rand(50, 3), vectors=np.random.rand(50, 3) + 0.1)
    r = server.plot_vector_data("F", filepath=str(path), status="estimate")
    assert r["arrows"] == 50 and r["status"] == "estimate"
    assert _alpha(bpy.data.objects["F"].active_material) == pytest.approx(0.35)


def test_vector_fields_inside_scene_data(server):
    data = {"collection": "V", "vector_fields": [
        {"name": "B", "points": [[0, 0, 0], [1, 0, 0]], "vectors": [[0, 0, 1], [0, 0, 2]]}]}
    r = server.import_scene_data(data=data)
    assert r["vector_fields"][0]["arrows"] == 2
    assert "V" in [c.name for c in bpy.data.objects["B"].users_collection]


def test_dispatch(server):
    resp = server.execute_command({"type": "import_scene_data", "params": {"data": _two_boxes()}})
    assert resp["status"] == "success", resp
    resp = server.execute_command({"type": "plot_vector_data",
                                   "params": {"name": "F", "points": [[0, 0, 0]], "vectors": [[1, 0, 0]]}})
    assert resp["status"] == "success", resp
