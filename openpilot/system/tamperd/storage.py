import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

from openpilot.common.hardware.hw import Paths


MAX_EVENTS = 20
MAX_STORAGE_BYTES = 250 * 1024 * 1024
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
    self._remove_incomplete_events()
    self.prune()

  @staticmethod
  def _validate_event_id(event_id: str) -> None:
    if not _EVENT_ID_RE.fullmatch(event_id):
      raise ValueError("invalid tamper event id")

  @staticmethod
  def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())

  def _event_directories(self) -> list[Path]:
    return [item for item in self.root.iterdir() if item.is_dir() and not item.name.startswith(".")]

  def _remove_incomplete_events(self) -> None:
    for item in self.root.iterdir():
      if item.name.startswith(".") and item.is_dir():
        shutil.rmtree(item)

  def prune(self, preserve: set[str] | None = None) -> None:
    preserved = preserve or set()
    events = sorted(self._event_directories(), key=lambda path: (path.stat().st_mtime_ns, path.name))
    total_bytes = sum(self._directory_size(path) for path in events)
    while len(events) > self.max_events or total_bytes > self.max_bytes:
      victim = next((path for path in events if path.name not in preserved), None)
      if victim is None:
        break
      victim_size = self._directory_size(victim)
      shutil.rmtree(victim)
      events.remove(victim)
      total_bytes -= victim_size

  @staticmethod
  def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
      file.write(data)
      file.flush()
      os.fsync(file.fileno())

  def save_event(self, event_id: str, metadata: Mapping, images: Mapping[str, bytes]) -> Path:
    self._validate_event_id(event_id)
    target = self.root / event_id
    if target.exists():
      raise FileExistsError(f"tamper event already exists: {event_id}")

    metadata_bytes = json.dumps(metadata, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_bytes = len(metadata_bytes) + sum(len(image) for image in images.values())
    if payload_bytes > self.max_bytes:
      raise ValueError("tamper event exceeds storage quota")

    temporary = Path(tempfile.mkdtemp(prefix=f".{event_id}.", dir=self.root))
    os.chmod(temporary, 0o700)
    try:
      self._write_private(temporary / "event.json", metadata_bytes)
      for camera, image in images.items():
        if camera not in ("road", "wide", "driver"):
          raise ValueError(f"unknown tamper camera: {camera}")
        self._write_private(temporary / f"{camera}.jpg", image)
      os.replace(temporary, target)
      self.prune(preserve={event_id})
      return target
    except Exception:
      if temporary.exists():
        shutil.rmtree(temporary)
      raise
