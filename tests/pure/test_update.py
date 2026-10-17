"""Updates from GitHub releases: versions, picking the release zip, checking the download, and
where an update may be installed."""

import hashlib
import json
import os
import pathlib

import pytest

from realworn.core import update as U


def _release(tag="v3.5.0", name="realworn-3.5.0.zip", **kw):
    asset = dict(name=name, size=3, browser_download_url="https://example.invalid/" + name,
                 digest="sha256:" + hashlib.sha256(b"zip").hexdigest())
    return dict(dict(tag_name=tag, draft=False, prerelease=False, html_url="https://example.invalid/r",
                     assets=[dict(name="Source.zip", size=1, browser_download_url="x"), asset]), **kw)


def test_versions():
    assert U.parse_version("v3.4.0") == (3, 4, 0)
    assert U.parse_version("3.10") == (3, 10)
    assert U.parse_version("v3.4.0-beta") is None
    assert U.is_newer((3, 10, 0), (3, 9, 9))
    assert U.is_newer((3, 5), (3, 4, 9))
    assert not U.is_newer((3, 4), (3, 4, 0))
    assert U.version_text((3, 5, 0)) == "3.5.0"


def test_release_info_picks_the_zip_of_its_own_version():
    info = U.release_info(_release())
    assert info["version"] == (3, 5, 0) and info["name"] == "realworn-3.5.0.zip"
    assert info["size"] == 3 and info["sha256"] == hashlib.sha256(b"zip").hexdigest()
    assert U.release_info(_release(name="realworn-3.4.0.zip")) is None  # a stale zip on a new tag
    assert U.release_info(_release(draft=True)) is None
    assert U.release_info(_release(prerelease=True)) is None
    assert U.release_info(_release(tag="nightly")) is None


def test_fetch_and_download_check_the_zip(tmp_path):
    (tmp_path / "realworn-3.5.0.zip").write_bytes(b"zip")
    rel = _release()
    rel["assets"][1]["browser_download_url"] = (tmp_path / "realworn-3.5.0.zip").as_uri()
    api = tmp_path / "latest.json"
    api.write_text(json.dumps(rel))
    info = U.fetch_latest(api.as_uri())
    out = tmp_path / "out"
    out.mkdir()
    assert pathlib.Path(U.download(info, str(out))).read_bytes() == b"zip"
    with pytest.raises(ValueError, match="checksum"):
        U.download(dict(info, sha256="0" * 64), str(out))
    with pytest.raises(ValueError, match="incomplete"):
        U.download(dict(info, size=4), str(out))


def test_install_target_only_a_real_install_in_a_user_repository(tmp_path):
    repo = tmp_path / "user_default"
    (repo / "realworn").mkdir(parents=True)
    repos = [("user_default", str(repo), "USER", False), ("blender_org", str(tmp_path / "org"), "USER", True),
             ("system", str(tmp_path / "sys"), "SYSTEM", False)]
    assert U.install_target("bl_ext.user_default.realworn", str(repo / "realworn"), repos) == ("user_default", None)
    assert U.install_target("realworn", str(repo / "realworn"), repos)[0] is None
    assert U.install_target("bl_ext.blender_org.realworn", str(tmp_path / "org" / "realworn"), repos)[0] is None
    assert U.install_target("bl_ext.system.realworn", str(tmp_path / "sys" / "realworn"), repos)[0] is None


def test_install_target_refuses_a_linked_source_folder(tmp_path):
    """A development repository whose realworn folder links to the source checkout: installing over
    it would delete the source."""
    src = tmp_path / "checkout" / "realworn"
    src.mkdir(parents=True)
    dev = tmp_path / "dev"
    dev.mkdir()
    try:
        os.symlink(src, dev / "realworn", target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("cannot create a link here")
        import subprocess
        subprocess.run(["cmd", "/c", "mklink", "/J", str(dev / "realworn"), str(src)], check=True,
                       capture_output=True)
    repos = [("dev", str(dev), "USER", False)]
    for package_dir in (str(src), str(dev / "realworn")):
        repo, why = U.install_target("bl_ext.dev.realworn", package_dir, repos)
        assert repo is None and "source" in why
