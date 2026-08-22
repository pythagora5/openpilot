#!/usr/bin/env python3

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.tamperd.capture import TamperCapture
from openpilot.system.tamperd.detector import SENSITIVITY_PROFILES
from openpilot.system.tamperd.state import TamperEvent, TamperStateMachine
from openpilot.system.tamperd.timebase import boottime_ns, monotonic_to_boottime_ns


SENSOR_UNAVAILABLE_TIMEOUT_NS = int(1e9)
SENSITIVITY_REFRESH_NS = int(5e9)


def clear_capture_deadline(params: Params) -> None:
  try:
    params.put("TamperModeCaptureRequestedMono", 0, block=True)
  finally:
    params.put("TamperModeCaptureDeadlineMono", 0, block=True)


def normalize_sensitivity(value) -> int:
  try:
    sensitivity = int(value)
  except (TypeError, ValueError):
    return 1
  return sensitivity if sensitivity in SENSITIVITY_PROFILES else 1


def publish_status(params: Params, status: dict, previous_status: dict | None) -> dict:
  if status != previous_status:
    params.put("TamperModeStatus", status, block=False)
  return status


def event_to_param(event: TamperEvent) -> dict:
  return {
    "detectedAtMono": event.detected_at_ns,
    "reason": event.reason,
    "peakMotion": event.peak_motion,
    "orientationChangeDeg": event.orientation_change_deg,
    "deliveryState": "not_started",
  }


def record_event(params: Params, event: TamperEvent, outcome: dict) -> None:
  event_data = event_to_param(event)
  event_data.update(outcome)
  params.put("TamperModeLastEvent", event_data, block=True)


def process_sensor_sample(params: Params, machine: TamperStateMachine, sensor_timestamp_ns: int,
                          vector, previous_status: dict | None) -> tuple[dict, TamperEvent | None]:
  timestamp_ns = monotonic_to_boottime_ns(sensor_timestamp_ns)
  event = machine.process_sample(timestamp_ns, vector)
  status = publish_status(params, machine.status(), previous_status)
  return status, event


def main() -> None:
  params = Params()
  clear_capture_deadline(params)
  try:
    raw_sensitivity = params.get("TamperModeSensitivity", return_default=True)
    sensitivity = normalize_sensitivity(raw_sensitivity)
    if raw_sensitivity != sensitivity:
      cloudlog.error(f"invalid tamper sensitivity {raw_sensitivity!r}; using medium")

    machine = TamperStateMachine(sensitivity=sensitivity)
    capture = TamperCapture(params)
    last_status = publish_status(params, {"state": "starting"}, None)
    started_at_boot_ns = boottime_ns()
    last_valid_boot_ns: int | None = None
    last_sensitivity_check_ns = started_at_boot_ns

    sm = messaging.SubMaster(["accelerometer"], poll="accelerometer")
    while True:
      sm.update(1000)
      now_boot_ns = boottime_ns()

      if now_boot_ns - last_sensitivity_check_ns >= SENSITIVITY_REFRESH_NS:
        new_raw_sensitivity = params.get("TamperModeSensitivity", return_default=True)
        if new_raw_sensitivity != raw_sensitivity:
          new_sensitivity = normalize_sensitivity(new_raw_sensitivity)
          if new_raw_sensitivity != new_sensitivity:
            cloudlog.error(f"invalid tamper sensitivity {new_raw_sensitivity!r}; using medium")
          if new_sensitivity != sensitivity:
            sensitivity = new_sensitivity
            machine = TamperStateMachine(sensitivity=sensitivity)
            last_status = publish_status(params, machine.status(), last_status)
          raw_sensitivity = new_raw_sensitivity
        last_sensitivity_check_ns = now_boot_ns

      sensor_available = (sm.updated["accelerometer"] and sm.alive["accelerometer"] and
                          sm.valid["accelerometer"])
      if not sensor_available:
        last_seen_ns = last_valid_boot_ns if last_valid_boot_ns is not None else started_at_boot_ns
        if now_boot_ns - last_seen_ns >= SENSOR_UNAVAILABLE_TIMEOUT_NS:
          unavailable_status = {"state": "sensor_unavailable"}
          if last_status != unavailable_status:
            machine.reset()
            cloudlog.error("tamper accelerometer unavailable")
            last_status = publish_status(params, unavailable_status, last_status)
        continue

      sensor = sm["accelerometer"]
      if sensor.which() != "acceleration":
        continue

      if last_status == {"state": "sensor_unavailable"}:
        machine.reset()
        cloudlog.info("tamper accelerometer recovered")
      last_valid_boot_ns = now_boot_ns

      last_status, event = process_sensor_sample(params, machine, sensor.timestamp, sensor.acceleration.v, last_status)
      if event is not None:
        outcome = capture.capture(event)
        record_event(params, event, outcome.as_param())
        last_status = publish_status(params, machine.status(), {"state": "capturing"})
  finally:
    clear_capture_deadline(params)


if __name__ == "__main__":
  main()
