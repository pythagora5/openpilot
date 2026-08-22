from pathlib import Path

import requests

from openpilot.system.tamperd.capture import CaptureOutcome
from openpilot.system.tamperd.delivery import NtfyPublisher, TamperNotifier, validate_ntfy_url
from openpilot.system.tamperd.state import TamperEvent


class FakeResponse:
  def __init__(self, status_code=200):
    self.status_code = status_code
    self.closed = False

  def close(self):
    self.closed = True


class FakeSession:
  def __init__(self, responses=None, exception=None):
    self.trust_env = True
    self.responses = list(responses or [FakeResponse()])
    self.exception = exception
    self.requests = []
    self.closed = False

  def request(self, method, url, **kwargs):
    self.requests.append((method, url, kwargs))
    if self.exception is not None:
      raise self.exception
    return self.responses.pop(0)

  def close(self):
    self.closed = True


class FakeParams:
  def __init__(self, url):
    self.url = url

  def get(self, key):
    assert key == "TamperModeNtfyUrl"
    return self.url


class FakePublisher:
  def __init__(self, detection_error=None, photo_errors=None, calls=None):
    self.detection_error = detection_error
    self.photo_errors = photo_errors or {}
    self.calls = calls if calls is not None else []
    self.closed = False

  def publish_detection(self):
    self.calls.append("notification")
    return self.detection_error

  def publish_photo(self, camera, image):
    self.calls.append((camera, image))
    return self.photo_errors.get(camera)

  def close(self):
    self.closed = True


def test_validate_ntfy_url_requires_secret_https_topic_path():
  assert validate_ntfy_url("https://ntfy.sh/a-secret-topic/") == "https://ntfy.sh/a-secret-topic"
  for invalid in (
    "", "http://ntfy.sh/topic", "https://ntfy.sh", "https://user:pass@ntfy.sh/topic",
    "https://ntfy.sh/topic?token=secret", "https://ntfy.sh/topic#fragment", "https://ntfy.sh/my topic",
    "https://ntfy.sh/topic\nX-Test: bad", "https://ntfy.sh/topic\x7f",
  ):
    try:
      validate_ntfy_url(invalid)
    except ValueError:
      pass
    else:
      raise AssertionError(f"accepted invalid URL: {invalid!r}")


def test_publisher_uses_bounded_non_redirecting_requests():
  responses = [FakeResponse(), FakeResponse()]
  session = FakeSession(responses)
  publisher = NtfyPublisher("https://ntfy.example/secret-topic", session)

  assert publisher.publish_detection() is None
  assert publisher.publish_photo("road", b"jpeg") is None

  text_method, text_url, text_kwargs = session.requests[0]
  assert (text_method, text_url) == ("POST", "https://ntfy.example/secret-topic")
  assert text_kwargs["allow_redirects"] is False
  assert text_kwargs["verify"] is True
  assert text_kwargs["timeout"] == (3.05, 5.)
  assert text_kwargs["headers"]["Content-Type"] == "text/plain; charset=utf-8"
  assert b"Camera capture has started" in text_kwargs["data"]
  photo_method, _, photo_kwargs = session.requests[1]
  assert photo_method == "PUT"
  assert photo_kwargs["headers"]["X-Filename"] == "tamper-road.jpg"
  assert photo_kwargs["data"] == b"jpeg"
  assert session.trust_env is False
  assert all(response.closed for response in responses)


def test_publisher_returns_coarse_errors_without_url_or_body():
  response = FakeResponse(503)
  publisher = NtfyPublisher("https://ntfy.example/secret-topic", FakeSession([response]))
  assert publisher.publish_detection() == "http_503"
  assert response.closed

  publisher = NtfyPublisher(
    "https://ntfy.example/secret-topic",
    FakeSession(exception=requests.ConnectionError("https://ntfy.example/secret-topic leaked")),
  )
  assert publisher.publish_detection() == "request_failed"


def test_notifier_sends_only_captured_photos(tmp_path):
  event_path = Path(tmp_path) / "event-1"
  event_path.mkdir()
  (event_path / "road.jpg").write_bytes(b"road-jpeg")
  (event_path / "wide.jpg").write_bytes(b"wide-jpeg")
  calls = []
  publisher_urls = []
  publisher = FakePublisher(calls=calls)

  def publisher_factory(url):
    publisher_urls.append(url)
    return publisher

  notifier = TamperNotifier(FakeParams("https://ntfy.example/topic"), publisher_factory)
  event = TamperEvent(1, "impact", 2., 3.)

  delivery = notifier.notify_detection(event)
  notifier.params.url = "https://ntfy.example/different-topic"
  capture = CaptureOutcome("event-1", "captured", ("road", "wide"), {}, str(event_path))
  delivery = notifier.notify_photos(capture, delivery)

  assert calls == ["notification", ("road", b"road-jpeg"), ("wide", b"wide-jpeg")]
  assert publisher_urls == ["https://ntfy.example/topic"]
  assert delivery.as_param(capture.captured_cameras)["deliveryState"] == "sent"


def test_notifier_reports_partial_delivery_without_blocking_other_photos(tmp_path):
  event_path = Path(tmp_path) / "event-1"
  event_path.mkdir()
  (event_path / "road.jpg").write_bytes(b"road-jpeg")
  publisher = FakePublisher(detection_error="request_failed", photo_errors={"road": "http_503"})
  notifier = TamperNotifier(FakeParams("https://ntfy.example/topic"), lambda _url: publisher)

  delivery = notifier.notify_detection(TamperEvent(1, "impact", 2., 3.))
  capture = CaptureOutcome("event-1", "captured", ("road", "wide"), {}, str(event_path))
  delivery = notifier.notify_photos(capture, delivery)
  result = delivery.as_param(capture.captured_cameras)

  assert result["deliveryState"] == "failed"
  assert result["deliveryErrors"] == {
    "notification": "request_failed",
    "road": "http_503",
    "wide": "file_missing",
  }


def test_notifier_handles_missing_and_invalid_configuration():
  event = TamperEvent(1, "impact", 2., 3.)
  missing = TamperNotifier(FakeParams(""), lambda _url: FakePublisher()).notify_detection(event)
  invalid = TamperNotifier(FakeParams("http://ntfy.example/topic"), lambda url: NtfyPublisher(url)).notify_detection(event)

  assert missing.as_param()["deliveryState"] == "not_configured"
  assert missing.errors == {"configuration": "not_configured"}
  assert invalid.errors == {"configuration": "invalid_url"}


def test_notifier_closes_old_publisher_when_url_changes():
  params = FakeParams("https://ntfy.example/topic-one")
  publishers = []

  def factory(_url):
    publisher = FakePublisher()
    publishers.append(publisher)
    return publisher

  notifier = TamperNotifier(params, factory)
  notifier.notify_detection(TamperEvent(1, "impact", 2., 3.))
  params.url = "https://ntfy.example/topic-two"
  notifier.notify_detection(TamperEvent(2, "impact", 2., 3.))

  assert len(publishers) == 2
  assert publishers[0].closed
  assert not publishers[1].closed
  notifier.close()
  assert publishers[1].closed


def test_no_storage_path_skips_photo_publication():
  publisher = FakePublisher()
  notifier = TamperNotifier(FakeParams("https://ntfy.example/topic"), lambda _url: publisher)
  delivery = notifier.notify_detection(TamperEvent(1, "impact", 2., 3.))

  result = notifier.notify_photos(CaptureOutcome("event-1", "capture_failed"), delivery)

  assert result == delivery
  assert publisher.calls == ["notification"]


def test_transient_publisher_creation_failure_is_retried():
  attempts = 0
  publisher = FakePublisher()

  def factory(_url):
    nonlocal attempts
    attempts += 1
    if attempts == 1:
      raise OSError("temporary resource failure")
    return publisher

  notifier = TamperNotifier(FakeParams("https://ntfy.example/topic"), factory)
  first = notifier.notify_detection(TamperEvent(1, "impact", 2., 3.))
  failed_photos = notifier.notify_photos(CaptureOutcome("event-1", "captured", ("road",), {}, "/tmp/event-1"), first)
  second = notifier.notify_detection(TamperEvent(2, "impact", 2., 3.))

  assert first.as_param()["deliveryState"] == "failed"
  assert first.errors == {"configuration": "publisher_error"}
  assert failed_photos.errors == {"configuration": "publisher_error"}
  assert second.notification_sent
  assert attempts == 2
