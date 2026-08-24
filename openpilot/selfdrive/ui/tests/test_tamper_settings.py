from openpilot.selfdrive.ui.layouts.settings.toggles import (
  normalize_tamper_sensitivity, ntfy_test_enabled, ntfy_test_result_text, ntfy_test_result_visible,
  ntfy_url_configured, store_ntfy_url, tamper_status_text,
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
