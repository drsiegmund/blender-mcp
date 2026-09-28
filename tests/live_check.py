#!/usr/bin/env python3
"""Live check of the add-on against a running Blender (no Claude, no dependencies).

Start the BlenderMCP server in Blender, then run from a terminal:

    python3 tests/live_check.py

Everything happens in a new scene "MCP_Live_Test" inside the open file; the
script aborts if it cannot switch to it. Don't save the file afterwards (or
delete that scene) to leave your work untouched. Results (report.md and
images) are written to ~/blender_mcp_live_check/.
"""
import json
import os
import shutil
import socket
import sys
import time
import traceback

HOST, PORT = "localhost", int(os.environ.get("BLENDER_PORT", 9876))
OUT = os.path.expanduser("~/blender_mcp_live_check")
TMP = os.path.join(OUT, "tmp")

DIPOLE = ["3*x*z/(x**2+y**2+z**2)**2.5", "3*y*z/(x**2+y**2+z**2)**2.5",
          "(3*z**2-(x**2+y**2+z**2))/(x**2+y**2+z**2)**2.5"]
LORENZ = ["sigma*(y-x)", "x*(rho-z)-y", "x*y-beta*z"]

SETUP = r'''
import bpy, bmesh
wm = bpy.context.window_manager
old = bpy.data.scenes.get("MCP_Live_Test")
if old:
    bpy.data.scenes.remove(old)
sc = bpy.data.scenes.new("MCP_Live_Test")
for win in wm.windows:
    win.scene = sc
mesh = bpy.data.meshes.new("LiveCube")
bm = bmesh.new(); bmesh.ops.create_cube(bm, size=2.0); bm.to_mesh(mesh); bm.free()
cube = bpy.data.objects.new("LiveCube", mesh); sc.collection.objects.link(cube)
cam = bpy.data.objects.new("LiveCam", bpy.data.cameras.new("LiveCam")); sc.collection.objects.link(cam)
cam.location = (0, -12, 3); cam.rotation_euler = (1.35, 0, 0); sc.camera = cam
sun = bpy.data.objects.new("LiveSun", bpy.data.lights.new("LiveSun", "SUN")); sc.collection.objects.link(sun)
sun.rotation_euler = (0.7, 0.2, 0.6); sun.data.energy = 3
sc.world = bpy.data.worlds.new("LiveWorld"); sc.world.color = (0.05, 0.05, 0.06)
print(bpy.app.version_string, "|", bpy.context.scene.name)
'''


class Blender:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=10)
        self.sock.settimeout(200)

    def call(self, command, **params):
        start = time.time()
        self.sock.sendall(json.dumps({"type": command, "params": params}).encode())
        buf = b""
        while True:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("Blender closed the connection")
            buf += chunk
            try:
                resp = json.loads(buf)
                break
            except json.JSONDecodeError:
                continue
        elapsed = time.time() - start
        if resp.get("status") == "error":
            raise RuntimeError(resp.get("message"))
        return resp.get("result", {}), elapsed


rows = []


def record(step, ok, note):
    rows.append((step, "OK" if ok else "FEHLER", note))
    print(f"[{'OK' if ok else 'FEHLER':6}] {step}: {note}", flush=True)


def check(step, fn):
    try:
        ok, note = fn()
        record(step, ok, note)
    except Exception as e:  # keep going, report everything
        record(step, False, f"{type(e).__name__}: {e}")
        traceback.print_exc()


def keep_image(src, name):
    if src and os.path.exists(src):
        dst = os.path.join(OUT, name)
        shutil.copyfile(src, dst)
        return dst
    return None


def wait_render(b, label):
    """Poll until a render finishes; returns (result, poll log)."""
    log = []
    start = time.time()
    while True:
        res, latency = b.call("poll_render_status")
        log.append((round(time.time() - start, 2), round(latency, 2), res.get("status"),
                    (res.get("result") or {}).get("frames_done")))
        if res.get("status") in ("completed", "failed", "idle"):
            return res, log
        if time.time() - start > 600:
            raise TimeoutError(f"{label} did not finish within 10 minutes")
        time.sleep(0.3)


def main():
    os.makedirs(TMP, exist_ok=True)
    try:
        b = Blender()
    except OSError as e:
        sys.exit(f"Keine Verbindung zu Blender auf {HOST}:{PORT} ({e}). Läuft der BlenderMCP-Server?")

    # 0. New add-on version loaded?
    try:
        b.call("list_renders")
    except RuntimeError as e:
        sys.exit(f"Das laufende Add-on ist die alte Version ({e}). Bitte addon.py neu installieren.")

    # 1. Isolated test scene
    res, _ = b.call("execute_code", code=SETUP)
    info = res.get("result", "").strip()
    scene_name, _ = b.call("get_scene_info")
    if scene_name.get("name") != "MCP_Live_Test":
        sys.exit(f"Abbruch: aktive Szene ist '{scene_name.get('name')}', nicht MCP_Live_Test. Nichts wurde verändert "
                 "außer dem Anlegen der leeren Szene MCP_Live_Test.")
    record("Setup", True, f"Blender {info}")

    # 2. Animation & timeline
    def animation():
        b.call("insert_keyframes", object_name="LiveCube", data_path="location",
               keyframes=[{"frame": 1, "value": [-3, 0, 0]}, {"frame": 40, "value": [3, 0, 0]}],
               interpolation="LINEAR")
        b.call("set_timeline", frame_start=1, frame_end=40)
        state, _ = b.call("scrub_timeline", frame=20.5)
        x = state["objects"]["LiveCube"]["world_location"][0]
        data, _ = b.call("get_animation_data", object_name="LiveCube")
        n = len(data["objects"]["LiveCube"]["fcurves"])
        return abs(x) < 1e-3, f"x bei Frame 20.5 = {x:.4f} (erwartet 0), {n} F-Curves"
    check("Keyframes/Timeline/Scrub", animation)

    # 3. EEVEE still render
    def eevee_render():
        started, _ = b.call("render_scene", filepath=os.path.join(TMP, "still.png"),
                            resolution_x=640, resolution_y=360, engine="EEVEE")
        res, log = wait_render(b, "render_scene")
        path = keep_image((res.get("result") or {}).get("filepath"), "1_eevee_still.png")
        longest = max(entry[1] for entry in log)
        return res["status"] == "completed" and path is not None, \
            f"{res['status']}, {len(log)} Polls, längste Poll-Antwort {longest}s, Bild: {path}"
    check("EEVEE render_scene", eevee_render)

    # 4. Animation preview: does progress show between frames?
    def preview():
        b.call("render_animation_preview", filepath=os.path.join(TMP, "preview.png"), num_frames=6,
               resolution_x=320, resolution_y=180, engine="EEVEE")
        res, log = wait_render(b, "render_animation_preview")
        progress = [entry[3] for entry in log if entry[3] is not None]
        path = keep_image((res.get("result") or {}).get("filepath"), "2_eevee_preview.png")
        steps = sorted(set(progress))
        return res["status"] == "completed" and path is not None, \
            f"{res['status']}, sichtbarer Fortschritt frames_done={steps}, Bild: {path}"
    check("EEVEE Animations-Vorschau", preview)

    # 5. NLA
    def nla():
        r, _ = b.call("push_action_to_nla", object_name="LiveCube", track_name="Base")
        action = r["nla_tracks"][0]["strips"][0]["action"]
        r, _ = b.call("add_nla_strip", object_name="LiveCube", action_name=action, frame_start=60,
                      track_name="Base", repeat=2)
        strips = r["nla_tracks"][0]["strips"]
        return len(strips) == 2 and strips[1]["frame_end"] > 60, \
            f"Strips: {[(s['name'], s['frame_start'], s['frame_end']) for s in strips]}"
    check("NLA", nla)

    # 6. Visualization
    b.call("execute_code", code="import bpy\nsc = bpy.context.scene\n"
                                "bpy.data.objects['LiveCube'].hide_render = True\n"
                                "bpy.data.objects['LiveCube'].hide_viewport = True\n"
                                "sc.camera.location = (0, -8, 0); sc.camera.rotation_euler = (1.5708, 0, 0)\n"
                                "sc.frame_set(1)")

    def dipole():
        r, t = b.call("plot_vector_field", name="Dipole", field=DIPOLE, bounds=[[-2, 2], [0, 0], [-2, 2]],
                      resolution=[17, 1, 17], mode="both")
        b.call("render_scene", filepath=os.path.join(TMP, "dipole.png"), resolution_x=800, resolution_y=800,
               engine="EEVEE")
        res, _ = wait_render(b, "dipole render")
        path = keep_image((res.get("result") or {}).get("filepath"), "3_dipole.png")
        return path is not None, f"{r.get('arrows')} Pfeile, {r.get('streamlines')} Feldlinien, " \
                                 f"{r.get('color')}, {t:.1f}s, Bild: {path}"
    check("plot_vector_field Dipol", dipole)

    def lorenz():
        b.call("execute_code", code="import bpy\nfor n in ('Dipole', 'Dipole_streamlines'):\n"
                                    "    o = bpy.data.objects.get(n)\n"
                                    "    if o: o.hide_render = True; o.hide_viewport = True\n"
                                    "c = bpy.context.scene.camera\nc.location = (11, -11, 6)\n"
                                    "c.rotation_euler = (1.15, 0, 0.785)")
        r, t = b.call("plot_trajectory", name="Lorenz", ode=LORENZ, initial=[[1, 1, 1], [1.001, 1, 1]],
                      t_span=[0, 30], steps=6000, params={"sigma": 10, "rho": 28, "beta": 8 / 3},
                      fit_size=6, thickness=0.02, animate=True, frame_start=1, frame_end=120)
        b.call("scrub_timeline", frame=120)
        b.call("render_scene", filepath=os.path.join(TMP, "lorenz.png"), resolution_x=800, resolution_y=600,
               engine="EEVEE")
        res, _ = wait_render(b, "lorenz render")
        path = keep_image((res.get("result") or {}).get("filepath"), "4_lorenz.png")
        return path is not None and r["trajectories"] == 2, \
            f"{r['trajectories']} Trajektorien, Marker {r['animation']['markers']}, {t:.1f}s, Bild: {path}"
    check("plot_trajectory Lorenz (animiert)", lorenz)

    # 7. Compare the last two renders
    def compare():
        out = os.path.join(OUT, "5_compare.png")
        r, _ = b.call("compare_renders", filepath=out)
        return os.path.exists(out), f"Render #{r['before']['number']} vs #{r['after']['number']}, " \
                                    f"geändert: {r['changed_fraction'] * 100:.1f} %"
    check("compare_renders", compare)

    # 8. Snapshot, diff, change log
    def change_tracking():
        b.call("snapshot_scene")
        b.call("insert_keyframes", object_name="LiveSun", data_path="data.energy",
               keyframes=[{"frame": 1, "value": 1}, {"frame": 40, "value": 5}])
        diff, _ = b.call("diff_scene")
        log, _ = b.call("get_change_log", summary=True)
        kf = diff.get("keyframe_changes", {})
        return "LiveSun" in kf, f"Diff: {diff.get('summary')}; Change-Log-Einträge: " \
                                f"{len(log.get('changes', log)) if isinstance(log, dict) else log}"
    check("snapshot/diff/change_log", change_tracking)

    shutil.rmtree(TMP, ignore_errors=True)
    report = ["| Schritt | Ergebnis | Beobachtung |", "|---|---|---|"]
    report += [f"| {s} | {r} | {n.replace('|', '/')} |" for s, r, n in rows]
    with open(os.path.join(OUT, "report.md"), "w") as f:
        f.write("\n".join(report) + "\n")
    print("\n" + "\n".join(report))
    print(f"\nBilder und report.md liegen in {OUT}")
    print("Hinweis: Die Szene MCP_Live_Test bleibt zum Anschauen offen. Datei danach nicht speichern "
          "(oder die Szene löschen).")


if __name__ == "__main__":
    main()
