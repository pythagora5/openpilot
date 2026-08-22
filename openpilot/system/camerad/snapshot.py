#!/usr/bin/env python3

import time
from collections.abc import Callable, Iterable

import numpy as np

import openpilot.cereal.messaging as messaging
from msgq.visionipc import VisionIpcClient, VisionStreamType
from openpilot.common.realtime import DT_MDL


VISION_STREAMS = {
  "roadCameraState": VisionStreamType.VISION_STREAM_ROAD,
  "driverCameraState": VisionStreamType.VISION_STREAM_DRIVER,
  "wideRoadCameraState": VisionStreamType.VISION_STREAM_WIDE_ROAD,
}

SNAPSHOT_CONNECT_TIMEOUT_S = 2.
SNAPSHOT_CAPTURE_RESERVE_S = 3.
SNAPSHOT_STARTUP_GRACE_S = 6.
SNAPSHOT_POLL_MS = 100


def yuv_to_rgb(y, u, v):
  ul = np.repeat(np.repeat(u, 2).reshape(u.shape[0], y.shape[1]), 2, axis=0).reshape(y.shape)
  vl = np.repeat(np.repeat(v, 2).reshape(v.shape[0], y.shape[1]), 2, axis=0).reshape(y.shape)

  yuv = np.dstack((y, ul, vl)).astype(np.int16)
  yuv[:, :, 1:] -= 128

  m = np.array([
    [1.00000,  1.00000, 1.00000],
    [0.00000, -0.39465, 2.03211],
    [1.13983, -0.58060, 0.00000],
  ])
  rgb = np.dot(yuv, m).clip(0, 255)
  return rgb.astype(np.uint8)


def extract_image(buf):
  # NV12 format: Y plane followed by interleaved UV plane
  # UV plane size is stride * uv_height, where uv_height = align(height/2, 16)
  uv_height = ((buf.height // 2) + 15) // 16 * 16
  uv_plane_size = buf.stride * uv_height

  y = np.array(buf.data[:buf.uv_offset], dtype=np.uint8).reshape((-1, buf.stride))[:buf.height, :buf.width]
  uv_data = buf.data[buf.uv_offset:buf.uv_offset + uv_plane_size]
  u = np.array(uv_data[::2], dtype=np.uint8).reshape((-1, buf.stride//2))[:buf.height//2, :buf.width//2]
  v = np.array(uv_data[1::2], dtype=np.uint8).reshape((-1, buf.stride//2))[:buf.height//2, :buf.width//2]

  return yuv_to_rgb(y, u, v)


def get_snapshots_bounded(frames: Iterable[str], timeout_s: float = 15., warmup_s: float = 4.,
                          cancelled: Callable[[], bool] | None = None) -> tuple[dict[str, np.ndarray], dict[str, str]]:
  """Capture RGB images within one total deadline, returning partial results and per-camera errors."""
  if timeout_s <= 0 or warmup_s < 0:
    raise ValueError("snapshot timeout must be positive and warmup non-negative")

  sockets = list(dict.fromkeys(frames))
  if not sockets:
    return {}, {}
  unknown = set(sockets) - VISION_STREAMS.keys()
  if unknown:
    raise ValueError(f"unknown camera state(s): {sorted(unknown)}")

  is_cancelled = cancelled or (lambda: False)
  started_at = time.monotonic()
  deadline = started_at + timeout_s
  sm = messaging.SubMaster(sockets)
  vipc_clients = {s: VisionIpcClient("camerad", VISION_STREAMS[s], True) for s in sockets}
  images: dict[str, np.ndarray] = {}
  errors: dict[str, str] = {}

  # wait 4 sec from camerad startup for focus and exposure
  warmup_frames = int(warmup_s / DT_MDL)
  pending_warmup = set(sockets)
  capture_reserve_s = min(SNAPSHOT_CAPTURE_RESERVE_S, timeout_s * .25)
  warmup_deadline = min(deadline - capture_reserve_s, started_at + warmup_s + SNAPSHOT_STARTUP_GRACE_S)
  while pending_warmup and time.monotonic() < warmup_deadline:
    if is_cancelled():
      return {}, dict.fromkeys(sockets, "cancelled")
    for name in list(pending_warmup):
      if sm[name].frameId >= warmup_frames:
        pending_warmup.remove(name)
    if not pending_warmup:
      break
    remaining_ms = int((warmup_deadline - time.monotonic()) * 1000)
    if remaining_ms <= 0:
      break
    sm.update(min(SNAPSHOT_POLL_MS, remaining_ms))

  for name in pending_warmup:
    errors[name] = "warmup_timeout"

  pending = set(sockets) - pending_warmup
  connect_deadline = min(deadline, time.monotonic() + SNAPSHOT_CONNECT_TIMEOUT_S)
  while pending and time.monotonic() < connect_deadline and not is_cancelled():
    for name in list(pending):
      if vipc_clients[name].connect(False):
        pending.remove(name)
    if pending:
      time.sleep(min(.05, max(0., connect_deadline - time.monotonic())))

  for name in pending:
    errors[name] = "connect_timeout" if not is_cancelled() else "cancelled"

  for name in sockets:
    if name in errors:
      continue
    while time.monotonic() < deadline and not is_cancelled():
      remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
      buf = vipc_clients[name].recv(timeout_ms=min(SNAPSHOT_POLL_MS, remaining_ms))
      if buf is not None:
        try:
          images[name] = extract_image(buf)
        except (TypeError, ValueError) as exc:
          errors[name] = f"invalid_frame:{type(exc).__name__}"
        break
    if name not in images and name not in errors:
      errors[name] = "cancelled" if is_cancelled() else "frame_timeout"

  return images, errors


def get_snapshots(frame="roadCameraState", front_frame="driverCameraState", timeout_s: float = 20.):
  if timeout_s <= 0:
    raise ValueError("snapshot timeout must be positive")
  sockets = [s for s in (frame, front_frame) if s is not None]
  deadline = time.monotonic() + timeout_s
  collected: dict[str, np.ndarray] = {}
  errors: dict[str, str] = {}
  while time.monotonic() < deadline:
    remaining_s = deadline - time.monotonic()
    images, errors = get_snapshots_bounded(sockets, timeout_s=min(15., remaining_s))
    collected.update(images)
    if all(socket in collected for socket in sockets):
      return (collected.get(frame) if frame is not None else None,
              collected.get(front_frame) if front_frame is not None else None)
    time.sleep(min(.25, max(0., deadline - time.monotonic())))
  raise TimeoutError(f"camera snapshot timed out: {errors}")
