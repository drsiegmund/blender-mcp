import math

import bpy
import numpy as np
import pytest

ROTATION = ["-y", "x", "0"]
PLANE = [[-2, 2], [-2, 2], [0, 0]]
LORENZ = ["sigma*(y-x)", "x*(rho-z)-y", "x*y-beta*z"]
LORENZ_PARAMS = {"sigma": 10, "rho": 28, "beta": 8 / 3}


def _curve_points(name):
    return [np.array([p.co[:3] for p in spline.points]) for spline in bpy.data.objects[name].data.splines]


def test_arrows_for_planar_field(server):
    r = server.plot_vector_field("Rot", ROTATION, PLANE, resolution=[5, 5, 1])
    assert r["objects"] == ["Rot"]
    assert r["arrows"] == 24 and r["skipped_samples"] == 1, "zero vector at the origin is skipped"
    assert r["magnitude_range"] == [1.0, pytest.approx(2 * math.sqrt(2), rel=1e-5)]
    mesh = bpy.data.objects["Rot"].data
    values = np.empty(len(mesh.vertices), dtype=np.float32)
    mesh.attributes["magnitude"].data.foreach_get("value", values)
    assert values.min() == 0.0 and values.max() == pytest.approx(1.0)
    assert mesh.materials[0].name == "Rot_colormap"


def test_arrows_point_along_field(server):
    server.plot_vector_field("One", ["1", "0", "0"], [[0, 0], [0, 0], [0, 0]], resolution=[1, 1, 1])
    verts = np.array([v.co for v in bpy.data.objects["One"].data.vertices])
    tip = verts[np.argmax(verts[:, 0])]
    assert tip[1] == pytest.approx(0, abs=1e-6) and tip[2] == pytest.approx(0, abs=1e-6)


def test_log_color_scale_auto(server):
    field = ["x/(x**2+y**2)**2", "y/(x**2+y**2)**2", "0"]
    r = server.plot_vector_field("Point", field, PLANE, resolution=[9, 9, 1])
    assert "log" in r["color"]
    assert "linear" in server.plot_vector_field("Rot", ROTATION, PLANE, resolution=[5, 5, 1])["color"]


def test_streamlines_follow_circles(server):
    seeds = [[0.5, 0, 0], [1.0, 0, 0], [1.5, 0, 0]]
    r = server.plot_vector_field("Rot", ROTATION, PLANE, mode="streamlines", seeds=seeds,
                                 step_size=0.02, max_steps=200)
    assert r["objects"] == ["Rot_streamlines"] and r["streamlines"] == 3
    for line, seed in zip(_curve_points("Rot_streamlines"), seeds):
        radii = np.linalg.norm(line[:, :2], axis=1)
        assert radii == pytest.approx(seed[0], abs=1e-4)


def test_replot_replaces_objects(server):
    server.plot_vector_field("Rot", ROTATION, PLANE, resolution=[3, 3, 1], mode="both")
    server.plot_vector_field("Rot", ROTATION, PLANE, resolution=[5, 5, 1], mode="both")
    names = [o.name for o in bpy.context.scene.objects if o.name.startswith("Rot")]
    assert sorted(names) == ["Rot", "Rot_streamlines"]


@pytest.mark.parametrize("field, bounds, kwargs, message", [
    (["-y", "x"], PLANE, {}, "3 expressions"),
    (["__import__('os')", "0", "0"], PLANE, {}, "Unknown names"),
    (["open", "0", "0"], PLANE, {}, "Unknown names"),
    (["-y +", "x", "0"], PLANE, {}, "Invalid expression"),
    (ROTATION, [[2, -2], [0, 0], [0, 0]], {}, "bounds"),
    (ROTATION, PLANE, {"resolution": [200, 200, 1]}, "at most 20000"),
    (ROTATION, PLANE, {"mode": "dots"}, "mode must be"),
    (["0", "0", "0"], PLANE, {}, "zero or undefined"),
    (["x", "0", "0"], PLANE, {"params": {"x": 1}}, "reserved"),
])
def test_vector_field_errors(server, field, bounds, kwargs, message):
    with pytest.raises(ValueError, match=message):
        server.plot_vector_field("Bad", field, bounds, **kwargs)


def test_trajectory_from_points(server):
    r = server.plot_trajectory("Path", points=[[0, 0, 0], [1, 0, 0], [1, 1, 0]])
    assert (r["source"], r["trajectories"], r["points_per_trajectory"]) == ("points", 1, [3])
    assert bpy.data.objects["Path"].type == 'CURVE'


def test_harmonic_oscillator_closes_orbit(server):
    r = server.plot_trajectory("Osc", ode=["y", "-x", "0"], initial=[1, 0, 0],
                               t_span=[0, 2 * math.pi], steps=400)
    assert r["points_per_trajectory"] == [401]
    line = _curve_points("Osc")[0]
    assert line[-1] == pytest.approx([1, 0, 0], abs=1e-6)
    assert np.linalg.norm(line[:, :2], axis=1) == pytest.approx(1.0, abs=1e-6)


def test_multiple_trajectories_get_own_materials(server):
    server.plot_trajectory("Lorenz", ode=LORENZ, params=LORENZ_PARAMS,
                           initial=[[1, 1, 1], [1.001, 1, 1]], t_span=[0, 30], steps=3000)
    curve = bpy.data.objects["Lorenz"].data
    assert [s.material_index for s in curve.splines] == [0, 1]
    assert len(curve.materials) == 2
    a, b = _curve_points("Lorenz")
    assert np.linalg.norm(a[-1] - b[-1]) > 1, "chaotic trajectories separate"


def test_fit_size_and_blowup(server):
    r = server.plot_trajectory("Blow", ode=["x**2", "0", "0"], initial=[1, 0, 0], t_span=[0, 2], steps=200,
                               fit_size=4)
    assert r["truncated_nonfinite"] == 1
    line = _curve_points("Blow")[0]
    assert np.ptp(line, axis=0).max() == pytest.approx(4)


def test_animated_trajectory(server, scene):
    r = server.plot_trajectory("Osc", ode=["y", "-x", "0"], initial=[[1, 0, 0], [2, 0, 0]],
                               t_span=[0, math.pi], steps=100, animate=True, frame_start=1, frame_end=25)
    assert r["animation"]["markers"] == ["Osc_marker_0", "Osc_marker_1"]
    curve = bpy.data.objects["Osc"].data
    scene.frame_set(13)
    assert curve.bevel_factor_end == pytest.approx(0.5)
    scene.frame_set(25)
    assert curve.bevel_factor_end == pytest.approx(1.0)
    assert bpy.data.objects["Osc_marker_1"].matrix_world.translation[:] == pytest.approx((-2, 0, 0), abs=1e-4)


@pytest.mark.parametrize("kwargs, message", [
    ({}, "either 'points' or 'ode'"),
    ({"points": [[0, 0, 0]], "ode": ["0", "0", "0"]}, "either 'points' or 'ode'"),
    ({"ode": ["0", "0", "0"]}, "'initial' is required"),
    ({"points": [[0, 0, 0]]}, "at least 2 finite points"),
    ({"points": [[0, 0, 0], [1, 1, 1]], "animate": True, "frame_start": 5, "frame_end": 5}, "frame_end"),
])
def test_trajectory_errors(server, kwargs, message):
    with pytest.raises(ValueError, match=message):
        server.plot_trajectory("Bad", **kwargs)
