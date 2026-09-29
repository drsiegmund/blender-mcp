"""Command dispatch and snapshot/diff behavior."""


def test_execute_command_routes_new_handlers(cube_animation):
    for command, params in [
        ("scrub_timeline", {"frame": 1}),
        ("get_animation_data", {}),
        ("set_timeline", {"fps": 25}),
        ("push_action_to_nla", {"object_name": "Cube"}),
    ]:
        resp = cube_animation.execute_command({"type": command, "params": params})
        assert resp["status"] == "success", resp


def test_execute_command_reports_errors(server):
    resp = server.execute_command({"type": "insert_keyframes",
                                   "params": {"object_name": "Nope", "data_path": "location",
                                              "keyframes": [{"frame": 1}]}})
    assert resp["status"] == "error" and "Object not found" in resp["message"]


def test_diff_detects_keyframe_changes(server):
    server.snapshot_scene()
    server.insert_keyframes("Cube", "location", [{"frame": 1}, {"frame": 10}])
    server.insert_keyframes("Light", "data.energy", [{"frame": 5}])
    diff = server.diff_scene()
    assert diff["keyframe_changes"]["Cube"]["location"] == {"old": [], "new": [1, 10]}
    assert diff["keyframe_changes"]["Light"]["data.energy"] == {"old": [], "new": [5]}


def test_snapshot_only_lists_scene_materials(server):
    import bpy
    bpy.data.materials.new("UnusedElsewhere")
    used = bpy.data.materials.new("OnCube")
    bpy.data.objects["Cube"].data.materials.append(used)
    mats = server._build_snapshot()["materials"]
    assert "OnCube" in mats and "UnusedElsewhere" not in mats


def test_diff_camera_world_and_visibility(server):
    import bpy
    server.snapshot_scene()
    cam = bpy.data.objects["Camera"].data
    cam.type, cam.ortho_scale = 'ORTHO', 12.4
    bpy.context.scene.world.color = (0.1, 0.2, 0.3)
    bpy.data.objects["Cube"].hide_render = True
    diff = server.diff_scene()
    assert diff["camera_changes"]["Camera"]["type"] == {"old": "PERSP", "new": "ORTHO"}
    assert diff["camera_changes"]["Camera"]["ortho_scale"]["new"] == 12.4
    assert diff["world_changes"]["color"]["new"] == [0.1, 0.2, 0.3]
    assert diff["modified_objects"]["Cube"]["hide_render"] == {"old": False, "new": True}
    assert "world changed" in diff["summary"]


def test_diff_flags_changes_from_animation(cube_animation):
    import bpy
    bpy.context.scene.frame_set(1)
    cube_animation.snapshot_scene()
    bpy.context.scene.frame_set(20)
    diff = cube_animation.diff_scene()
    assert diff["modified_objects"]["Cube"]["location"]["animated"] is True
    assert "only in animated properties" in diff["summary"]
