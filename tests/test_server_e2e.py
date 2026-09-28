"""End-to-end: MCP tool functions in server.py -> socket -> add-on dispatcher -> Blender."""
import json
import os
import socket
import subprocess
import sys

import pytest

os.environ.setdefault("DISABLE_TELEMETRY", "1")
S = pytest.importorskip("blender_mcp.server")


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def blender():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "fake_blender.py"), str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    for line in proc.stdout:  # the add-on prints its own messages first
        if line.strip() == "READY":
            break
    else:
        pytest.fail("fake Blender did not start")
    os.environ["BLENDER_PORT"] = str(port)
    S._blender_connection = None
    yield
    try:
        S.get_blender_connection().sock.sendall(b'{"type": "__quit__"}')
        proc.wait(timeout=10)
    finally:
        proc.kill()
        S._blender_connection = None


def test_animation_tools_roundtrip(blender):
    S.insert_keyframes(None, object_name="Cube", data_path="location",
                       keyframes=[{"frame": 1, "value": [-3, 0, 0]}, {"frame": 30, "value": [3, 0, 0]}],
                       interpolation="LINEAR")
    S.set_timeline(None, frame_start=1, frame_end=30)
    state = json.loads(S.scrub_timeline(None, frame=15.5))
    assert state["objects"]["Cube"]["world_location"][0] == pytest.approx(0.0, abs=1e-3)
    assert "Cube" in json.loads(S.get_animation_data(None))["objects"]
    assert S.insert_keyframes(None, object_name="Cube", data_path="bogus",
                              keyframes=[{"frame": 1}]).startswith("Error")


def test_preview_poll_and_review(blender):
    started = json.loads(S.render_animation_preview(None, num_frames=4, resolution_x=48,
                                                    resolution_y=27, engine="CYCLES", samples=1))
    assert started["status"] == "started"
    image, meta = S.poll_render_status(None)
    assert type(image).__name__ == "Image"
    assert json.loads(meta)["frames"] == [1, 11, 20, 30]
    assert type(S.review_render(None)[0]).__name__ == "Image"


def test_nla_tools_roundtrip(blender):
    r = json.loads(S.push_action_to_nla(None, object_name="Cube", track_name="Base"))
    action = r["nla_tracks"][0]["strips"][0]["action"]
    r = json.loads(S.add_nla_strip(None, object_name="Cube", action_name=action, frame_start=40,
                                   track_name="Base", repeat=2))
    strip = r["nla_tracks"][0]["strips"][1]["name"]
    r = json.loads(S.update_nla_strip(None, object_name="Cube", track_name="Base",
                                      strip_name=strip, frame_start=50))
    assert r["nla_tracks"][0]["strips"][1]["frame_start"] == 50
    assert json.loads(S.set_nla_track(None, object_name="Cube", track_name="Base", mute=True))["nla_tracks"][0]["mute"]
    assert json.loads(S.remove_nla(None, object_name="Cube", track_name="Base"))["nla_tracks"] == []


def test_visualization_tools_roundtrip(blender):
    r = json.loads(S.plot_vector_field(None, name="Rot", field=["-y", "x", "0"],
                                       bounds=[[-1, 1], [-1, 1], [0, 0]], resolution=[4, 4, 1], mode="both"))
    assert r["objects"] == ["Rot", "Rot_streamlines"]
    r = json.loads(S.plot_trajectory(None, name="Lorenz", ode=["s*(y-x)", "x*(28-z)-y", "x*y-2.667*z"],
                                     params={"s": 10}, initial=[1, 1, 1], t_span=[0, 5], steps=500,
                                     fit_size=4, animate=True, frame_start=1, frame_end=20))
    assert r["animation"]["markers"] == ["Lorenz_marker_0"]
    assert S.plot_vector_field(None, name="Bad", field=["os", "0", "0"],
                               bounds=[[0, 1], [0, 1], [0, 0]]).startswith("Error")


def test_compare_renders_roundtrip(blender):
    for _ in range(2):
        S.render_animation_preview(None, num_frames=1, resolution_x=32, resolution_y=18,
                                   engine="CYCLES", samples=1)
        S.poll_render_status(None)
    renders = json.loads(S.list_renders(None))["renders"]
    assert len(renders) >= 2 and renders[-1]["type"] == "animation_preview"
    image, stats = S.compare_renders(None)
    assert type(image).__name__ == "Image"
    assert json.loads(stats)["after"]["number"] == renders[-1]["number"]
