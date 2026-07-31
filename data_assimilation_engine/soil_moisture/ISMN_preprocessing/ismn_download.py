"""Download or sync raw ISMN files into a local staging directory.

This module is intentionally simple. It supports:
- copying/syncing from a remote filesystem supported by fsspec
- filtering for .stm files
- optional limit for smoke tests

Examples of remote_source:
- file:///path/to/raw_ismn
- s3://bucket/path/to/raw_ismn
- /already/mounted/path/raw_ismn

This module does NOT parse ISMN content. It only stages raw files locally.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import fsspec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadResult:
    remote_source: str
    local_output_dir: str
    discovered_files: int
    copied_files: int
    skipped_files: int


class ISMNDownloader:
    """Stage raw ISMN .stm files from a remote/local source."""

    def __init__(
        self,
        remote_source: str,
        local_output_dir: str,
        fs: Optional[fsspec.AbstractFileSystem] = None,
        overwrite: bool = False,
        limit_files: int | None = None,
    ) -> None:
        self.remote_source = remote_source.rstrip("/")
        self.local_output_dir = local_output_dir.rstrip("/")
        self.fs = fs or self._infer_filesystem(remote_source)
        self.overwrite = overwrite
        self.limit_files = limit_files

    def _infer_filesystem(self, source: str) -> fsspec.AbstractFileSystem:
        if source.startswith("s3://"):
            return fsspec.filesystem("s3")
        if source.startswith("file://"):
            return fsspec.filesystem("file")
        # default fallback
        return fsspec.filesystem("file")

    def run(self) -> DownloadResult:
        files = self.discover_stm_files(self.remote_source)
        if self.limit_files is not None:
            files = files[: self.limit_files]

        Path(self.local_output_dir).mkdir(parents=True, exist_ok=True)

        copied = 0
        skipped = 0

        for src in files:
            rel_path = self._relative_remote_path(src)
            dst = os.path.join(self.local_output_dir, rel_path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)

            if os.path.exists(dst) and not self.overwrite:
                logger.info("Skipping existing file: %s", dst)
                skipped += 1
                continue

            logger.info("Copying %s -> %s", src, dst)
            with self.fs.open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                fdst.write(fsrc.read())
            copied += 1

        return DownloadResult(
            remote_source=self.remote_source,
            local_output_dir=self.local_output_dir,
            discovered_files=len(files),
            copied_files=copied,
            skipped_files=skipped,
        )

    def discover_stm_files(self, source: str) -> list[str]:
        found: list[str] = []
        self._discover(source, found)
        return found

    def _discover(self, path: str, found: list[str]) -> None:
        if self.fs.isfile(path) and path.lower().endswith(".stm"):
            found.append(path)
            return

        if not self.fs.isdir(path):
            return

        for entry in self.fs.ls(path, detail=True):
            entry_path = entry["name"]
            entry_type = entry["type"]
            if entry_type == "file" and entry_path.lower().endswith(".stm"):
                found.append(entry_path)
            elif entry_type == "directory":
                self._discover(entry_path, found)

    def _relative_remote_path(self, src: str) -> str:
        source = self.remote_source
        if source.startswith("file://"):
            source = source.replace("file://", "", 1)

        src_clean = src.replace("file://", "", 1)
        source_clean = source.rstrip("/")

        if src_clean.startswith(source_clean):
            rel = src_clean[len(source_clean):].lstrip("/")
            return rel or os.path.basename(src_clean)

        return os.path.basename(src_clean)
