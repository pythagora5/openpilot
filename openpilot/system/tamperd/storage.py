import fcntl
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from openpilot.common.hardware.hw import Paths


MAX_EVENTS = 20
MAX_STORAGE_BYTES = 250 * 1024 * 1024
INCOMPLETE_EVENT_MAX_AGE_S = 5 * 60
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class EventStorage:
  def __init__(self, root: str | Path | None = None, max_events: int = MAX_EVENTS,
               max_bytes: int = MAX_STORAGE_BYTES):
    if max_events < 1 or max_bytes < 1:
      raise ValueError("tamper storage limits must be positive")
    self.root = Path(root or Paths.tamper_root())
    self.max_events = max_events
    self.max_bytes = max_bytes
    self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(self.root, 0o700)
    self.lock_path = self.root.parent / f".{self.root.name}.lock"
    with self._locked():
      self._remove_incomplete_events()
      self._prune_locked()

  @contextmanager
  def _locked(self):
    fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
      fcntl.flock(fd, fcntl.LOCK_EX)
      yield
    finally:
      fcntl.flock(fd, fcntl.LOCK_UN)
      os.close(fd)

  @staticmethod
  def _validate_event_id(event_id: str) -> None:
    if not _EVENT_ID_RE.fullmatch(event_id):
      raise ValueError("invalid tamper event id")

  @staticmethod
  def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())

  def _event_directories(self) -> list[Path]:
    return [item for item in self.root.iterdir() if item.is_dir() and not item.name.startswith(".")]

  def _storage_directories(self) -> list[Path]:
    return [item for item in self.root.iterdir() if item.is_dir()]

  def _remove_incomplete_events(self) -> None:
    cutoff = datetime.now(UTC).timestamp() - INCOMPLETE_EVENT_MAX_AGE_S
    for item in self.root.iterdir():
      if item.name.startswith(".") and item.is_dir() and item.stat().st_mtime < cutoff:
        shutil.rmtree(item)

  @staticmethod
  def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
      os.fsync(fd)
    finally:
      os.close(fd)

  def _prune_locked(self, preserve: set[str] | None = None, reserve_events: int = 0,
                    reserve_bytes: int = 0) -> bool:
    preserved = preserve or set()
    events = sorted(self._event_directories(), key=lambda path: (path.stat().st_mtime_ns, path.name))
    storage_directories = self._storage_directories()
    protected = [path for path in events if path.name in preserved]
    incomplete = [path for path in storage_directories if path.name.startswith(".")]
    fixed_bytes = sum(self._directory_size(path) for path in protected + incomplete)
    if len(protected) + reserve_events > self.max_events or fixed_bytes + reserve_bytes > self.max_bytes:
      return False

    total_bytes = sum(self._directory_size(path) for path in storage_directories)
    while len(events) + reserve_events > self.max_events or total_bytes + reserve_bytes > self.max_bytes:
      victim = next((path for path in events if path.name not in preserved), None)
      if victim is None:
        break
      victim_size = self._directory_size(victim)
      shutil.rmtree(victim)
      events.remove(victim)
      total_bytes -= victim_size
    return len(events) + reserve_events <= self.max_events and total_bytes + reserve_bytes <= self.max_bytes

  def prune(self, preserve: set[str] | None = None) -> None:
    with self._locked():
      self._remove_incomplete_events()
      self._prune_locked(preserve)

  @staticmethod
  def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
      file.write(data)
      file.flush()
      os.fsync(file.fileno())

  def save_event(self, event_id: str, metadata: Mapping, images: Mapping[str, bytes]) -> Path:
    self._validate_event_id(event_id)
    unknown_cameras = set(images) - {"road", "wide", "driver"}
    if unknown_cameras:
      raise ValueError(f"unknown tamper camera(s): {sorted(unknown_cameras)}")

    metadata_bytes = json.dumps(metadata, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_bytes = len(metadata_bytes) + sum(len(image) for image in images.values())
    if payload_bytes > self.max_bytes:
      raise ValueError("tamper event exceeds storage quota")

    with self._locked():
      self._remove_incomplete_events()
      target = self.root / event_id
      if target.exists():
        raise FileExistsError(f"tamper event already exists: {event_id}")
      if not self._prune_locked(reserve_events=1, reserve_bytes=payload_bytes):
        raise OSError("tamper storage quota unavailable")

      temporary = Path(tempfile.mkdtemp(prefix=f".{event_id}.", dir=self.root))
      os.chmod(temporary, 0o700)
      try:
        self._write_private(temporary / "event.json", metadata_bytes)
        for camera, image in images.items():
          self._write_private(temporary / f"{camera}.jpg", image)
        self._fsync_directory(temporary)
        os.replace(temporary, target)
        self._fsync_directory(self.root)
        return target
      except Exception:
        if temporary.exists():
          shutil.rmtree(temporary)
        raise
