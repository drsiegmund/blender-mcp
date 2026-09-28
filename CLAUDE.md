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

- **`snapshot_scene`** — Captures the complete scene state: all objects (position, rotation, scale, visibility, parenting, constraints, modifiers), materials (Principled BSDF properties), cameras, lights, keyframes, and timeline settings. Stored as baseline for later comparison.
- **`diff_scene`** — Compares current scene against the last snapshot. Returns categorized changes: added/removed objects, modified properties, constraint and modifier changes, material changes, camera/light changes, timeline and keyframe changes. Does not update the baseline.

### Render Feedback Loop

- **`render_scene`** — Starts a real Blender render (not a viewport screenshot) asynchronously and returns a render ID immediately, so long renders don't hit the socket timeout. Supports EEVEE and Cycles with configurable resolution and samples. Saves/restores all render settings automatically.
- **`poll_render_status`** — Checks the async render started by `render_scene`. Returns the status (`rendering`, `completed`, `failed`, `idle`) and, once complete, the rendered image plus metadata.
- **`review_render`** — Returns the last render or a viewport screenshot together with scene metadata (object count, materials, lights, cameras, timeline). Designed for Claude Vision to analyze composition, lighting, and suggest improvements. Falls back to the result of the last async render if no render path is cached.

### Depsgraph Change Detection

- **`get_change_log`** — Returns automatically collected scene changes. A `depsgraph_update_post` handler runs in the background while the server is active, logging transform, geometry, and shading updates per object. Summary mode (default) aggregates events; detail mode returns raw entries.
- **`clear_change_log`** — Resets the change log. Use after reviewing changes to establish a fresh baseline.

### Batch Script Execution

- **`execute_batch_script`** — Runs a long-running Python script in Blender asynchronously (via `bpy.app.timers`) and returns a batch ID immediately. Use instead of `execute_blender_code` for scripts that would exceed the socket timeout (e.g. baking, simulations, heavy geometry generation). Only one batch runs at a time.
- **`poll_batch_status`** — Returns the status of the running batch script and, once complete, its captured stdout or the error.

### Server Behavior

- Starting the add-on server switches the 3D viewport to Material Preview so viewport screenshots show materials.
- Socket timeout for synchronous commands is 180 s; the async tools return within 30 s.
- All commands, async renders and batch scripts run on Blender's main thread (via `bpy.app.timers`). While a render or batch script runs, Blender's UI and all other MCP commands are blocked; a poll sent during that time is answered only once the job has finished (or hits the 180 s timeout, in which case poll again).

## Collaborative Workflow

1. **Snapshot** the scene before making changes (`snapshot_scene`)
2. Make modifications (via `execute_blender_code` or manually in Blender)
3. **Diff** to see exactly what changed (`diff_scene`) or check the automatic **change log** (`get_change_log`)
4. **Render** the scene (`render_scene`, then `poll_render_status` until complete) and **review** it (`review_render`) — Claude sees the image and provides feedback on composition, lighting, materials
5. Iterate: apply improvements, render again, compare
6. **Clear** the change log when satisfied (`clear_change_log`)

## Roadmap

- **Animation workflow** — Tools for keyframe insertion, timeline scrubbing, animation preview rendering, and NLA strip management
- **Scientific visualization** — Support for visualizing magnetic fields, force fields, dynamic physical systems (particle systems, fluid simulations, rigid body dynamics)
