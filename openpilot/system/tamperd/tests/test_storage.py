import json
import os

import pytest

from openpilot.system.tamperd.storage import EventStorage


def test_save_event_is_atomic_and_private(tmp_path):
  storage = EventStorage(tmp_path)
  event_path = storage.save_event("event-1", {"reason": "impact"}, {"road": b"jpeg"})

  assert json.loads((event_path / "event.json").read_text()) == {"reason": "impact"}
  assert (event_path / "road.jpg").read_bytes() == b"jpeg"
  assert not list(tmp_path.glob(".*"))
  assert os.stat(tmp_path).st_mode & 0o777 == 0o700
  assert os.stat(event_path / "road.jpg").st_mode & 0o777 == 0o600


def test_invalid_payload_leaves_no_partial_event(tmp_path):
  storage = EventStorage(tmp_path)

  with pytest.raises(ValueError):
    storage.save_event("event-1", {}, {"unknown": b"jpeg"})

  assert list(tmp_path.iterdir()) == []


def test_storage_prunes_oldest_event(tmp_path):
  storage = EventStorage(tmp_path, max_events=2, max_bytes=1000)
  storage.save_event("event-1", {}, {})
  storage.save_event("event-2", {}, {})
  storage.save_event("event-3", {}, {})

  assert {path.name for path in tmp_path.iterdir()} == {"event-2", "event-3"}


def test_oversized_event_is_rejected_before_writing(tmp_path):
  storage = EventStorage(tmp_path, max_bytes=4)

  with pytest.raises(ValueError, match="quota"):
    storage.save_event("event-1", {}, {"road": b"1234"})

  assert list(tmp_path.iterdir()) == []


def test_incomplete_event_is_removed_at_startup(tmp_path):
  incomplete = tmp_path / ".event-1.partial"
  incomplete.mkdir()
  (incomplete / "road.jpg").write_bytes(b"partial")

  EventStorage(tmp_path)

  assert not incomplete.exists()
