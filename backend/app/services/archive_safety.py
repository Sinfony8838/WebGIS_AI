"""Bounded ZIP validation shared by Office imports and geodata extraction.

This module has no runtime/store/config dependency. Validation reads members
in bounded chunks and checks CRC before a caller persists or parses content.
It does not extract files, execute Office, or rewrite the supplied archive.
"""
from __future__ import annotations

import io
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List

READ_CHUNK_BYTES = 64 * 1024
MAX_MEMBER_PATH_BYTES = 4096
MAX_MEMBER_PATH_DEPTH = 64


class ArchiveValidationError(ValueError):
    """Invalid, ambiguous or unsupported archive; map to HTTP 400."""


class ArchiveLimitError(ArchiveValidationError):
    """Archive exceeds a configured resource budget; map to HTTP 413."""


@dataclass(frozen=True)
class ZipLimits:
    max_total_bytes: int
    max_member_bytes: int
    max_entries: int = 2000

    def __post_init__(self) -> None:
        if min(self.max_total_bytes, self.max_member_bytes, self.max_entries) <= 0:
            raise ValueError("ZIP budgets must be positive")


OFFICE_ZIP_LIMITS = ZipLimits(200 * 1024 * 1024, 200 * 1024 * 1024)
_WINDOWS_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)


def _member_key(info: zipfile.ZipInfo) -> str:
    name = info.filename.replace("\\", "/")
    # Bound path processing as well as expanded content. ZIP permits 64 KiB
    # member names, which otherwise make ancestor checks costly even for tiny
    # empty archives. Ordinary OOXML and geodata paths fit well below these.
    if len(name.encode("utf-8")) > MAX_MEMBER_PATH_BYTES:
        raise ArchiveLimitError("ZIP 条目路径过长")
    parts = PurePosixPath(name).parts
    if len(parts) > MAX_MEMBER_PATH_DEPTH:
        raise ArchiveLimitError("ZIP 条目路径层级过深")
    if (not name or "\x00" in info.orig_filename or name.startswith("/") or ":" in name
            or ".." in parts or not parts
            or any(part.rstrip(" .") != part or _WINDOWS_RESERVED.match(part)
                   or any(char in part for char in '<>"|?*') for part in parts)):
        raise ArchiveValidationError(f"Unsafe ZIP entry: {info.filename}")
    mode = (info.external_attr >> 16) & 0o170000
    if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ArchiveValidationError(f"Unsafe ZIP entry: {info.filename}")
    return "/".join(part.casefold() for part in parts)


def validate_zip(archive: zipfile.ZipFile, limits: ZipLimits, *,
                 required_members: tuple[str, ...] = ()) -> List[zipfile.ZipInfo]:
    """Validate metadata first, then bounded real reads including CRC checks.

    Limits apply to all members, including unreferenced OOXML media. Names are
    normalized for both Windows and POSIX destinations before duplicate checks.
    Deflate/stored archives cover normal Office and Shapefile ZIP producers;
    other codecs are rejected rather than permitting unbounded codec memory.
    """
    members = archive.infolist()
    if len(members) > limits.max_entries:
        raise ArchiveLimitError(f"ZIP 内条目数超过安全上限（{limits.max_entries}）")
    declared_total = 0
    targets: dict[str, bool] = {}
    for member in members:
        key = _member_key(member)
        if key in targets:
            raise ArchiveValidationError(f"ZIP 包含重复路径：{member.filename}")
        targets[key] = member.is_dir()
        if member.file_size < 0 or member.compress_size < 0:
            raise ArchiveValidationError("ZIP 条目大小无效")
        if member.is_dir() and member.file_size:
            raise ArchiveValidationError("ZIP 目录包含异常数据")
        if member.file_size > limits.max_member_bytes:
            raise ArchiveLimitError(f"ZIP 条目解压后过大（{member.filename}）")
        declared_total += member.file_size
        if declared_total > limits.max_total_bytes:
            raise ArchiveLimitError("ZIP 解压后总大小超过安全上限")
        if member.flag_bits & 1:
            raise ArchiveValidationError("不支持加密 ZIP 文件")
        if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ArchiveValidationError("不支持该 ZIP 压缩方式，请使用普通 ZIP/Deflate")
    for key in targets:
        parts = key.split("/")
        if any(targets.get("/".join(parts[:index])) is False for index in range(1, len(parts))):
            raise ArchiveValidationError("ZIP 文件与目录路径冲突")
    names = {member.filename for member in members if not member.is_dir()}
    if not set(required_members).issubset(names):
        raise ArchiveValidationError("文件缺少必需的文档结构，可能已损坏")

    actual_total = 0
    try:
        for member in members:
            if member.is_dir():
                continue
            actual_member = 0
            with archive.open(member) as source:
                while True:
                    remaining = min(limits.max_member_bytes - actual_member, limits.max_total_bytes - actual_total)
                    chunk = source.read(min(READ_CHUNK_BYTES, remaining + 1))
                    if not chunk:
                        break
                    actual_member += len(chunk)
                    actual_total += len(chunk)
                    if actual_member > limits.max_member_bytes or actual_total > limits.max_total_bytes:
                        raise ArchiveLimitError("ZIP 实际解压大小超过安全上限")
            if actual_member != member.file_size:
                raise ArchiveValidationError("ZIP 条目实际大小与声明不符")
    except (zipfile.BadZipFile, EOFError, zlib.error, RuntimeError, NotImplementedError) as exc:
        raise ArchiveValidationError("ZIP 数据或 CRC 校验失败，文件可能已损坏") from exc
    return members


def validate_office_bytes(raw: bytes, kind: str, *, limits: ZipLimits | None = None) -> None:
    """Validate DOCX/PPTX bytes before a third-party parser or renderer opens them.

    Binary .doc/.ppt callers must preserve their existing handling separately.
    No compression-ratio rejection: repetitive but budget-compliant text is valid.
    """
    main_part = {"docx": "word/document.xml", "pptx": "ppt/presentation.xml"}.get(kind.lower().lstrip("."))
    if main_part is None:
        raise ValueError("Only DOCX and PPTX use ZIP validation")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            validate_zip(archive, limits or OFFICE_ZIP_LIMITS,
                         required_members=("[Content_Types].xml", "_rels/.rels", main_part))
    except zipfile.BadZipFile as exc:
        raise ArchiveValidationError("文件不是有效的 Office ZIP 文档") from exc
