from openpilot.selfdrive.ui.layouts.settings.toggles import (
  normalize_tamper_sensitivity, ntfy_test_enabled, ntfy_test_result_text, ntfy_test_result_visible,
  ntfy_url_configured, store_ntfy_url, tamper_status_text, tamper_voltage_description, tamper_voltage_status_is_stale,
  tamper_voltage_text,
)


class FakeParams:
  def __init__(self, values=None):
    self.values = values or {}
    self.writes = []

  def get_bool(self, key):
    return bool(self.values.get(key, False))

  def get(self, key, return_default=False):
    if return_default and key == "TamperModeSensitivity":
      return self.values.get(key, 1)
    return self.values.get(key)

  def put(self, key, value, block=False):
    self.values[key] = value
    self.writes.append((key, value, block))

  def remove(self, key):
    self.values.pop(key, None)
    self.writes.append((key, None, False))


def test_ntfy_configuration_status_never_exposes_topic_value():
  params = FakeParams({"TamperModeNtfyUrl": "https://ntfy.example/a-secret-topic"})

  assert ntfy_url_configured(params)
  assert not ntfy_url_configured(FakeParams({"TamperModeNtfyUrl": "http://ntfy.example/topic"}))


def test_tamper_status_prioritizes_enable_and_voltage_gates():
  assert tamper_status_text(FakeParams({"TamperModeEnabled": True}), started=True) == "Unavailable while on-road"
  assert tamper_status_text(FakeParams()) == "Disabled"
  assert tamper_status_text(FakeParams({"TamperModeEnabled": True})) == "Waiting for safe voltage"
  assert tamper_status_text(FakeParams({
    "TamperModeEnabled": True,
    "TamperModeVoltageStatus": {"state": "arming"},
  })) == "Voltage gate arming"
  assert tamper_status_text(FakeParams({
    "TamperModeEnabled": True,
    "TamperModeVoltageStatus": {"state": "arming", "resetReason": "sample_gap"},
  })) == "Rearming after signal gap"
  assert tamper_status_text(FakeParams({
    "TamperModeEnabled": True,
    "TamperModeVoltageStatus": {"state": "unavailable"},
  })) == "Voltage data unavailable"
  assert tamper_status_text(FakeParams({
    "TamperModeEnabled": True,
    "TamperModeVoltageSafe": True,
    "TamperModeStatus": {"state": "armed"},
  })) == "Armed"
  assert tamper_status_text(FakeParams({
    "TamperModeEnabled": True,
    "TamperModeVoltageSafe": True,
    "TamperModeStatus": {"state": "sensor_unavailable"},
  })) == "Sensor unavailable"
  assert tamper_status_text(FakeParams({
    "TamperModeEnabled": True,
    "TamperModeVoltageSafe": True,
  }), process_running=False) == "Monitor unavailable"
  assert tamper_status_text(FakeParams({
    "TamperModeEnabled": True,
    "TamperModeVoltageSafe": True,
  }), process_running=None) == "Starting"


def test_ntfy_url_storage_rejects_invalid_and_blank_removes():
  params = FakeParams({"TamperModeNtfyUrl": "https://ntfy.example/old-topic"})

  assert not store_ntfy_url(params, "http://ntfy.example/insecure")
  assert params.values["TamperModeNtfyUrl"] == "https://ntfy.example/old-topic"
  assert store_ntfy_url(params, " https://ntfy.example/new-topic/ ")
  assert params.values["TamperModeNtfyUrl"] == "https://ntfy.example/new-topic"
  assert store_ntfy_url(params, "  ")
  assert "TamperModeNtfyUrl" not in params.values


def test_tamper_sensitivity_clamps_invalid_values():
  assert normalize_tamper_sensitivity(0) == 0
  assert normalize_tamper_sensitivity(1) == 1
  assert normalize_tamper_sensitivity(2) == 2
  assert normalize_tamper_sensitivity(None) == 1
  assert normalize_tamper_sensitivity(99) == 1


def test_tamper_voltage_text_explains_gate_state():
  assert tamper_voltage_text(FakeParams()) == "Waiting for data"
  assert tamper_voltage_text(FakeParams({
    "TamperModeVoltageStatus": {"state": "below_threshold", "voltageMv": 12300, "armVoltageMv": 12400},
  })) == "12.3 V < 12.4 V"
  assert tamper_voltage_text(FakeParams({
    "TamperModeVoltageStatus": {"state": "below_disarm", "voltageMv": 12000, "disarmVoltageMv": 12100},
  })) == "12.0 V < 12.1 V cutoff"
  assert tamper_voltage_text(FakeParams({
    "TamperModeVoltageStatus": {"state": "arming", "voltageMv": 12500, "remainingS": 45},
  })) == "12.5 V / 45 s"
  assert tamper_voltage_text(FakeParams({
    "TamperModeVoltageStatus": {"state": "safe", "voltageMv": 12600},
  })) == "12.6 V / OK"
  assert tamper_voltage_text(FakeParams({"TamperModeVoltageStatus": {"state": "ignition_on"}})) == "Ignition on"
  assert tamper_voltage_text(FakeParams({"TamperModeVoltageStatus": {"state": "unavailable"}})) == "Unavailable"
  assert tamper_voltage_text(FakeParams({"TamperModeVoltageStatus": {"state": "arming", "voltageMv": True}})) == "Waiting for data"
  assert tamper_voltage_text(FakeParams({
    "TamperModeVoltageStatus": {"state": "arming", "voltageMv": 12500},
  })) == "Timing unavailable"


def test_tamper_voltage_status_rejects_stale_or_future_diagnostics():
  fresh = {"state": "arming", "updatedAtMonoS": 95}
  assert not tamper_voltage_status_is_stale(fresh, now_mono=100.)
  assert tamper_voltage_status_is_stale(fresh, now_mono=106.)
  assert tamper_voltage_status_is_stale({"state": "safe", "updatedAtMonoS": 50}, now_mono=100.)
  assert tamper_voltage_status_is_stale({"state": "safe", "updatedAtMonoS": 101}, now_mono=100.)
  assert tamper_voltage_text(FakeParams({
    "TamperModeVoltageStatus": {"state": "arming", "voltageMv": 12500, "remainingS": 45, "updatedAtMonoS": 80},
  }), now_mono=100.) == "Stale data"
  assert tamper_status_text(FakeParams({
    "TamperModeEnabled": True,
    "TamperModeVoltageStatus": {"state": "arming", "updatedAtMonoS": 80},
  }), now_mono=100.) == "Voltage data unavailable"


def test_tamper_voltage_description_uses_shared_gate_thresholds():
  assert "12.4 V" in tamper_voltage_description()
  assert "60 seconds" in tamper_voltage_description()
  assert "12.1 V" in tamper_voltage_description()


def test_ntfy_test_results_are_actionable_and_do_not_expose_topic():
  assert "Confirm it arrived" in ntfy_test_result_text(None)
  assert "HTTPS topic URL" in ntfy_test_result_text("invalid_url")
  assert "internet connection" in ntfy_test_result_text("request_failed")
  assert "rejected" in ntfy_test_result_text("http_403")
  assert "try again" in ntfy_test_result_text("internal_error")
  assert "topic-name" not in ntfy_test_result_text("https://ntfy.example/topic-name")


def test_ntfy_test_enablement_is_offroad_and_independent_of_voltage_gate():
  assert ntfy_test_enabled(url_configured=True, offroad=True, in_progress=False)
  assert not ntfy_test_enabled(url_configured=False, offroad=True, in_progress=False)
  assert not ntfy_test_enabled(url_configured=True, offroad=False, in_progress=False)
  assert not ntfy_test_enabled(url_configured=True, offroad=True, in_progress=True)


def test_ntfy_test_results_only_surface_for_the_current_offroad_panel():
  assert ntfy_test_result_visible(result_generation=2, current_generation=2, offroad=True)
  assert not ntfy_test_result_visible(result_generation=1, current_generation=2, offroad=True)
  assert not ntfy_test_result_visible(result_generation=2, current_generation=2, offroad=False)
