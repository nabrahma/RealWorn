# SPDX-License-Identifier: GPL-3.0-or-later
"""Updates from the project's GitHub releases: find the latest release, download its zip and check
it, and decide where an update may be installed. No bpy here: operators/update.py runs the network
parts on a thread and installs with Blender's own extension installer on the main thread."""

import hashlib
import json
import os
import re
import urllib.request

REPO = "nabrahma/RealWorn"
LATEST_URL = "https://api.github.com/repos/{}/releases/latest".format(REPO)
RELEASES_PAGE = "https://github.com/{}/releases/latest".format(REPO)
TIMEOUT = 20
_ASSET = re.compile(r"realworn-(\d+(?:\.\d+)*)\.zip")


def parse_version(text):
    """'v3.5.0' or '3.5.0' -> (3, 5, 0); None when it is not a version."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def version_text(version):
    return ".".join(str(x) for x in version)


def is_newer(latest, current):
    pad = lambda v: tuple(v) + (0,) * max(0, 3 - len(v))
    return pad(latest) > pad(current)


def manifest_version(package_dir):
    """The version in the add-on's blender_manifest.toml."""
    import tomllib
    with open(os.path.join(package_dir, "blender_manifest.toml"), "rb") as fh:
        return parse_version(tomllib.load(fh)["version"])


def release_info(release):
    """A release as the GitHub API returns it -> dict(version, tag, name, url, size, sha256, page),
    or None when it is a draft or pre-release or has no RealWorn zip of its own version."""
    if release.get("draft") or release.get("prerelease"):
        return None
    version = parse_version(release.get("tag_name"))
    if version is None:
        return None
    for asset in release.get("assets") or ():
        m = _ASSET.fullmatch(asset.get("name", ""))
        if m and parse_version(m.group(1)) == version:
            digest = asset.get("digest") or ""
            return dict(version=version, tag=release["tag_name"], name=asset["name"],
                        url=asset["browser_download_url"], size=int(asset.get("size") or 0),
                        sha256=digest[len("sha256:"):] if digest.startswith("sha256:") else "",
                        page=release.get("html_url") or RELEASES_PAGE)
    return None


def _open(url, api=False):
    headers = {"User-Agent": "RealWorn-updater"}
    if api:
        headers["Accept"] = "application/vnd.github+json"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT)


def fetch_latest(url=LATEST_URL):
    """The latest release's info (see release_info), or None when it has no RealWorn zip."""
    with _open(url, api=True) as r:
        return release_info(json.load(r))


def download(info, folder):
    """Download the release zip into `folder`; its size and SHA-256 must match the release's."""
    path = os.path.join(folder, info["name"])
    h, n = hashlib.sha256(), 0
    with _open(info["url"]) as r, open(path, "wb") as fh:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            h.update(chunk)
            fh.write(chunk)
            n += len(chunk)
    if info["size"] and n != info["size"]:
        raise ValueError("download incomplete: {} of {} bytes".format(n, info["size"]))
    if info["sha256"] and h.hexdigest() != info["sha256"].lower():
        raise ValueError("download damaged: checksum does not match the release")
    return path


def install_target(package, package_dir, repos):
    """The extension repository an update can be installed into, as (module, None), or
    (None, reason). `repos` lists (module, directory, source, use_remote_url) for each repository.
    Only a copy that was installed into a user repository qualifies: never one linked to a source
    folder (installing over it would delete the source)."""
    parts = package.split(".")
    if len(parts) != 3 or parts[0] != "bl_ext":
        return None, "RealWorn is not installed as an extension"
    repo = next((r for r in repos if r[0] == parts[1]), None)
    if repo is None:
        return None, "RealWorn's extension repository was not found"
    module, directory, source, remote = repo
    if source != "USER":
        return None, "RealWorn is installed in a system repository"
    if remote:
        return None, "RealWorn came from an online repository: update it in Get Extensions"
    norm = lambda p: os.path.normcase(os.path.normpath(p))
    installed = os.path.join(os.path.realpath(directory), parts[2])  # the folder itself, not where a link points
    linked = os.path.islink(installed) or getattr(os.path, "isjunction", lambda p: False)(installed)
    if linked or norm(os.path.realpath(package_dir)) != norm(installed):
        return None, "This RealWorn is linked to a source folder: update the source instead"
    return module, None
