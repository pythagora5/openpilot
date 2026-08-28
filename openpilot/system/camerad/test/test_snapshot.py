import numpy as np

from openpilot.system.camerad import snapshot


class FakeClock:
  def __init__(self):
    self.now = 0.

  def monotonic(self):
    return self.now

  def advance_ms(self, milliseconds):
    self.now += milliseconds / 1000.

  def sleep(self, seconds):
    self.now += seconds


class CameraState:
  def __init__(self, frame_id):
    self.frameId = frame_id


class FakeSubMaster:
  def __init__(self, sockets, clock, frame_id):
    self.states = {socket: CameraState(frame_id) for socket in sockets}
    self.clock = clock

  def __getitem__(self, socket):
    return self.states[socket]

  def update(self, timeout_ms):
    self.clock.advance_ms(timeout_ms)


class FakeClient:
  def __init__(self, connected, buffer=None):
    self.connected = connected
    self.buffer = buffer

  def connect(self, _blocking):
    return self.connected

  def recv(self, timeout_ms):
    return self.buffer


def test_bounded_snapshot_warmup_timeout(monkeypatch):
  clock = FakeClock()
  monkeypatch.setattr(snapshot.time, "monotonic", clock.monotonic)
  monkeypatch.setattr(snapshot.messaging, "SubMaster", lambda sockets: FakeSubMaster(sockets, clock, 0))
  monkeypatch.setattr(snapshot, "VisionIpcClient", lambda *_args: FakeClient(True))

  images, errors = snapshot.get_snapshots_bounded(["roadCameraState", "wideRoadCameraState"], timeout_s=.25)

  assert images == {}
  assert errors == {"roadCameraState": "warmup_timeout", "wideRoadCameraState": "warmup_timeout"}
  assert .18 <= clock.now < .288


def test_bounded_snapshot_keeps_camera_that_warms_up(monkeypatch):
  clock = FakeClock()
  clients = {
    snapshot.VisionStreamType.VISION_STREAM_ROAD: FakeClient(True, "road-buffer"),
    snapshot.VisionStreamType.VISION_STREAM_WIDE_ROAD: FakeClient(True, "wide-buffer"),
  }
  sm = FakeSubMaster(["roadCameraState", "wideRoadCameraState"], clock, 0)
  sm.states["roadCameraState"].frameId = 1000
  monkeypatch.setattr(snapshot.time, "monotonic", clock.monotonic)
  monkeypatch.setattr(snapshot.messaging, "SubMaster", lambda _sockets: sm)
  monkeypatch.setattr(snapshot, "VisionIpcClient", lambda _name, stream, _rgb: clients[stream])
  monkeypatch.setattr(snapshot, "extract_image", lambda buffer: np.array([buffer], dtype=object))

  images, errors = snapshot.get_snapshots_bounded(
    ["roadCameraState", "wideRoadCameraState"], timeout_s=3., warmup_s=.25,
  )

  assert images["roadCameraState"].tolist() == ["road-buffer"]
  assert errors == {"wideRoadCameraState": "warmup_timeout"}


def test_dead_camera_cannot_consume_full_tamper_capture_budget(monkeypatch):
  clock = FakeClock()
  clients = {
    snapshot.VisionStreamType.VISION_STREAM_ROAD: FakeClient(True, "road-buffer"),
    snapshot.VisionStreamType.VISION_STREAM_WIDE_ROAD: FakeClient(True, "wide-buffer"),
  }
  sm = FakeSubMaster(["roadCameraState", "wideRoadCameraState"], clock, 0)
  sm.states["roadCameraState"].frameId = 1000
  monkeypatch.setattr(snapshot.time, "monotonic", clock.monotonic)
  monkeypatch.setattr(snapshot.messaging, "SubMaster", lambda _sockets: sm)
  monkeypatch.setattr(snapshot, "VisionIpcClient", lambda _name, stream, _rgb: clients[stream])
  monkeypatch.setattr(snapshot, "extract_image", lambda buffer: np.array([buffer], dtype=object))

  images, errors = snapshot.get_snapshots_bounded(
    ["roadCameraState", "wideRoadCameraState"], timeout_s=22., warmup_s=4.,
  )

  assert images["roadCameraState"].tolist() == ["road-buffer"]
  assert errors == {"wideRoadCameraState": "warmup_timeout"}
  assert 9.9 <= clock.now < 10.1


def test_bounded_snapshot_returns_partial_results(monkeypatch):
  clock = FakeClock()
  clients = {
    snapshot.VisionStreamType.VISION_STREAM_ROAD: FakeClient(True, "road-buffer"),
    snapshot.VisionStreamType.VISION_STREAM_WIDE_ROAD: FakeClient(False),
  }
  monkeypatch.setattr(snapshot.time, "monotonic", clock.monotonic)
  monkeypatch.setattr(snapshot.time, "sleep", clock.sleep)
  monkeypatch.setattr(snapshot.messaging, "SubMaster", lambda sockets: FakeSubMaster(sockets, clock, 1000))
  monkeypatch.setattr(snapshot, "VisionIpcClient", lambda _name, stream, _rgb: clients[stream])
  monkeypatch.setattr(snapshot, "extract_image", lambda buffer: np.array([buffer], dtype=object))

  images, errors = snapshot.get_snapshots_bounded(
    ["roadCameraState", "wideRoadCameraState"], timeout_s=3., warmup_s=0.,
  )

  assert images["roadCameraState"].tolist() == ["road-buffer"]
  assert errors == {"wideRoadCameraState": "connect_timeout"}
  assert 2. <= clock.now <= 2.05


def test_bounded_snapshot_rejects_unknown_camera():
  try:
    snapshot.get_snapshots_bounded(["notACamera"])
  except ValueError as exc:
    assert "notACamera" in str(exc)
  else:
    raise AssertionError("unknown camera was accepted")


def test_legacy_wrapper_retries_until_all_requested_cameras_arrive(monkeypatch):
  road = np.zeros((2, 2, 3), dtype=np.uint8)
  driver = np.ones((2, 2, 3), dtype=np.uint8)
  attempts = iter([
    ({"roadCameraState": road}, {"driverCameraState": "frame_timeout"}),
    ({"roadCameraState": road, "driverCameraState": driver}, {}),
  ])
  monkeypatch.setattr(snapshot, "get_snapshots_bounded", lambda _sockets, **_kwargs: next(attempts))
  sleep_calls = []
  monkeypatch.setattr(snapshot.time, "sleep", sleep_calls.append)

  captured_road, captured_driver = snapshot.get_snapshots()

  assert captured_road is road
  assert captured_driver is driver
  assert sleep_calls == [.25]


def test_legacy_wrapper_has_an_overall_deadline(monkeypatch):
  clock = FakeClock()
  monkeypatch.setattr(snapshot.time, "monotonic", clock.monotonic)
  monkeypatch.setattr(snapshot.time, "sleep", clock.sleep)
  monkeypatch.setattr(snapshot, "get_snapshots_bounded", lambda _sockets, **_kwargs: ({}, {"roadCameraState": "frame_timeout"}))

  try:
    snapshot.get_snapshots(frame="roadCameraState", front_frame=None, timeout_s=.5)
  except TimeoutError as exc:
    assert "frame_timeout" in str(exc)
  else:
    raise AssertionError("legacy snapshot wrapper exceeded its deadline")

  assert clock.now == .5
