from openpilot.system.tamperd import tamperd


class RecordingParams:
  def __init__(self):
    self.writes = []

  def put(self, key, value, block=False):
    self.writes.append((key, value, block))


class FakeCapture:
  def __init__(self, calls):
    self.calls = calls

  def capture(self, _event):
    self.calls.append("capture")
    return tamperd.CaptureOutcome("event-1", "captured", ("road", "wide"), {}, "/tmp/event-1")


class FakeNotifier:
  def __init__(self, calls):
    self.calls = calls

  def notify_detection(self, _event):
    self.calls.append("notification")
    return tamperd.DeliveryOutcome(True, notification_sent=True)

  def notify_photos(self, _capture, outcome):
    self.calls.append("photos")
    return tamperd.DeliveryOutcome(True, outcome.notification_sent, ("road", "wide"), outcome.errors)

  def close(self):
    pass


class RaisingNotifier(FakeNotifier):
  def notify_detection(self, _event):
    self.calls.append("notification_failed")
    raise OSError("network setup failed")


def test_sensitivity_falls_back_to_medium():
  assert tamperd.normalize_sensitivity(None) == 1
  assert tamperd.normalize_sensitivity(-1) == 1
  assert tamperd.normalize_sensitivity(3) == 1
  assert tamperd.normalize_sensitivity("invalid") == 1
  assert tamperd.normalize_sensitivity(0) == 0
  assert tamperd.normalize_sensitivity(2) == 2


def test_status_writes_are_nonblocking_and_deduplicated():
  params = RecordingParams()
  status = {"state": "armed"}

  previous = tamperd.publish_status(params, status, None)
  previous = tamperd.publish_status(params, status, previous)

  assert previous == status
  assert params.writes == [("TamperModeStatus", status, False)]


def test_event_timestamp_is_already_boottime():
  event = tamperd.TamperEvent(125, "impact", 3.5, 1.2)
  event_data = tamperd.event_to_param(event)
  assert event_data["detectedAtMono"] == 125
  assert event_data["reason"] == "impact"
  assert event_data["deliveryState"] == "not_started"


def test_record_event_merges_capture_outcome():
  params = RecordingParams()
  event = tamperd.TamperEvent(125, "impact", 3.5, 1.2)

  tamperd.record_event(params, event, {
    "eventId": "event-1",
    "captureState": "captured",
    "capturedCameras": ["road", "wide"],
  })

  key, value, blocking = params.writes[0]
  assert key == "TamperModeLastEvent"
  assert value["reason"] == "impact"
  assert value["eventId"] == "event-1"
  assert value["capturedCameras"] == ["road", "wide"]
  assert blocking


def test_handle_event_attempts_notification_before_capture_then_photos():
  params = RecordingParams()
  calls = []
  event = tamperd.TamperEvent(125, "impact", 3.5, 1.2)

  alerts = []
  capture, delivery = tamperd.handle_tamper_event(params, FakeCapture(calls), FakeNotifier(calls), event, alerts.append)

  assert set(calls[:2]) == {"notification", "capture"}
  assert calls[-1] == "photos"
  assert capture.event_id == "event-1"
  assert delivery.photos_sent == ("road", "wide")
  event_writes = [value for key, value, _blocking in params.writes if key == "TamperModeLastEvent"]
  assert event_writes[0]["deliveryState"] == "partial"
  assert event_writes[0]["eventId"] == "event-1"
  assert event_writes[0]["storagePath"] == "/tmp/event-1"
  assert event_writes[-1]["deliveryState"] == "sent"
  assert event_writes[-1]["captureState"] == "captured"
  assert alerts == [
    "Tampering detected. Photos captured; notification delivery in progress.",
    "Tampering detected, notification and photos sent.",
  ]


def test_notification_exception_cannot_prevent_capture():
  params = RecordingParams()
  calls = []
  event = tamperd.TamperEvent(125, "impact", 3.5, 1.2)

  capture, delivery = tamperd.handle_tamper_event(params, FakeCapture(calls), RaisingNotifier(calls), event, lambda _message: None)

  assert "capture" in calls
  assert capture.capture_state == "captured"
  assert delivery.errors == {"notification": "internal_error"}


def test_tamper_alert_messages_do_not_claim_photos_were_sent_on_failure():
  captured = tamperd.CaptureOutcome("event-1", "captured", ("road", "wide"), {}, "/tmp/event-1")
  complete = tamperd.DeliveryOutcome(True, True, ("road", "wide"))
  partial = tamperd.DeliveryOutcome(True, True, ("road",), {"wide": "http_503"})
  not_configured = tamperd.DeliveryOutcome(False, errors={"configuration": "not_configured"})
  incomplete_capture = tamperd.CaptureOutcome(
    "event-1", "captured", ("road",), {"wide": "frame_timeout"}, "/tmp/event-1",
  )
  silently_incomplete = tamperd.CaptureOutcome("event-1", "captured", ("road",), {}, "/tmp/event-1")

  assert tamperd.format_tamper_alert(captured, complete) == "Tampering detected, notification and photos sent."
  assert "one or more photos could not be delivered" in tamperd.format_tamper_alert(captured, partial)
  assert "saved locally" in tamperd.format_tamper_alert(captured, not_configured)
  assert "camera capture was incomplete" in tamperd.format_tamper_alert(incomplete_capture, complete)
  assert "camera capture was incomplete" in tamperd.format_tamper_alert(silently_incomplete, complete)


def test_empty_tamper_alert_uses_visible_fallback(monkeypatch):
  calls = []
  monkeypatch.setattr(tamperd, "set_offroad_alert", lambda *args, **kwargs: calls.append((args, kwargs)))

  tamperd.safe_set_tamper_alert("  ")

  assert calls[0][1]["extra_text"] == "Tampering detected."


def test_cooldown_status_is_written_once_across_jittering_samples(monkeypatch):
  params = RecordingParams()
  machine = tamperd.TamperStateMachine(cooldown_s=120.)
  sensor_timestamp_ns = 0
  clock_jitter_ns = 0

  def jittering_boottime(timestamp):
    nonlocal clock_jitter_ns
    clock_jitter_ns += 100
    return timestamp + clock_jitter_ns

  monkeypatch.setattr(tamperd, "monotonic_to_boottime_ns", jittering_boottime)
  for _ in range(502):
    machine.process_sample(sensor_timestamp_ns, (0., 0., 9.81))
    sensor_timestamp_ns += int(0.01e9)
  previous_status = {"state": "armed"}

  previous_status, event = tamperd.process_sensor_sample(
    params, machine, sensor_timestamp_ns, (3.5, 0., 9.81), previous_status,
  )
  assert event is not None

  for _ in range(10):
    sensor_timestamp_ns += int(0.01e9)
    previous_status, event = tamperd.process_sensor_sample(
      params, machine, sensor_timestamp_ns, (0., 0., 9.81), previous_status,
    )
    assert event is None

  status_writes = [write for write in params.writes if write[0] == "TamperModeStatus"]
  assert len(status_writes) == 1
