"""Immutable original-document storage.

The original upload is the one artifact everything else is derived from, so it is
content-addressed and written exactly once. Nothing in the pipeline may overwrite it
(`docs/09_CODEX_EXECUTION.md` section 8).

The abstraction exists so object storage can replace the local filesystem later
without touching ingestion code.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Protocol


class StorageError(RuntimeError):
    """Raised when the original bytes cannot be persisted or read back."""


def checksum_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStorage(Protocol):
    def put_original(self, checksum: str, data: bytes) -> str:
        """Persist original bytes durably and return their opaque storage URI."""

    def read(self, uri: str) -> bytes:
        """Read an object back by URI."""

    def local_path(self, uri: str) -> Path:
        """A readable local path for the object, for parsers that need a file."""

    def exists(self, uri: str) -> bool: ...


class LocalObjectStorage:
    """Content-addressed, write-once storage on the local filesystem."""

    scheme = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _path_for_checksum(self, checksum: str) -> Path:
        return self.root / checksum[:2] / checksum[2:4] / f"{checksum}.bin"

    def put_original(self, checksum: str, data: bytes) -> str:
        if checksum_of(data) != checksum:
            raise StorageError("checksum does not match the payload")

        target = self._path_for_checksum(checksum)
        uri = f"{self.scheme}://{target.relative_to(self.root).as_posix()}"

        if target.exists():
            # Content-addressed and immutable: identical bytes are already durable.
            return uri

        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file and rename, so a crash never leaves a partial
        # original that later looks complete.
        handle, temporary = tempfile.mkstemp(dir=target.parent, suffix=".part")
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except OSError as exc:  # pragma: no cover - filesystem failure path
            Path(temporary).unlink(missing_ok=True)
            raise StorageError(f"could not persist original bytes: {exc}") from exc

        return uri

    def local_path(self, uri: str) -> Path:
        if not uri.startswith(f"{self.scheme}://"):
            raise StorageError(f"unsupported storage uri: {uri}")
        relative = uri[len(self.scheme) + 3 :]
        path = (self.root / relative).resolve()
        if not str(path).startswith(str(self.root)):
            raise StorageError("storage uri escapes the storage root")
        return path

    def read(self, uri: str) -> bytes:
        path = self.local_path(uri)
        if not path.is_file():
            raise StorageError(f"object not found: {uri}")
        return path.read_bytes()

    def exists(self, uri: str) -> bool:
        try:
            return self.local_path(uri).is_file()
        except StorageError:
            return False
