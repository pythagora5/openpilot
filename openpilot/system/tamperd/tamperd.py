#!/usr/bin/env python3

from concurrent.futures import ThreadPoolExecutor

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.tamperd.capture import CaptureOutcome, TamperCapture
from openpilot.system.tamperd.delivery import DeliveryOutcome, TamperNotifier
from openpilot.system.tamperd.detector import SENSITIVITY_PROFILES
from openpilot.system.tamperd.state import TamperEvent, TamperStateMachine
from openpilot.system.tamperd.timebase import boottime_ns, monotonic_to_boottime_ns
from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert


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


def safe_record_event(params: Params, event: TamperEvent, outcome: dict) -> None:
  try:
    record_event(params, event, outcome)
  except Exception:
    cloudlog.error("failed to persist tamper event state")


def safe_notify_detection(notifier: TamperNotifier, event: TamperEvent) -> DeliveryOutcome:
  try:
    return notifier.notify_detection(event)
  except Exception:
    return DeliveryOutcome(True, errors={"notification": "internal_error"})


def safe_set_tamper_alert(message: str) -> None:
  try:
    set_offroad_alert("Offroad_TamperDetected", True, extra_text=message.strip() or "Tampering detected.")
  except Exception:
    cloudlog.error("failed to persist tamper offroad alert")


def format_tamper_alert(capture: CaptureOutcome, delivery: DeliveryOutcome) -> str:
  expected_photos = capture.captured_cameras if capture.capture_state == "captured" else None
  delivery_state = delivery.as_param(expected_photos)["deliveryState"]
  capture_complete = (capture.capture_state == "captured" and not capture.capture_errors and
                      {"road", "wide"} <= set(capture.captured_cameras))
  if capture_complete and delivery_state == "sent":
    return "Tampering detected, notification and photos sent."
  if capture.capture_state == "cancelled_gate_closed":
    return "Tampering detected, but capture stopped because the voltage safety gate closed."
  if capture.capture_state != "captured" and delivery.notification_sent:
    return "Tampering detected. Notification sent, but photos could not be captured."
  if capture.capture_state == "captured" and not capture_complete and delivery.notification_sent:
    return "Tampering detected. Notification sent, but road/wide camera capture was incomplete."
  if capture.capture_state == "captured" and not capture_complete and delivery_state == "not_configured":
    return "Tampering detected. Some camera evidence was saved locally, but capture was incomplete and ntfy is not configured."
  if capture.capture_state == "captured" and delivery_state == "not_configured":
    return "Tampering detected. Photos saved locally; ntfy notifications are not configured."
  if capture.capture_state == "captured" and delivery.notification_sent:
    return "Tampering detected. Notification sent, but one or more photos could not be delivered."
  if capture.capture_state == "captured":
    if not capture_complete:
      return "Tampering detected. Camera capture and notification delivery were incomplete."
    return "Tampering detected. Photos saved locally, but notification delivery failed."
  return "Tampering detected, but notification and camera capture failed."


def handle_tamper_event(params: Params, capture: TamperCapture, notifier: TamperNotifier,
                        event: TamperEvent, alert_callback=safe_set_tamper_alert) -> tuple[CaptureOutcome, DeliveryOutcome]:
  with ThreadPoolExecutor(max_workers=1, thread_name_prefix="tamper_ntfy") as executor:
    notification = executor.submit(safe_notify_detection, notifier, event)
    capture_outcome = capture.capture(event)
    delivery = notification.result()
  interim_outcome = capture_outcome.as_param()
  interim_outcome.update(delivery.as_param())
  safe_record_event(params, event, interim_outcome)
  if capture_outcome.capture_state == "captured":
    alert_callback("Tampering detected. Photos captured; notification delivery in progress.")
  try:
    delivery = notifier.notify_photos(capture_outcome, delivery)
  except Exception:
    errors = dict(delivery.errors or {})
    errors["photos"] = "internal_error"
    delivery = DeliveryOutcome(delivery.configured, delivery.notification_sent, delivery.photos_sent, errors)
  expected_photos = capture_outcome.captured_cameras
  final_outcome = capture_outcome.as_param()
  final_outcome.update(delivery.as_param(expected_photos if capture_outcome.capture_state == "captured" else None))
  safe_record_event(params, event, final_outcome)
  alert_callback(format_tamper_alert(capture_outcome, delivery))
  return capture_outcome, delivery


def process_sensor_sample(params: Params, machine: TamperStateMachine, sensor_timestamp_ns: int,
                          vector, previous_status: dict | None) -> tuple[dict, TamperEvent | None]:
  timestamp_ns = monotonic_to_boottime_ns(sensor_timestamp_ns)
  event = machine.process_sample(timestamp_ns, vector)
  status = publish_status(params, machine.status(), previous_status)
  return status, event


def main() -> None:
  params = Params()
  notifier = None
  clear_capture_deadline(params)
  try:
    raw_sensitivity = params.get("TamperModeSensitivity", return_default=True)
    sensitivity = normalize_sensitivity(raw_sensitivity)
    if raw_sensitivity != sensitivity:
      cloudlog.error(f"invalid tamper sensitivity {raw_sensitivity!r}; using medium")

    machine = TamperStateMachine(sensitivity=sensitivity)
    capture = TamperCapture(params)
    notifier = TamperNotifier(params)
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
        handle_tamper_event(params, capture, notifier, event)
        last_status = publish_status(params, machine.status(), {"state": "capturing"})
  finally:
    try:
      if notifier is not None:
        notifier.close()
    finally:
      clear_capture_deadline(params)


if __name__ == "__main__":
  main()
