import bpy
import pytest


@pytest.fixture
def pushed(cube_animation):
    r = cube_animation.push_action_to_nla("Cube", track_name="Base", strip_name="Slide")
    return cube_animation, r["nla_tracks"][0]["strips"][0]["action"]


def test_push_down_keeps_animation(pushed):
    s, _ = pushed
    anim = bpy.data.objects["Cube"].animation_data
    assert anim.action is None
    assert anim.nla_tracks["Base"].strips["Slide"]
    bpy.context.scene.frame_set(40)
    assert bpy.data.objects["Cube"].location.x == pytest.approx(3.0)


def test_add_strip_and_overlap(pushed):
    s, action = pushed
    r = s.add_nla_strip("Cube", action, 60, track_name="Base", strip_name="Again", repeat=2, blend_type="add")
    strip = r["nla_tracks"][0]["strips"][1]
    assert (strip["frame_start"], strip["repeat"], strip["blend_type"]) == (60.0, 2.0, "ADD")
    with pytest.raises(ValueError, match="Could not add strip"):
        s.add_nla_strip("Cube", action, 10, track_name="Base")
    r = s.add_nla_strip("Cube", action, 10, track_name="Layer2", scale=0.5)
    assert [t["name"] for t in r["nla_tracks"]] == ["Base", "Layer2"]


def test_update_strip_keeps_length(pushed):
    s, action = pushed
    s.add_nla_strip("Cube", action, 60, track_name="Base", strip_name="Again", repeat=2)
    r = s.update_nla_strip("Cube", "Base", "Again", frame_start=100, mute=True, extrapolation="HOLD_FORWARD")
    strip = r["nla_tracks"][0]["strips"][1]
    assert strip["frame_start"] == 100 and strip["mute"]
    assert strip["frame_end"] == pytest.approx(100 + 2 * 39)


def test_track_settings_and_removal(pushed):
    s, action = pushed
    s.add_nla_strip("Cube", action, 1, track_name="Layer2")
    r = s.set_nla_track("Cube", "Layer2", mute=True, name="Muted")
    assert (r["nla_tracks"][1]["name"], r["nla_tracks"][1]["mute"]) == ("Muted", True)
    assert s.remove_nla("Cube", "Muted")["nla_tracks"][0]["name"] == "Base"
    assert s.remove_nla("Cube", "Base", "Slide")["nla_tracks"][0]["strips"] == []


def test_data_target(server):
    server.insert_keyframes("Light", "data.energy", [{"frame": 1, "value": 10}, {"frame": 20, "value": 500}])
    r = server.push_action_to_nla("Light", target="data")
    assert r["target"] == "data" and r["nla_tracks"]
    assert "data" in server.get_animation_data("Light")["objects"]["Light"]["nla_tracks"]


@pytest.mark.parametrize("call, message", [
    (lambda s: s.push_action_to_nla("Camera"), "no active action"),
    (lambda s: s.add_nla_strip("Cube", "Nope", 1), "Action not found"),
    (lambda s: s.update_nla_strip("Cube", "Base", "X"), "NLA strip not found"),
    (lambda s: s.update_nla_strip("Cube", "Base", "Slide", blend_type="MIX"), "Invalid blend_type"),
    (lambda s: s.push_action_to_nla("Cube", target="world"), "Invalid target"),
])
def test_nla_errors(pushed, call, message):
    with pytest.raises(ValueError, match=message):
        call(pushed[0])
