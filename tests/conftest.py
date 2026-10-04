"""Shared fixtures for headless add-on tests.

The add-on handlers are tested against Blender running as a Python module
(``pip install -r tests/requirements.txt``). ``bpy.app.timers`` do not fire
in module mode, so async jobs are driven by calling their step functions.
"""
import importlib.util
import pathlib

import pytest

try:
    import bpy
except ImportError:  # bpy is only installable on Python 3.11
    bpy = None
    collect_ignore_glob = ["test_*.py"]

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def addon():
    spec = importlib.util.spec_from_file_location("blendermcp_addon", ROOT / "addon.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(addon):
    """A BlenderMCPServer on a fresh default scene (Cube, Light, Camera)."""
    bpy.ops.wm.read_factory_settings(use_empty=False)
    addon.register()
    yield addon.BlenderMCPServer()
    addon.unregister()


@pytest.fixture
def scene():
    return bpy.context.scene


@pytest.fixture
def cube_animation(server):
    """Cube moving linearly from x=-3 (frame 1) to x=3 (frame 40)."""
    server.insert_keyframes("Cube", "location", [
        {"frame": 1, "value": [-3, 0, 0]},
        {"frame": 40, "value": [3, 0, 0]},
    ], interpolation="LINEAR")
    server.set_timeline(frame_start=1, frame_end=40)
    return server
