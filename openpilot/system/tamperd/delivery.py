from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from openpilot.common.params import Params
from openpilot.system.tamperd.capture import CaptureOutcome
from openpilot.system.tamperd.config import validate_ntfy_url
from openpilot.system.tamperd.state import TamperEvent


TEXT_TIMEOUT = (3.05, 5.)
ATTACHMENT_TIMEOUT = (3.05, 15.)
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
CAMERA_LABELS = {
  "road": "Road camera",
  "wide": "Wide road camera",
  "driver": "Driver camera",
}


class NtfyPublisher:
  def __init__(self, url: str, session: requests.Session | None = None):
    self.url = validate_ntfy_url(url)
    self.session = session or requests.Session()
    self.session.trust_env = False

  def close(self) -> None:
    self.session.close()

  def _request(self, method: str, data: bytes, headers: dict[str, str], timeout: tuple[float, float]) -> str | None:
    response = None
    try:
      response = self.session.request(
        method, self.url, data=data, headers=headers, timeout=timeout,
        allow_redirects=False, verify=True,
      )
      if 200 <= response.status_code < 300:
        return None
      return f"http_{response.status_code}"
    except requests.RequestException:
      return "request_failed"
    finally:
      if response is not None:
        response.close()

  def publish_detection(self) -> str | None:
    return self._request(
      "POST",
      b"Movement was detected while your vehicle was parked. Camera capture has started.",
      {
        "Content-Type": "text/plain; charset=utf-8",
        "X-Title": "Vehicle tampering detected",
        "X-Priority": "high",
        "X-Tags": "warning,car",
      },
      TEXT_TIMEOUT,
    )

  def publish_photo(self, camera: str, image: bytes) -> str | None:
    label = CAMERA_LABELS[camera]
    return self._request(
      "PUT",
      image,
      {
        "Content-Type": "image/jpeg",
        "X-Filename": f"tamper-{camera}.jpg",
        "X-Message": f"{label} photo from the tamper event.",
        "X-Title": "Vehicle tampering photo",
        "X-Priority": "high",
        "X-Tags": "camera,car",
      },
      ATTACHMENT_TIMEOUT,
    )


@dataclass(frozen=True)
class DeliveryOutcome:
  configured: bool
  notification_sent: bool = False
  photos_sent: tuple[str, ...] = ()
  errors: dict[str, str] | None = None

  def as_param(self, expected_photos: tuple[str, ...] | None = None) -> dict:
    errors = self.errors or {}
    if not self.configured:
      state = "not_configured"
    elif self.notification_sent and expected_photos is not None and set(expected_photos) <= set(self.photos_sent):
      state = "sent"
    elif self.notification_sent or self.photos_sent:
      state = "partial"
    else:
      state = "failed"
    return {
      "deliveryState": state,
      "notificationSent": self.notification_sent,
      "photosSent": list(self.photos_sent),
      "deliveryErrors": errors,
    }


class TamperNotifier:
  def __init__(self, params: Params, publisher_factory: Callable[[str], NtfyPublisher] = NtfyPublisher):
    self.params = params
    self.publisher_factory = publisher_factory
    self._url: str | None = None
    self._publisher: NtfyPublisher | None = None

  def _get_publisher(self) -> tuple[NtfyPublisher | None, str | None]:
    raw_url = self.params.get("TamperModeNtfyUrl") or ""
    if not isinstance(raw_url, str) or not raw_url.strip():
      return None, "not_configured"
    if raw_url != self._url or self._publisher is None:
      if self._publisher is not None:
        try:
          self._publisher.close()
        except Exception:
          pass
      self._publisher = None
      try:
        self._publisher = self.publisher_factory(raw_url)
      except ValueError:
        return None, "invalid_url"
      except Exception:
        return None, "publisher_error"
      self._url = raw_url
    return self._publisher, None

  def close(self) -> None:
    if self._publisher is not None:
      try:
        self._publisher.close()
      except Exception:
        pass
      self._publisher = None

  def notify_detection(self, _event: TamperEvent) -> DeliveryOutcome:
    publisher, configuration_error = self._get_publisher()
    if publisher is None:
      configured = configuration_error == "publisher_error"
      return DeliveryOutcome(configured, errors={"configuration": configuration_error or "invalid_url"})
    try:
      error = publisher.publish_detection()
    except Exception:
      error = "internal_error"
    return DeliveryOutcome(True, notification_sent=error is None,
                           errors={} if error is None else {"notification": error})

  def notify_photos(self, capture: CaptureOutcome, outcome: DeliveryOutcome) -> DeliveryOutcome:
    if not outcome.configured or not capture.storage_path:
      return outcome
    publisher = self._publisher
    if publisher is None:
      errors = dict(outcome.errors or {})
      errors.setdefault("configuration", "publisher_unavailable")
      return DeliveryOutcome(outcome.configured, outcome.notification_sent, outcome.photos_sent, errors)

    errors = dict(outcome.errors or {})
    sent = list(outcome.photos_sent)
    event_path = Path(capture.storage_path)
    for camera in capture.captured_cameras:
      if camera not in CAMERA_LABELS:
        errors[camera] = "invalid_camera"
        continue
      try:
        image_path = event_path / f"{camera}.jpg"
        if not image_path.is_file():
          errors[camera] = "file_missing"
          continue
        if image_path.stat().st_size > MAX_ATTACHMENT_BYTES:
          errors[camera] = "file_too_large"
          continue
        image = image_path.read_bytes()
      except OSError:
        errors[camera] = "file_unavailable"
        continue
      try:
        error = publisher.publish_photo(camera, image)
      except Exception:
        error = "internal_error"
      if error is None:
        sent.append(camera)
      else:
        errors[camera] = error
    return DeliveryOutcome(True, outcome.notification_sent, tuple(sorted(set(sent))), errors)
