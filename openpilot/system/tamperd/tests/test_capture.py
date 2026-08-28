import json
from datetime import UTC, datetime

import numpy as np

from openpilot.system.tamperd.capture import CAPTURE_LEASE_NS, TamperCapture, encode_jpeg
from openpilot.system.tamperd.state import TamperEvent
from openpilot.system.tamperd.storage import EventStorage


class FakeParams:
  def __init__(self, values=None):
    self.values = {
      "TamperModeEnabled": True,
      "TamperModeVoltageSafe": True,
      "TamperModeIncludeDriverCamera": False,
    }
    self.values.update(values or {})
    self.writes = []

  def get_bool(self, key):
    return bool(self.values[key])

  def put(self, key, value, block=False):
    self.values[key] = value
    self.writes.append((key, value, block))


EVENT = TamperEvent(123, "impact", 2.5, 4.)
NOW = datetime(2026, 8, 22, 1, 2, 3, tzinfo=UTC)


def test_capture_saves_road_and_wide_and_clears_lease(tmp_path):
  params = FakeParams()
  rgb = np.zeros((8, 8, 3), dtype=np.uint8)

  def snapshots(frames, **kwargs):
    assert frames == ["roadCameraState", "wideRoadCameraState"]
    assert not kwargs["cancelled"]()
    return dict.fromkeys(frames, rgb), {}

  capture = TamperCapture(params, EventStorage(tmp_path), snapshots, lambda: 1_000, lambda: NOW)
  outcome = capture.capture(EVENT)

  assert outcome.capture_state == "captured"
  assert outcome.captured_cameras == ("road", "wide")
  assert params.writes[0] == ("TamperModeCaptureDeadlineMono", 1_000 + CAPTURE_LEASE_NS, True)
  assert params.writes[1] == ("TamperModeCaptureRequestedMono", 1_000, True)
  assert params.writes[-2:] == [
    ("TamperModeCaptureRequestedMono", 0, True),
    ("TamperModeCaptureDeadlineMono", 0, True),
  ]
  event_path = tmp_path / outcome.event_id
  metadata = json.loads((event_path / "event.json").read_text())
  assert metadata["capturedCameras"] == ["road", "wide"]
  assert (event_path / "road.jpg").read_bytes().startswith(b"\xff\xd8")


def test_capture_gate_closed_does_not_request_cameras(tmp_path):
  params = FakeParams({"TamperModeVoltageSafe": False})
  called = False

  def snapshots(*_args, **_kwargs):
    nonlocal called
    called = True

  outcome = TamperCapture(params, EventStorage(tmp_path), snapshots, utc_now=lambda: NOW).capture(EVENT)

  assert outcome.capture_state == "skipped_gate_closed"
  assert not called
  assert params.writes == []


def test_driver_camera_is_opt_in_and_partial_errors_are_recorded(tmp_path):
  params = FakeParams({"TamperModeIncludeDriverCamera": True})
  rgb = np.zeros((4, 4, 3), dtype=np.uint8)

  def snapshots(frames, **_kwargs):
    assert frames[-1] == "driverCameraState"
    return {"roadCameraState": rgb}, {
      "wideRoadCameraState": "frame_timeout",
      "driverCameraState": "frame_timeout",
    }

  outcome = TamperCapture(params, EventStorage(tmp_path), snapshots, utc_now=lambda: NOW).capture(EVENT)

  assert outcome.capture_state == "captured"
  assert outcome.captured_cameras == ("road",)
  assert outcome.capture_errors == {"wide": "frame_timeout", "driver": "frame_timeout"}


def test_capture_exception_clears_lease(tmp_path):
  params = FakeParams()

  def snapshots(*_args, **_kwargs):
    raise RuntimeError("camera unavailable")

  outcome = TamperCapture(params, EventStorage(tmp_path), snapshots, utc_now=lambda: NOW).capture(EVENT)

  assert outcome.capture_state == "capture_failed"
  assert outcome.capture_errors == {"capture": "capture_error:RuntimeError"}
  assert params.values["TamperModeCaptureRequestedMono"] == 0
  assert params.values["TamperModeCaptureDeadlineMono"] == 0


def test_gate_closing_during_capture_discards_images(tmp_path):
  params = FakeParams()
  rgb = np.zeros((4, 4, 3), dtype=np.uint8)

  def snapshots(frames, **_kwargs):
    params.values["TamperModeVoltageSafe"] = False
    return dict.fromkeys(frames, rgb), {}

  outcome = TamperCapture(params, EventStorage(tmp_path), snapshots, utc_now=lambda: NOW).capture(EVENT)

  assert outcome.capture_state == "cancelled_gate_closed"
  assert outcome.capture_errors == {"capture": "gate_closed"}
  assert list(tmp_path.iterdir()) == []


def test_no_images_does_not_consume_storage_slot(tmp_path):
  params = FakeParams()

  def snapshots(_frames, **_kwargs):
    return {}, {"roadCameraState": "frame_timeout", "wideRoadCameraState": "frame_timeout"}

  outcome = TamperCapture(params, EventStorage(tmp_path), snapshots, utc_now=lambda: NOW).capture(EVENT)

  assert outcome.capture_state == "capture_failed"
  assert list(tmp_path.iterdir()) == []


def test_encode_jpeg_rejects_non_rgb_input():
  try:
    encode_jpeg(np.zeros((8, 8), dtype=np.uint8))
  except ValueError:
    pass
  else:
    raise AssertionError("non-RGB input was accepted")
