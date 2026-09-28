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
