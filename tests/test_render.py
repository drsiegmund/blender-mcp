import os

import bpy


def _run_preview(server):
    ticks = 0
    while server._preview_step() is not None:
        ticks += 1
        assert server.poll_render_status()["result"]["frames_done"] == ticks
    return server.poll_render_status()


def test_render_settings_roundtrip(server, scene):
    before = (scene.render.engine, scene.render.resolution_x, scene.render.filepath)
    saved, engine_id, samples = server._apply_render_settings("CYCLES", 111, 77, 3)
    assert (scene.render.engine, scene.render.resolution_x, scene.cycles.samples) == ("CYCLES", 111, 3)
    server._restore_render_settings(saved)
    assert (scene.render.engine, scene.render.resolution_x, scene.render.filepath) == before


def test_preview_frame_sampling(server):
    assert server._preview_frames(1, 40, 6) == [1, 9, 17, 24, 32, 40]
    assert server._preview_frames(5, 5, 9) == [5]
    assert server._preview_frames(1, 3, 9) == [1, 2, 3]


def test_animation_preview_contact_sheet(cube_animation, scene, tmp_path):
    s = cube_animation
    scene.frame_set(7)
    before = (scene.render.engine, scene.render.resolution_x)
    sheet = str(tmp_path / "preview.png")

    r = s.render_animation_preview(filepath=sheet, num_frames=6, columns=3,
                                   resolution_x=64, resolution_y=36, engine="CYCLES", samples=1)
    assert r["frames"] == [1, 9, 17, 24, 32, 40]
    assert "already in progress" in s.render_animation_preview(filepath=sheet)["error"]

    status = _run_preview(s)
    assert status["status"] == "completed"
    result = status["result"]
    assert (result["columns"], result["rows"]) == (3, 2)

    img = bpy.data.images.load(sheet)
    assert tuple(img.size) == (3 * 64 + 4 * 4, 2 * 36 + 3 * 4)
    assert scene.frame_current == 7
    assert (scene.render.engine, scene.render.resolution_x) == before
    assert os.listdir(tmp_path) == ["preview.png"], "temporary frames are removed"


def test_animation_preview_rejects_bad_range(server, tmp_path):
    r = server.render_animation_preview(filepath=str(tmp_path / "x.png"), frame_start=30, frame_end=10)
    assert "must not be greater" in r["error"]
