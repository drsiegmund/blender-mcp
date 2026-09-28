# BlenderMCP — Collaborative AI-Assisted 3D Design

A fork of [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp) extended with tools for collaborative 3D workflows between Blender and Claude.

The core idea: Claude can see your scene, understand what changed, render it, and give you concrete visual feedback — all through MCP (Model Context Protocol).

## What's New

### Scene Snapshot & Diff
Take a complete snapshot of your Blender scene — all objects, materials, constraints, modifiers, keyframes, cameras, lights, and timeline settings. Compare against a previous snapshot to see exactly what changed: added/removed objects, moved geometry, modified materials, constraint parameter changes.

```
snapshot_scene → make changes → diff_scene → see what changed
```

### Render Feedback Loop
Trigger real Blender renders (EEVEE or Cycles) from Claude and get visual feedback. `render_scene` returns immediately; the result is fetched with `poll_render_status`. Claude sees the rendered image alongside scene metadata and can suggest improvements to composition, lighting, and materials.

```
render_scene → poll_render_status → review_render → apply feedback → render again → compare_renders
```

`compare_renders` puts the previous and the latest render side by side with a difference image, so each iteration shows what actually changed.

### Depsgraph Change Detection
A background handler (`depsgraph_update_post`) continuously logs scene changes while the MCP server runs. No snapshot needed — just ask what changed.

```
clear_change_log → work in Blender → get_change_log → see all changes
```

### Animation & Timeline
Insert and delete keyframes on any animatable property (including light energy and camera focal length via `data.` paths), inspect fcurves, NLA tracks and drivers, set the frame range and fps, and scrub to any frame to see where everything is.

```
insert_keyframes → set_timeline → scrub_timeline → render_animation_preview
```

`render_animation_preview` renders evenly spaced frames into one labeled contact sheet, so Claude can judge the motion in a single image. NLA tools (`push_action_to_nla`, `add_nla_strip`, `update_nla_strip`, `set_nla_track`, `remove_nla`) layer and sequence actions.

### Scientific Visualization
Plot vector fields (arrows colored by magnitude, field lines) and ODE trajectories straight from formulas — e.g. the field lines of a magnetic dipole or two diverging trajectories of the Lorenz attractor, optionally animated.

```
plot_vector_field(field=["-y", "x", "0"], ...)  →  render_scene  →  review_render
plot_trajectory(ode=["sigma*(y-x)", "x*(rho-z)-y", "x*y-beta*z"], animate=True, ...)
```

### Constraints & Modifiers
Snapshots and diffs now capture object constraints (Track To, Follow Path, Copy Location, etc.) and modifiers (Subdivision, Array, Mirror, Solidify, etc.) with type-specific parameters. Essential for animation workflows where camera paths are driven by constraints.

## Collaborative Workflow

1. **Snapshot** the scene before making changes (`snapshot_scene`)
2. **Modify** the scene — via `execute_blender_code` or manually in Blender
3. **Detect changes** with `diff_scene` (explicit) or `get_change_log` (automatic)
4. **Render** the scene (`render_scene`, then `poll_render_status`) and **review** it (`review_render`)
5. **Iterate** — Claude analyzes the render and suggests improvements
6. **Clear** the change log when satisfied (`clear_change_log`)

## MCP Tools

| Tool | Description |
|------|-------------|
| `snapshot_scene` | Capture complete scene state as baseline |
| `diff_scene` | Compare current state against last snapshot |
| `get_change_log` | Get automatically collected change events |
| `clear_change_log` | Reset the change log |
| `render_scene` | Start an async render with EEVEE/Cycles (configurable resolution, samples) |
| `poll_render_status` | Check the async render; returns the image when complete |
| `list_renders` | Numbered history of the last 20 renders |
| `compare_renders` | Before / after / difference image with change statistics |
| `review_render` | Get last render or viewport screenshot with scene metadata |
| `insert_keyframes` | Insert keyframes with values and interpolation |
| `delete_keyframes` | Delete keyframes by property, frame or component |
| `get_animation_data` | Fcurves, keyframe values, actions, NLA tracks, drivers |
| `set_timeline` | Set frame range, fps and current frame |
| `scrub_timeline` | Jump to a frame and get the evaluated object states |
| `render_animation_preview` | Render sampled frames into a labeled contact sheet (async) |
| `push_action_to_nla` | Push the active action down into an NLA track |
| `add_nla_strip` | Place an action as NLA strip (repeat, scale, blend) |
| `update_nla_strip` | Move or change an NLA strip |
| `set_nla_track` | Mute, solo or rename an NLA track |
| `remove_nla` | Remove an NLA strip or track |
| `plot_vector_field` | Vector field as colored arrows and/or streamlines |
| `plot_trajectory` | Trajectories from points or an ODE (RK4), optionally animated |
| `get_scene_info` | Quick scene overview (object count, materials) |
| `get_object_info` | Detailed info for a single object (incl. constraints, modifiers) |
| `get_viewport_screenshot` | Capture the 3D viewport |
| `execute_blender_code` | Run arbitrary Python in Blender |
| `execute_batch_script` | Run a long Python script asynchronously |
| `poll_batch_status` | Check the async batch script; returns its output when complete |

## Installation

### 1. Blender Addon

- Open Blender → Edit → Preferences → Add-ons
- Click "Install from Disk" and select `addon.py`
- Enable "BlenderMCP" in the add-on list
- In the 3D Viewport sidebar (N), open the BlenderMCP tab and click "Start Server"

### 2. MCP Server with Claude Code

```bash
# Clone the fork
git clone https://github.com/drsiegmund/blender-mcp.git
cd blender-mcp

# Add the local MCP server to Claude Code
claude mcp add blender-mcp -- uv run --directory /path/to/blender-mcp python -m blender_mcp.server

# Start Claude Code
claude
```

Make sure the Blender addon server is running before starting Claude Code.

### 3. Verify

In Claude Code, ask Claude to run `get_scene_info` — if it returns your scene data, everything is connected.

## Roadmap

- **Scientific visualization** — Parametric surfaces, LaTeX labels, color legends, physics simulations (particles, fluids, rigid bodies)
- **Feedback loop** — Scene checkpoints (save/restore)
- **Cowork integration** — Multi-user collaborative sessions with shared scene state

## Stack

- Python, bpy (Blender Python API)
- Anthropic Claude with Vision
- MCP (Model Context Protocol)
- FastMCP server framework

## Credits

- Original project: [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp)
- Fork with collaborative extensions: [drsiegmund/blender-mcp](https://github.com/drsiegmund/blender-mcp)
