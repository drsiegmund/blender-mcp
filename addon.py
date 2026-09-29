# Code created by Siddharth Ahuja: www.github.com/ahujasid © 2025

import re
import bpy
import mathutils
import json
import threading
import socket
import time
import requests
import tempfile
import traceback
import os
import shutil
import zipfile
from bpy.props import IntProperty, BoolProperty
import io
from datetime import datetime
import hashlib, hmac, base64
import os.path as osp
from contextlib import redirect_stdout, suppress

bl_info = {
    "name": "Blender MCP",
    "author": "BlenderMCP",
    "version": (1, 2),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > BlenderMCP",
    "description": "Connect Blender to Claude via MCP",
    "category": "Interface",
}

RODIN_FREE_TRIAL_KEY = "k9TcfFoEhNd9cCPP2guHAHHHkctZHIRhZDywZ1euGUXwihbYLpOjQhofby80NJez"

# Add User-Agent as required by Poly Haven API
REQ_HEADERS = requests.utils.default_headers()
REQ_HEADERS.update({"User-Agent": "blender-mcp"})

class BlenderMCPServer:
    def __init__(self, host='localhost', port=9876):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.server_thread = None
        self._last_snapshot = None
        self._last_render_path = None
        self._change_log = []
        self._change_log_enabled = False
        self._depsgraph_handler = None
        self._render_status = None
        self._render_result = None
        self._render_id = None
        self._batch_status = None
        self._batch_result = None
        self._batch_id = None
        self._preview_job = None
        self._render_history = []

    def _make_depsgraph_handler(self):
        """Create a closure that captures self for use as a bpy.app.handlers callback."""
        def handler(scene):
            self._on_depsgraph_update(scene)
        return handler

    def start(self):
        if self.running:
            print("Server is already running")
            return

        self.running = True

        try:
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)

            # Start server thread
            self.server_thread = threading.Thread(target=self._server_loop)
            self.server_thread.daemon = True
            self.server_thread.start()

            # Register depsgraph change handler
            self._depsgraph_handler = self._make_depsgraph_handler()
            bpy.app.handlers.depsgraph_update_post.append(self._depsgraph_handler)
            self._change_log_enabled = True

            # Set viewport to Material Preview for better visual feedback
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.shading.type = 'MATERIAL'
                            break
                    break

            print(f"BlenderMCP server started on {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to start server: {str(e)}")
            self.stop()

    def stop(self):
        # Disable change log and remove depsgraph handler
        self._change_log_enabled = False
        if self._depsgraph_handler and self._depsgraph_handler in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(self._depsgraph_handler)
            self._depsgraph_handler = None

        self.running = False

        # Close socket
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

        # Wait for thread to finish
        if self.server_thread:
            try:
                if self.server_thread.is_alive():
                    self.server_thread.join(timeout=1.0)
            except:
                pass
            self.server_thread = None

        print("BlenderMCP server stopped")

    def _server_loop(self):
        """Main server loop in a separate thread"""
        print("Server thread started")
        self.socket.settimeout(1.0)  # Timeout to allow for stopping

        while self.running:
            try:
                # Accept new connection
                try:
                    client, address = self.socket.accept()
                    print(f"Connected to client: {address}")

                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except socket.timeout:
                    # Just check running condition
                    continue
                except Exception as e:
                    print(f"Error accepting connection: {str(e)}")
                    time.sleep(0.5)
            except Exception as e:
                print(f"Error in server loop: {str(e)}")
                if not self.running:
                    break
                time.sleep(0.5)

        print("Server thread stopped")

    def _handle_client(self, client):
        """Handle connected client"""
        print("Client handler started")
        client.settimeout(None)  # No timeout
        buffer = b''

        try:
            while self.running:
                # Receive data
                try:
                    data = client.recv(8192)
                    if not data:
                        print("Client disconnected")
                        break

                    buffer += data
                    try:
                        # Try to parse command
                        command = json.loads(buffer.decode('utf-8'))
                        buffer = b''

                        # Execute command in Blender's main thread
                        def execute_wrapper():
                            try:
                                response = self.execute_command(command)
                                response_json = json.dumps(response)
                                try:
                                    client.sendall(response_json.encode('utf-8'))
                                except:
                                    print("Failed to send response - client disconnected")
                            except Exception as e:
                                print(f"Error executing command: {str(e)}")
                                traceback.print_exc()
                                try:
                                    error_response = {
                                        "status": "error",
                                        "message": str(e)
                                    }
                                    client.sendall(json.dumps(error_response).encode('utf-8'))
                                except:
                                    pass
                            return None

                        # Schedule execution in main thread
                        bpy.app.timers.register(execute_wrapper, first_interval=0.0)
                    except json.JSONDecodeError:
                        # Incomplete data, wait for more
                        pass
                except Exception as e:
                    print(f"Error receiving data: {str(e)}")
                    break
        except Exception as e:
            print(f"Error in client handler: {str(e)}")
        finally:
            try:
                client.close()
            except:
                pass
            print("Client handler stopped")

    def execute_command(self, command):
        """Execute a command in the main Blender thread"""
        try:
            return self._execute_command_internal(command)

        except Exception as e:
            print(f"Error executing command: {str(e)}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _execute_command_internal(self, command):
        """Internal command execution with proper context"""
        cmd_type = command.get("type")
        params = command.get("params", {})

        # Add a handler for checking PolyHaven status
        if cmd_type == "get_polyhaven_status":
            return {"status": "success", "result": self.get_polyhaven_status()}

        # Base handlers that are always available
        handlers = {
            "get_scene_info": self.get_scene_info,
            "get_object_info": self.get_object_info,
            "snapshot_scene": self.snapshot_scene,
            "diff_scene": self.diff_scene,
            "get_change_log": self.get_change_log,
            "clear_change_log": self.clear_change_log,
            "render_scene": self.render_scene,
            "poll_render_status": self.poll_render_status,
            "render_animation_preview": self.render_animation_preview,
            "list_renders": self.list_renders,
            "compare_renders": self.compare_renders,
            "execute_batch_script": self.execute_batch_script,
            "poll_batch_status": self.poll_batch_status,
            "insert_keyframes": self.insert_keyframes,
            "delete_keyframes": self.delete_keyframes,
            "get_animation_data": self.get_animation_data,
            "set_timeline": self.set_timeline,
            "scrub_timeline": self.scrub_timeline,
            "push_action_to_nla": self.push_action_to_nla,
            "add_nla_strip": self.add_nla_strip,
            "update_nla_strip": self.update_nla_strip,
            "remove_nla": self.remove_nla,
            "set_nla_track": self.set_nla_track,
            "plot_vector_field": self.plot_vector_field,
            "plot_trajectory": self.plot_trajectory,
            "get_viewport_screenshot": self.get_viewport_screenshot,
            "execute_code": self.execute_code,
            "get_telemetry_consent": self.get_telemetry_consent,
            "get_polyhaven_status": self.get_polyhaven_status,
            "get_hyper3d_status": self.get_hyper3d_status,
            "get_sketchfab_status": self.get_sketchfab_status,
            "get_hunyuan3d_status": self.get_hunyuan3d_status,
        }

        # Add Polyhaven handlers only if enabled
        if bpy.context.scene.blendermcp_use_polyhaven:
            polyhaven_handlers = {
                "get_polyhaven_categories": self.get_polyhaven_categories,
                "search_polyhaven_assets": self.search_polyhaven_assets,
                "download_polyhaven_asset": self.download_polyhaven_asset,
                "set_texture": self.set_texture,
            }
            handlers.update(polyhaven_handlers)

        # Add Hyper3d handlers only if enabled
        if bpy.context.scene.blendermcp_use_hyper3d:
            polyhaven_handlers = {
                "create_rodin_job": self.create_rodin_job,
                "poll_rodin_job_status": self.poll_rodin_job_status,
                "import_generated_asset": self.import_generated_asset,
            }
            handlers.update(polyhaven_handlers)

        # Add Sketchfab handlers only if enabled
        if bpy.context.scene.blendermcp_use_sketchfab:
            sketchfab_handlers = {
                "search_sketchfab_models": self.search_sketchfab_models,
                "get_sketchfab_model_preview": self.get_sketchfab_model_preview,
                "download_sketchfab_model": self.download_sketchfab_model,
            }
            handlers.update(sketchfab_handlers)
        
        # Add Hunyuan3d handlers only if enabled
        if bpy.context.scene.blendermcp_use_hunyuan3d:
            hunyuan_handlers = {
                "create_hunyuan_job": self.create_hunyuan_job,
                "poll_hunyuan_job_status": self.poll_hunyuan_job_status,
                "import_generated_asset_hunyuan": self.import_generated_asset_hunyuan
            }
            handlers.update(hunyuan_handlers)

        handler = handlers.get(cmd_type)
        if handler:
            try:
                print(f"Executing handler for {cmd_type}")
                result = handler(**params)
                print(f"Handler execution complete")
                return {"status": "success", "result": result}
            except Exception as e:
                print(f"Error in handler: {str(e)}")
                traceback.print_exc()
                return {"status": "error", "message": str(e)}
        else:
            return {"status": "error", "message": f"Unknown command type: {cmd_type}"}



    def get_scene_info(self):
        """Get information about the current Blender scene"""
        try:
            print("Getting scene info...")
            # Simplify the scene info to reduce data size
            scene_info = {
                "name": bpy.context.scene.name,
                "object_count": len(bpy.context.scene.objects),
                "objects": [],
                "materials_count": len(bpy.data.materials),
            }

            # Collect minimal object information (limit to first 10 objects)
            for i, obj in enumerate(bpy.context.scene.objects):
                if i >= 10:  # Reduced from 20 to 10
                    break

                obj_info = {
                    "name": obj.name,
                    "type": obj.type,
                    # Only include basic location data
                    "location": [round(float(obj.location.x), 2),
                                round(float(obj.location.y), 2),
                                round(float(obj.location.z), 2)],
                }
                scene_info["objects"].append(obj_info)

            print(f"Scene info collected: {len(scene_info['objects'])} objects")
            return scene_info
        except Exception as e:
            print(f"Error in get_scene_info: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}

    @staticmethod
    def _get_aabb(obj):
        """ Returns the world-space axis-aligned bounding box (AABB) of an object. """
        if obj.type != 'MESH':
            raise TypeError("Object must be a mesh")

        # Get the bounding box corners in local space
        local_bbox_corners = [mathutils.Vector(corner) for corner in obj.bound_box]

        # Convert to world coordinates
        world_bbox_corners = [obj.matrix_world @ corner for corner in local_bbox_corners]

        # Compute axis-aligned min/max coordinates
        min_corner = mathutils.Vector(map(min, zip(*world_bbox_corners)))
        max_corner = mathutils.Vector(map(max, zip(*world_bbox_corners)))

        return [
            [*min_corner], [*max_corner]
        ]



    def get_object_info(self, name):
        """Get detailed information about a specific object"""
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object not found: {name}")

        # Basic object info
        obj_info = {
            "name": obj.name,
            "type": obj.type,
            "location": [obj.location.x, obj.location.y, obj.location.z],
            "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
            "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            "visible": obj.visible_get(),
            "materials": [],
        }

        if obj.type == "MESH":
            bounding_box = self._get_aabb(obj)
            obj_info["world_bounding_box"] = bounding_box

        # Add material slots
        for slot in obj.material_slots:
            if slot.material:
                obj_info["materials"].append(slot.material.name)

        # Add mesh data if applicable
        if obj.type == 'MESH' and obj.data:
            mesh = obj.data
            obj_info["mesh"] = {
                "vertices": len(mesh.vertices),
                "edges": len(mesh.edges),
                "polygons": len(mesh.polygons),
            }

        obj_info["constraints"] = self._get_constraints(obj)
        obj_info["modifiers"] = self._get_modifiers(obj)

        return obj_info

    def _round_vec(self, vec, decimals=4):
        return [round(float(v), decimals) for v in vec]

    def _get_engine_id(self, engine_name):
        """Map engine name to Blender's internal engine identifier."""
        if engine_name.upper() == "EEVEE":
            # Check which EEVEE identifier is available in this Blender version
            engine_items = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
            if "BLENDER_EEVEE_NEXT" in engine_items:
                return "BLENDER_EEVEE_NEXT"
            return "BLENDER_EEVEE"
        return "CYCLES"

    def _get_fcurve_collection(self, id_block):
        """Get the fcurve collection animating an ID block (object, light, camera, ...).

        Handles layered actions with slots (Blender 4.4+) and legacy actions.
        Returns None if the ID has no action.
        """
        anim = getattr(id_block, "animation_data", None)
        if not anim or not anim.action:
            return None
        action = anim.action
        if getattr(action, "is_action_layered", False):
            slot = getattr(anim, "action_slot", None)
            for layer in action.layers:
                for strip in layer.strips:
                    if slot is not None:
                        channelbag = strip.channelbag(slot)
                    else:
                        channelbag = strip.channelbags[0] if len(strip.channelbags) else None
                    if channelbag:
                        return channelbag.fcurves
            return None
        return getattr(action, "fcurves", None)

    def _get_fcurves(self, id_block):
        """Get the fcurves animating an ID block as a list."""
        fcurves = self._get_fcurve_collection(id_block)
        return list(fcurves) if fcurves is not None else []

    def _get_anim_targets(self, obj):
        """Yield (id_block, path_prefix) for an object and its data block."""
        yield obj, ""
        if obj.data is not None and hasattr(obj.data, "animation_data"):
            yield obj.data, "data."

    def _get_keyframes(self, obj):
        """Extract keyframe frames for an object and its data, grouped by data_path."""
        keyframes = {}
        for target, prefix in self._get_anim_targets(obj):
            for fc in self._get_fcurves(target):
                path = prefix + fc.data_path
                frames = sorted(set(round(kf.co[0]) for kf in fc.keyframe_points))
                keyframes[path] = sorted(set(keyframes.get(path, []) + frames))
        return keyframes

    def _get_material_props(self, mat):
        """Extract Principled BSDF properties from a material."""
        props = {"base_color": None, "roughness": None, "metallic": None, "transmission": None}
        # Blender 5.0+ always uses nodes and deprecates use_nodes
        if not mat.node_tree or (bpy.app.version < (5, 0, 0) and not mat.use_nodes):
            return props
        for node in mat.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                props["base_color"] = self._round_vec(node.inputs["Base Color"].default_value)
                props["roughness"] = round(float(node.inputs["Roughness"].default_value), 4)
                props["metallic"] = round(float(node.inputs["Metallic"].default_value), 4)
                transmission_input = node.inputs.get("Transmission Weight") or node.inputs.get("Transmission")
                if transmission_input:
                    props["transmission"] = round(float(transmission_input.default_value), 4)
                break
        return props

    def _get_constraints(self, obj):
        """Extract constraints from an object."""
        constraints = []
        for c in obj.constraints:
            data = {
                "name": c.name,
                "type": c.type,
                "enabled": not c.mute,
                "target": c.target.name if hasattr(c, 'target') and c.target else None,
                "params": {},
            }
            if hasattr(c, 'influence'):
                data["params"]["influence"] = round(float(c.influence), 4)
            if c.type == 'TRACK_TO':
                data["params"]["track_axis"] = c.track_axis
                data["params"]["up_axis"] = c.up_axis
            elif c.type == 'FOLLOW_PATH':
                data["params"]["offset"] = round(float(c.offset), 4)
                data["params"]["use_fixed_location"] = c.use_fixed_location
                data["params"]["forward_axis"] = c.forward_axis
                data["params"]["up_axis"] = c.up_axis
            elif c.type in ('COPY_LOCATION', 'COPY_ROTATION', 'COPY_SCALE'):
                data["params"]["use_x"] = c.use_x
                data["params"]["use_y"] = c.use_y
                data["params"]["use_z"] = c.use_z
            elif c.type == 'DAMPED_TRACK':
                data["params"]["track_axis"] = c.track_axis
            elif c.type == 'LOCKED_TRACK':
                data["params"]["track_axis"] = c.track_axis
                data["params"]["lock_axis"] = c.lock_axis
            constraints.append(data)
        return constraints

    def _get_modifiers(self, obj):
        """Extract modifiers from an object."""
        modifiers = []
        for m in obj.modifiers:
            data = {
                "name": m.name,
                "type": m.type,
                "show_render": m.show_render,
                "show_viewport": m.show_viewport,
                "params": {},
            }
            if m.type == 'SUBSURF':
                data["params"]["levels"] = m.levels
                data["params"]["render_levels"] = m.render_levels
            elif m.type == 'ARRAY':
                data["params"]["count"] = m.count
                data["params"]["use_relative_offset"] = m.use_relative_offset
                data["params"]["relative_offset_displace"] = self._round_vec(m.relative_offset_displace)
            elif m.type == 'MIRROR':
                data["params"]["use_axis"] = [m.use_axis[0], m.use_axis[1], m.use_axis[2]]
            elif m.type == 'SOLIDIFY':
                data["params"]["thickness"] = round(float(m.thickness), 4)
                data["params"]["offset"] = round(float(m.offset), 4)
            elif m.type == 'BEVEL':
                data["params"]["width"] = round(float(m.width), 4)
                data["params"]["segments"] = m.segments
            elif m.type == 'BOOLEAN':
                data["params"]["operation"] = m.operation
                data["params"]["object"] = m.object.name if m.object else None
            elif m.type == 'SHRINKWRAP':
                data["params"]["target"] = m.target.name if m.target else None
                data["params"]["wrap_method"] = m.wrap_method
            modifiers.append(data)
        return modifiers

    def _build_snapshot(self):
        """Build a complete snapshot of the current scene state."""
        from datetime import datetime
        scene = bpy.context.scene

        snapshot = {
            "timestamp": datetime.now().isoformat(timespec='seconds'),
            "scene_name": scene.name,
            "timeline": {
                "frame_start": scene.frame_start,
                "frame_end": scene.frame_end,
                "fps": scene.render.fps,
                "current_frame": scene.frame_current,
            },
            "objects": {},
            "materials": {},
            "cameras": {},
            "lights": {},
        }

        for obj in scene.objects:
            obj_data = {
                "type": obj.type,
                "location": self._round_vec(obj.location),
                "rotation": self._round_vec(obj.rotation_euler),
                "scale": self._round_vec(obj.scale),
                "visible": obj.visible_get(),
                "parent": obj.parent.name if obj.parent else None,
                "children": [c.name for c in obj.children],
                "materials": [slot.material.name for slot in obj.material_slots if slot.material],
                "keyframes": self._get_keyframes(obj),
                "constraints": self._get_constraints(obj),
                "modifiers": self._get_modifiers(obj),
            }
            snapshot["objects"][obj.name] = obj_data

            if obj.type == 'CAMERA' and obj.data:
                snapshot["cameras"][obj.name] = {
                    "location": self._round_vec(obj.location),
                    "rotation": self._round_vec(obj.rotation_euler),
                    "focal_length": round(float(obj.data.lens), 4),
                    "sensor_width": round(float(obj.data.sensor_width), 4),
                    "sensor_height": round(float(obj.data.sensor_height), 4),
                }

            if obj.type == 'LIGHT' and obj.data:
                snapshot["lights"][obj.name] = {
                    "location": self._round_vec(obj.location),
                    "rotation": self._round_vec(obj.rotation_euler),
                    "light_type": obj.data.type,
                    "color": self._round_vec(obj.data.color),
                    "energy": round(float(obj.data.energy), 4),
                }

        for mat in bpy.data.materials:
            snapshot["materials"][mat.name] = self._get_material_props(mat)

        return snapshot

    def snapshot_scene(self):
        """Take a snapshot of the current scene and store it as baseline."""
        try:
            self._last_snapshot = self._build_snapshot()
            return self._last_snapshot
        except Exception as e:
            print(f"Error in snapshot_scene: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}

    def _diff_dicts(self, old, new, keys):
        """Compare specific keys between two dicts, return changed keys."""
        changes = {}
        for k in keys:
            old_val = old.get(k)
            new_val = new.get(k)
            if old_val != new_val:
                changes[k] = {"old": old_val, "new": new_val}
        return changes

    def diff_scene(self):
        """Compare current scene state against the last snapshot."""
        if self._last_snapshot is None:
            return {"error": "No snapshot taken yet. Call snapshot_scene first."}

        try:
            current = self._build_snapshot()
            old = self._last_snapshot
            diff = {
                "has_changes": False,
                "summary": "",
                "added_objects": [],
                "removed_objects": [],
                "modified_objects": {},
                "added_materials": [],
                "removed_materials": [],
                "modified_materials": {},
                "camera_changes": {},
                "light_changes": {},
                "timeline_changes": {},
                "keyframe_changes": {},
            }

            # Objects
            old_objs = set(old["objects"].keys())
            new_objs = set(current["objects"].keys())
            diff["added_objects"] = sorted(new_objs - old_objs)
            diff["removed_objects"] = sorted(old_objs - new_objs)

            obj_props = ["location", "rotation", "scale", "visible", "parent", "materials", "constraints", "modifiers"]
            for name in old_objs & new_objs:
                changes = self._diff_dicts(old["objects"][name], current["objects"][name], obj_props)
                if changes:
                    diff["modified_objects"][name] = changes

            # Materials
            old_mats = set(old["materials"].keys())
            new_mats = set(current["materials"].keys())
            diff["added_materials"] = sorted(new_mats - old_mats)
            diff["removed_materials"] = sorted(old_mats - new_mats)

            mat_props = ["base_color", "roughness", "metallic", "transmission"]
            for name in old_mats & new_mats:
                changes = self._diff_dicts(old["materials"][name], current["materials"][name], mat_props)
                if changes:
                    diff["modified_materials"][name] = changes

            # Cameras
            cam_props = ["location", "rotation", "focal_length", "sensor_width", "sensor_height"]
            for name in set(old["cameras"].keys()) & set(current["cameras"].keys()):
                changes = self._diff_dicts(old["cameras"][name], current["cameras"][name], cam_props)
                if changes:
                    diff["camera_changes"][name] = changes

            # Lights
            light_props = ["location", "rotation", "light_type", "color", "energy"]
            for name in set(old["lights"].keys()) & set(current["lights"].keys()):
                changes = self._diff_dicts(old["lights"][name], current["lights"][name], light_props)
                if changes:
                    diff["light_changes"][name] = changes

            # Timeline
            timeline_props = ["frame_start", "frame_end", "fps"]
            diff["timeline_changes"] = self._diff_dicts(old["timeline"], current["timeline"], timeline_props)

            # Keyframes
            for name in old_objs & new_objs:
                old_kf = old["objects"][name].get("keyframes", {})
                new_kf = current["objects"][name].get("keyframes", {})
                if old_kf != new_kf:
                    kf_changes = {}
                    all_paths = set(old_kf.keys()) | set(new_kf.keys())
                    for path in all_paths:
                        if old_kf.get(path) != new_kf.get(path):
                            kf_changes[path] = {"old": old_kf.get(path, []), "new": new_kf.get(path, [])}
                    if kf_changes:
                        diff["keyframe_changes"][name] = kf_changes

            # Summary
            parts = []
            if diff["added_objects"]:
                parts.append(f"{len(diff['added_objects'])} added")
            if diff["removed_objects"]:
                parts.append(f"{len(diff['removed_objects'])} removed")
            if diff["modified_objects"]:
                parts.append(f"{len(diff['modified_objects'])} modified")
            if diff["added_materials"] or diff["removed_materials"] or diff["modified_materials"]:
                mat_count = len(diff["added_materials"]) + len(diff["removed_materials"]) + len(diff["modified_materials"])
                parts.append(f"{mat_count} material(s) changed")
            if diff["camera_changes"]:
                parts.append("camera changed")
            if diff["light_changes"]:
                parts.append("lights changed")
            if diff["timeline_changes"]:
                parts.append("timeline changed")
            if diff["keyframe_changes"]:
                parts.append("keyframes changed")

            diff["has_changes"] = bool(parts)
            diff["summary"] = ", ".join(parts) if parts else "No changes detected"

            return diff
        except Exception as e:
            print(f"Error in diff_scene: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}

    def _on_depsgraph_update(self, scene):
        """Callback for depsgraph_update_post, logs scene changes."""
        if not self._change_log_enabled:
            return
        try:
            depsgraph = bpy.context.view_layer.depsgraph
            from datetime import datetime
            timestamp = datetime.now().isoformat(timespec='seconds')
            for update in depsgraph.updates:
                entry = {
                    "timestamp": timestamp,
                    "id_name": update.id.name,
                    "id_type": type(update.id).__name__,
                    "is_updated_transform": update.is_updated_transform,
                    "is_updated_geometry": update.is_updated_geometry,
                    "is_updated_shading": update.is_updated_shading,
                }
                self._change_log.append(entry)
            if len(self._change_log) > 1000:
                self._change_log = self._change_log[-1000:]
        except Exception:
            pass  # Never crash Blender from a handler

    def get_change_log(self, since=None, summary=True):
        """Return the accumulated change log, optionally filtered and summarized."""
        try:
            entries = self._change_log
            if since:
                entries = [e for e in entries if e["timestamp"] >= since]

            if not summary:
                return {"entry_count": len(entries), "entries": entries}

            # Summary mode: group by object name
            changed_objects = {}
            for e in entries:
                name = e["id_name"]
                if name not in changed_objects:
                    changed_objects[name] = {"type": e["id_type"], "transforms": 0, "geometry": 0, "shading": 0}
                if e["is_updated_transform"]:
                    changed_objects[name]["transforms"] += 1
                if e["is_updated_geometry"]:
                    changed_objects[name]["geometry"] += 1
                if e["is_updated_shading"]:
                    changed_objects[name]["shading"] += 1

            return {
                "entry_count": len(entries),
                "changed_objects": changed_objects,
                "summary": f"{len(changed_objects)} objects changed ({len(entries)} events)",
            }
        except Exception as e:
            return {"error": str(e)}

    def clear_change_log(self):
        """Clear the change log and return the number of cleared entries."""
        count = len(self._change_log)
        self._change_log = []
        return {"cleared": count}

    def get_viewport_screenshot(self, max_size=800, filepath=None, format="png"):
        """
        Capture a screenshot of the current 3D viewport and save it to the specified path.

        Parameters:
        - max_size: Maximum size in pixels for the largest dimension of the image
        - filepath: Path where to save the screenshot file
        - format: Image format (png, jpg, etc.)

        Returns success/error status
        """
        try:
            if not filepath:
                return {"error": "No filepath provided"}

            # Find the active 3D viewport
            area = None
            for a in bpy.context.screen.areas:
                if a.type == 'VIEW_3D':
                    area = a
                    break

            if not area:
                return {"error": "No 3D viewport found"}

            # Take screenshot with proper context override
            with bpy.context.temp_override(area=area):
                bpy.ops.screen.screenshot_area(filepath=filepath)

            # Load and resize if needed
            img = bpy.data.images.load(filepath)
            width, height = img.size

            if max(width, height) > max_size:
                scale = max_size / max(width, height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                img.scale(new_width, new_height)

                # Set format and save
                img.file_format = format.upper()
                img.save()
                width, height = new_width, new_height

            # Cleanup Blender image data
            bpy.data.images.remove(img)

            return {
                "success": True,
                "width": width,
                "height": height,
                "filepath": filepath
            }

        except Exception as e:
            return {"error": str(e)}

    def _apply_render_settings(self, engine, resolution_x, resolution_y, samples):
        """Apply render settings and return (saved_settings, engine_id, samples_used)."""
        scene = bpy.context.scene
        render = scene.render
        saved = {
            "engine": render.engine,
            "resolution_x": render.resolution_x,
            "resolution_y": render.resolution_y,
            "resolution_percentage": render.resolution_percentage,
            "filepath": render.filepath,
            "file_format": render.image_settings.file_format,
            "eevee_samples": scene.eevee.taa_render_samples if hasattr(scene.eevee, 'taa_render_samples') else None,
            "cycles_samples": scene.cycles.samples if hasattr(scene, 'cycles') else None,
        }

        engine_id = self._get_engine_id(engine)
        render.engine = engine_id
        render.resolution_x = resolution_x
        render.resolution_y = resolution_y
        render.resolution_percentage = 100
        render.image_settings.file_format = 'PNG'

        if engine.upper() == "EEVEE":
            s = min(samples or 32, 256)
            if hasattr(scene.eevee, 'taa_render_samples'):
                scene.eevee.taa_render_samples = s
        else:
            s = min(samples or 64, 256)
            scene.cycles.samples = s
        return saved, engine_id, s

    def _restore_render_settings(self, saved):
        scene = bpy.context.scene
        render = scene.render
        render.engine = saved["engine"]
        render.resolution_x = saved["resolution_x"]
        render.resolution_y = saved["resolution_y"]
        render.resolution_percentage = saved["resolution_percentage"]
        render.filepath = saved["filepath"]
        render.image_settings.file_format = saved["file_format"]
        if saved["eevee_samples"] is not None and hasattr(scene.eevee, 'taa_render_samples'):
            scene.eevee.taa_render_samples = saved["eevee_samples"]
        if saved["cycles_samples"] is not None and hasattr(scene, 'cycles'):
            scene.cycles.samples = saved["cycles_samples"]

    def render_scene(self, filepath=None, resolution_x=1280, resolution_y=720,
                     engine="EEVEE", samples=None):
        """Start an async render and return immediately."""
        import uuid as _uuid
        if not filepath:
            return {"error": "No filepath provided"}

        if self._render_status == "rendering":
            return {"error": "A render is already in progress", "render_id": self._render_id}

        saved, engine_id, s = self._apply_render_settings(engine, resolution_x, resolution_y, samples)
        bpy.context.scene.render.filepath = filepath

        # Set async render state
        self._render_id = str(_uuid.uuid4())
        self._render_status = "rendering"
        self._render_result = None

        server_ref = self

        def _do_render():
            try:
                print(f"Rendering with {engine_id}, {resolution_x}x{resolution_y}, {s} samples...")
                bpy.ops.render.render(write_still=True)
                server_ref._render_status = "completed"
                server_ref._render_result = {
                    "filepath": filepath, "width": resolution_x,
                    "height": resolution_y, "engine": engine,
                }
                server_ref._last_render_path = filepath
                with suppress(OSError):  # history is best effort; the render itself succeeded
                    server_ref._remember_render(filepath, {"type": "render", "engine": engine,
                                                           "width": resolution_x, "height": resolution_y})
                print("Render complete")
            except Exception as e:
                server_ref._render_status = "failed"
                server_ref._render_result = {"error": str(e)}
                print(f"Render failed: {str(e)}")
            finally:
                server_ref._restore_render_settings(saved)
            return None

        bpy.app.timers.register(_do_render, first_interval=0.1)

        return {"status": "started", "render_id": self._render_id}

    # ---- Render history & comparison ----

    _RENDER_HISTORY_SIZE = 20

    def _history_dir(self):
        path = os.path.join(tempfile.gettempdir(), f"blender_mcp_history_{os.getpid()}")
        os.makedirs(path, exist_ok=True)
        return path

    def _remember_render(self, filepath, info):
        """Keep a copy of a finished render so later renders don't overwrite it."""
        from datetime import datetime
        number = self._render_history[-1]["number"] + 1 if self._render_history else 1
        copy_path = os.path.join(self._history_dir(), f"render_{number:03d}.png")
        shutil.copyfile(filepath, copy_path)
        entry = dict(info, number=number, filepath=copy_path,
                     time=datetime.now().isoformat(timespec="seconds"),
                     frame=bpy.context.scene.frame_current)
        self._render_history.append(entry)
        while len(self._render_history) > self._RENDER_HISTORY_SIZE:
            old = self._render_history.pop(0)
            with suppress(OSError):
                os.remove(old["filepath"])
        return entry

    def list_renders(self):
        return {"renders": [{k: v for k, v in e.items() if k != "filepath"} for e in self._render_history]}

    def _find_render(self, ref):
        """ref: render number (>= 1) or negative index into the history (-1 = latest)."""
        ref = int(ref)
        if ref < 0:
            if -ref > len(self._render_history):
                raise ValueError(f"Only {len(self._render_history)} render(s) in the history")
            return self._render_history[ref]
        for entry in self._render_history:
            if entry["number"] == ref:
                return entry
        raise ValueError(f"Render #{ref} is not in the history (see list_renders)")

    def _load_rgba(self, path):
        import numpy as np
        img = bpy.data.images.load(path, check_existing=False)
        try:
            w, h = img.size
            buf = np.empty(w * h * 4, dtype=np.float32)
            img.pixels.foreach_get(buf)
            return buf.reshape(h, w, 4)
        finally:
            bpy.data.images.remove(img)

    def compare_renders(self, before=-2, after=-1, filepath=None, threshold=0.02):
        """Compose before | after | difference and measure how much changed."""
        import numpy as np
        if not filepath:
            return {"error": "No filepath provided"}
        a_entry, b_entry = self._find_render(before), self._find_render(after)
        a, b = self._load_rgba(a_entry["filepath"]), self._load_rgba(b_entry["filepath"])
        if a.shape != b.shape:
            # Nearest-neighbour resize of "before" to the size of "after"
            ys = (np.arange(b.shape[0]) * a.shape[0] / b.shape[0]).astype(int)
            xs = (np.arange(b.shape[1]) * a.shape[1] / b.shape[1]).astype(int)
            a = a[ys][:, xs]

        diff = np.abs(a[..., :3] - b[..., :3]).mean(axis=2)
        changed = diff > threshold
        gray = b[..., :3].mean(axis=2, keepdims=True) * 0.35
        heat = np.clip(diff / max(float(diff.max()), threshold * 5), 0, 1)[..., None]
        diff_panel = np.concatenate([gray * (1 - heat) + heat * np.array([1.0, 0.1, 0.1]),
                                     np.ones(diff.shape + (1,))], axis=2)

        h, w = b.shape[:2]
        gap = 4
        sheet = np.empty((h + 2 * gap, 3 * w + 4 * gap, 4), dtype=np.float32)
        sheet[:] = (0.15, 0.15, 0.15, 1.0)
        label_scale = max(2, h // 60)
        for i, (panel, label) in enumerate([(a, str(a_entry["number"])), (b, str(b_entry["number"])),
                                            (diff_panel, None)]):
            tile = panel.astype(np.float32).copy()
            tile[..., 3] = 1.0
            if label:
                self._draw_label(tile, label, label_scale)
            x0 = gap + i * (w + gap)
            sheet[gap:gap + h, x0:x0 + w] = tile

        out = bpy.data.images.new("MCP_Compare", sheet.shape[1], sheet.shape[0], alpha=True)
        try:
            out.pixels.foreach_set(sheet.ravel())
            out.filepath_raw = filepath
            out.file_format = 'PNG'
            out.save()
        finally:
            bpy.data.images.remove(out)

        result = {
            "filepath": filepath,
            "before": {k: v for k, v in a_entry.items() if k != "filepath"},
            "after": {k: v for k, v in b_entry.items() if k != "filepath"},
            "layout": "before | after | difference (red = changed); panels labeled with render numbers",
            "changed_fraction": round(float(changed.mean()), 4),
            "mean_difference": round(float(diff.mean()), 4),
            "max_difference": round(float(diff.max()), 4),
        }
        if changed.any():
            rows, cols = np.nonzero(changed)
            # Image rows are stored bottom-up; report the box with a top-left origin
            result["changed_bbox"] = {"x_min": int(cols.min()), "x_max": int(cols.max()),
                                      "y_min": int(h - 1 - rows.max()), "y_max": int(h - 1 - rows.min())}
        return result

    # ---- Animation preview (contact sheet) ----

    # 3x5 bitmap digits for frame labels, rows top to bottom
    _DIGITS = {
        "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
        "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
        "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
        "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "010", "010", "010"],
        "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
        "-": ["000", "000", "111", "000", "000"],
    }

    def _preview_frames(self, frame_start, frame_end, num_frames):
        if num_frames <= 1 or frame_start == frame_end:
            return [frame_start]
        step = (frame_end - frame_start) / (num_frames - 1)
        frames = [int(round(frame_start + i * step)) for i in range(num_frames)]
        return sorted(set(frames))

    def _draw_label(self, tile, text, scale):
        """Draw text (digits) into the top-left corner of an RGBA tile (rows bottom-up)."""
        h = tile.shape[0]
        glyph_w, glyph_h = 3 * scale, 5 * scale
        pad = scale
        box_w = len(text) * (glyph_w + scale) + pad
        box_h = glyph_h + 2 * pad
        if box_w > tile.shape[1] or box_h > h:
            return
        tile[h - box_h:h, 0:box_w] = (0.0, 0.0, 0.0, 1.0)
        for i, ch in enumerate(text):
            pattern = self._DIGITS.get(ch)
            if not pattern:
                continue
            x0 = pad + i * (glyph_w + scale)
            for row, bits in enumerate(pattern):
                for col, bit in enumerate(bits):
                    if bit == "1":
                        y_top = h - pad - row * scale
                        tile[y_top - scale:y_top, x0 + col * scale:x0 + (col + 1) * scale] = (1.0, 1.0, 1.0, 1.0)

    def _compose_contact_sheet(self, frame_paths, frames, columns, filepath):
        """Compose rendered frames into one labeled grid image. Returns (columns, rows)."""
        import numpy as np
        n = len(frame_paths)
        cols = max(1, min(columns or int(np.ceil(np.sqrt(n))), n))
        rows = int(np.ceil(n / cols))
        gap = 4

        tiles = []
        for path in frame_paths:
            img = bpy.data.images.load(path, check_existing=False)
            try:
                w, h = img.size
                buf = np.empty(w * h * 4, dtype=np.float32)
                img.pixels.foreach_get(buf)
                tiles.append(buf.reshape(h, w, 4))
            finally:
                bpy.data.images.remove(img)

        h, w = tiles[0].shape[:2]
        sheet_w = cols * w + (cols + 1) * gap
        sheet_h = rows * h + (rows + 1) * gap
        sheet = np.empty((sheet_h, sheet_w, 4), dtype=np.float32)
        sheet[:] = (0.15, 0.15, 0.15, 1.0)
        label_scale = max(2, h // 60)
        for i, (tile, frame) in enumerate(zip(tiles, frames)):
            tile = tile.copy()
            tile[..., 3] = 1.0
            self._draw_label(tile, str(frame), label_scale)
            r, c = divmod(i, cols)
            # Image rows are stored bottom-up; row 0 of the grid is at the top
            y0 = gap + (rows - 1 - r) * (h + gap)
            x0 = gap + c * (w + gap)
            sheet[y0:y0 + h, x0:x0 + w] = tile

        out = bpy.data.images.new("MCP_ContactSheet", sheet_w, sheet_h, alpha=True)
        try:
            out.pixels.foreach_set(sheet.ravel())
            out.filepath_raw = filepath
            out.file_format = 'PNG'
            out.save()
        finally:
            bpy.data.images.remove(out)
        return cols, rows

    def render_animation_preview(self, filepath=None, frame_start=None, frame_end=None,
                                 num_frames=9, columns=None, resolution_x=480,
                                 resolution_y=270, engine="EEVEE", samples=None):
        """Start rendering sampled frames into a contact sheet; poll with poll_render_status."""
        import uuid as _uuid
        if not filepath:
            return {"error": "No filepath provided"}
        if self._render_status == "rendering":
            return {"error": "A render is already in progress", "render_id": self._render_id}

        scene = bpy.context.scene
        start = scene.frame_start if frame_start is None else int(frame_start)
        end = scene.frame_end if frame_end is None else int(frame_end)
        if start > end:
            return {"error": f"frame_start ({start}) must not be greater than frame_end ({end})"}
        num_frames = max(1, min(int(num_frames), 25))
        frames = self._preview_frames(start, end, num_frames)

        saved, engine_id, s = self._apply_render_settings(engine, resolution_x, resolution_y, samples)
        base, _ = os.path.splitext(filepath)
        self._preview_job = {
            "frames": frames,
            "paths": [f"{base}_f{frame:05d}.png" for frame in frames],
            "next": 0,
            "saved": saved,
            "frame_current": scene.frame_current,
            "filepath": filepath,
            "columns": columns,
            "engine": engine,
            "samples": s,
            "tile_size": [resolution_x, resolution_y],
        }
        self._render_id = str(_uuid.uuid4())
        self._render_status = "rendering"
        self._render_result = {"type": "animation_preview", "frames_done": 0, "frames_total": len(frames)}

        bpy.app.timers.register(self._preview_step, first_interval=0.1)
        return {"status": "started", "render_id": self._render_id, "frames": frames,
                "engine": engine_id, "samples": s}

    def _preview_step(self):
        """Render one preview frame per timer tick so polls are answered in between."""
        job = self._preview_job
        if job is None:
            return None
        scene = bpy.context.scene
        try:
            i = job["next"]
            if i < len(job["frames"]):
                scene.frame_set(job["frames"][i])
                scene.render.filepath = job["paths"][i]
                bpy.ops.render.render(write_still=True)
                job["next"] = i + 1
                self._render_result["frames_done"] = i + 1
                return 0.01

            cols, rows = self._compose_contact_sheet(job["paths"], job["frames"], job["columns"], job["filepath"])
            self._render_status = "completed"
            self._render_result = {
                "type": "animation_preview",
                "filepath": job["filepath"],
                "frames": job["frames"],
                "columns": cols,
                "rows": rows,
                "tile_size": job["tile_size"],
                "engine": job["engine"],
                "samples": job["samples"],
                "layout": "row-major, top-left first; each tile is labeled with its frame number",
            }
            self._last_render_path = job["filepath"]
            with suppress(OSError):
                self._remember_render(job["filepath"], {"type": "animation_preview", "frames": job["frames"]})
        except Exception as e:
            traceback.print_exc()
            self._render_status = "failed"
            self._render_result = {"type": "animation_preview", "error": str(e)}
        self._finish_preview_job()
        return None

    def _finish_preview_job(self):
        job = self._preview_job
        self._preview_job = None
        scene = bpy.context.scene
        self._restore_render_settings(job["saved"])
        scene.frame_set(job["frame_current"])
        for path in job["paths"]:
            with suppress(OSError):
                os.remove(path)

    def poll_render_status(self):
        """Poll the status of an async render."""
        return {
            "render_id": self._render_id,
            "status": self._render_status or "idle",
            "result": self._render_result,
        }

    def execute_batch_script(self, script_path=None, code=None):
        """Execute a long-running script asynchronously."""
        import uuid as _uuid
        if self._batch_status == "running":
            return {"error": "A batch script is already running", "batch_id": self._batch_id}

        if code:
            script_code = code
        elif script_path:
            with open(script_path, 'r') as f:
                script_code = f.read()
        else:
            return {"error": "No code or script_path provided"}

        self._batch_id = str(_uuid.uuid4())
        self._batch_status = "running"
        self._batch_result = None

        server_ref = self

        def _do_execute():
            try:
                namespace = {"bpy": bpy}
                capture_buffer = io.StringIO()
                with redirect_stdout(capture_buffer):
                    exec(script_code, namespace)
                server_ref._batch_status = "completed"
                server_ref._batch_result = {"output": capture_buffer.getvalue()}
            except Exception as e:
                server_ref._batch_status = "failed"
                server_ref._batch_result = {"error": str(e)}
            return None

        bpy.app.timers.register(_do_execute, first_interval=0.1)

        return {"status": "started", "batch_id": self._batch_id}

    def poll_batch_status(self):
        """Poll the status of an async batch script."""
        return {
            "batch_id": self._batch_id,
            "status": self._batch_status or "idle",
            "result": self._batch_result,
        }

    # ---- Animation & Timeline ----

    _INTERPOLATIONS = {
        'CONSTANT', 'LINEAR', 'BEZIER', 'SINE', 'QUAD', 'CUBIC', 'QUART',
        'QUINT', 'EXPO', 'CIRC', 'BACK', 'BOUNCE', 'ELASTIC',
    }

    def _get_object(self, object_name):
        obj = bpy.data.objects.get(object_name)
        if not obj:
            raise ValueError(f"Object not found: {object_name}")
        return obj

    def _resolve_anim_target(self, obj, data_path):
        """Map a data_path to (id_block, path). A "data." prefix targets obj.data."""
        if data_path.startswith("data."):
            if obj.data is None:
                raise ValueError(f"Object '{obj.name}' has no data block")
            return obj.data, data_path[len("data."):]
        return obj, data_path

    def _set_path_value(self, target, path, value, index):
        """Set the value of an animatable property given by an RNA path."""
        custom = re.match(r'^(.*)\[(["\'])(.+)\2\]$', path)
        if custom:
            owner = target.path_resolve(custom.group(1)) if custom.group(1) else target
            key = custom.group(3)
            if index >= 0:
                owner[key][index] = value
            else:
                owner[key] = value
            return
        match = re.match(r'^(.*?)\.?([A-Za-z_]\w*)$', path)
        if not match:
            raise ValueError(f"Unsupported data_path: {path}")
        owner = target.path_resolve(match.group(1)) if match.group(1) else target
        attr = match.group(2)
        if index >= 0:
            getattr(owner, attr)[index] = value
        else:
            setattr(owner, attr, value)

    def _serialize_fcurve(self, fc, prefix="", max_keyframes=100):
        points = fc.keyframe_points
        data = {
            "data_path": prefix + fc.data_path,
            "index": fc.array_index,
            "keyframe_count": len(points),
            "extrapolation": fc.extrapolation,
            "keyframes": [
                {
                    "frame": round(float(kp.co[0]), 3),
                    "value": round(float(kp.co[1]), 4),
                    "interpolation": kp.interpolation,
                }
                for kp in list(points)[:max_keyframes]
            ],
        }
        if len(points) > max_keyframes:
            data["truncated"] = True
        if fc.mute:
            data["mute"] = True
        return data

    def _serialize_nla(self, anim):
        tracks = []
        if not anim:
            return tracks
        for track in anim.nla_tracks:
            tracks.append({
                "name": track.name,
                "mute": track.mute,
                "is_solo": track.is_solo,
                "strips": [
                    {
                        "name": strip.name,
                        "action": strip.action.name if strip.action else None,
                        "frame_start": round(float(strip.frame_start), 3),
                        "frame_end": round(float(strip.frame_end), 3),
                        "blend_type": strip.blend_type,
                        "repeat": round(float(strip.repeat), 3),
                        "scale": round(float(strip.scale), 3),
                        "mute": strip.mute,
                    }
                    for strip in track.strips
                ],
            })
        return tracks

    def _get_timeline(self):
        scene = bpy.context.scene
        return {
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "frame_current": scene.frame_current,
            "fps": scene.render.fps,
            "fps_base": round(float(scene.render.fps_base), 4),
            "effective_fps": round(scene.render.fps / scene.render.fps_base, 3),
        }

    def _has_animation(self, obj):
        for target, _ in self._get_anim_targets(obj):
            anim = getattr(target, "animation_data", None)
            if anim and (anim.action or len(anim.nla_tracks) or len(anim.drivers)):
                return True
        return False

    def _is_dynamic(self, obj):
        """True if the object's transform can change over time."""
        while obj is not None:
            if self._has_animation(obj) or len(obj.constraints):
                return True
            obj = obj.parent
        return False

    def insert_keyframes(self, object_name, data_path, keyframes, index=-1, interpolation=None):
        """Insert keyframes on an object (or its data via a "data." prefix).

        keyframes: list of {"frame": number, "value": optional scalar or list,
                            "interpolation": optional}
        """
        obj = self._get_object(object_name)
        target, path = self._resolve_anim_target(obj, data_path)
        try:
            target.path_resolve(path)
        except ValueError:
            raise ValueError(f"Invalid data_path '{data_path}' for object '{object_name}'")
        if not keyframes:
            raise ValueError("No keyframes given")
        if interpolation and interpolation.upper() not in self._INTERPOLATIONS:
            raise ValueError(f"Invalid interpolation: {interpolation}. Use one of {sorted(self._INTERPOLATIONS)}")

        scene = bpy.context.scene
        inserted = []
        interp_by_frame = {}
        for kf in keyframes:
            if "frame" not in kf:
                raise ValueError(f"Keyframe without 'frame': {kf}")
            frame = float(kf["frame"])
            if "value" in kf and kf["value"] is not None:
                self._set_path_value(target, path, kf["value"], index)
            if not target.keyframe_insert(data_path=path, index=index, frame=frame):
                raise RuntimeError(f"Could not insert keyframe for '{data_path}' at frame {frame}")
            inserted.append(frame)
            kf_interp = kf.get("interpolation") or interpolation
            if kf_interp:
                kf_interp = kf_interp.upper()
                if kf_interp not in self._INTERPOLATIONS:
                    raise ValueError(f"Invalid interpolation: {kf_interp}")
                interp_by_frame[frame] = kf_interp

        fcurves = [fc for fc in self._get_fcurves(target)
                   if fc.data_path == path and (index < 0 or fc.array_index == index)]
        for fc in fcurves:
            for kp in fc.keyframe_points:
                interp = interp_by_frame.get(float(kp.co[0]))
                if interp:
                    kp.interpolation = interp
            fc.update()

        # Re-evaluate so the scene shows the animated state of the current frame
        scene.frame_set(scene.frame_current)

        prefix = "data." if target is not obj else ""
        return {
            "object": obj.name,
            "data_path": data_path,
            "inserted_frames": inserted,
            "fcurves": [self._serialize_fcurve(fc, prefix) for fc in fcurves],
        }

    def delete_keyframes(self, object_name, data_path=None, frames=None, index=-1):
        """Delete keyframes. Without data_path all channels, without frames all keys."""
        obj = self._get_object(object_name)
        if data_path:
            target, path = self._resolve_anim_target(obj, data_path)
            targets = [(target, path, "data." if target is not obj else "")]
        else:
            targets = [(t, None, prefix) for t, prefix in self._get_anim_targets(obj)]

        frame_set = {round(float(f), 3) for f in frames} if frames is not None else None
        removed = {}
        for target, path, prefix in targets:
            collection = self._get_fcurve_collection(target)
            if collection is None:
                continue
            for fc in list(collection):
                if path is not None and fc.data_path != path:
                    continue
                if index >= 0 and fc.array_index != index:
                    continue
                points = fc.keyframe_points
                count = 0
                for kp in reversed(list(points)):
                    if frame_set is None or round(float(kp.co[0]), 3) in frame_set:
                        points.remove(kp, fast=True)
                        count += 1
                if count:
                    key = f"{prefix}{fc.data_path}[{fc.array_index}]"
                    removed[key] = count
                if len(points) == 0:
                    collection.remove(fc)
                else:
                    fc.update()

        scene = bpy.context.scene
        scene.frame_set(scene.frame_current)
        return {
            "object": obj.name,
            "removed": removed,
            "removed_total": sum(removed.values()),
        }

    def get_animation_data(self, object_name=None, max_keyframes=100):
        """Return fcurves, keyframe values and NLA tracks of one or all animated objects."""
        if object_name:
            objects = [self._get_object(object_name)]
        else:
            objects = [o for o in bpy.context.scene.objects if self._has_animation(o)]

        result = {"timeline": self._get_timeline(), "objects": {}}
        for obj in objects:
            obj_data = {"fcurves": [], "actions": {}, "nla_tracks": {}, "drivers": []}
            frames = []
            for target, prefix in self._get_anim_targets(obj):
                anim = getattr(target, "animation_data", None)
                if not anim:
                    continue
                key = prefix.rstrip(".") or "object"
                if anim.action:
                    obj_data["actions"][key] = {
                        "action": anim.action.name,
                        "slot": anim.action_slot.name_display if getattr(anim, "action_slot", None) else None,
                    }
                for fc in self._get_fcurves(target):
                    obj_data["fcurves"].append(self._serialize_fcurve(fc, prefix, max_keyframes))
                    frames.extend(float(kp.co[0]) for kp in fc.keyframe_points)
                nla = self._serialize_nla(anim)
                if nla:
                    obj_data["nla_tracks"][key] = nla
                for drv in anim.drivers:
                    obj_data["drivers"].append({
                        "data_path": prefix + drv.data_path,
                        "index": drv.array_index,
                        "expression": drv.driver.expression if drv.driver.type == 'SCRIPTED' else drv.driver.type,
                    })
            if frames:
                obj_data["frame_range"] = [min(frames), max(frames)]
            result["objects"][obj.name] = obj_data
        return result

    def set_timeline(self, frame_start=None, frame_end=None, fps=None, frame_current=None):
        """Set scene frame range, frame rate and/or current frame."""
        scene = bpy.context.scene
        start = frame_start if frame_start is not None else scene.frame_start
        end = frame_end if frame_end is not None else scene.frame_end
        if start > end:
            raise ValueError(f"frame_start ({start}) must not be greater than frame_end ({end})")
        # Set in an order that never makes start > end temporarily
        if frame_end is not None and frame_end < scene.frame_start:
            scene.frame_start = start
            scene.frame_end = end
        else:
            scene.frame_end = end
            scene.frame_start = start
        if fps is not None:
            if fps < 1:
                raise ValueError("fps must be at least 1")
            scene.render.fps = int(fps)
            scene.render.fps_base = 1.0
        if frame_current is not None:
            scene.frame_set(int(frame_current))
        return self._get_timeline()

    def scrub_timeline(self, frame, object_names=None):
        """Jump to a frame and return the evaluated state of animated objects."""
        scene = bpy.context.scene
        frame = float(frame)
        whole = int(frame // 1)
        scene.frame_set(whole, subframe=frame - whole)

        if object_names:
            objects = [self._get_object(name) for name in object_names]
        else:
            objects = [o for o in scene.objects if self._is_dynamic(o)]

        states = {}
        for obj in objects:
            loc, rot, scale = obj.matrix_world.decompose()
            state = {
                "world_location": self._round_vec(loc),
                "world_rotation": self._round_vec(rot.to_euler()),
                "world_scale": self._round_vec(scale),
                "visible": obj.visible_get(),
                "hide_render": obj.hide_render,
            }
            if obj.type == 'CAMERA':
                state["focal_length"] = round(float(obj.data.lens), 4)
            elif obj.type == 'LIGHT':
                state["energy"] = round(float(obj.data.energy), 4)
                state["color"] = self._round_vec(obj.data.color)
            states[obj.name] = state

        return {"frame": frame, "timeline": self._get_timeline(), "objects": states}

    # ---- NLA ----

    _BLEND_TYPES = {'REPLACE', 'COMBINE', 'ADD', 'SUBTRACT', 'MULTIPLY'}
    _STRIP_EXTRAPOLATIONS = {'HOLD', 'HOLD_FORWARD', 'NOTHING'}

    def _get_nla_owner(self, obj, target):
        if target == "object":
            return obj
        if target == "data":
            if obj.data is None:
                raise ValueError(f"Object '{obj.name}' has no data block")
            return obj.data
        raise ValueError(f"Invalid target: {target}. Use 'object' or 'data'")

    def _get_nla_track(self, anim, track_name):
        track = anim.nla_tracks.get(track_name) if anim else None
        if not track:
            raise ValueError(f"NLA track not found: {track_name}")
        return track

    def _get_nla_strip(self, track, strip_name):
        strip = track.strips.get(strip_name)
        if not strip:
            raise ValueError(f"NLA strip not found in track '{track.name}': {strip_name}")
        return strip

    def _apply_strip_settings(self, strip, repeat=None, scale=None, blend_type=None,
                              extrapolation=None, blend_in=None, blend_out=None, mute=None):
        if blend_type is not None:
            if blend_type.upper() not in self._BLEND_TYPES:
                raise ValueError(f"Invalid blend_type: {blend_type}. Use one of {sorted(self._BLEND_TYPES)}")
            strip.blend_type = blend_type.upper()
        if extrapolation is not None:
            if extrapolation.upper() not in self._STRIP_EXTRAPOLATIONS:
                raise ValueError(f"Invalid extrapolation: {extrapolation}. Use one of {sorted(self._STRIP_EXTRAPOLATIONS)}")
            strip.extrapolation = extrapolation.upper()
        if repeat is not None:
            strip.repeat = float(repeat)
        if scale is not None:
            strip.scale = float(scale)
        if blend_in is not None:
            strip.blend_in = float(blend_in)
        if blend_out is not None:
            strip.blend_out = float(blend_out)
        if mute is not None:
            strip.mute = bool(mute)

    def _nla_result(self, obj, owner):
        bpy.context.scene.frame_set(bpy.context.scene.frame_current)
        anim = owner.animation_data
        return {
            "object": obj.name,
            "target": "object" if owner is obj else "data",
            "active_action": anim.action.name if anim and anim.action else None,
            "nla_tracks": self._serialize_nla(anim),
        }

    def push_action_to_nla(self, object_name, target="object", track_name=None, strip_name=None):
        """Move the active action into a new NLA track (like 'Push Down' in the UI)."""
        obj = self._get_object(object_name)
        owner = self._get_nla_owner(obj, target)
        anim = owner.animation_data
        if not anim or not anim.action:
            raise ValueError(f"'{object_name}' ({target}) has no active action to push down")
        action = anim.action
        slot = getattr(anim, "action_slot", None)
        track = anim.nla_tracks.new()
        if track_name:
            track.name = track_name
        strip = track.strips.new(strip_name or action.name, int(action.frame_range[0]), action)
        if slot is not None and hasattr(strip, "action_slot"):
            strip.action_slot = slot
        anim.action = None
        return self._nla_result(obj, owner)

    def add_nla_strip(self, object_name, action_name, frame_start, target="object",
                      track_name=None, strip_name=None, repeat=None, scale=None,
                      blend_type=None, extrapolation=None, blend_in=None, blend_out=None):
        """Add an action as NLA strip, on an existing or new track."""
        obj = self._get_object(object_name)
        owner = self._get_nla_owner(obj, target)
        action = bpy.data.actions.get(action_name)
        if not action:
            raise ValueError(f"Action not found: {action_name}")
        anim = owner.animation_data or owner.animation_data_create()
        track = anim.nla_tracks.get(track_name) if track_name else None
        if track is None:
            track = anim.nla_tracks.new()
            if track_name:
                track.name = track_name
        try:
            strip = track.strips.new(strip_name or action.name, int(frame_start), action)
        except RuntimeError as e:
            raise ValueError(f"Could not add strip at frame {frame_start} on track '{track.name}': {e}")
        self._apply_strip_settings(strip, repeat, scale, blend_type, extrapolation, blend_in, blend_out)
        return self._nla_result(obj, owner)

    def update_nla_strip(self, object_name, track_name, strip_name, target="object",
                         frame_start=None, repeat=None, scale=None, blend_type=None,
                         extrapolation=None, blend_in=None, blend_out=None, mute=None):
        """Move or change an NLA strip."""
        obj = self._get_object(object_name)
        owner = self._get_nla_owner(obj, target)
        track = self._get_nla_track(owner.animation_data, track_name)
        strip = self._get_nla_strip(track, strip_name)
        self._apply_strip_settings(strip, repeat, scale, blend_type, extrapolation, blend_in, blend_out, mute)
        if frame_start is not None:
            # frame_start_ui moves the strip and keeps its length
            strip.frame_start_ui = float(frame_start)
        return self._nla_result(obj, owner)

    def remove_nla(self, object_name, track_name, strip_name=None, target="object"):
        """Remove an NLA strip, or the whole track if no strip is given."""
        obj = self._get_object(object_name)
        owner = self._get_nla_owner(obj, target)
        anim = owner.animation_data
        track = self._get_nla_track(anim, track_name)
        if strip_name:
            track.strips.remove(self._get_nla_strip(track, strip_name))
        else:
            anim.nla_tracks.remove(track)
        return self._nla_result(obj, owner)

    def set_nla_track(self, object_name, track_name, target="object", mute=None, solo=None, name=None):
        """Mute, solo or rename an NLA track."""
        obj = self._get_object(object_name)
        owner = self._get_nla_owner(obj, target)
        track = self._get_nla_track(owner.animation_data, track_name)
        if mute is not None:
            track.mute = bool(mute)
        if solo is not None:
            track.is_solo = bool(solo)
        if name:
            track.name = name
        return self._nla_result(obj, owner)

    # ---- Scientific visualization ----

    # viridis at 0, 0.25, 0.5, 0.75, 1, converted from sRGB to linear RGB
    _VIRIDIS = [
        (0.0, (0.0580, 0.0004, 0.0887)),
        (0.25, (0.0431, 0.0848, 0.2588)),
        (0.5, (0.0148, 0.2813, 0.2639)),
        (0.75, (0.1123, 0.5852, 0.1212)),
        (1.0, (0.9847, 0.7997, 0.0182)),
    ]

    _EXPR_FUNCS = (
        "sin", "cos", "tan", "arcsin", "arccos", "arctan", "arctan2", "sinh", "cosh",
        "tanh", "exp", "log", "log10", "sqrt", "abs", "sign", "minimum", "maximum",
        "where", "hypot", "floor", "ceil",
    )

    def _expr_namespace(self, variables, params):
        import numpy as np
        ns = {name: getattr(np, name) for name in self._EXPR_FUNCS}
        ns.update({"pi": np.pi, "e": np.e})
        for key, value in (params or {}).items():
            if not str(key).isidentifier() or key in ns or key in variables:
                raise ValueError(f"Invalid or reserved parameter name: {key}")
            ns[key] = float(value)
        ns.update(variables)
        return ns

    def _compile_vector_expr(self, exprs, var_names, params):
        """Compile 3 expression strings into f(**vars) -> (N, 3) array."""
        import numpy as np
        if not isinstance(exprs, (list, tuple)) or len(exprs) != 3:
            raise ValueError("Expected a list of 3 expressions for the x, y and z components")
        self._expr_namespace(dict.fromkeys(var_names), params)  # validates parameter names
        codes = []
        for expr in exprs:
            try:
                codes.append(compile(str(expr), "<expr>", "eval"))
            except SyntaxError as e:
                raise ValueError(f"Invalid expression '{expr}': {e.msg}")
            names = set(codes[-1].co_names)
            allowed = set(self._EXPR_FUNCS) | {"pi", "e"} | set(var_names) | set(params or {})
            unknown = names - allowed
            if unknown:
                raise ValueError(f"Unknown names in '{expr}': {sorted(unknown)}. "
                                 f"Variables: {list(var_names)}, functions: {list(self._EXPR_FUNCS)}")

        def evaluate(**variables):
            n = len(next(iter(variables.values())))
            ns = self._expr_namespace(variables, params)
            out = np.empty((n, 3))
            with np.errstate(all="ignore"):
                for i, code in enumerate(codes):
                    out[:, i] = np.broadcast_to(eval(code, {"__builtins__": {}}, ns), (n,))
            return out
        return evaluate

    def _colormap(self, t):
        t = min(max(float(t), 0.0), 1.0)
        for (t0, c0), (t1, c1) in zip(self._VIRIDIS, self._VIRIDIS[1:]):
            if t <= t1:
                f = (t - t0) / (t1 - t0)
                return tuple(a + (b - a) * f for a, b in zip(c0, c1))
        return self._VIRIDIS[-1][1]

    def _replace_object(self, name):
        obj = bpy.data.objects.get(name)
        if not obj:
            return
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)

    def _solid_material(self, name, color, emission=0.0):
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        if bpy.app.version < (5, 0, 0):
            mat.use_nodes = True
        bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf is None:
            bsdf = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        rgba = (*color[:3], 1.0)
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = 0.4
        emission_color = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
        if emission_color is not None:
            emission_color.default_value = rgba
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = emission
        mat.diffuse_color = rgba
        return mat

    def _attribute_colormap_material(self, name, attribute):
        """Material coloring by a 0..1 float attribute through a viridis color ramp."""
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        if bpy.app.version < (5, 0, 0):
            mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        out = nodes.new("ShaderNodeOutputMaterial")
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        attr = nodes.new("ShaderNodeAttribute")
        attr.attribute_name = attribute
        ramp = nodes.new("ShaderNodeValToRGB")
        elements = ramp.color_ramp.elements
        elements[0].position, elements[0].color = 0.0, (*self._VIRIDIS[0][1], 1.0)
        elements[1].position, elements[1].color = 1.0, (*self._VIRIDIS[-1][1], 1.0)
        for pos, color in self._VIRIDIS[1:-1]:
            elements.new(pos).color = (*color, 1.0)
        links.new(attr.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        bsdf.inputs["Roughness"].default_value = 0.4
        return mat

    def _arrow_template(self, sides=8, shaft_radius=0.04, head_radius=0.1, head_length=0.3):
        """Unit arrow along +Z from 0 to 1. Returns (verts, faces) as numpy arrays."""
        import numpy as np
        angles = np.linspace(0, 2 * np.pi, sides, endpoint=False)
        ring = np.stack([np.cos(angles), np.sin(angles)], axis=1)
        z_neck = 1.0 - head_length
        verts = np.concatenate([
            np.column_stack([ring * shaft_radius, np.zeros(sides)]),        # shaft bottom
            np.column_stack([ring * shaft_radius, np.full(sides, z_neck)]),  # shaft top
            np.column_stack([ring * head_radius, np.full(sides, z_neck)]),   # head base
            [[0.0, 0.0, 1.0], [0.0, 0.0, 0.0]],                            # tip, bottom center
        ])
        tip, bottom = 3 * sides, 3 * sides + 1
        faces = []
        for i in range(sides):
            j = (i + 1) % sides
            faces.append([i, j, sides + j, sides + i])                       # shaft side
            faces.append([sides + i, sides + j, 2 * sides + j, 2 * sides + i])  # neck ring
            faces.append([2 * sides + i, 2 * sides + j, tip])                # head cone
            faces.append([j, i, bottom])                                     # bottom cap
        return verts, faces

    def _rotations_to(self, directions):
        """Rotation matrices (N, 3, 3) turning +Z onto each unit direction."""
        import numpy as np
        d = directions
        n = len(d)
        c = d[:, 2]
        v = np.stack([-d[:, 1], d[:, 0], np.zeros(n)], axis=1)  # z x d
        k = np.zeros((n, 3, 3))
        k[:, 0, 1], k[:, 0, 2] = -v[:, 2], v[:, 1]
        k[:, 1, 0], k[:, 1, 2] = v[:, 2], -v[:, 0]
        k[:, 2, 0], k[:, 2, 1] = -v[:, 1], v[:, 0]
        with np.errstate(all="ignore"):
            factor = np.where(c > -1 + 1e-9, 1.0 / (1.0 + c), 0.0)
        rot = np.eye(3)[None] + k + np.einsum("nij,njk->nik", k, k) * factor[:, None, None]
        rot[c <= -1 + 1e-9] = np.diag([1.0, -1.0, -1.0])
        return rot

    def _build_arrows(self, name, points, vectors, magnitudes, arrow_length, normalize, thickness,
                      color_scale="linear"):
        import numpy as np
        m_max = float(magnitudes.max())
        dirs = vectors / magnitudes[:, None]
        lengths = np.full(len(points), arrow_length) if normalize else arrow_length * magnitudes / m_max
        widths = np.minimum(1.0, lengths / arrow_length) * thickness / 0.04

        tmpl_v, tmpl_f = self._arrow_template()
        rot = self._rotations_to(dirs)
        scaled = tmpl_v[None] * np.stack([widths, widths, lengths], axis=1)[:, None, :]
        # Arrows are centered on their sample point
        scaled[:, :, 2] -= lengths[:, None] / 2
        verts = np.einsum("nij,nvj->nvi", rot, scaled) + points[:, None, :]
        nv = len(tmpl_v)
        faces = [[i * nv + idx for idx in face] for i in range(len(points)) for face in tmpl_f]

        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts.reshape(-1, 3).tolist(), [], faces)
        mesh.update()
        values = np.log10(magnitudes) if color_scale == "log" else magnitudes
        span = float(values.max() - values.min()) or 1.0
        norm = np.repeat((values - values.min()) / span, nv).astype(np.float32)
        attr = mesh.attributes.new("magnitude", 'FLOAT', 'POINT')
        attr.data.foreach_set("value", norm)
        mesh.materials.append(self._attribute_colormap_material(f"{name}_colormap", "magnitude"))
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        return obj

    def _build_polyline_curve(self, name, polylines, thickness, materials=None, material_indices=None,
                              radii=None):
        import numpy as np
        curve = bpy.data.curves.new(name, 'CURVE')
        curve.dimensions = '3D'
        curve.bevel_depth = thickness
        curve.bevel_resolution = 2
        curve.use_fill_caps = True
        # Materials must exist before material_index is set, otherwise it is clamped to 0
        for mat in materials or []:
            curve.materials.append(mat)
        for i, line in enumerate(polylines):
            spline = curve.splines.new('POLY')
            spline.points.add(len(line) - 1)
            co = np.column_stack([line, np.ones(len(line))]).astype(np.float32)
            spline.points.foreach_set("co", co.ravel())
            if radii is not None:
                spline.points.foreach_set("radius", np.full(len(line), radii[i], dtype=np.float32))
            if material_indices is not None:
                spline.material_index = material_indices[i]
        obj = bpy.data.objects.new(name, curve)
        bpy.context.scene.collection.objects.link(obj)
        return obj

    def _integrate_streamlines(self, field, seeds, bounds, step_size, max_steps):
        """RK4 along the normalized field (arc length), both directions from each seed."""
        import numpy as np
        lo, hi = bounds[:, 0], bounds[:, 1]
        margin = 1e-6 + 0.01 * (hi - lo)

        def direction(p):
            f = field(x=p[:, 0], y=p[:, 1], z=p[:, 2])
            norm = np.linalg.norm(f, axis=1)
            with np.errstate(all="ignore"):
                d = f / norm[:, None]
            bad = ~np.isfinite(d).all(axis=1) | (norm < 1e-12)
            d[bad] = 0.0
            return d, bad

        halves = []
        for sign in (1.0, -1.0):
            p = seeds.copy()
            alive = np.ones(len(p), dtype=bool)
            paths = [[q.copy()] for q in p]
            h = sign * step_size
            for _ in range(max_steps):
                if not alive.any():
                    break
                idx = np.nonzero(alive)[0]
                q = p[idx]
                k1, b1 = direction(q)
                k2, b2 = direction(q + h / 2 * k1)
                k3, b3 = direction(q + h / 2 * k2)
                k4, b4 = direction(q + h * k3)
                nxt = q + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
                inside = ((nxt >= lo - margin) & (nxt <= hi + margin)).all(axis=1)
                ok = inside & ~(b1 | b2 | b3 | b4) & np.isfinite(nxt).all(axis=1)
                for j, i in enumerate(idx):
                    if ok[j]:
                        paths[i].append(nxt[j])
                p[idx[ok]] = nxt[ok]
                alive[idx[~ok]] = False
            halves.append(paths)

        lines = []
        for fwd, bwd in zip(*halves):
            line = np.array(bwd[::-1] + fwd[1:])
            if len(line) >= 2:
                lines.append(line)
        return lines

    def plot_vector_field(self, name, field, bounds, resolution=(10, 10, 1), params=None,
                          mode="arrows", normalize=True, arrow_scale=0.8, thickness=0.02,
                          color_scale="auto",
                          seeds=None, seed_resolution=None, step_size=None, max_steps=500,
                          streamline_color=(0.7, 0.7, 0.72)):
        """Visualize a vector field F(x, y, z) as colored arrows and/or streamlines."""
        import numpy as np
        if mode not in ("arrows", "streamlines", "both"):
            raise ValueError("mode must be 'arrows', 'streamlines' or 'both'")
        bounds = np.array(bounds, dtype=float)
        if bounds.shape != (3, 2) or (bounds[:, 1] < bounds[:, 0]).any():
            raise ValueError("bounds must be [[xmin, xmax], [ymin, ymax], [zmin, zmax]] with min <= max")
        res = [max(1, int(r)) for r in resolution]
        if len(res) != 3 or np.prod(res) > 20000:
            raise ValueError("resolution must have 3 entries with at most 20000 samples in total")
        f = self._compile_vector_expr(field, ("x", "y", "z"), params)

        axes = [np.linspace(lo, hi, n) if n > 1 else np.array([(lo + hi) / 2])
                for (lo, hi), n in zip(bounds, res)]
        grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
        spacing = min((hi - lo) / (n - 1) for (lo, hi), n in zip(bounds, res) if n > 1) \
            if any(n > 1 for n in res) else 1.0

        result = {"name": name, "objects": []}
        if mode in ("arrows", "both"):
            vectors = f(x=grid[:, 0], y=grid[:, 1], z=grid[:, 2])
            mags = np.linalg.norm(vectors, axis=1)
            valid = np.isfinite(vectors).all(axis=1) & (mags > 1e-12)
            if not valid.any():
                raise ValueError("The field is zero or undefined at all sample points")
            if color_scale not in ("auto", "linear", "log"):
                raise ValueError("color_scale must be 'auto', 'linear' or 'log'")
            m = mags[valid]
            if color_scale == "auto":
                color_scale = "log" if m.max() / m.min() > 100 else "linear"
            self._replace_object(name)
            obj = self._build_arrows(name, grid[valid], vectors[valid], m,
                                     arrow_scale * spacing, normalize, thickness, color_scale)
            result["objects"].append(obj.name)
            result["arrows"] = int(valid.sum())
            result["skipped_samples"] = int((~valid).sum())
            result["magnitude_range"] = [round(float(mags[valid].min()), 6), round(float(mags[valid].max()), 6)]
            result["color"] = f"viridis by {color_scale} magnitude (dark = weak, yellow = strong)"

        if mode in ("streamlines", "both"):
            if seeds is not None:
                seed_pts = np.array(seeds, dtype=float).reshape(-1, 3)
            else:
                # About a quarter of the arrow resolution keeps the arrows visible between lines
                seed_res = seed_resolution or [max(2, n // 4) if n > 1 else 1 for n in res]
                seed_axes = [np.linspace(lo, hi, n + 2)[1:-1] if n > 1 else np.array([(lo + hi) / 2])
                             for (lo, hi), n in zip(bounds, seed_res)]
                seed_pts = np.stack(np.meshgrid(*seed_axes, indexing="ij"), axis=-1).reshape(-1, 3)
            if len(seed_pts) > 2000:
                raise ValueError("At most 2000 streamline seeds are supported")
            h = step_size or spacing * 0.1
            # Keep flat fields flat: integrate within the degenerate axis range
            lines = self._integrate_streamlines(f, seed_pts, bounds, h, int(max_steps))
            if not lines:
                raise ValueError("No streamline could be traced from the seeds")
            stream_name = f"{name}_streamlines"
            self._replace_object(stream_name)
            mat = self._solid_material(f"{stream_name}_mat", streamline_color)
            obj = self._build_polyline_curve(stream_name, lines, thickness * 0.5, [mat])
            result["objects"].append(obj.name)
            result["streamlines"] = len(lines)
            result["streamline_points"] = int(sum(len(l) for l in lines))
        return result

    def _integrate_ode(self, rhs, initial, t0, t1, steps):
        """Fixed-step RK4 for all initial conditions at once. Returns (steps+1, K, 3) and times."""
        import numpy as np
        dt = (t1 - t0) / steps
        y = np.array(initial, dtype=float).reshape(-1, 3)
        out = np.full((steps + 1, len(y), 3), np.nan)
        out[0] = y

        def f(t, y):
            return rhs(x=y[:, 0], y=y[:, 1], z=y[:, 2], t=np.full(len(y), t))

        t = t0
        for i in range(steps):
            k1 = f(t, y)
            k2 = f(t + dt / 2, y + dt / 2 * k1)
            k3 = f(t + dt / 2, y + dt / 2 * k2)
            k4 = f(t + dt, y + dt * k3)
            y = y + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
            t += dt
            out[i + 1] = y
        return out, np.linspace(t0, t1, steps + 1)

    def plot_trajectory(self, name, points=None, ode=None, initial=None, t_span=(0.0, 10.0),
                        steps=2000, params=None, thickness=0.03, color=None, fit_size=None,
                        animate=False, frame_start=None, frame_end=None, marker_size=None):
        """Draw trajectories from given points or by integrating an ODE dx/dt = F(x, y, z, t)."""
        import numpy as np
        if (points is None) == (ode is None):
            raise ValueError("Give either 'points' or 'ode' (with 'initial')")
        if points is not None:
            arr = np.array(points, dtype=float)
            lines = [arr] if arr.ndim == 2 else list(arr)
            source = "points"
        else:
            if initial is None:
                raise ValueError("'initial' is required with 'ode'")
            steps = int(steps)
            if not 1 <= steps <= 200000:
                raise ValueError("steps must be between 1 and 200000")
            rhs = self._compile_vector_expr(ode, ("x", "y", "z", "t"), params)
            sol, _ = self._integrate_ode(rhs, initial, float(t_span[0]), float(t_span[1]), steps)
            lines = [sol[:, k] for k in range(sol.shape[1])]
            source = "ode"

        cleaned, truncated = [], 0
        for line in lines:
            line = np.asarray(line, dtype=float).reshape(-1, 3)
            finite = np.isfinite(line).all(axis=1)
            if not finite.all():
                truncated += 1
                line = line[:np.argmin(finite)]  # cut at the first non-finite point
            if len(line) >= 2:
                cleaned.append(line)
        if not cleaned:
            raise ValueError("No trajectory with at least 2 finite points")

        all_pts = np.concatenate(cleaned)
        transform = {"scale": 1.0, "offset": [0.0, 0.0, 0.0]}
        if fit_size:
            center = (all_pts.max(axis=0) + all_pts.min(axis=0)) / 2
            extent = float((all_pts.max(axis=0) - all_pts.min(axis=0)).max()) or 1.0
            scale = float(fit_size) / extent
            cleaned = [(line - center) * scale for line in cleaned]
            transform = {"scale": round(scale, 6), "offset": self._round_vec(-center * scale)}

        n = len(cleaned)
        colors = [color] * n if color else [self._colormap(i / max(n - 1, 1)) for i in range(n)]
        mats = [self._solid_material(f"{name}_mat_{i}", c, emission=0.3) for i, c in enumerate(colors)]
        self._replace_object(name)
        # Slightly thinner tubes for later trajectories: where trajectories coincide, the
        # outer tube shows one clean color instead of z-fighting stripes
        radii = [1.0 - 0.15 * i / max(n - 1, 1) for i in range(n)]
        obj = self._build_polyline_curve(name, cleaned, thickness, mats, list(range(n)), radii)

        result = {"name": name, "source": source, "trajectories": n,
                  "points_per_trajectory": [len(l) for l in cleaned],
                  "bounds": [self._round_vec(all_pts.min(axis=0)), self._round_vec(all_pts.max(axis=0))],
                  "transform": transform}
        if truncated:
            result["truncated_nonfinite"] = truncated

        if animate:
            scene = bpy.context.scene
            fs = scene.frame_start if frame_start is None else int(frame_start)
            fe = scene.frame_end if frame_end is None else int(frame_end)
            if fe <= fs:
                raise ValueError("frame_end must be greater than frame_start")
            curve = obj.data
            # SPLINE mapping follows point index, i.e. integration time for ODE trajectories
            curve.bevel_factor_mapping_end = 'SPLINE'
            curve.bevel_factor_end = 0.0
            curve.keyframe_insert("bevel_factor_end", frame=fs)
            curve.bevel_factor_end = 1.0
            curve.keyframe_insert("bevel_factor_end", frame=fe)
            for fc in self._get_fcurves(curve):
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'

            markers = []
            radius = marker_size or thickness * 3
            frames = np.arange(fs, fe + 1)
            for i, line in enumerate(cleaned):
                marker_name = f"{name}_marker_{i}"
                self._replace_object(marker_name)
                mesh = bpy.data.meshes.new(marker_name)
                import bmesh
                bm = bmesh.new()
                bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=radius)
                bm.to_mesh(mesh)
                bm.free()
                mesh.materials.append(self._solid_material(f"{name}_marker_mat_{i}", colors[i], emission=2.0))
                marker = bpy.data.objects.new(marker_name, mesh)
                scene.collection.objects.link(marker)
                marker.parent = obj
                idx = np.round((frames - fs) / (fe - fs) * (len(line) - 1)).astype(int)
                for frame, j in zip(frames, idx):
                    marker.location = line[j]
                    marker.keyframe_insert("location", frame=int(frame))
                for fc in self._get_fcurves(marker):
                    for kp in fc.keyframe_points:
                        kp.interpolation = 'LINEAR'
                markers.append(marker_name)
            scene.frame_set(scene.frame_current)
            result["animation"] = {"frame_start": fs, "frame_end": fe, "markers": markers}
        return result

    def execute_code(self, code):
        """Execute arbitrary Blender Python code"""
        # This is powerful but potentially dangerous - use with caution
        try:
            # Create a local namespace for execution
            namespace = {"bpy": bpy}

            # Capture stdout during execution, and return it as result
            capture_buffer = io.StringIO()
            with redirect_stdout(capture_buffer):
                exec(code, namespace)

            captured_output = capture_buffer.getvalue()
            return {"executed": True, "result": captured_output}
        except Exception as e:
            raise Exception(f"Code execution error: {str(e)}")



    def get_polyhaven_categories(self, asset_type):
        """Get categories for a specific asset type from Polyhaven"""
        try:
            if asset_type not in ["hdris", "textures", "models", "all"]:
                return {"error": f"Invalid asset type: {asset_type}. Must be one of: hdris, textures, models, all"}

            response = requests.get(f"https://api.polyhaven.com/categories/{asset_type}", headers=REQ_HEADERS)
            if response.status_code == 200:
                return {"categories": response.json()}
            else:
                return {"error": f"API request failed with status code {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def search_polyhaven_assets(self, asset_type=None, categories=None):
        """Search for assets from Polyhaven with optional filtering"""
        try:
            url = "https://api.polyhaven.com/assets"
            params = {}

            if asset_type and asset_type != "all":
                if asset_type not in ["hdris", "textures", "models"]:
                    return {"error": f"Invalid asset type: {asset_type}. Must be one of: hdris, textures, models, all"}
                params["type"] = asset_type

            if categories:
                params["categories"] = categories

            response = requests.get(url, params=params, headers=REQ_HEADERS)
            if response.status_code == 200:
                # Limit the response size to avoid overwhelming Blender
                assets = response.json()
                # Return only the first 20 assets to keep response size manageable
                limited_assets = {}
                for i, (key, value) in enumerate(assets.items()):
                    if i >= 20:  # Limit to 20 assets
                        break
                    limited_assets[key] = value

                return {"assets": limited_assets, "total_count": len(assets), "returned_count": len(limited_assets)}
            else:
                return {"error": f"API request failed with status code {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def download_polyhaven_asset(self, asset_id, asset_type, resolution="1k", file_format=None):
        try:
            # First get the files information
            files_response = requests.get(f"https://api.polyhaven.com/files/{asset_id}", headers=REQ_HEADERS)
            if files_response.status_code != 200:
                return {"error": f"Failed to get asset files: {files_response.status_code}"}

            files_data = files_response.json()

            # Handle different asset types
            if asset_type == "hdris":
                # For HDRIs, download the .hdr or .exr file
                if not file_format:
                    file_format = "hdr"  # Default format for HDRIs

                if "hdri" in files_data and resolution in files_data["hdri"] and file_format in files_data["hdri"][resolution]:
                    file_info = files_data["hdri"][resolution][file_format]
                    file_url = file_info["url"]

                    # For HDRIs, we need to save to a temporary file first
                    # since Blender can't properly load HDR data directly from memory
                    with tempfile.NamedTemporaryFile(suffix=f".{file_format}", delete=False) as tmp_file:
                        # Download the file
                        response = requests.get(file_url, headers=REQ_HEADERS)
                        if response.status_code != 200:
                            return {"error": f"Failed to download HDRI: {response.status_code}"}

                        tmp_file.write(response.content)
                        tmp_path = tmp_file.name

                    try:
                        # Create a new world if none exists
                        if not bpy.data.worlds:
                            bpy.data.worlds.new("World")

                        world = bpy.data.worlds[0]
                        world.use_nodes = True
                        node_tree = world.node_tree

                        # Clear existing nodes
                        for node in node_tree.nodes:
                            node_tree.nodes.remove(node)

                        # Create nodes
                        tex_coord = node_tree.nodes.new(type='ShaderNodeTexCoord')
                        tex_coord.location = (-800, 0)

                        mapping = node_tree.nodes.new(type='ShaderNodeMapping')
                        mapping.location = (-600, 0)

                        # Load the image from the temporary file
                        env_tex = node_tree.nodes.new(type='ShaderNodeTexEnvironment')
                        env_tex.location = (-400, 0)
                        env_tex.image = bpy.data.images.load(tmp_path)

                        # Use a color space that exists in all Blender versions
                        if file_format.lower() == 'exr':
                            # Try to use Linear color space for EXR files
                            try:
                                env_tex.image.colorspace_settings.name = 'Linear'
                            except:
                                # Fallback to Non-Color if Linear isn't available
                                env_tex.image.colorspace_settings.name = 'Non-Color'
                        else:  # hdr
                            # For HDR files, try these options in order
                            for color_space in ['Linear', 'Linear Rec.709', 'Non-Color']:
                                try:
                                    env_tex.image.colorspace_settings.name = color_space
                                    break  # Stop if we successfully set a color space
                                except:
                                    continue

                        background = node_tree.nodes.new(type='ShaderNodeBackground')
                        background.location = (-200, 0)

                        output = node_tree.nodes.new(type='ShaderNodeOutputWorld')
                        output.location = (0, 0)

                        # Connect nodes
                        node_tree.links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])
                        node_tree.links.new(mapping.outputs['Vector'], env_tex.inputs['Vector'])
                        node_tree.links.new(env_tex.outputs['Color'], background.inputs['Color'])
                        node_tree.links.new(background.outputs['Background'], output.inputs['Surface'])

                        # Set as active world
                        bpy.context.scene.world = world

                        # Clean up temporary file
                        try:
                            tempfile._cleanup()  # This will clean up all temporary files
                        except:
                            pass

                        return {
                            "success": True,
                            "message": f"HDRI {asset_id} imported successfully",
                            "image_name": env_tex.image.name
                        }
                    except Exception as e:
                        return {"error": f"Failed to set up HDRI in Blender: {str(e)}"}
                else:
                    return {"error": f"Requested resolution or format not available for this HDRI"}

            elif asset_type == "textures":
                if not file_format:
                    file_format = "jpg"  # Default format for textures

                downloaded_maps = {}

                try:
                    for map_type in files_data:
                        if map_type not in ["blend", "gltf"]:  # Skip non-texture files
                            if resolution in files_data[map_type] and file_format in files_data[map_type][resolution]:
                                file_info = files_data[map_type][resolution][file_format]
                                file_url = file_info["url"]

                                # Use NamedTemporaryFile like we do for HDRIs
                                with tempfile.NamedTemporaryFile(suffix=f".{file_format}", delete=False) as tmp_file:
                                    # Download the file
                                    response = requests.get(file_url, headers=REQ_HEADERS)
                                    if response.status_code == 200:
                                        tmp_file.write(response.content)
                                        tmp_path = tmp_file.name

                                        # Load image from temporary file
                                        image = bpy.data.images.load(tmp_path)
                                        image.name = f"{asset_id}_{map_type}.{file_format}"

                                        # Pack the image into .blend file
                                        image.pack()

                                        # Set color space based on map type
                                        if map_type in ['color', 'diffuse', 'albedo']:
                                            try:
                                                image.colorspace_settings.name = 'sRGB'
                                            except:
                                                pass
                                        else:
                                            try:
                                                image.colorspace_settings.name = 'Non-Color'
                                            except:
                                                pass

                                        downloaded_maps[map_type] = image

                                        # Clean up temporary file
                                        try:
                                            os.unlink(tmp_path)
                                        except:
                                            pass

                    if not downloaded_maps:
                        return {"error": f"No texture maps found for the requested resolution and format"}

                    # Create a new material with the downloaded textures
                    mat = bpy.data.materials.new(name=asset_id)
                    mat.use_nodes = True
                    nodes = mat.node_tree.nodes
                    links = mat.node_tree.links

                    # Clear default nodes
                    for node in nodes:
                        nodes.remove(node)

                    # Create output node
                    output = nodes.new(type='ShaderNodeOutputMaterial')
                    output.location = (300, 0)

                    # Create principled BSDF node
                    principled = nodes.new(type='ShaderNodeBsdfPrincipled')
                    principled.location = (0, 0)
                    links.new(principled.outputs[0], output.inputs[0])

                    # Add texture nodes based on available maps
                    tex_coord = nodes.new(type='ShaderNodeTexCoord')
                    tex_coord.location = (-800, 0)

                    mapping = nodes.new(type='ShaderNodeMapping')
                    mapping.location = (-600, 0)
                    mapping.vector_type = 'TEXTURE'  # Changed from default 'POINT' to 'TEXTURE'
                    links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])

                    # Position offset for texture nodes
                    x_pos = -400
                    y_pos = 300

                    # Connect different texture maps
                    for map_type, image in downloaded_maps.items():
                        tex_node = nodes.new(type='ShaderNodeTexImage')
                        tex_node.location = (x_pos, y_pos)
                        tex_node.image = image

                        # Set color space based on map type
                        if map_type.lower() in ['color', 'diffuse', 'albedo']:
                            try:
                                tex_node.image.colorspace_settings.name = 'sRGB'
                            except:
                                pass  # Use default if sRGB not available
                        else:
                            try:
                                tex_node.image.colorspace_settings.name = 'Non-Color'
                            except:
                                pass  # Use default if Non-Color not available

                        links.new(mapping.outputs['Vector'], tex_node.inputs['Vector'])

                        # Connect to appropriate input on Principled BSDF
                        if map_type.lower() in ['color', 'diffuse', 'albedo']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
                        elif map_type.lower() in ['roughness', 'rough']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Roughness'])
                        elif map_type.lower() in ['metallic', 'metalness', 'metal']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Metallic'])
                        elif map_type.lower() in ['normal', 'nor']:
                            # Add normal map node
                            normal_map = nodes.new(type='ShaderNodeNormalMap')
                            normal_map.location = (x_pos + 200, y_pos)
                            links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                            links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
                        elif map_type in ['displacement', 'disp', 'height']:
                            # Add displacement node
                            disp_node = nodes.new(type='ShaderNodeDisplacement')
                            disp_node.location = (x_pos + 200, y_pos - 200)
                            links.new(tex_node.outputs['Color'], disp_node.inputs['Height'])
                            links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])

                        y_pos -= 250

                    return {
                        "success": True,
                        "message": f"Texture {asset_id} imported as material",
                        "material": mat.name,
                        "maps": list(downloaded_maps.keys())
                    }

                except Exception as e:
                    return {"error": f"Failed to process textures: {str(e)}"}

            elif asset_type == "models":
                # For models, prefer glTF format if available
                if not file_format:
                    file_format = "gltf"  # Default format for models

                if file_format in files_data and resolution in files_data[file_format]:
                    file_info = files_data[file_format][resolution][file_format]
                    file_url = file_info["url"]

                    # Create a temporary directory to store the model and its dependencies
                    temp_dir = tempfile.mkdtemp()
                    main_file_path = ""

                    try:
                        # Download the main model file
                        main_file_name = file_url.split("/")[-1]
                        main_file_path = os.path.join(temp_dir, main_file_name)

                        response = requests.get(file_url, headers=REQ_HEADERS)
                        if response.status_code != 200:
                            return {"error": f"Failed to download model: {response.status_code}"}

                        with open(main_file_path, "wb") as f:
                            f.write(response.content)

                        # Check for included files and download them
                        if "include" in file_info and file_info["include"]:
                            for include_path, include_info in file_info["include"].items():
                                # Get the URL for the included file - this is the fix
                                include_url = include_info["url"]

                                # Create the directory structure for the included file
                                include_file_path = os.path.join(temp_dir, include_path)
                                os.makedirs(os.path.dirname(include_file_path), exist_ok=True)

                                # Download the included file
                                include_response = requests.get(include_url, headers=REQ_HEADERS)
                                if include_response.status_code == 200:
                                    with open(include_file_path, "wb") as f:
                                        f.write(include_response.content)
                                else:
                                    print(f"Failed to download included file: {include_path}")

                        # Import the model into Blender
                        if file_format == "gltf" or file_format == "glb":
                            bpy.ops.import_scene.gltf(filepath=main_file_path)
                        elif file_format == "fbx":
                            bpy.ops.import_scene.fbx(filepath=main_file_path)
                        elif file_format == "obj":
                            bpy.ops.import_scene.obj(filepath=main_file_path)
                        elif file_format == "blend":
                            # For blend files, we need to append or link
                            with bpy.data.libraries.load(main_file_path, link=False) as (data_from, data_to):
                                data_to.objects = data_from.objects

                            # Link the objects to the scene
                            for obj in data_to.objects:
                                if obj is not None:
                                    bpy.context.collection.objects.link(obj)
                        else:
                            return {"error": f"Unsupported model format: {file_format}"}

                        # Get the names of imported objects
                        imported_objects = [obj.name for obj in bpy.context.selected_objects]

                        return {
                            "success": True,
                            "message": f"Model {asset_id} imported successfully",
                            "imported_objects": imported_objects
                        }
                    except Exception as e:
                        return {"error": f"Failed to import model: {str(e)}"}
                    finally:
                        # Clean up temporary directory
                        with suppress(Exception):
                            shutil.rmtree(temp_dir)
                else:
                    return {"error": f"Requested format or resolution not available for this model"}

            else:
                return {"error": f"Unsupported asset type: {asset_type}"}

        except Exception as e:
            return {"error": f"Failed to download asset: {str(e)}"}

    def set_texture(self, object_name, texture_id):
        """Apply a previously downloaded Polyhaven texture to an object by creating a new material"""
        try:
            # Get the object
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}

            # Make sure object can accept materials
            if not hasattr(obj, 'data') or not hasattr(obj.data, 'materials'):
                return {"error": f"Object {object_name} cannot accept materials"}

            # Find all images related to this texture and ensure they're properly loaded
            texture_images = {}
            for img in bpy.data.images:
                if img.name.startswith(texture_id + "_"):
                    # Extract the map type from the image name
                    map_type = img.name.split('_')[-1].split('.')[0]

                    # Force a reload of the image
                    img.reload()

                    # Ensure proper color space
                    if map_type.lower() in ['color', 'diffuse', 'albedo']:
                        try:
                            img.colorspace_settings.name = 'sRGB'
                        except:
                            pass
                    else:
                        try:
                            img.colorspace_settings.name = 'Non-Color'
                        except:
                            pass

                    # Ensure the image is packed
                    if not img.packed_file:
                        img.pack()

                    texture_images[map_type] = img
                    print(f"Loaded texture map: {map_type} - {img.name}")

                    # Debug info
                    print(f"Image size: {img.size[0]}x{img.size[1]}")
                    print(f"Color space: {img.colorspace_settings.name}")
                    print(f"File format: {img.file_format}")
                    print(f"Is packed: {bool(img.packed_file)}")

            if not texture_images:
                return {"error": f"No texture images found for: {texture_id}. Please download the texture first."}

            # Create a new material
            new_mat_name = f"{texture_id}_material_{object_name}"

            # Remove any existing material with this name to avoid conflicts
            existing_mat = bpy.data.materials.get(new_mat_name)
            if existing_mat:
                bpy.data.materials.remove(existing_mat)

            new_mat = bpy.data.materials.new(name=new_mat_name)
            new_mat.use_nodes = True

            # Set up the material nodes
            nodes = new_mat.node_tree.nodes
            links = new_mat.node_tree.links

            # Clear default nodes
            nodes.clear()

            # Create output node
            output = nodes.new(type='ShaderNodeOutputMaterial')
            output.location = (600, 0)

            # Create principled BSDF node
            principled = nodes.new(type='ShaderNodeBsdfPrincipled')
            principled.location = (300, 0)
            links.new(principled.outputs[0], output.inputs[0])

            # Add texture nodes based on available maps
            tex_coord = nodes.new(type='ShaderNodeTexCoord')
            tex_coord.location = (-800, 0)

            mapping = nodes.new(type='ShaderNodeMapping')
            mapping.location = (-600, 0)
            mapping.vector_type = 'TEXTURE'  # Changed from default 'POINT' to 'TEXTURE'
            links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])

            # Position offset for texture nodes
            x_pos = -400
            y_pos = 300

            # Connect different texture maps
            for map_type, image in texture_images.items():
                tex_node = nodes.new(type='ShaderNodeTexImage')
                tex_node.location = (x_pos, y_pos)
                tex_node.image = image

                # Set color space based on map type
                if map_type.lower() in ['color', 'diffuse', 'albedo']:
                    try:
                        tex_node.image.colorspace_settings.name = 'sRGB'
                    except:
                        pass  # Use default if sRGB not available
                else:
                    try:
                        tex_node.image.colorspace_settings.name = 'Non-Color'
                    except:
                        pass  # Use default if Non-Color not available

                links.new(mapping.outputs['Vector'], tex_node.inputs['Vector'])

                # Connect to appropriate input on Principled BSDF
                if map_type.lower() in ['color', 'diffuse', 'albedo']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
                elif map_type.lower() in ['roughness', 'rough']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Roughness'])
                elif map_type.lower() in ['metallic', 'metalness', 'metal']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Metallic'])
                elif map_type.lower() in ['normal', 'nor', 'dx', 'gl']:
                    # Add normal map node
                    normal_map = nodes.new(type='ShaderNodeNormalMap')
                    normal_map.location = (x_pos + 200, y_pos)
                    links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                    links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
                elif map_type.lower() in ['displacement', 'disp', 'height']:
                    # Add displacement node
                    disp_node = nodes.new(type='ShaderNodeDisplacement')
                    disp_node.location = (x_pos + 200, y_pos - 200)
                    disp_node.inputs['Scale'].default_value = 0.1  # Reduce displacement strength
                    links.new(tex_node.outputs['Color'], disp_node.inputs['Height'])
                    links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])

                y_pos -= 250

            # Second pass: Connect nodes with proper handling for special cases
            texture_nodes = {}

            # First find all texture nodes and store them by map type
            for node in nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    for map_type, image in texture_images.items():
                        if node.image == image:
                            texture_nodes[map_type] = node
                            break

            # Now connect everything using the nodes instead of images
            # Handle base color (diffuse)
            for map_name in ['color', 'diffuse', 'albedo']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Base Color'])
                    print(f"Connected {map_name} to Base Color")
                    break

            # Handle roughness
            for map_name in ['roughness', 'rough']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Roughness'])
                    print(f"Connected {map_name} to Roughness")
                    break

            # Handle metallic
            for map_name in ['metallic', 'metalness', 'metal']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Metallic'])
                    print(f"Connected {map_name} to Metallic")
                    break

            # Handle normal maps
            for map_name in ['gl', 'dx', 'nor']:
                if map_name in texture_nodes:
                    normal_map_node = nodes.new(type='ShaderNodeNormalMap')
                    normal_map_node.location = (100, 100)
                    links.new(texture_nodes[map_name].outputs['Color'], normal_map_node.inputs['Color'])
                    links.new(normal_map_node.outputs['Normal'], principled.inputs['Normal'])
                    print(f"Connected {map_name} to Normal")
                    break

            # Handle displacement
            for map_name in ['displacement', 'disp', 'height']:
                if map_name in texture_nodes:
                    disp_node = nodes.new(type='ShaderNodeDisplacement')
                    disp_node.location = (300, -200)
                    disp_node.inputs['Scale'].default_value = 0.1  # Reduce displacement strength
                    links.new(texture_nodes[map_name].outputs['Color'], disp_node.inputs['Height'])
                    links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])
                    print(f"Connected {map_name} to Displacement")
                    break

            # Handle ARM texture (Ambient Occlusion, Roughness, Metallic)
            if 'arm' in texture_nodes:
                separate_rgb = nodes.new(type='ShaderNodeSeparateRGB')
                separate_rgb.location = (-200, -100)
                links.new(texture_nodes['arm'].outputs['Color'], separate_rgb.inputs['Image'])

                # Connect Roughness (G) if no dedicated roughness map
                if not any(map_name in texture_nodes for map_name in ['roughness', 'rough']):
                    links.new(separate_rgb.outputs['G'], principled.inputs['Roughness'])
                    print("Connected ARM.G to Roughness")

                # Connect Metallic (B) if no dedicated metallic map
                if not any(map_name in texture_nodes for map_name in ['metallic', 'metalness', 'metal']):
                    links.new(separate_rgb.outputs['B'], principled.inputs['Metallic'])
                    print("Connected ARM.B to Metallic")

                # For AO (R channel), multiply with base color if we have one
                base_color_node = None
                for map_name in ['color', 'diffuse', 'albedo']:
                    if map_name in texture_nodes:
                        base_color_node = texture_nodes[map_name]
                        break

                if base_color_node:
                    mix_node = nodes.new(type='ShaderNodeMixRGB')
                    mix_node.location = (100, 200)
                    mix_node.blend_type = 'MULTIPLY'
                    mix_node.inputs['Fac'].default_value = 0.8  # 80% influence

                    # Disconnect direct connection to base color
                    for link in base_color_node.outputs['Color'].links:
                        if link.to_socket == principled.inputs['Base Color']:
                            links.remove(link)

                    # Connect through the mix node
                    links.new(base_color_node.outputs['Color'], mix_node.inputs[1])
                    links.new(separate_rgb.outputs['R'], mix_node.inputs[2])
                    links.new(mix_node.outputs['Color'], principled.inputs['Base Color'])
                    print("Connected ARM.R to AO mix with Base Color")

            # Handle AO (Ambient Occlusion) if separate
            if 'ao' in texture_nodes:
                base_color_node = None
                for map_name in ['color', 'diffuse', 'albedo']:
                    if map_name in texture_nodes:
                        base_color_node = texture_nodes[map_name]
                        break

                if base_color_node:
                    mix_node = nodes.new(type='ShaderNodeMixRGB')
                    mix_node.location = (100, 200)
                    mix_node.blend_type = 'MULTIPLY'
                    mix_node.inputs['Fac'].default_value = 0.8  # 80% influence

                    # Disconnect direct connection to base color
                    for link in base_color_node.outputs['Color'].links:
                        if link.to_socket == principled.inputs['Base Color']:
                            links.remove(link)

                    # Connect through the mix node
                    links.new(base_color_node.outputs['Color'], mix_node.inputs[1])
                    links.new(texture_nodes['ao'].outputs['Color'], mix_node.inputs[2])
                    links.new(mix_node.outputs['Color'], principled.inputs['Base Color'])
                    print("Connected AO to mix with Base Color")

            # CRITICAL: Make sure to clear all existing materials from the object
            while len(obj.data.materials) > 0:
                obj.data.materials.pop(index=0)

            # Assign the new material to the object
            obj.data.materials.append(new_mat)

            # CRITICAL: Make the object active and select it
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            # CRITICAL: Force Blender to update the material
            bpy.context.view_layer.update()

            # Get the list of texture maps
            texture_maps = list(texture_images.keys())

            # Get info about texture nodes for debugging
            material_info = {
                "name": new_mat.name,
                "has_nodes": new_mat.use_nodes,
                "node_count": len(new_mat.node_tree.nodes),
                "texture_nodes": []
            }

            for node in new_mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    connections = []
                    for output in node.outputs:
                        for link in output.links:
                            connections.append(f"{output.name} → {link.to_node.name}.{link.to_socket.name}")

                    material_info["texture_nodes"].append({
                        "name": node.name,
                        "image": node.image.name,
                        "colorspace": node.image.colorspace_settings.name,
                        "connections": connections
                    })

            return {
                "success": True,
                "message": f"Created new material and applied texture {texture_id} to {object_name}",
                "material": new_mat.name,
                "maps": texture_maps,
                "material_info": material_info
            }

        except Exception as e:
            print(f"Error in set_texture: {str(e)}")
            traceback.print_exc()
            return {"error": f"Failed to apply texture: {str(e)}"}

    def get_telemetry_consent(self):
        """Get the current telemetry consent status"""
        try:
            # Get addon preferences - use the module name
            addon_prefs = bpy.context.preferences.addons.get(__name__)
            if addon_prefs:
                consent = addon_prefs.preferences.telemetry_consent
            else:
                # Fallback to default if preferences not available
                consent = True
        except (AttributeError, KeyError):
            # Fallback to default if preferences not available
            consent = True
        return {"consent": consent}

    def get_polyhaven_status(self):
        """Get the current status of PolyHaven integration"""
        enabled = bpy.context.scene.blendermcp_use_polyhaven
        if enabled:
            return {"enabled": True, "message": "PolyHaven integration is enabled and ready to use."}
        else:
            return {
                "enabled": False,
                "message": """PolyHaven integration is currently disabled. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Check the 'Use assets from Poly Haven' checkbox
                            3. Restart the connection to Claude"""
        }

    #region Hyper3D
    def get_hyper3d_status(self):
        """Get the current status of Hyper3D Rodin integration"""
        enabled = bpy.context.scene.blendermcp_use_hyper3d
        if enabled:
            if not bpy.context.scene.blendermcp_hyper3d_api_key:
                return {
                    "enabled": False,
                    "message": """Hyper3D Rodin integration is currently enabled, but API key is not given. To enable it:
                                1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                                2. Keep the 'Use Hyper3D Rodin 3D model generation' checkbox checked
                                3. Choose the right plaform and fill in the API Key
                                4. Restart the connection to Claude"""
                }
            mode = bpy.context.scene.blendermcp_hyper3d_mode
            message = f"Hyper3D Rodin integration is enabled and ready to use. Mode: {mode}. " + \
                f"Key type: {'private' if bpy.context.scene.blendermcp_hyper3d_api_key != RODIN_FREE_TRIAL_KEY else 'free_trial'}"
            return {
                "enabled": True,
                "message": message
            }
        else:
            return {
                "enabled": False,
                "message": """Hyper3D Rodin integration is currently disabled. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Check the 'Use Hyper3D Rodin 3D model generation' checkbox
                            3. Restart the connection to Claude"""
            }

    def create_rodin_job(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.create_rodin_job_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.create_rodin_job_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def create_rodin_job_main_site(
            self,
            text_prompt: str=None,
            images: list[tuple[str, str]]=None,
            bbox_condition=None
        ):
        try:
            if images is None:
                images = []
            """Call Rodin API, get the job uuid and subscription key"""
            files = [
                *[("images", (f"{i:04d}{img_suffix}", img)) for i, (img_suffix, img) in enumerate(images)],
                ("tier", (None, "Sketch")),
                ("mesh_mode", (None, "Raw")),
            ]
            if text_prompt:
                files.append(("prompt", (None, text_prompt)))
            if bbox_condition:
                files.append(("bbox_condition", (None, json.dumps(bbox_condition))))
            response = requests.post(
                "https://hyperhuman.deemos.com/api/v2/rodin",
                headers={
                    "Authorization": f"Bearer {bpy.context.scene.blendermcp_hyper3d_api_key}",
                },
                files=files
            )
            data = response.json()
            return data
        except Exception as e:
            return {"error": str(e)}

    def create_rodin_job_fal_ai(
            self,
            text_prompt: str=None,
            images: list[tuple[str, str]]=None,
            bbox_condition=None
        ):
        try:
            req_data = {
                "tier": "Sketch",
            }
            if images:
                req_data["input_image_urls"] = images
            if text_prompt:
                req_data["prompt"] = text_prompt
            if bbox_condition:
                req_data["bbox_condition"] = bbox_condition
            response = requests.post(
                "https://queue.fal.run/fal-ai/hyper3d/rodin",
                headers={
                    "Authorization": f"Key {bpy.context.scene.blendermcp_hyper3d_api_key}",
                    "Content-Type": "application/json",
                },
                json=req_data
            )
            data = response.json()
            return data
        except Exception as e:
            return {"error": str(e)}

    def poll_rodin_job_status(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.poll_rodin_job_status_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.poll_rodin_job_status_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def poll_rodin_job_status_main_site(self, subscription_key: str):
        """Call the job status API to get the job status"""
        response = requests.post(
            "https://hyperhuman.deemos.com/api/v2/status",
            headers={
                "Authorization": f"Bearer {bpy.context.scene.blendermcp_hyper3d_api_key}",
            },
            json={
                "subscription_key": subscription_key,
            },
        )
        data = response.json()
        return {
            "status_list": [i["status"] for i in data["jobs"]]
        }

    def poll_rodin_job_status_fal_ai(self, request_id: str):
        """Call the job status API to get the job status"""
        response = requests.get(
            f"https://queue.fal.run/fal-ai/hyper3d/requests/{request_id}/status",
            headers={
                "Authorization": f"KEY {bpy.context.scene.blendermcp_hyper3d_api_key}",
            },
        )
        data = response.json()
        return data

    @staticmethod
    def _clean_imported_glb(filepath, mesh_name=None):
        # Get the set of existing objects before import
        existing_objects = set(bpy.data.objects)

        # Import the GLB file
        bpy.ops.import_scene.gltf(filepath=filepath)

        # Ensure the context is updated
        bpy.context.view_layer.update()

        # Get all imported objects
        imported_objects = list(set(bpy.data.objects) - existing_objects)
        # imported_objects = [obj for obj in bpy.context.view_layer.objects if obj.select_get()]

        if not imported_objects:
            print("Error: No objects were imported.")
            return

        # Identify the mesh object
        mesh_obj = None

        if len(imported_objects) == 1 and imported_objects[0].type == 'MESH':
            mesh_obj = imported_objects[0]
            print("Single mesh imported, no cleanup needed.")
        else:
            if len(imported_objects) == 2:
                empty_objs = [i for i in imported_objects if i.type == "EMPTY"]
                if len(empty_objs) != 1:
                    print("Error: Expected an empty node with one mesh child or a single mesh object.")
                    return
                parent_obj = empty_objs.pop()
                if len(parent_obj.children) == 1:
                    potential_mesh = parent_obj.children[0]
                    if potential_mesh.type == 'MESH':
                        print("GLB structure confirmed: Empty node with one mesh child.")

                        # Unparent the mesh from the empty node
                        potential_mesh.parent = None

                        # Remove the empty node
                        bpy.data.objects.remove(parent_obj)
                        print("Removed empty node, keeping only the mesh.")

                        mesh_obj = potential_mesh
                    else:
                        print("Error: Child is not a mesh object.")
                        return
                else:
                    print("Error: Expected an empty node with one mesh child or a single mesh object.")
                    return
            else:
                print("Error: Expected an empty node with one mesh child or a single mesh object.")
                return

        # Rename the mesh if needed
        try:
            if mesh_obj and mesh_obj.name is not None and mesh_name:
                mesh_obj.name = mesh_name
                if mesh_obj.data.name is not None:
                    mesh_obj.data.name = mesh_name
                print(f"Mesh renamed to: {mesh_name}")
        except Exception as e:
            print("Having issue with renaming, give up renaming.")

        return mesh_obj

    def import_generated_asset(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.import_generated_asset_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.import_generated_asset_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def import_generated_asset_main_site(self, task_uuid: str, name: str):
        """Fetch the generated asset, import into blender"""
        response = requests.post(
            "https://hyperhuman.deemos.com/api/v2/download",
            headers={
                "Authorization": f"Bearer {bpy.context.scene.blendermcp_hyper3d_api_key}",
            },
            json={
                'task_uuid': task_uuid
            }
        )
        data_ = response.json()
        temp_file = None
        for i in data_["list"]:
            if i["name"].endswith(".glb"):
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False,
                    prefix=task_uuid,
                    suffix=".glb",
                )

                try:
                    # Download the content
                    response = requests.get(i["url"], stream=True)
                    response.raise_for_status()  # Raise an exception for HTTP errors

                    # Write the content to the temporary file
                    for chunk in response.iter_content(chunk_size=8192):
                        temp_file.write(chunk)

                    # Close the file
                    temp_file.close()

                except Exception as e:
                    # Clean up the file if there's an error
                    temp_file.close()
                    os.unlink(temp_file.name)
                    return {"succeed": False, "error": str(e)}

                break
        else:
            return {"succeed": False, "error": "Generation failed. Please first make sure that all jobs of the task are done and then try again later."}

        try:
            obj = self._clean_imported_glb(
                filepath=temp_file.name,
                mesh_name=name
            )
            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box

            return {
                "succeed": True, **result
            }
        except Exception as e:
            return {"succeed": False, "error": str(e)}

    def import_generated_asset_fal_ai(self, request_id: str, name: str):
        """Fetch the generated asset, import into blender"""
        response = requests.get(
            f"https://queue.fal.run/fal-ai/hyper3d/requests/{request_id}",
            headers={
                "Authorization": f"Key {bpy.context.scene.blendermcp_hyper3d_api_key}",
            }
        )
        data_ = response.json()
        temp_file = None

        temp_file = tempfile.NamedTemporaryFile(
            delete=False,
            prefix=request_id,
            suffix=".glb",
        )

        try:
            # Download the content
            response = requests.get(data_["model_mesh"]["url"], stream=True)
            response.raise_for_status()  # Raise an exception for HTTP errors

            # Write the content to the temporary file
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)

            # Close the file
            temp_file.close()

        except Exception as e:
            # Clean up the file if there's an error
            temp_file.close()
            os.unlink(temp_file.name)
            return {"succeed": False, "error": str(e)}

        try:
            obj = self._clean_imported_glb(
                filepath=temp_file.name,
                mesh_name=name
            )
            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box

            return {
                "succeed": True, **result
            }
        except Exception as e:
            return {"succeed": False, "error": str(e)}
    #endregion
 
    #region Sketchfab API
    def get_sketchfab_status(self):
        """Get the current status of Sketchfab integration"""
        enabled = bpy.context.scene.blendermcp_use_sketchfab
        api_key = bpy.context.scene.blendermcp_sketchfab_api_key

        # Test the API key if present
        if api_key:
            try:
                headers = {
                    "Authorization": f"Token {api_key}"
                }

                response = requests.get(
                    "https://api.sketchfab.com/v3/me",
                    headers=headers,
                    timeout=30  # Add timeout of 30 seconds
                )

                if response.status_code == 200:
                    user_data = response.json()
                    username = user_data.get("username", "Unknown user")
                    return {
                        "enabled": True,
                        "message": f"Sketchfab integration is enabled and ready to use. Logged in as: {username}"
                    }
                else:
                    return {
                        "enabled": False,
                        "message": f"Sketchfab API key seems invalid. Status code: {response.status_code}"
                    }
            except requests.exceptions.Timeout:
                return {
                    "enabled": False,
                    "message": "Timeout connecting to Sketchfab API. Check your internet connection."
                }
            except Exception as e:
                return {
                    "enabled": False,
                    "message": f"Error testing Sketchfab API key: {str(e)}"
                }

        if enabled and api_key:
            return {"enabled": True, "message": "Sketchfab integration is enabled and ready to use."}
        elif enabled and not api_key:
            return {
                "enabled": False,
                "message": """Sketchfab integration is currently enabled, but API key is not given. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Keep the 'Use Sketchfab' checkbox checked
                            3. Enter your Sketchfab API Key
                            4. Restart the connection to Claude"""
            }
        else:
            return {
                "enabled": False,
                "message": """Sketchfab integration is currently disabled. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Check the 'Use assets from Sketchfab' checkbox
                            3. Enter your Sketchfab API Key
                            4. Restart the connection to Claude"""
            }

    def search_sketchfab_models(self, query, categories=None, count=20, downloadable=True):
        """Search for models on Sketchfab based on query and optional filters"""
        try:
            api_key = bpy.context.scene.blendermcp_sketchfab_api_key
            if not api_key:
                return {"error": "Sketchfab API key is not configured"}

            # Build search parameters with exact fields from Sketchfab API docs
            params = {
                "type": "models",
                "q": query,
                "count": count,
                "downloadable": downloadable,
                "archives_flavours": False
            }

            if categories:
                params["categories"] = categories

            # Make API request to Sketchfab search endpoint
            # The proper format according to Sketchfab API docs for API key auth
            headers = {
                "Authorization": f"Token {api_key}"
            }


            # Use the search endpoint as specified in the API documentation
            response = requests.get(
                "https://api.sketchfab.com/v3/search",
                headers=headers,
                params=params,
                timeout=30  # Add timeout of 30 seconds
            )

            if response.status_code == 401:
                return {"error": "Authentication failed (401). Check your API key."}

            if response.status_code != 200:
                return {"error": f"API request failed with status code {response.status_code}"}

            response_data = response.json()

            # Safety check on the response structure
            if response_data is None:
                return {"error": "Received empty response from Sketchfab API"}

            # Handle 'results' potentially missing from response
            results = response_data.get("results", [])
            if not isinstance(results, list):
                return {"error": f"Unexpected response format from Sketchfab API: {response_data}"}

            return response_data

        except requests.exceptions.Timeout:
            return {"error": "Request timed out. Check your internet connection."}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON response from Sketchfab API: {str(e)}"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    def get_sketchfab_model_preview(self, uid):
        """Get thumbnail preview image of a Sketchfab model by its UID"""
        try:
            import base64
            
            api_key = bpy.context.scene.blendermcp_sketchfab_api_key
            if not api_key:
                return {"error": "Sketchfab API key is not configured"}

            headers = {"Authorization": f"Token {api_key}"}
            
            # Get model info which includes thumbnails
            response = requests.get(
                f"https://api.sketchfab.com/v3/models/{uid}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 401:
                return {"error": "Authentication failed (401). Check your API key."}
            
            if response.status_code == 404:
                return {"error": f"Model not found: {uid}"}
            
            if response.status_code != 200:
                return {"error": f"Failed to get model info: {response.status_code}"}
            
            data = response.json()
            thumbnails = data.get("thumbnails", {}).get("images", [])
            
            if not thumbnails:
                return {"error": "No thumbnail available for this model"}
            
            # Find a suitable thumbnail (prefer medium size ~640px)
            selected_thumbnail = None
            for thumb in thumbnails:
                width = thumb.get("width", 0)
                if 400 <= width <= 800:
                    selected_thumbnail = thumb
                    break
            
            # Fallback to the first available thumbnail
            if not selected_thumbnail:
                selected_thumbnail = thumbnails[0]
            
            thumbnail_url = selected_thumbnail.get("url")
            if not thumbnail_url:
                return {"error": "Thumbnail URL not found"}
            
            # Download the thumbnail image
            img_response = requests.get(thumbnail_url, timeout=30)
            if img_response.status_code != 200:
                return {"error": f"Failed to download thumbnail: {img_response.status_code}"}
            
            # Encode image as base64
            image_data = base64.b64encode(img_response.content).decode('ascii')
            
            # Determine format from content type or URL
            content_type = img_response.headers.get("Content-Type", "")
            if "png" in content_type or thumbnail_url.endswith(".png"):
                img_format = "png"
            else:
                img_format = "jpeg"
            
            # Get additional model info for context
            model_name = data.get("name", "Unknown")
            author = data.get("user", {}).get("username", "Unknown")
            
            return {
                "success": True,
                "image_data": image_data,
                "format": img_format,
                "model_name": model_name,
                "author": author,
                "uid": uid,
                "thumbnail_width": selected_thumbnail.get("width"),
                "thumbnail_height": selected_thumbnail.get("height")
            }
            
        except requests.exceptions.Timeout:
            return {"error": "Request timed out. Check your internet connection."}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"Failed to get model preview: {str(e)}"}

    def download_sketchfab_model(self, uid, normalize_size=False, target_size=1.0):
        """Download a model from Sketchfab by its UID
        
        Parameters:
        - uid: The unique identifier of the Sketchfab model
        - normalize_size: If True, scale the model so its largest dimension equals target_size
        - target_size: The target size in Blender units (meters) for the largest dimension
        """
        try:
            api_key = bpy.context.scene.blendermcp_sketchfab_api_key
            if not api_key:
                return {"error": "Sketchfab API key is not configured"}

            # Use proper authorization header for API key auth
            headers = {
                "Authorization": f"Token {api_key}"
            }

            # Request download URL using the exact endpoint from the documentation
            download_endpoint = f"https://api.sketchfab.com/v3/models/{uid}/download"

            response = requests.get(
                download_endpoint,
                headers=headers,
                timeout=30  # Add timeout of 30 seconds
            )

            if response.status_code == 401:
                return {"error": "Authentication failed (401). Check your API key."}

            if response.status_code != 200:
                return {"error": f"Download request failed with status code {response.status_code}"}

            data = response.json()

            # Safety check for None data
            if data is None:
                return {"error": "Received empty response from Sketchfab API for download request"}

            # Extract download URL with safety checks
            gltf_data = data.get("gltf")
            if not gltf_data:
                return {"error": "No gltf download URL available for this model. Response: " + str(data)}

            download_url = gltf_data.get("url")
            if not download_url:
                return {"error": "No download URL available for this model. Make sure the model is downloadable and you have access."}

            # Download the model (already has timeout)
            model_response = requests.get(download_url, timeout=60)  # 60 second timeout

            if model_response.status_code != 200:
                return {"error": f"Model download failed with status code {model_response.status_code}"}

            # Save to temporary file
            temp_dir = tempfile.mkdtemp()
            zip_file_path = os.path.join(temp_dir, f"{uid}.zip")

            with open(zip_file_path, "wb") as f:
                f.write(model_response.content)

            # Extract the zip file with enhanced security
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                # More secure zip slip prevention
                for file_info in zip_ref.infolist():
                    # Get the path of the file
                    file_path = file_info.filename

                    # Convert directory separators to the current OS style
                    # This handles both / and \ in zip entries
                    target_path = os.path.join(temp_dir, os.path.normpath(file_path))

                    # Get absolute paths for comparison
                    abs_temp_dir = os.path.abspath(temp_dir)
                    abs_target_path = os.path.abspath(target_path)

                    # Ensure the normalized path doesn't escape the target directory
                    if not abs_target_path.startswith(abs_temp_dir):
                        with suppress(Exception):
                            shutil.rmtree(temp_dir)
                        return {"error": "Security issue: Zip contains files with path traversal attempt"}

                    # Additional explicit check for directory traversal
                    if ".." in file_path:
                        with suppress(Exception):
                            shutil.rmtree(temp_dir)
                        return {"error": "Security issue: Zip contains files with directory traversal sequence"}

                # If all files passed security checks, extract them
                zip_ref.extractall(temp_dir)

            # Find the main glTF file
            gltf_files = [f for f in os.listdir(temp_dir) if f.endswith('.gltf') or f.endswith('.glb')]

            if not gltf_files:
                with suppress(Exception):
                    shutil.rmtree(temp_dir)
                return {"error": "No glTF file found in the downloaded model"}

            main_file = os.path.join(temp_dir, gltf_files[0])

            # Import the model
            bpy.ops.import_scene.gltf(filepath=main_file)

            # Get the imported objects
            imported_objects = list(bpy.context.selected_objects)
            imported_object_names = [obj.name for obj in imported_objects]

            # Clean up temporary files
            with suppress(Exception):
                shutil.rmtree(temp_dir)

            # Find root objects (objects without parents in the imported set)
            root_objects = [obj for obj in imported_objects if obj.parent is None]

            # Helper function to recursively get all mesh children
            def get_all_mesh_children(obj):
                """Recursively collect all mesh objects in the hierarchy"""
                meshes = []
                if obj.type == 'MESH':
                    meshes.append(obj)
                for child in obj.children:
                    meshes.extend(get_all_mesh_children(child))
                return meshes

            # Collect ALL meshes from the entire hierarchy (starting from roots)
            all_meshes = []
            for obj in root_objects:
                all_meshes.extend(get_all_mesh_children(obj))
            
            if all_meshes:
                # Calculate combined world bounding box for all meshes
                all_min = mathutils.Vector((float('inf'), float('inf'), float('inf')))
                all_max = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))
                
                for mesh_obj in all_meshes:
                    # Get world-space bounding box corners
                    for corner in mesh_obj.bound_box:
                        world_corner = mesh_obj.matrix_world @ mathutils.Vector(corner)
                        all_min.x = min(all_min.x, world_corner.x)
                        all_min.y = min(all_min.y, world_corner.y)
                        all_min.z = min(all_min.z, world_corner.z)
                        all_max.x = max(all_max.x, world_corner.x)
                        all_max.y = max(all_max.y, world_corner.y)
                        all_max.z = max(all_max.z, world_corner.z)
                
                # Calculate dimensions
                dimensions = [
                    all_max.x - all_min.x,
                    all_max.y - all_min.y,
                    all_max.z - all_min.z
                ]
                max_dimension = max(dimensions)
                
                # Apply normalization if requested
                scale_applied = 1.0
                if normalize_size and max_dimension > 0:
                    scale_factor = target_size / max_dimension
                    scale_applied = scale_factor
                    
                    # ✅ Only apply scale to ROOT objects (not children!)
                    # Child objects inherit parent's scale through matrix_world
                    for root in root_objects:
                        root.scale = (
                            root.scale.x * scale_factor,
                            root.scale.y * scale_factor,
                            root.scale.z * scale_factor
                        )
                    
                    # Update the scene to recalculate matrix_world for all objects
                    bpy.context.view_layer.update()
                    
                    # Recalculate bounding box after scaling
                    all_min = mathutils.Vector((float('inf'), float('inf'), float('inf')))
                    all_max = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))
                    
                    for mesh_obj in all_meshes:
                        for corner in mesh_obj.bound_box:
                            world_corner = mesh_obj.matrix_world @ mathutils.Vector(corner)
                            all_min.x = min(all_min.x, world_corner.x)
                            all_min.y = min(all_min.y, world_corner.y)
                            all_min.z = min(all_min.z, world_corner.z)
                            all_max.x = max(all_max.x, world_corner.x)
                            all_max.y = max(all_max.y, world_corner.y)
                            all_max.z = max(all_max.z, world_corner.z)
                    
                    dimensions = [
                        all_max.x - all_min.x,
                        all_max.y - all_min.y,
                        all_max.z - all_min.z
                    ]
                
                world_bounding_box = [[all_min.x, all_min.y, all_min.z], [all_max.x, all_max.y, all_max.z]]
            else:
                world_bounding_box = None
                dimensions = None
                scale_applied = 1.0

            result = {
                "success": True,
                "message": "Model imported successfully",
                "imported_objects": imported_object_names
            }
            
            if world_bounding_box:
                result["world_bounding_box"] = world_bounding_box
            if dimensions:
                result["dimensions"] = [round(d, 4) for d in dimensions]
            if normalize_size:
                result["scale_applied"] = round(scale_applied, 6)
                result["normalized"] = True
            
            return result

        except requests.exceptions.Timeout:
            return {"error": "Request timed out. Check your internet connection and try again with a simpler model."}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON response from Sketchfab API: {str(e)}"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"Failed to download model: {str(e)}"}
    #endregion

    #region Hunyuan3D
    def get_hunyuan3d_status(self):
        """Get the current status of Hunyuan3D integration"""
        enabled = bpy.context.scene.blendermcp_use_hunyuan3d
        hunyuan3d_mode = bpy.context.scene.blendermcp_hunyuan3d_mode
        if enabled:
            match hunyuan3d_mode:
                case "OFFICIAL_API":
                    if not bpy.context.scene.blendermcp_hunyuan3d_secret_id or not bpy.context.scene.blendermcp_hunyuan3d_secret_key:
                        return {
                            "enabled": False, 
                            "mode": hunyuan3d_mode, 
                            "message": """Hunyuan3D integration is currently enabled, but SecretId or SecretKey is not given. To enable it:
                                1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                                2. Keep the 'Use Tencent Hunyuan 3D model generation' checkbox checked
                                3. Choose the right platform and fill in the SecretId and SecretKey
                                4. Restart the connection to Claude"""
                        }
                case "LOCAL_API":
                    if not bpy.context.scene.blendermcp_hunyuan3d_api_url:
                        return {
                            "enabled": False, 
                            "mode": hunyuan3d_mode, 
                            "message": """Hunyuan3D integration is currently enabled, but API URL  is not given. To enable it:
                                1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                                2. Keep the 'Use Tencent Hunyuan 3D model generation' checkbox checked
                                3. Choose the right platform and fill in the API URL
                                4. Restart the connection to Claude"""
                        }
                case _:
                    return {
                        "enabled": False, 
                        "message": "Hunyuan3D integration is enabled and mode is not supported."
                    }
            return {
                "enabled": True, 
                "mode": hunyuan3d_mode,
                "message": "Hunyuan3D integration is enabled and ready to use."
            }
        return {
            "enabled": False, 
            "message": """Hunyuan3D integration is currently disabled. To enable it:
                        1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                        2. Check the 'Use Tencent Hunyuan 3D model generation' checkbox
                        3. Restart the connection to Claude"""
        }
    
    @staticmethod
    def get_tencent_cloud_sign_headers(
        method: str,
        path: str,
        headParams: dict,
        data: dict,
        service: str,
        region: str,
        secret_id: str,
        secret_key: str,
        host: str = None
    ):
        """Generate the signature header required for Tencent Cloud API requests headers"""
        # Generate timestamp
        timestamp = int(time.time())
        date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
        
        # If host is not provided, it is generated based on service and region.
        if not host:
            host = f"{service}.tencentcloudapi.com"
        
        endpoint = f"https://{host}"
        
        # Constructing the request body
        payload_str = json.dumps(data)
        
        # ************* Step 1: Concatenate the canonical request string *************
        canonical_uri = path
        canonical_querystring = ""
        ct = "application/json; charset=utf-8"
        canonical_headers = f"content-type:{ct}\nhost:{host}\nx-tc-action:{headParams.get('Action', '').lower()}\n"
        signed_headers = "content-type;host;x-tc-action"
        hashed_request_payload = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        
        canonical_request = (method + "\n" +
                            canonical_uri + "\n" +
                            canonical_querystring + "\n" +
                            canonical_headers + "\n" +
                            signed_headers + "\n" +
                            hashed_request_payload)

        # ************* Step 2: Construct the reception signature string *************
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = ("TC3-HMAC-SHA256" + "\n" +
                        str(timestamp) + "\n" +
                        credential_scope + "\n" +
                        hashed_canonical_request)

        # ************* Step 3: Calculate the signature *************
        def sign(key, msg):
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        secret_date = sign(("TC3" + secret_key).encode("utf-8"), date)
        secret_service = sign(secret_date, service)
        secret_signing = sign(secret_service, "tc3_request")
        signature = hmac.new(
            secret_signing, 
            string_to_sign.encode("utf-8"), 
            hashlib.sha256
        ).hexdigest()

        # ************* Step 4: Connect Authorization *************
        authorization = ("TC3-HMAC-SHA256" + " " +
                        "Credential=" + secret_id + "/" + credential_scope + ", " +
                        "SignedHeaders=" + signed_headers + ", " +
                        "Signature=" + signature)

        # Constructing request headers
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": host,
            "X-TC-Action": headParams.get("Action", ""),
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": headParams.get("Version", ""),
            "X-TC-Region": region
        }

        return headers, endpoint

    def create_hunyuan_job(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hunyuan3d_mode:
            case "OFFICIAL_API":
                return self.create_hunyuan_job_main_site(*args, **kwargs)
            case "LOCAL_API":
                return self.create_hunyuan_job_local_site(*args, **kwargs)
            case _:
                return f"Error: Unknown Hunyuan3D mode!"

    def create_hunyuan_job_main_site(
        self,
        text_prompt: str = None,
        image: str = None
    ):
        try:
            secret_id = bpy.context.scene.blendermcp_hunyuan3d_secret_id
            secret_key = bpy.context.scene.blendermcp_hunyuan3d_secret_key

            if not secret_id or not secret_key:
                return {"error": "SecretId or SecretKey is not given"}

            # Parameter verification
            if not text_prompt and not image:
                return {"error": "Prompt or Image is required"}
            if text_prompt and image:
                return {"error": "Prompt and Image cannot be provided simultaneously"}
            # Fixed parameter configuration
            service = "hunyuan"
            action = "SubmitHunyuanTo3DJob"
            version = "2023-09-01"
            region = "ap-guangzhou"

            headParams={
                "Action": action,
                "Version": version,
                "Region": region,
            }

            # Constructing request parameters
            data = {
                "Num": 1  # The current API limit is only 1
            }

            # Handling text prompts
            if text_prompt:
                if len(text_prompt) > 200:
                    return {"error": "Prompt exceeds 200 characters limit"}
                data["Prompt"] = text_prompt

            # Handling image
            if image:
                if re.match(r'^https?://', image, re.IGNORECASE) is not None:
                    data["ImageUrl"] = image
                else:
                    try:
                        # Convert to Base64 format
                        with open(image, "rb") as f:
                            image_base64 = base64.b64encode(f.read()).decode("ascii")
                        data["ImageBase64"] = image_base64
                    except Exception as e:
                        return {"error": f"Image encoding failed: {str(e)}"}
            
            # Get signed headers
            headers, endpoint = self.get_tencent_cloud_sign_headers("POST", "/", headParams, data, service, region, secret_id, secret_key)

            response = requests.post(
                endpoint,
                headers = headers,
                data = json.dumps(data)
            )

            if response.status_code == 200:
                return response.json()
            return {
                "error": f"API request failed with status {response.status_code}: {response}"
            }
        except Exception as e:
            return {"error": str(e)}

    def create_hunyuan_job_local_site(
        self,
        text_prompt: str = None,
        image: str = None):
        try:
            base_url = bpy.context.scene.blendermcp_hunyuan3d_api_url.rstrip('/')
            octree_resolution = bpy.context.scene.blendermcp_hunyuan3d_octree_resolution
            num_inference_steps = bpy.context.scene.blendermcp_hunyuan3d_num_inference_steps
            guidance_scale = bpy.context.scene.blendermcp_hunyuan3d_guidance_scale
            texture = bpy.context.scene.blendermcp_hunyuan3d_texture

            if not base_url:
                return {"error": "API URL is not given"}
            # Parameter verification
            if not text_prompt and not image:
                return {"error": "Prompt or Image is required"}

            # Constructing request parameters
            data = {
                "octree_resolution": octree_resolution,
                "num_inference_steps": num_inference_steps,
                "guidance_scale": guidance_scale,
                "texture": texture,
            }

            # Handling text prompts
            if text_prompt:
                data["text"] = text_prompt

            # Handling image
            if image:
                if re.match(r'^https?://', image, re.IGNORECASE) is not None:
                    try:
                        resImg = requests.get(image)
                        resImg.raise_for_status()
                        image_base64 = base64.b64encode(resImg.content).decode("ascii")
                        data["image"] = image_base64
                    except Exception as e:
                        return {"error": f"Failed to download or encode image: {str(e)}"} 
                else:
                    try:
                        # Convert to Base64 format
                        with open(image, "rb") as f:
                            image_base64 = base64.b64encode(f.read()).decode("ascii")
                        data["image"] = image_base64
                    except Exception as e:
                        return {"error": f"Image encoding failed: {str(e)}"}

            response = requests.post(
                f"{base_url}/generate",
                json = data,
            )

            if response.status_code != 200:
                return {
                    "error": f"Generation failed: {response.text}"
                }
        
            # Decode base64 and save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".glb") as temp_file:
                temp_file.write(response.content)
                temp_file_name = temp_file.name

            # Import the GLB file in the main thread
            def import_handler():
                bpy.ops.import_scene.gltf(filepath=temp_file_name)
                os.unlink(temp_file.name)
                return None
            
            bpy.app.timers.register(import_handler)

            return {
                "status": "DONE",
                "message": "Generation and Import glb succeeded"
            }
        except Exception as e:
            print(f"An error occurred: {e}")
            return {"error": str(e)}
        
    
    def poll_hunyuan_job_status(self, *args, **kwargs):
        return self.poll_hunyuan_job_status_ai(*args, **kwargs)
    
    def poll_hunyuan_job_status_ai(self, job_id: str):
        """Call the job status API to get the job status"""
        print(job_id)
        try:
            secret_id = bpy.context.scene.blendermcp_hunyuan3d_secret_id
            secret_key = bpy.context.scene.blendermcp_hunyuan3d_secret_key

            if not secret_id or not secret_key:
                return {"error": "SecretId or SecretKey is not given"}
            if not job_id:
                return {"error": "JobId is required"}
            
            service = "hunyuan"
            action = "QueryHunyuanTo3DJob"
            version = "2023-09-01"
            region = "ap-guangzhou"

            headParams={
                "Action": action,
                "Version": version,
                "Region": region,
            }

            clean_job_id = job_id.removeprefix("job_")
            data = {
                "JobId": clean_job_id
            }

            headers, endpoint = self.get_tencent_cloud_sign_headers("POST", "/", headParams, data, service, region, secret_id, secret_key)

            response = requests.post(
                endpoint,
                headers=headers,
                data=json.dumps(data)
            )

            if response.status_code == 200:
                return response.json()
            return {
                "error": f"API request failed with status {response.status_code}: {response}"
            }
        except Exception as e:
            return {"error": str(e)}

    def import_generated_asset_hunyuan(self, *args, **kwargs):
        return self.import_generated_asset_hunyuan_ai(*args, **kwargs)
            
    def import_generated_asset_hunyuan_ai(self, name: str , zip_file_url: str):
        if not zip_file_url:
            return {"error": "Zip file not found"}
        
        # Validate URL
        if not re.match(r'^https?://', zip_file_url, re.IGNORECASE):
            return {"error": "Invalid URL format. Must start with http:// or https://"}
        
        # Create a temporary directory
        temp_dir = tempfile.mkdtemp(prefix="tencent_obj_")
        zip_file_path = osp.join(temp_dir, "model.zip")
        obj_file_path = osp.join(temp_dir, "model.obj")
        mtl_file_path = osp.join(temp_dir, "model.mtl")

        try:
            # Download ZIP file
            zip_response = requests.get(zip_file_url, stream=True)
            zip_response.raise_for_status()
            with open(zip_file_path, "wb") as f:
                for chunk in zip_response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Unzip the ZIP
            with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            # Find the .obj file (there may be multiple, assuming the main file is model.obj)
            for file in os.listdir(temp_dir):
                if file.endswith(".obj"):
                    obj_file_path = osp.join(temp_dir, file)

            if not osp.exists(obj_file_path):
                return {"succeed": False, "error": "OBJ file not found after extraction"}

            # Import obj file
            if bpy.app.version>=(4, 0, 0):
                bpy.ops.wm.obj_import(filepath=obj_file_path)
            else:
                bpy.ops.import_scene.obj(filepath=obj_file_path)

            imported_objs = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
            if not imported_objs:
                return {"succeed": False, "error": "No mesh objects imported"}

            obj = imported_objs[0]
            if name:
                obj.name = name

            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box

            return {"succeed": True, **result}
        except Exception as e:
            return {"succeed": False, "error": str(e)}
        finally:
            #  Clean up temporary zip and obj, save texture and mtl
            try:
                if os.path.exists(zip_file_path):
                    os.remove(zip_file_path) 
                if os.path.exists(obj_file_path):
                    os.remove(obj_file_path)
            except Exception as e:
                print(f"Failed to clean up temporary directory {temp_dir}: {e}")
    #endregion

# Blender Addon Preferences
class BLENDERMCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    
    telemetry_consent: BoolProperty(
        name="Allow Telemetry",
        description="Allow collection of prompts, code snippets, and screenshots to help improve Blender MCP",
        default=True
    )

    def draw(self, context):
        layout = self.layout
        
        # Telemetry section
        layout.label(text="Telemetry & Privacy:", icon='PREFERENCES')
        
        box = layout.box()
        row = box.row()
        row.prop(self, "telemetry_consent", text="Allow Telemetry")
        
        # Info text
        box.separator()
        if self.telemetry_consent:
            box.label(text="With consent: We collect anonymized prompts, code, and screenshots.", icon='INFO')
        else:
            box.label(text="Without consent: We only collect minimal anonymous usage data", icon='INFO')
            box.label(text="(tool names, success/failure, duration - no prompts or code).", icon='BLANK1')
        box.separator()
        box.label(text="All data is fully anonymized. You can change this anytime.", icon='CHECKMARK')
        
        # Terms and Conditions link
        box.separator()
        row = box.row()
        row.operator("blendermcp.open_terms", text="View Terms and Conditions", icon='TEXT')

# Blender UI Panel
class BLENDERMCP_PT_Panel(bpy.types.Panel):
    bl_label = "Blender MCP"
    bl_idname = "BLENDERMCP_PT_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderMCP'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "blendermcp_port")
        layout.prop(scene, "blendermcp_use_polyhaven", text="Use assets from Poly Haven")

        layout.prop(scene, "blendermcp_use_hyper3d", text="Use Hyper3D Rodin 3D model generation")
        if scene.blendermcp_use_hyper3d:
            layout.prop(scene, "blendermcp_hyper3d_mode", text="Rodin Mode")
            layout.prop(scene, "blendermcp_hyper3d_api_key", text="API Key")
            layout.operator("blendermcp.set_hyper3d_free_trial_api_key", text="Set Free Trial API Key")

        layout.prop(scene, "blendermcp_use_sketchfab", text="Use assets from Sketchfab")
        if scene.blendermcp_use_sketchfab:
            layout.prop(scene, "blendermcp_sketchfab_api_key", text="API Key")

        layout.prop(scene, "blendermcp_use_hunyuan3d", text="Use Tencent Hunyuan 3D model generation")
        if scene.blendermcp_use_hunyuan3d:
            layout.prop(scene, "blendermcp_hunyuan3d_mode", text="Hunyuan3D Mode")
            if scene.blendermcp_hunyuan3d_mode == 'OFFICIAL_API':
                layout.prop(scene, "blendermcp_hunyuan3d_secret_id", text="SecretId")
                layout.prop(scene, "blendermcp_hunyuan3d_secret_key", text="SecretKey")
            if scene.blendermcp_hunyuan3d_mode == 'LOCAL_API':
                layout.prop(scene, "blendermcp_hunyuan3d_api_url", text="API URL")
                layout.prop(scene, "blendermcp_hunyuan3d_octree_resolution", text="Octree Resolution")
                layout.prop(scene, "blendermcp_hunyuan3d_num_inference_steps", text="Number of Inference Steps")
                layout.prop(scene, "blendermcp_hunyuan3d_guidance_scale", text="Guidance Scale")
                layout.prop(scene, "blendermcp_hunyuan3d_texture", text="Generate Texture")
        
        if not scene.blendermcp_server_running:
            layout.operator("blendermcp.start_server", text="Connect to MCP server")
        else:
            layout.operator("blendermcp.stop_server", text="Disconnect from MCP server")
            layout.label(text=f"Running on port {scene.blendermcp_port}")

# Operator to set Hyper3D API Key
class BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey(bpy.types.Operator):
    bl_idname = "blendermcp.set_hyper3d_free_trial_api_key"
    bl_label = "Set Free Trial API Key"

    def execute(self, context):
        context.scene.blendermcp_hyper3d_api_key = RODIN_FREE_TRIAL_KEY
        context.scene.blendermcp_hyper3d_mode = 'MAIN_SITE'
        self.report({'INFO'}, "API Key set successfully!")
        return {'FINISHED'}

# Operator to start the server
class BLENDERMCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Connect to Claude"
    bl_description = "Start the BlenderMCP server to connect with Claude"

    def execute(self, context):
        scene = context.scene

        # Create a new server instance
        if not hasattr(bpy.types, "blendermcp_server") or not bpy.types.blendermcp_server:
            bpy.types.blendermcp_server = BlenderMCPServer(port=scene.blendermcp_port)

        # Start the server
        bpy.types.blendermcp_server.start()
        scene.blendermcp_server_running = True

        return {'FINISHED'}

# Operator to stop the server
class BLENDERMCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop the connection to Claude"
    bl_description = "Stop the connection to Claude"

    def execute(self, context):
        scene = context.scene

        # Stop the server if it exists
        if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
            bpy.types.blendermcp_server.stop()
            del bpy.types.blendermcp_server

        scene.blendermcp_server_running = False

        return {'FINISHED'}

# Operator to open Terms and Conditions
class BLENDERMCP_OT_OpenTerms(bpy.types.Operator):
    bl_idname = "blendermcp.open_terms"
    bl_label = "View Terms and Conditions"
    bl_description = "Open the Terms and Conditions document"

    def execute(self, context):
        # Open the Terms and Conditions on GitHub
        terms_url = "https://github.com/ahujasid/blender-mcp/blob/main/TERMS_AND_CONDITIONS.md"
        try:
            import webbrowser
            webbrowser.open(terms_url)
            self.report({'INFO'}, "Terms and Conditions opened in browser")
        except Exception as e:
            self.report({'ERROR'}, f"Could not open Terms and Conditions: {str(e)}")
        
        return {'FINISHED'}

# Registration functions
def register():
    bpy.types.Scene.blendermcp_port = IntProperty(
        name="Port",
        description="Port for the BlenderMCP server",
        default=9876,
        min=1024,
        max=65535
    )

    bpy.types.Scene.blendermcp_server_running = bpy.props.BoolProperty(
        name="Server Running",
        default=False
    )

    bpy.types.Scene.blendermcp_use_polyhaven = bpy.props.BoolProperty(
        name="Use Poly Haven",
        description="Enable Poly Haven asset integration",
        default=False
    )

    bpy.types.Scene.blendermcp_use_hyper3d = bpy.props.BoolProperty(
        name="Use Hyper3D Rodin",
        description="Enable Hyper3D Rodin generatino integration",
        default=False
    )

    bpy.types.Scene.blendermcp_hyper3d_mode = bpy.props.EnumProperty(
        name="Rodin Mode",
        description="Choose the platform used to call Rodin APIs",
        items=[
            ("MAIN_SITE", "hyper3d.ai", "hyper3d.ai"),
            ("FAL_AI", "fal.ai", "fal.ai"),
        ],
        default="MAIN_SITE"
    )

    bpy.types.Scene.blendermcp_hyper3d_api_key = bpy.props.StringProperty(
        name="Hyper3D API Key",
        subtype="PASSWORD",
        description="API Key provided by Hyper3D",
        default=""
    )

    bpy.types.Scene.blendermcp_use_hunyuan3d = bpy.props.BoolProperty(
        name="Use Hunyuan 3D",
        description="Enable Hunyuan asset integration",
        default=False
    )

    bpy.types.Scene.blendermcp_hunyuan3d_mode = bpy.props.EnumProperty(
        name="Hunyuan3D Mode",
        description="Choose a local or official APIs",
        items=[
            ("LOCAL_API", "local api", "local api"),
            ("OFFICIAL_API", "official api", "official api"),
        ],
        default="LOCAL_API"
    )

    bpy.types.Scene.blendermcp_hunyuan3d_secret_id = bpy.props.StringProperty(
        name="Hunyuan 3D SecretId",
        description="SecretId provided by Hunyuan 3D",
        default=""
    )

    bpy.types.Scene.blendermcp_hunyuan3d_secret_key = bpy.props.StringProperty(
        name="Hunyuan 3D SecretKey",
        subtype="PASSWORD",
        description="SecretKey provided by Hunyuan 3D",
        default=""
    )

    bpy.types.Scene.blendermcp_hunyuan3d_api_url = bpy.props.StringProperty(
        name="API URL",
        description="URL of the Hunyuan 3D API service",
        default="http://localhost:8081"
    )

    bpy.types.Scene.blendermcp_hunyuan3d_octree_resolution = bpy.props.IntProperty(
        name="Octree Resolution",
        description="Octree resolution for the 3D generation",
        default=256,
        min=128,
        max=512,
    )

    bpy.types.Scene.blendermcp_hunyuan3d_num_inference_steps = bpy.props.IntProperty(
        name="Number of Inference Steps",
        description="Number of inference steps for the 3D generation",
        default=20,
        min=20,
        max=50,
    )

    bpy.types.Scene.blendermcp_hunyuan3d_guidance_scale = bpy.props.FloatProperty(
        name="Guidance Scale",
        description="Guidance scale for the 3D generation",
        default=5.5,
        min=1.0,
        max=10.0,
    )

    bpy.types.Scene.blendermcp_hunyuan3d_texture = bpy.props.BoolProperty(
        name="Generate Texture",
        description="Whether to generate texture for the 3D model",
        default=False,
    )
    
    bpy.types.Scene.blendermcp_use_sketchfab = bpy.props.BoolProperty(
        name="Use Sketchfab",
        description="Enable Sketchfab asset integration",
        default=False
    )

    bpy.types.Scene.blendermcp_sketchfab_api_key = bpy.props.StringProperty(
        name="Sketchfab API Key",
        subtype="PASSWORD",
        description="API Key provided by Sketchfab",
        default=""
    )

    # Register preferences class
    bpy.utils.register_class(BLENDERMCP_AddonPreferences)

    bpy.utils.register_class(BLENDERMCP_PT_Panel)
    bpy.utils.register_class(BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey)
    bpy.utils.register_class(BLENDERMCP_OT_StartServer)
    bpy.utils.register_class(BLENDERMCP_OT_StopServer)
    bpy.utils.register_class(BLENDERMCP_OT_OpenTerms)

    print("BlenderMCP addon registered")

def unregister():
    # Stop the server if it's running
    if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
        bpy.types.blendermcp_server.stop()
        del bpy.types.blendermcp_server

    bpy.utils.unregister_class(BLENDERMCP_PT_Panel)
    bpy.utils.unregister_class(BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey)
    bpy.utils.unregister_class(BLENDERMCP_OT_StartServer)
    bpy.utils.unregister_class(BLENDERMCP_OT_StopServer)
    bpy.utils.unregister_class(BLENDERMCP_OT_OpenTerms)
    bpy.utils.unregister_class(BLENDERMCP_AddonPreferences)

    del bpy.types.Scene.blendermcp_port
    del bpy.types.Scene.blendermcp_server_running
    del bpy.types.Scene.blendermcp_use_polyhaven
    del bpy.types.Scene.blendermcp_use_hyper3d
    del bpy.types.Scene.blendermcp_hyper3d_mode
    del bpy.types.Scene.blendermcp_hyper3d_api_key
    del bpy.types.Scene.blendermcp_use_sketchfab
    del bpy.types.Scene.blendermcp_sketchfab_api_key
    del bpy.types.Scene.blendermcp_use_hunyuan3d
    del bpy.types.Scene.blendermcp_hunyuan3d_mode
    del bpy.types.Scene.blendermcp_hunyuan3d_secret_id
    del bpy.types.Scene.blendermcp_hunyuan3d_secret_key
    del bpy.types.Scene.blendermcp_hunyuan3d_api_url
    del bpy.types.Scene.blendermcp_hunyuan3d_octree_resolution
    del bpy.types.Scene.blendermcp_hunyuan3d_num_inference_steps
    del bpy.types.Scene.blendermcp_hunyuan3d_guidance_scale
    del bpy.types.Scene.blendermcp_hunyuan3d_texture

    print("BlenderMCP addon unregistered")

if __name__ == "__main__":
    register()
