from openpilot.system.tamperd import tamperd


class RecordingParams:
  def __init__(self):
    self.writes = []

  def put(self, key, value, block=False):
    self.writes.append((key, value, block))


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
