"""Immutable original storage tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage import LocalObjectStorage, StorageError, checksum_of


def test_original_bytes_round_trip(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    data = b"%PDF-1.7 sample"
    uri = storage.put_original(checksum_of(data), data)

    assert storage.exists(uri)
    assert storage.read(uri) == data


def test_identical_bytes_are_stored_once(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    data = b"%PDF-1.7 sample"
    first = storage.put_original(checksum_of(data), data)
    second = storage.put_original(checksum_of(data), data)

    assert first == second
    assert len(list(tmp_path.rglob("*.bin"))) == 1


def test_checksum_mismatch_is_refused(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    with pytest.raises(StorageError):
        storage.put_original("0" * 64, b"%PDF-1.7 sample")


def test_uri_cannot_escape_the_storage_root(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path / "root")
    with pytest.raises(StorageError):
        storage.local_path("local://../../etc/passwd")


def test_unknown_scheme_is_refused(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    with pytest.raises(StorageError):
        storage.local_path("s3://bucket/key")


def test_missing_object_is_a_structured_error(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    with pytest.raises(StorageError):
        storage.read("local://ab/cd/missing.bin")
