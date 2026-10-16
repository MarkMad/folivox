"""Reusing weights found on this computer: matching, size and sha checks, hard link versus copy."""

import hashlib
import os

import pytest

from folivox.tts import builds, fish_setup, reuse


def fake_build():
    base = builds.load().build("s2pro-mlx-8bit")
    data = b"weights-weights"
    files = ({"path": "model.safetensors", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
             {"path": "config.json", "size": 2, "sha256": None})
    return builds.Build(**{**base.__dict__, "files": files}), data


@pytest.fixture(autouse=True)
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(builds, "engines_root", lambda: tmp_path / "engines")
    monkeypatch.setattr(reuse, "hf_cache_roots", lambda: [tmp_path / "hf"])
    monkeypatch.setattr(reuse, "lmstudio_roots", lambda: [tmp_path / "lms"])


def snapshot(tmp_path, b, name="model.safetensors", data=b"weights-weights"):
    org, _, repo = b.repo.partition("/")
    d = tmp_path / "hf" / f"models--{org}--{repo}" / "snapshots" / "abc"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    return d / name


def test_match_is_hard_linked_on_one_volume(tmp_path):
    b, data = fake_build()
    src = snapshot(tmp_path, b)
    assert reuse.found_bytes(b) == len(data)  # files without a sha256 are never counted
    assert reuse.adopt(b) == {"model.safetensors": "linked"}
    dst = builds.weights_dir(b) / "model.safetensors"
    assert os.path.samefile(src, dst) and not dst.is_symlink()


def test_copy_when_linking_is_impossible(tmp_path, monkeypatch):
    b, _ = fake_build()
    src = snapshot(tmp_path, b)

    def no_link(*a, **k):
        raise OSError("cross-device")

    monkeypatch.setattr(os, "link", no_link)
    assert reuse.adopt(b) == {"model.safetensors": "copied"}
    dst = builds.weights_dir(b) / "model.safetensors"
    assert dst.read_bytes() == src.read_bytes() and not os.path.samefile(src, dst)


def test_size_mismatch_is_not_a_candidate(tmp_path):
    b, _ = fake_build()
    snapshot(tmp_path, b, data=b"short")
    assert reuse.find(b) == {} and reuse.adopt(b) == {}


def test_sha_mismatch_is_never_used(tmp_path):
    b, data = fake_build()
    snapshot(tmp_path, b, data=data.upper())  # same size, other content
    assert reuse.adopt(b) == {}
    assert not (builds.weights_dir(b) / "model.safetensors").exists()


def test_other_places_and_the_next_candidate(tmp_path):
    b, data = fake_build()
    snapshot(tmp_path, b, data=data.upper())  # bad copy in the HF cache
    org, _, repo = b.repo.partition("/")
    good = tmp_path / "lms" / org / repo
    good.mkdir(parents=True)
    (good / "model.safetensors").write_bytes(data)  # good one in LM Studio
    assert reuse.adopt(b) == {"model.safetensors": "linked"}
    assert (builds.weights_dir(b) / "model.safetensors").read_bytes() == data


def test_older_folivox_build_folder_is_a_source(tmp_path):
    b, data = fake_build()
    other = next(o for o in builds.load().builds if o.id != b.id)
    wd = builds.weights_dir(other)
    wd.mkdir(parents=True)
    (wd / "model.safetensors").write_bytes(data)
    assert reuse.found_bytes(b) == len(data)


def test_install_downloads_only_what_was_not_found(tmp_path, monkeypatch):
    b, data = fake_build()
    snapshot(tmp_path, b)
    monkeypatch.setattr(fish_setup.licences, "require", lambda b: None)
    monkeypatch.setattr(fish_setup, "free_disk_ok", lambda *a: None)
    monkeypatch.setattr(fish_setup, "ensure_runtime", lambda *a: None)
    asked = []

    def fake_download(b, wd, names, progress, log):
        asked.append(names)
        (wd / "config.json").write_text("{}")

    monkeypatch.setattr(fish_setup, "_download", fake_download)
    phases = []
    fish_setup.install(b, None, lambda m: None, phase=lambda n, s: phases.append(n))
    assert asked == [["config.json"]] and phases == ["found", "downloading"]
    assert (builds.weights_dir(b) / "model.safetensors").read_bytes() == data
