"""Run inside a separate Blender with its own user profile (BLENDER_USER_RESOURCES) by
tests/test_update.py: install OLD.zip as an extension, serve NEW.zip as a newer release from local
files, press Update, and check Blender replaced and re-enabled RealWorn. Prints one JSON line.

    blender --background --factory-startup --online-mode --python update_install.py -- OLD.zip NEW.zip
"""

import hashlib
import json
import os
import sys
import time

import bpy

old, new = sys.argv[sys.argv.index("--") + 1:][:2]
MOD = "bl_ext.user_default.realworn"
out = dict(profile=bpy.utils.resource_path("USER"))
bpy.ops.extensions.package_install_files(filepath=old, repo="user_default", enable_on_install=True, overwrite=True)
U = sys.modules[MOD + ".operators.update"]
out.update(old_enabled=MOD in bpy.context.preferences.addons, old_version=U.current_version(), target=U.target())

data = open(new, "rb").read()
release = dict(tag_name="v{}".format(os.path.basename(new)[len("realworn-"):-len(".zip")]), draft=False,
               prerelease=False, html_url="", assets=[dict(
                   name=os.path.basename(new), size=len(data), browser_download_url="file:///" + new.replace("\\", "/"),
                   digest="sha256:" + hashlib.sha256(data).hexdigest())])
U.update.fetch_latest = lambda: U.update.release_info(release)  # no network


def drive():
    """Background Blender runs no timers: hand the thread's result to the timer function."""
    for _ in range(400):
        if not U._results.empty():
            return U._poll()
        time.sleep(0.05)
    raise RuntimeError("no result from the update thread")


U.start_check()
drive()
out["checked"] = U.STATE["status"]
bpy.ops.realworn.update_install()
drive()
U2 = sys.modules.get(MOD + ".operators.update")
out.update(old_state=U.STATE["status"], old_message=U.STATE["message"], reloaded=U2 is not None and U2 is not U,
           new_enabled=MOD in bpy.context.preferences.addons, new_version=U2.current_version() if U2 else None,
           operators=hasattr(bpy.types, "REALWORN_OT_update_install"))
print("UPDATE_RESULT " + json.dumps(out), flush=True)
