import json

import pytest

from pisumathu import paths
from pisumathu.asr import models


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    yield tmp_path


def test_known_model_resolves_under_models_dir():
    path = models.resolve_model("tiny")
    assert path == paths.models_dir() / "tiny"


@pytest.mark.parametrize("name", ["../../etc", "tiny/../../x", "", "banana", "/abs/path"])
def test_unknown_or_traversing_names_rejected(name):
    with pytest.raises(models.ModelError):
        models.resolve_model(name)


def test_model_available_false_when_absent():
    assert models.model_available("tiny") is False


def test_model_available_true_when_model_bin_present():
    directory = models.resolve_model("tiny")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "model.bin").write_bytes(b"weights")
    assert models.model_available("tiny") is True


def test_verify_fails_without_manifest():
    directory = models.resolve_model("tiny")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "model.bin").write_bytes(b"weights")
    assert models.verify_model("tiny") is False


def test_verify_passes_for_manifested_model():
    directory = models.resolve_model("tiny")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "model.bin").write_bytes(b"weights")
    (directory / "config.json").write_text("{}", encoding="utf-8")
    models._write_manifest(directory, "tiny")
    assert models.verify_model("tiny") is True


def test_verify_detects_tampering():
    directory = models.resolve_model("tiny")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "model.bin").write_bytes(b"weights")
    models._write_manifest(directory, "tiny")
    (directory / "model.bin").write_bytes(b"tampered")
    assert models.verify_model("tiny") is False


def test_verify_rejects_manifest_path_traversal():
    directory = models.resolve_model("tiny")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / models.MANIFEST_NAME).write_text(
        json.dumps({"files": {"../../../etc/passwd": "deadbeef"}}), encoding="utf-8"
    )
    assert models.verify_model("tiny") is False


def test_default_model_is_tiny():
    assert models.DEFAULT_MODEL == "tiny"
    assert models.DEFAULT_MODEL in models.MODEL_IDS
