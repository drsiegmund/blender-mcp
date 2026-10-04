# CLAUDE.md

This project is a fork of [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp).

## Goal

Extend the MCP server with a collaborative workflow featuring:

- **Diff detection** via `depsgraph_update_post` to track scene changes
- **Render feedback loop** for iterative visual refinement using Claude Vision
- **Animation/Timeline support** for keyframe and timeline operations

## Stack

- Python, bpy (Blender Python API)
- Anthropic Claude API with Vision
- MCP (Model Context Protocol)

## Conventions

- Commit messages in English

## Testing

Tests live in `tests/` and run against Blender as a Python module (Python 3.11 required for bpy 5.0):

```bash
python3.11 -m venv .venv-test && source .venv-test/bin/activate
pip install -e . -r tests/requirements.txt
python -m pytest tests
```

- Fixtures in `tests/conftest.py` load `addon.py` via `importlib` and give each test a fresh default scene and `BlenderMCPServer`.
- `bpy.app.timers` do not fire in module mode: async preview renders are driven by calling `_preview_step()` directly. The socket loop, async `render_scene` and batch scripts still need a real Blender to test.
- Renders in tests use Cycles on the CPU (EEVEE needs a GPU/EGL).
- `tests/test_server_e2e.py` runs the MCP tool functions from `server.py` against `tests/fake_blender.py`, a subprocess that serves the add-on dispatcher over TCP.
- GitHub Actions (`.github/workflows/tests.yml`) runs the suite on every push and pull request.
- `tests/live_check.py` checks a running Blender without Claude: start the add-on server, run `python3 tests/live_check.py` (stdlib only). It works in a new scene `MCP_Live_Test`, measures poll latency during renders (EEVEE, timers, real socket loop) and writes `report.md` plus images to `~/blender_mcp_live_check/`.
- Keep `mcp` pinned below 2.x: `FastMCP` was renamed in mcp 2 and the server fails to import.

## Custom MCP Tools

### Scene Snapshot & Diff

- **`snapshot_scene`** — Captures the complete scene state: all objects (position, rotation, scale, visibility, render visibility, parenting, constraints, modifiers), the materials used in the scene (Principled BSDF properties), cameras (incl. type, ortho scale, clipping), lights, world background, keyframes, and timeline settings. Stored as baseline for later comparison.
- **`diff_scene`** — Compares current scene against the last snapshot. Returns categorized changes: added/removed objects, modified properties, constraint and modifier changes, material changes, camera/light/world changes, timeline and keyframe changes. Changes of animated properties (e.g. after a frame change) are flagged with `"animated": true`. Does not update the baseline.

### Render Feedback Loop

- **`render_scene`** — Starts a real Blender render (not a viewport screenshot) asynchronously and returns a render ID immediately, so long renders don't hit the socket timeout. Supports EEVEE and Cycles with configurable resolution and samples. Saves/restores all render settings automatically.
- **`poll_render_status`** — Checks the async render started by `render_scene`. Returns the status (`rendering`, `completed`, `failed`, `idle`) and, once complete, the rendered image plus metadata.
- **`review_render`** — Returns the last render or a viewport screenshot together with scene metadata (object count, materials, lights, cameras, timeline). Designed for Claude Vision to analyze composition, lighting, and suggest improvements. Falls back to the result of the last async render if no render path is cached.

- **`list_renders`** — Lists the render history: every finished `render_scene` and `render_animation_preview` is copied into a per-session history (last 20), numbered in order.
- **`compare_renders`** — Shows two renders from the history as before | after | difference (changed pixels in red) and returns the changed fraction, mean/max difference and the bounding box of the change. Defaults compare the previous with the latest render. Different sizes are resampled; a note warns when almost everything changed (framing or background).

### Depsgraph Change Detection

- **`get_change_log`** — Returns automatically collected scene changes. A `depsgraph_update_post` handler runs in the background while the server is active, logging transform, geometry, and shading updates per object. Summary mode (default) aggregates events; detail mode returns raw entries.
- **`clear_change_log`** — Resets the change log. Use after reviewing changes to establish a fresh baseline.

### Animation & Timeline

- **`insert_keyframes`** — Inserts keyframes on any animatable property (`location`, `rotation_euler`, `modifiers["Array"].count`, `["custom_prop"]`, ...) with optional values and per-key interpolation. A `data.` prefix targets the object's data block (`data.energy` for lights, `data.lens` for cameras).
- **`delete_keyframes`** — Deletes keys by property, frame and/or vector component; removes fcurves that end up empty.
- **`get_animation_data`** — Returns fcurves with frame, value and interpolation per key, assigned actions/slots, NLA tracks and drivers for one or all animated objects, plus the timeline.
- **`set_timeline`** — Sets frame range, fps and current frame.
- **`scrub_timeline`** — Jumps to a (fractional) frame and returns the evaluated world transforms (incl. parents and constraints), visibility, camera focal length and light energy of all objects that can move. `restore_frame=True` returns to the previous frame afterwards.
- **`set_visibility`** — Shows or hides objects in renders and/or the viewport.

- **`render_animation_preview`** — Renders up to 25 evenly spaced frames into one contact sheet (grid, each tile labeled with its frame number) so Claude Vision can judge motion at a glance. Async like `render_scene`: fetch the sheet with `poll_render_status`. Frames render one per timer tick, so polls report progress (`frames_done`/`frames_total`) between frames. Render settings and the current frame are restored afterwards.

### NLA (Nonlinear Animation)

- **`push_action_to_nla`** — Pushes the active action down into a new NLA track (like "Push Down" in the UI).
- **`add_nla_strip`** — Places an existing action as a strip at a frame, with repeat, time scale, blend type, extrapolation and blend in/out.
- **`update_nla_strip`** — Moves a strip (keeping its length) or changes its settings; can mute it.
- **`set_nla_track`** — Mutes, solos or renames a track.
- **`remove_nla`** — Removes a strip, or a whole track if no strip is given (the action stays in the file).

All NLA tools take `target="data"` to work on the data block's animation (light, camera, ...).

Fcurve access is slot-aware and works with layered actions (Blender 4.4+/5.x) and legacy actions. Snapshots include keyframes of the object's data block under `data.` paths.

### Scientific Visualization

- **`plot_vector_field`** — Visualizes F(x, y, z), given as three numpy expressions, as arrows (one mesh, colored by magnitude via a viridis ramp on a `magnitude` attribute; linear or log scale, auto-selected for large ranges) and/or streamlines (RK4 along the normalized field, traced both ways from seeds on a grid, given points, or a circle/sphere around a source via `seed_radius`; lines traced twice are removed). Undefined samples (singularities) are skipped. Planar slices via equal min/max bounds.
- **`plot_trajectory`** — Draws trajectories from points or solves dx/dt = F(x, y, z, t) with fixed-step RK4 for one or several initial conditions (each with its own color). Optional `fit_size` scaling and an animation that draws the curve in integration time with a glowing marker.

- **`plot_vector_data`** — Draws precomputed vectors (inline lists, or a `.json`/`.npz` file read by Blender) as arrows colored by magnitude. Magnitudes above a percentile (default 95) are clamped so outliers near sources don't shrink the rest. Use for fields without a simple formula (e.g. computed by an external Python model).
- **`import_scene_data`** — Builds a scene from one JSON document (file or inline) into one collection: boxes with world poses (rotation matrix + center; an optional direction draws an arrow and colors the faces it points out of red, into blue), keyframed poses per frame, per-frame text labels (visible only on their frame), timeline markers, polylines and vector fields. Blender only draws, it never computes the numbers. For static boxes it returns the pose readback error (float32, ~1e-7).

Every element of `import_scene_data` and `plot_vector_data` carries a `status`: `"checked"` (default, opaque) or `"estimate"` (greyed, translucent), so estimated values are never shown like verified ones.

Expressions are compiled with a whitelist of numpy functions (`sin`, `exp`, `sqrt`, `arctan2`, ...), the variables and user `params`; any other name is rejected before evaluation. Re-plotting with the same name replaces the objects and their orphaned materials, which fits the render feedback loop.

### Batch Script Execution

- **`execute_batch_script`** — Runs a long-running Python script in Blender asynchronously (via `bpy.app.timers`) and returns a batch ID immediately. Use instead of `execute_blender_code` for scripts that would exceed the socket timeout (e.g. baking, simulations, heavy geometry generation). Only one batch runs at a time.
- **`poll_batch_status`** — Returns the status of the running batch script and, once complete, its captured stdout or the error.

### Server Behavior

- Starting the add-on server switches the 3D viewport to Material Preview so viewport screenshots show materials.
- Socket timeout for synchronous commands is 180 s; the async tools return within 30 s.
- All commands, async renders and batch scripts run on Blender's main thread (via `bpy.app.timers`). While a render or batch script runs, Blender's UI and all other MCP commands are blocked; a poll sent during that time is answered only once the job has finished (or hits the 180 s timeout, in which case poll again).

## Collaborative Workflow

1. **Snapshot** the scene before making changes (`snapshot_scene`)
2. Make modifications (via `execute_blender_code`, the animation tools, or manually in Blender)
3. **Diff** to see exactly what changed (`diff_scene`) or check the automatic **change log** (`get_change_log`)
4. **Render** the scene (`render_scene`, then `poll_render_status` until complete) and **review** it (`review_render`) — Claude sees the image and provides feedback on composition, lighting, materials. For animations, use `render_animation_preview` to review motion as a contact sheet
5. Iterate: apply improvements, render again, and check the effect with `compare_renders`
6. **Clear** the change log when satisfied (`clear_change_log`)

## Roadmap

- **Scientific visualization** — Done: vector fields and ODE trajectories. Next ideas: parametric surfaces and function graphs, LaTeX labels in 3D, color legends, physics simulations (particles, fluids, rigid bodies)
- **Feedback loop** — Scene checkpoints (save/restore); needs testing in a real Blender because restoring reloads the file
