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

## Custom MCP Tools

### Scene Snapshot & Diff

- **`snapshot_scene`** — Captures the complete scene state: all objects (position, rotation, scale, visibility, parenting), materials (Principled BSDF properties), cameras, lights, keyframes, and timeline settings. Stored as baseline for later comparison.
- **`diff_scene`** — Compares current scene against the last snapshot. Returns categorized changes: added/removed objects, modified properties, material changes, camera/light changes, timeline and keyframe changes. Does not update the baseline.

### Render Feedback Loop

- **`render_scene`** — Triggers a real Blender render (not a viewport screenshot). Supports EEVEE and Cycles with configurable resolution and samples. Saves/restores all render settings automatically.
- **`review_render`** — Returns the last render or a viewport screenshot together with scene metadata (object count, materials, lights, cameras, timeline). Designed for Claude Vision to analyze composition, lighting, and suggest improvements.

### Depsgraph Change Detection

- **`get_change_log`** — Returns automatically collected scene changes. A `depsgraph_update_post` handler runs in the background while the server is active, logging transform, geometry, and shading updates per object. Summary mode (default) aggregates events; detail mode returns raw entries.
- **`clear_change_log`** — Resets the change log. Use after reviewing changes to establish a fresh baseline.

## Collaborative Workflow

1. **Snapshot** the scene before making changes (`snapshot_scene`)
2. Make modifications (via `execute_blender_code` or manually in Blender)
3. **Diff** to see exactly what changed (`diff_scene`) or check the automatic **change log** (`get_change_log`)
4. **Render** the scene (`render_scene`) and **review** it (`review_render`) — Claude sees the image and provides feedback on composition, lighting, materials
5. Iterate: apply improvements, render again, compare
6. **Clear** the change log when satisfied (`clear_change_log`)

## Roadmap

- **Constraints recognition** — Detect and report object constraints (Track To, Follow Path, etc.) in snapshots and diffs
- **Animation workflow** — Tools for keyframe insertion, timeline scrubbing, animation preview rendering, and NLA strip management
- **Scientific visualization** — Support for visualizing magnetic fields, force fields, dynamic physical systems (particle systems, fluid simulations, rigid body dynamics)
