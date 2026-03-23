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
