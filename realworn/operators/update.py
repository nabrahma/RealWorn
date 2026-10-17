"""Updates: Check for Updates and Update. The check and the download run on a thread; a timer
applies the result on the main thread and installs the zip with Blender's extension installer, in
place, into the repository RealWorn was installed into."""

import contextlib
import os
import queue
import tempfile
import threading

import bpy

from ..core import update

PACKAGE = __package__.rsplit(".", 1)[0]
PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# status: "" (not checked), CHECKING, LATEST, AVAILABLE, DOWNLOADING, ERROR
STATE = dict(status="", info=None, message="")
_results = queue.Queue()


def current_version():
    try:
        return update.manifest_version(PACKAGE_DIR)
    except (OSError, KeyError, ValueError):
        return None


def target():
    """(repository module, None) when this copy can update itself, else (None, reason)."""
    repos = [(r.module, r.directory, r.source, r.use_remote_url) for r in bpy.context.preferences.extensions.repos]
    return update.install_target(PACKAGE, PACKAGE_DIR, repos)


def _redraw():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type in {"VIEW_3D", "IMAGE_EDITOR", "PREFERENCES"}:
                area.tag_redraw()


def _run(kind, fn, *args):
    def work():
        try:
            _results.put((kind, fn(*args)))
        except Exception as ex:  # network, disk or checksum: shown to the user as it is
            _results.put(("ERROR", str(ex) or type(ex).__name__))
    threading.Thread(target=work, daemon=True).start()
    if not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll, first_interval=0.25)


def start_check():
    if STATE["status"] in {"CHECKING", "DOWNLOADING"}:
        return False
    STATE.update(status="CHECKING", message="")
    _run("CHECKED", update.fetch_latest)
    return True


def _poll():
    try:
        kind, value = _results.get_nowait()
    except queue.Empty:
        return 0.25
    if kind == "ERROR":
        STATE.update(status="ERROR", message=value)
    elif kind == "CHECKED":
        cur = current_version()
        if value is None:
            STATE.update(status="ERROR", info=None, message="The latest release has no RealWorn zip")
        elif cur is None or update.is_newer(value["version"], cur):
            STATE.update(status="AVAILABLE", info=value, message="")
        else:
            STATE.update(status="LATEST", info=value, message="")
    elif kind == "DOWNLOADED":
        _redraw()
        return _install(value)
    _redraw()
    return None


def _install(path):
    """Install the downloaded zip over this copy. Blender disables RealWorn, replaces its files and
    enables the new version, so nothing of this module is used after the call."""
    repo, why = target()
    if repo is None:
        STATE.update(status="ERROR", message=why)
        _redraw()
        return None
    wm = bpy.context.window_manager
    ctx = bpy.context.temp_override(window=wm.windows[0]) if wm.windows else contextlib.nullcontext()
    try:
        with ctx:
            bpy.ops.extensions.package_install_files(filepath=path, repo=repo, enable_on_install=True,
                                                     overwrite=True)
    except Exception as ex:
        STATE.update(status="ERROR", message="Install failed: {}".format(ex))
        _redraw()
    return None


def _auto_check():
    from ..props import prefs
    p = prefs()
    if p is not None and p.check_updates and bpy.app.online_access and STATE["status"] == "":
        start_check()
    return None


def _online(op):
    if not bpy.app.online_access:
        op.report({"WARNING"}, "Online access is off (Preferences > System > Network > Allow Online Access)")
        return False
    return True


class RW_OT_update_check(bpy.types.Operator):
    """Ask GitHub for the latest RealWorn release"""
    bl_idname = "realworn.update_check"
    bl_label = "Check for Updates"

    def execute(self, context):
        if not _online(self):
            return {"CANCELLED"}
        start_check()
        return {"FINISHED"}


class RW_OT_update_install(bpy.types.Operator):
    """Download the latest RealWorn release and install it over this one"""
    bl_idname = "realworn.update_install"
    bl_label = "Update RealWorn"

    @classmethod
    def poll(cls, context):
        return STATE["status"] == "AVAILABLE"

    def execute(self, context):
        if not _online(self):
            return {"CANCELLED"}
        repo, why = target()
        if repo is None:
            self.report({"ERROR"}, why)
            return {"CANCELLED"}
        STATE.update(status="DOWNLOADING", message="")
        _run("DOWNLOADED", update.download, STATE["info"], tempfile.mkdtemp(prefix="realworn_update_"))
        return {"FINISHED"}


_classes = (RW_OT_update_check, RW_OT_update_install)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    if not bpy.app.background:
        bpy.app.timers.register(_auto_check, first_interval=4.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_auto_check):
        bpy.app.timers.unregister(_auto_check)
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
