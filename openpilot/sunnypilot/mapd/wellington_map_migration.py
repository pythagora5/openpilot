#!/usr/bin/env python3
"""Install the bundled Lyle Pilot Wellington map group before manager starts."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
from typing import Any

from openpilot.common.basedir import BASEDIR


MIGRATION_ID = "lyle-pilot-wellington-map-v1"
ARCHIVE_NAME = "lyle-pilot-wellington-mapd-v1.12.0-osm-2026-08-01-v1.tar.gz"
ARCHIVE_PATH = Path(BASEDIR) / "tools" / "map_data" / "wellington" / "pilot-v1" / ARCHIVE_NAME
ARCHIVE_SHA256 = "34cdc77e6b9316a520e2eb27fe0b7e4d963a9b748131056cf8c8438e0afb8db5"
GROUP_DIGEST = "a59a7e4d25dbbc51e1d0e4ad42d2fa5ec3db90e5b12830201c105d150225e0e4"
GROUP_MEMBER = PurePosixPath("offline/-42/174")
GROUP_RELATIVE = Path("offline/-42/174")
EXPECTED_FILE_COUNT = 64
DEVICE_MAP_ROOT = Path("/data/media/0/osm")


class MigrationError(RuntimeError):
  pass


class SimulatedPowerLoss(BaseException):
  """Test-only failure that intentionally bypasses caught-error recovery."""


def _sha256(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as file:
    for chunk in iter(lambda: file.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
  descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
  try:
    os.fsync(descriptor)
  finally:
    os.close(descriptor)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
  descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
  temporary_path = Path(temporary_name)
  try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
      json.dump(payload, file, indent=2, sort_keys=True)
      file.write("\n")
      file.flush()
      os.fsync(file.fileno())
    os.replace(temporary_path, path)
    _fsync_directory(path.parent)
  finally:
    if temporary_path.exists():
      temporary_path.unlink()


def _read_json(path: Path) -> dict[str, Any]:
  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as error:
    raise MigrationError(f"Cannot read migration state {path}: {error}") from error
  if not isinstance(payload, dict):
    raise MigrationError(f"Migration state is not an object: {path}")
  return payload


def _preserve(path: Path, label: str) -> Path | None:
  if not (path.exists() or path.is_symlink()):
    return None
  destination = path.with_name(f"{path.name}.{label}")
  if destination.exists():
    _discard(destination)
  os.replace(path, destination)
  _fsync_directory(path.parent)
  return destination


def _discard(path: Path) -> None:
  if path.is_dir() and not path.is_symlink():
    shutil.rmtree(path)
  elif path.exists() or path.is_symlink():
    path.unlink()
  _fsync_directory(path.parent)


def _inspect_archive(archive_path: Path, expected_sha256: str, expected_file_count: int) -> tuple[tarfile.TarInfo, ...]:
  if not archive_path.is_file():
    raise MigrationError(f"Bundled archive is missing: {archive_path}")
  actual_sha256 = _sha256(archive_path)
  if actual_sha256 != expected_sha256:
    raise MigrationError(f"Archive SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}")

  try:
    with tarfile.open(archive_path, "r:gz") as archive:
      members = tuple(archive.getmembers())
  except (OSError, tarfile.TarError) as error:
    raise MigrationError(f"Cannot read bundled archive: {error}") from error

  names = [member.name for member in members]
  if len(names) != len(set(names)):
    raise MigrationError("Archive contains duplicate member names")

  root_name = GROUP_MEMBER.as_posix()
  root_members = [member for member in members if member.name == root_name]
  if len(root_members) != 1 or not root_members[0].isdir():
    raise MigrationError(f"Archive must contain exactly one {root_name} directory")

  file_members = []
  for member in members:
    member_path = PurePosixPath(member.name)
    if member_path.is_absolute() or ".." in member_path.parts:
      raise MigrationError(f"Unsafe archive path: {member.name}")
    if member.name == root_name:
      continue
    if not member.isfile():
      raise MigrationError(f"Unsupported archive member type: {member.name}")
    if member_path.parent != GROUP_MEMBER:
      raise MigrationError(f"Archive member is outside the expected tile group: {member.name}")
    file_members.append(member)

  if len(file_members) != expected_file_count or len(members) != expected_file_count + 1:
    raise MigrationError(f"Archive must contain one directory and {expected_file_count} files; found {len(members)} members")
  return tuple(sorted(file_members, key=lambda member: member.name))


def _group_digest(group_path: Path, expected_names: set[str], expected_file_count: int) -> str:
  try:
    entries = tuple(group_path.iterdir())
  except OSError as error:
    raise MigrationError(f"Cannot read tile group {group_path}: {error}") from error

  if len(entries) != expected_file_count:
    raise MigrationError(f"Tile group contains {len(entries)} entries; expected {expected_file_count}")
  if any(entry.is_symlink() or not entry.is_file() for entry in entries):
    raise MigrationError("Tile group contains a non-regular file")
  names = {entry.name for entry in entries}
  if names != expected_names:
    raise MigrationError("Tile group filenames do not match the bundled archive")

  digest = hashlib.sha256()
  for entry in sorted(entries, key=lambda item: item.name):
    digest.update(entry.name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(bytes.fromhex(_sha256(entry)))
  return digest.hexdigest()


def _validate_group(group_path: Path, expected_names: set[str], expected_file_count: int, expected_digest: str) -> None:
  actual_digest = _group_digest(group_path, expected_names, expected_file_count)
  if actual_digest != expected_digest:
    raise MigrationError(f"Tile group digest mismatch: expected {expected_digest}, got {actual_digest}")


def _extract_group(archive_path: Path, members: tuple[tarfile.TarInfo, ...], stage: Path) -> Path:
  group_stage = stage / GROUP_RELATIVE
  group_stage.mkdir(parents=True, exist_ok=False)
  with tarfile.open(archive_path, "r:gz") as archive:
    for member in members:
      source = archive.extractfile(member)
      if source is None:
        raise MigrationError(f"Cannot extract archive member: {member.name}")
      destination = group_stage / PurePosixPath(member.name).name
      with source, destination.open("xb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)
        output.flush()
        os.fsync(output.fileno())
      destination.chmod(0o644)
  group_stage.chmod(0o755)
  _fsync_directory(group_stage)
  _fsync_directory(group_stage.parent)
  _fsync_directory(stage)
  return group_stage


def _transaction_payload(target_present_before: bool, phase: str, archive_sha256: str, group_digest: str) -> dict[str, Any]:
  return {
    "migration": MIGRATION_ID,
    "archive_sha256": archive_sha256,
    "group_digest": group_digest,
    "target_present_before": target_present_before,
    "phase": phase,
  }


def _recover_transaction(target: Path, backup: Path, transaction: Path, stage: Path) -> None:
  try:
    payload = _read_json(transaction)
  except MigrationError:
    _preserve(transaction, "unrecognized-transaction")
    _discard(stage)
    return
  if payload.get("migration") != MIGRATION_ID or not isinstance(payload.get("target_present_before"), bool):
    _preserve(transaction, "unrecognized-transaction")
    _discard(stage)
    return

  target_present_before = payload["target_present_before"]
  if target_present_before:
    if backup.exists():
      if target.exists():
        _preserve(target, "interrupted")
      os.replace(backup, target)
      _fsync_directory(target.parent)
  elif target.exists():
    _preserve(target, "interrupted")

  _discard(stage)
  _preserve(transaction, "recovered-transaction")


def _maybe_fail(failpoint: str | None, point: str) -> None:
  if failpoint == point:
    raise SimulatedPowerLoss(point)


def _matching_marker_payload(marker: Path, archive_sha256: str, group_digest: str, file_count: int) -> dict[str, Any] | None:
  if not marker.is_file():
    return None
  try:
    payload = _read_json(marker)
  except MigrationError:
    return None
  if not (
    payload.get("migration") == MIGRATION_ID
    and payload.get("archive_sha256") == archive_sha256
    and payload.get("group_digest") == group_digest
    and payload.get("file_count") == file_count
  ):
    return None
  return payload


def _marker_payload(archive_sha256: str, group_digest: str, file_count: int, expected_names: set[str]) -> dict[str, Any]:
  return {
    "migration": MIGRATION_ID,
    "archive_sha256": archive_sha256,
    "group_digest": group_digest,
    "file_count": file_count,
    "files": sorted(expected_names),
  }


def install_wellington_map(
  archive_path: Path,
  map_root: Path,
  *,
  expected_archive_sha256: str = ARCHIVE_SHA256,
  expected_group_digest: str = GROUP_DIGEST,
  expected_file_count: int = EXPECTED_FILE_COUNT,
  failpoint: str | None = None,
) -> str:
  map_root.mkdir(parents=True, exist_ok=True)
  target = map_root / GROUP_RELATIVE
  backup = target.with_name(f"{target.name}.{MIGRATION_ID}.backup")
  marker = map_root / f".{MIGRATION_ID}.installed.json"
  transaction = map_root / f".{MIGRATION_ID}.transaction.json"
  stage = map_root / f".{MIGRATION_ID}.stage"
  lock_path = map_root / f".{MIGRATION_ID}.lock"

  with lock_path.open("a+") as lock:
    try:
      fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
      raise MigrationError("Another Wellington map migration is already running") from error

    marker_payload = _matching_marker_payload(marker, expected_archive_sha256, expected_group_digest, expected_file_count)
    marker_names = marker_payload.get("files") if marker_payload is not None else None
    if (
      isinstance(marker_names, list)
      and len(marker_names) == expected_file_count
      and all(isinstance(name, str) for name in marker_names)
      and len(set(marker_names)) == expected_file_count
      and target.is_dir()
    ):
      try:
        _validate_group(target, set(marker_names), expected_file_count, expected_group_digest)
      except MigrationError:
        pass
      else:
        _discard(stage)
        _preserve(transaction, "completed-transaction")
        return "already_installed"

    members = _inspect_archive(archive_path, expected_archive_sha256, expected_file_count)
    expected_names = {PurePosixPath(member.name).name for member in members}
    matching_marker = marker_payload is not None

    target_valid = False
    if target.is_dir():
      try:
        _validate_group(target, expected_names, expected_file_count, expected_group_digest)
        target_valid = True
      except MigrationError:
        target_valid = False

    if target_valid:
      _atomic_json(marker, _marker_payload(expected_archive_sha256, expected_group_digest, expected_file_count, expected_names))
      _discard(stage)
      _preserve(transaction, "completed-transaction")
      return "already_installed"

    if transaction.exists():
      _recover_transaction(target, backup, transaction, stage)

    if backup.exists() and not matching_marker:
      if target.exists():
        _preserve(target, "backup-collision-target")
      os.replace(backup, target)
      _fsync_directory(target.parent)
    if matching_marker:
      _preserve(target, "invalid-installed-group")
    else:
      _preserve(marker, "invalid-marker")
    _discard(stage)

    target_present_before = target.exists()
    try:
      group_stage = _extract_group(archive_path, members, stage)
      _validate_group(group_stage, expected_names, expected_file_count, expected_group_digest)
      _atomic_json(
        transaction,
        _transaction_payload(target_present_before, "prepared", expected_archive_sha256, expected_group_digest),
      )
      _maybe_fail(failpoint, "after_prepared")

      target.parent.mkdir(parents=True, exist_ok=True)
      if target_present_before:
        os.replace(target, backup)
        _fsync_directory(target.parent)
      _atomic_json(
        transaction,
        _transaction_payload(target_present_before, "old_target_moved", expected_archive_sha256, expected_group_digest),
      )
      _maybe_fail(failpoint, "after_old_target_move")

      os.replace(group_stage, target)
      _fsync_directory(target.parent)
      _atomic_json(
        transaction,
        _transaction_payload(target_present_before, "target_swapped", expected_archive_sha256, expected_group_digest),
      )
      _maybe_fail(failpoint, "after_target_swap")
      _validate_group(target, expected_names, expected_file_count, expected_group_digest)

      for directory in (stage / "offline/-42", stage / "offline", stage):
        try:
          directory.rmdir()
        except OSError:
          break

      _atomic_json(marker, _marker_payload(expected_archive_sha256, expected_group_digest, expected_file_count, expected_names))
      try:
        _preserve(transaction, "completed-transaction")
      except OSError:
        # The installed marker and verified target are authoritative. A leftover
        # transaction is finalized by the idempotent path on the next boot.
        pass
      return "installed"
    except Exception as error:
      try:
        if transaction.exists():
          _recover_transaction(target, backup, transaction, stage)
        else:
          _discard(stage)
      except Exception as recovery_error:
        raise MigrationError(f"Migration failed ({error}); recovery also failed ({recovery_error})") from error
      if isinstance(error, MigrationError):
        raise
      raise MigrationError(f"Migration failed and the previous map group was restored: {error}") from error


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--archive", type=Path, default=ARCHIVE_PATH)
  parser.add_argument("--map-root", type=Path, default=DEVICE_MAP_ROOT)
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  if not Path("/AGNOS").is_file() and args.map_root == DEVICE_MAP_ROOT:
    print("Wellington map migration skipped: not running on AGNOS")
    return 0
  try:
    result = install_wellington_map(args.archive, args.map_root)
  except MigrationError as error:
    print(f"Wellington map migration error: {error}", file=sys.stderr)
    return 1
  print(f"Wellington map migration: {result}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
