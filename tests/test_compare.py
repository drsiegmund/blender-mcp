import bpy
import pytest


@pytest.fixture
def render(server, scene, tmp_path):
    server._apply_render_settings("CYCLES", 64, 48, 1)
    counter = iter(range(1000))

    def _render():
        path = str(tmp_path / f"r{next(counter)}.png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        return server._remember_render(path, {"type": "render"})
    return _render


def test_history_numbers_and_copies(server, render, tmp_path):
    first, second = render(), render()
    assert (first["number"], second["number"]) == (1, 2)
    assert first["filepath"] != second["filepath"]
    listed = server.list_renders()["renders"]
    assert [r["number"] for r in listed] == [1, 2]
    assert "filepath" not in listed[0]


def test_history_is_bounded(server, render):
    server._RENDER_HISTORY_SIZE = 3
    for _ in range(5):
        render()
    assert [r["number"] for r in server.list_renders()["renders"]] == [3, 4, 5]
    with pytest.raises(ValueError, match="not in the history"):
        server._find_render(1)


def test_compare_identical_renders(server, render, tmp_path):
    render(), render()
    r = server.compare_renders(filepath=str(tmp_path / "cmp.png"))
    assert r["changed_fraction"] == 0 and "changed_bbox" not in r
    img = bpy.data.images.load(str(tmp_path / "cmp.png"))
    assert tuple(img.size) == (3 * 64 + 4 * 4, 48 + 2 * 4)


def test_compare_detects_moved_object(server, render, tmp_path):
    render()
    bpy.data.objects["Cube"].location.x += 1.5
    render()
    r = server.compare_renders(before=1, after=2, filepath=str(tmp_path / "cmp.png"))
    assert r["changed_fraction"] > 0.05
    box = r["changed_bbox"]
    assert 0 <= box["x_min"] < box["x_max"] < 64 and 0 <= box["y_min"] < box["y_max"] < 48
    assert (r["before"]["number"], r["after"]["number"]) == (1, 2)


def test_compare_different_sizes(server, render, scene, tmp_path):
    render()
    scene.render.resolution_x, scene.render.resolution_y = 32, 24
    render()
    r = server.compare_renders(filepath=str(tmp_path / "cmp.png"))
    assert tuple(bpy.data.images.load(str(tmp_path / "cmp.png")).size) == (3 * 32 + 16, 24 + 8)
    assert r["max_difference"] < 0.5


def test_compare_needs_two_renders(server, render, tmp_path):
    render()
    with pytest.raises(ValueError, match="Only 1 render"):
        server.compare_renders(filepath=str(tmp_path / "cmp.png"))
