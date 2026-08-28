import io
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from PIL import Image

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.camerad.snapshot import get_snapshots_bounded
from openpilot.system.tamperd.state import TamperEvent
from openpilot.system.tamperd.storage import EventStorage
from openpilot.system.tamperd.timebase import boottime_ns


CAPTURE_LEASE_NS = int(30e9)
CAPTURE_TIMEOUT_S = 22.
CAMERA_NAMES = {
  "roadCameraState": "road",
  "wideRoadCameraState": "wide",
  "driverCameraState": "driver",
}


@dataclass(frozen=True)
class CaptureOutcome:
  event_id: str
  capture_state: str
  captured_cameras: tuple[str, ...] = ()
  capture_errors: dict[str, str] | None = None
  storage_path: str | None = None

  def as_param(self) -> dict:
    return {
      "eventId": self.event_id,
      "captureState": self.capture_state,
      "capturedCameras": list(self.captured_cameras),
      "captureErrors": self.capture_errors or {},
      "storagePath": self.storage_path,
    }


def encode_jpeg(image: np.ndarray, quality: int = 85) -> bytes:
  if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
    raise ValueError("tamper snapshot must be an RGB uint8 image")
  output = io.BytesIO()
  Image.fromarray(image, mode="RGB").save(output, format="JPEG", quality=quality, optimize=True)
  return output.getvalue()


class TamperCapture:
  def __init__(self, params: Params, storage: EventStorage | None = None,
               snapshot_fn: Callable = get_snapshots_bounded,
               clock_ns: Callable[[], int] = boottime_ns,
               utc_now: Callable[[], datetime] | None = None):
    self.params = params
    self.storage = storage or EventStorage()
    self.snapshot_fn = snapshot_fn
    self.clock_ns = clock_ns
    self.utc_now = utc_now or (lambda: datetime.now(UTC))

  def _capture_allowed(self) -> bool:
    return self.params.get_bool("TamperModeEnabled") and self.params.get_bool("TamperModeVoltageSafe")

  def capture(self, event: TamperEvent) -> CaptureOutcome:
    event_id = f"{self.utc_now().strftime('%Y%m%dT%H%M%S%fZ')}-{secrets.token_hex(3)}"
    if not self._capture_allowed():
      return CaptureOutcome(event_id, "skipped_gate_closed")

    requested_at_ns = self.clock_ns()
    deadline_ns = requested_at_ns + CAPTURE_LEASE_NS
    errors: dict[str, str] = {}
    images: dict[str, bytes] = {}
    lease_requested = False
    try:
      self.params.put("TamperModeCaptureDeadlineMono", deadline_ns, block=True)
      lease_requested = True
      self.params.put("TamperModeCaptureRequestedMono", requested_at_ns, block=True)
      self.params.put("TamperModeStatus", {"state": "capturing", "captureDeadlineMono": deadline_ns}, block=False)

      frames = ["roadCameraState", "wideRoadCameraState"]
      if self.params.get_bool("TamperModeIncludeDriverCamera"):
        frames.append("driverCameraState")

      snapshots, snapshot_errors = self.snapshot_fn(
        frames, timeout_s=CAPTURE_TIMEOUT_S, cancelled=lambda: not self._capture_allowed(),
      )
      errors.update({CAMERA_NAMES[name]: error for name, error in snapshot_errors.items()})
      if not self._capture_allowed():
        errors["capture"] = "gate_closed"
        return CaptureOutcome(event_id, "cancelled_gate_closed", capture_errors=errors)

      for frame, image in snapshots.items():
        camera = CAMERA_NAMES[frame]
        try:
          images[camera] = encode_jpeg(image)
        except (OSError, ValueError) as exc:
          errors[camera] = f"jpeg_error:{type(exc).__name__}"

      if not images:
        return CaptureOutcome(event_id, "capture_failed", capture_errors=errors)

      metadata = {
        "eventId": event_id,
        "detectedAtMono": event.detected_at_ns,
        "capturedAtUtc": self.utc_now().isoformat(),
        "reason": event.reason,
        "peakMotion": event.peak_motion,
        "orientationChangeDeg": event.orientation_change_deg,
        "capturedCameras": sorted(images),
        "captureErrors": errors,
      }
      path = self.storage.save_event(event_id, metadata, images)
      return CaptureOutcome(event_id, "captured", tuple(sorted(images)), errors, str(path))
    except Exception as exc:
      cloudlog.exception("tamper camera capture failed")
      errors["capture"] = f"capture_error:{type(exc).__name__}"
      return CaptureOutcome(event_id, "capture_failed", capture_errors=errors)
    finally:
      if lease_requested:
        try:
          self.params.put("TamperModeCaptureRequestedMono", 0, block=True)
        finally:
          self.params.put("TamperModeCaptureDeadlineMono", 0, block=True)
