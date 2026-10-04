"""Stand-in for Blender with the add-on server, for end-to-end tests.

Runs the add-on command dispatcher behind a TCP socket in the main thread.
Async preview jobs are stepped to completion after each command, since
bpy.app.timers do not fire in module mode. Usage: fake_blender.py PORT
"""
import importlib.util
import json
import os
import pathlib
import socket
import sys

import bpy

ROOT = pathlib.Path(__file__).resolve().parent.parent

bpy.ops.wm.read_factory_settings(use_empty=False)
spec = importlib.util.spec_from_file_location("blendermcp_addon", ROOT / "addon.py")
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)
addon.register()
server = addon.BlenderMCPServer()

listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", int(sys.argv[1])))
listener.listen(1)
print("READY", flush=True)
# Nobody reads stdout after READY; silence it so a full pipe cannot block us
devnull = os.open(os.devnull, os.O_WRONLY)
os.dup2(devnull, sys.stdout.fileno())

while True:
    client, _ = listener.accept()
    buffer = b""
    while True:
        data = client.recv(65536)
        if not data:
            break
        buffer += data
        try:
            command = json.loads(buffer)
        except json.JSONDecodeError:
            continue
        buffer = b""
        if command["type"] == "__quit__":
            sys.exit(0)
        client.sendall(json.dumps(server.execute_command(command)).encode())
        while server._preview_job is not None and server._preview_step() is not None:
            pass
