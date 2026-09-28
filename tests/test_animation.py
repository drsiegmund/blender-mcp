import math

import bpy
import pytest


def test_insert_vector_keyframes_with_interpolation(server):
    r = server.insert_keyframes("Cube", "location", [
        {"frame": 1, "value": [0, 0, 0]},
        {"frame": 50, "value": [4, 0, 2], "interpolation": "CONSTANT"},
    ], interpolation="LINEAR")
    assert r["inserted_frames"] == [1.0, 50.0]
    assert len(r["fcurves"]) == 3
    x, _, z = r["fcurves"]
    assert [k["interpolation"] for k in x["keyframes"]] == ["LINEAR", "CONSTANT"]
    assert z["keyframes"][1]["value"] == 2.0


def test_insert_single_component(server):
    r = server.insert_keyframes("Cube", "rotation_euler",
                                [{"frame": 1, "value": 0}, {"frame": 50, "value": math.pi}], index=2)
    assert [(f["data_path"], f["index"]) for f in r["fcurves"]] == [("rotation_euler", 2)]


def test_insert_keys_current_value_without_value(server):
    r = server.insert_keyframes("Cube", "scale", [{"frame": 10}])
    assert [k["value"] for f in r["fcurves"] for k in f["keyframes"]] == [1.0, 1.0, 1.0]


@pytest.mark.parametrize("obj, path, values, expected", [
    ("Light", "data.energy", (100, 2000), 2000),
    ("Camera", "data.lens", (35, 85), 85),
])
def test_data_block_paths(server, obj, path, values, expected):
    server.insert_keyframes(obj, path, [{"frame": 1, "value": values[0]}, {"frame": 50, "value": values[1]}])
    snap = server._build_snapshot()
    assert snap["objects"][obj]["keyframes"][path] == [1, 50]
    state = server.scrub_timeline(50, [obj])["objects"][obj]
    assert state.get("energy", state.get("focal_length")) == expected


def test_custom_property_and_modifier_paths(server):
    cube = bpy.data.objects["Cube"]
    cube["strength"] = 1.0
    cube.modifiers.new("Sub.001", "SUBSURF")
    server.insert_keyframes("Cube", '["strength"]', [{"frame": 1, "value": 0.0}, {"frame": 50, "value": 5.0}])
    server.insert_keyframes("Cube", 'modifiers["Sub.001"].levels', [{"frame": 1, "value": 0}, {"frame": 50, "value": 3}])
    paths = {f["data_path"] for f in server.get_animation_data("Cube")["objects"]["Cube"]["fcurves"]}
    assert paths == {'["strength"]', 'modifiers["Sub.001"].levels'}


@pytest.mark.parametrize("args, message", [
    (("Nope", "location", [{"frame": 1}]), "Object not found"),
    (("Cube", "not_a_prop", [{"frame": 1}]), "Invalid data_path"),
    (("Cube", "location", [{"frame": 1}], -1, "WOBBLE"), "Invalid interpolation"),
    (("Cube", "location", []), "No keyframes"),
])
def test_insert_errors(server, args, message):
    with pytest.raises(ValueError, match=message):
        server.insert_keyframes(*args)


def test_get_animation_data_lists_animated_objects(cube_animation):
    cube_animation.insert_keyframes("Light", "data.energy", [{"frame": 1, "value": 10}])
    r = cube_animation.get_animation_data()
    assert set(r["objects"]) == {"Cube", "Light"}
    cube = r["objects"]["Cube"]
    assert cube["frame_range"] == [1.0, 40.0]
    assert cube["actions"]["object"]["action"]
    assert "data" in r["objects"]["Light"]["actions"]


def test_set_timeline(server, scene):
    r = server.set_timeline(frame_start=1, frame_end=50, fps=30, frame_current=25)
    assert (r["frame_end"], r["fps"], r["frame_current"], r["effective_fps"]) == (50, 30, 25, 30.0)
    assert server.set_timeline(frame_start=100, frame_end=200)["frame_start"] == 100
    assert server.set_timeline(frame_start=1, frame_end=50)["frame_end"] == 50
    with pytest.raises(ValueError, match="must not be greater"):
        server.set_timeline(frame_start=60)


def test_scrub_timeline_evaluates_animation(cube_animation):
    assert cube_animation.scrub_timeline(40)["objects"]["Cube"]["world_location"] == [3.0, 0.0, 0.0]
    mid = cube_animation.scrub_timeline(20.5)
    assert mid["objects"]["Cube"]["world_location"][0] == pytest.approx(0.0, abs=1e-3)


def test_scrub_includes_children_and_constrained_objects(cube_animation):
    child = bpy.data.objects.new("Child", None)
    child.parent = bpy.data.objects["Cube"]
    tracker = bpy.data.objects.new("Tracker", None)
    tracker.constraints.new("TRACK_TO").target = bpy.data.objects["Cube"]
    for obj in (child, tracker):
        bpy.context.scene.collection.objects.link(obj)
    objects = cube_animation.scrub_timeline(10)["objects"]
    assert {"Cube", "Child", "Tracker"} <= set(objects)
    assert "Camera" not in objects
    assert list(cube_animation.scrub_timeline(10, ["Child"])["objects"]) == ["Child"]


def test_delete_keyframes(cube_animation):
    s = cube_animation
    s.insert_keyframes("Cube", "rotation_euler", [{"frame": 1, "value": 0}, {"frame": 9, "value": 1}], index=2)
    assert s.delete_keyframes("Cube", "location", frames=[40])["removed_total"] == 3
    assert s.delete_keyframes("Cube", "location", frames=[1], index=0)["removed_total"] == 1
    assert s.delete_keyframes("Cube", "rotation_euler")["removed_total"] == 2
    paths = {fc.data_path for fc in s._get_fcurves(bpy.data.objects["Cube"])}
    assert paths == {"location"}, "empty fcurves are removed"


def test_delete_all_keyframes_including_data(server):
    server.insert_keyframes("Light", "data.energy", [{"frame": 1, "value": 10}, {"frame": 5, "value": 20}])
    r = server.delete_keyframes("Light")
    assert r["removed"] == {"data.energy[0]": 2}
