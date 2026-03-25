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
Trigger real Blender renders (EEVEE or Cycles) from Claude and get visual feedback. Claude sees the rendered image alongside scene metadata and can suggest improvements to composition, lighting, and materials.

```
render_scene → review_render → apply feedback → render again
```

### Depsgraph Change Detection
A background handler (`depsgraph_update_post`) continuously logs scene changes while the MCP server runs. No snapshot needed — just ask what changed.

```
clear_change_log → work in Blender → get_change_log → see all changes
```

### Constraints & Modifiers
Snapshots and diffs now capture object constraints (Track To, Follow Path, Copy Location, etc.) and modifiers (Subdivision, Array, Mirror, Solidify, etc.) with type-specific parameters. Essential for animation workflows where camera paths are driven by constraints.

## Collaborative Workflow

1. **Snapshot** the scene before making changes (`snapshot_scene`)
2. **Modify** the scene — via `execute_blender_code` or manually in Blender
3. **Detect changes** with `diff_scene` (explicit) or `get_change_log` (automatic)
4. **Render** the scene (`render_scene`) and **review** it (`review_render`)
5. **Iterate** — Claude analyzes the render and suggests improvements
6. **Clear** the change log when satisfied (`clear_change_log`)

## MCP Tools

| Tool | Description |
|------|-------------|
| `snapshot_scene` | Capture complete scene state as baseline |
| `diff_scene` | Compare current state against last snapshot |
| `get_change_log` | Get automatically collected change events |
| `clear_change_log` | Reset the change log |
| `render_scene` | Render with EEVEE/Cycles (configurable resolution, samples) |
| `review_render` | Get last render or viewport screenshot with scene metadata |
| `get_scene_info` | Quick scene overview (object count, materials) |
| `get_object_info` | Detailed info for a single object (incl. constraints, modifiers) |
| `get_viewport_screenshot` | Capture the 3D viewport |
| `execute_blender_code` | Run arbitrary Python in Blender |

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

- **Animation workflow** — Keyframe insertion, timeline scrubbing, animation preview rendering, NLA strip management
- **Scientific visualization** — Magnetic fields, force fields, particle systems, fluid simulations, rigid body dynamics
- **Cowork integration** — Multi-user collaborative sessions with shared scene state

## Stack

- Python, bpy (Blender Python API)
- Anthropic Claude with Vision
- MCP (Model Context Protocol)
- FastMCP server framework

## Credits

- Original project: [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp)
- Fork with collaborative extensions: [drsiegmund/blender-mcp](https://github.com/drsiegmund/blender-mcp)
