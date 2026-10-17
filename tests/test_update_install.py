"""Update installs the newer release over the installed extension: run in a separate Blender with
its own user profile, so the user's own extensions are never touched."""

import json
import os
import shutil
import subprocess
import zipfile

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _blender(args, env=None):
    return subprocess.run([bpy.app.binary_path, "--factory-startup"] + args, capture_output=True, text=True,
                          timeout=600, env=env)


def test_update_replaces_the_installed_extension(out_dir):
    work = os.path.join(out_dir, "update")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    old = os.path.join(work, "realworn-1.0.0.zip")
    new = os.path.join(work, "realworn-99.0.0.zip")
    built = os.path.join(work, "build.zip")
    r = _blender(["--command", "extension", "build", "--source-dir", os.path.join(ROOT, "realworn"),
                  "--output-filepath", built])
    assert os.path.isfile(built), r.stdout + r.stderr
    for path, version in ((old, "1.0.0"), (new, "99.0.0")):  # the same code under two versions
        with zipfile.ZipFile(built) as a, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as b:
            for info in a.infolist():
                data = a.read(info)
                if info.filename.endswith("blender_manifest.toml"):
                    lines = [('version = "{}"'.format(version) if l.startswith("version =") else l)
                             for l in data.decode("utf-8").splitlines()]
                    data = ("\n".join(lines) + "\n").encode("utf-8")
                b.writestr(info, data)
    env = dict(os.environ, BLENDER_USER_RESOURCES=os.path.join(work, "profile"))
    r = _blender(["--background", "--online-mode", "--python", os.path.join(ROOT, "tests", "fixtures", "update_install.py"),
                  "--", old, new], env=env)
    line = next((l for l in r.stdout.splitlines() if l.startswith("UPDATE_RESULT ")), None)
    assert line, r.stdout[-3000:] + r.stderr[-3000:]
    res = json.loads(line[len("UPDATE_RESULT "):])
    print("\n[update] {}".format(res))
    assert os.path.normcase(os.path.abspath(work)) in os.path.normcase(os.path.abspath(res["profile"]))
    assert res["old_enabled"] and res["old_version"] == [1, 0, 0] and res["target"] == ["user_default", None]
    assert res["checked"] == "AVAILABLE"
    assert res["reloaded"] and res["new_enabled"] and res["operators"]
    assert res["new_version"] == [99, 0, 0], res
