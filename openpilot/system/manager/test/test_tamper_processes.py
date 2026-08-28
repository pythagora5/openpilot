from opendbc.car.structs import car
import pytest

from openpilot.common.params import Params
from openpilot.system.tamperd import tamperd
from openpilot.system.manager.process_config import managed_processes, tamper_capture, tamper_monitoring


class TestTamperProcesses:
  def setup_method(self):
    self.params = Params()
    self.CP = car.CarParams.new_message()

  def teardown_method(self):
    for key in ("TamperModeEnabled", "TamperModeVoltageSafe", "TamperModeCaptureRequestedMono",
                "TamperModeCaptureDeadlineMono"):
      self.params.remove(key)

  def enable_safe_monitoring(self):
    self.params.put_bool("TamperModeEnabled", True, block=True)
    self.params.put_bool("TamperModeVoltageSafe", True, block=True)

  def request_capture(self, now: int, duration_ns: int = int(20e9)):
    self.params.put("TamperModeCaptureRequestedMono", now, block=True)
    self.params.put("TamperModeCaptureDeadlineMono", now + duration_ns, block=True)

  def test_monitoring_requires_enabled_safe_and_offroad(self):
    assert not tamper_monitoring(False, self.params, self.CP)

    self.params.put_bool("TamperModeEnabled", True, block=True)
    assert not tamper_monitoring(False, self.params, self.CP)

    self.params.put_bool("TamperModeVoltageSafe", True, block=True)
    assert tamper_monitoring(False, self.params, self.CP)
    assert not tamper_monitoring(True, self.params, self.CP)

  def test_capture_requires_short_lived_deadline(self, monkeypatch):
    now = 100 * 1_000_000_000
    monkeypatch.setattr("openpilot.system.manager.process_config.boottime_ns", lambda: now)
    self.enable_safe_monitoring()

    assert not tamper_capture(False, self.params, self.CP)

    self.request_capture(now)
    assert tamper_capture(False, self.params, self.CP)

    self.request_capture(now - int(20e9))
    assert not tamper_capture(False, self.params, self.CP)

    self.request_capture(now, int(31e9))
    assert not tamper_capture(False, self.params, self.CP)

    monkeypatch.setattr("openpilot.system.manager.process_config.boottime_ns", lambda: now + int(2e9))
    assert not tamper_capture(False, self.params, self.CP)

  def test_capture_stops_when_monitoring_becomes_unsafe(self, monkeypatch):
    now = 100 * 1_000_000_000
    monkeypatch.setattr("openpilot.system.manager.process_config.boottime_ns", lambda: now)
    self.enable_safe_monitoring()
    self.request_capture(now)

    assert tamper_capture(False, self.params, self.CP)
    self.params.put_bool("TamperModeVoltageSafe", False, block=True)
    assert not tamper_capture(False, self.params, self.CP)

  def test_process_wiring(self, monkeypatch):
    now = 100 * 1_000_000_000
    monkeypatch.setattr("openpilot.system.manager.process_config.boottime_ns", lambda: now)
    self.enable_safe_monitoring()

    assert managed_processes["tamperd"].should_run(False, self.params, self.CP)
    assert managed_processes["sensord"].should_run(False, self.params, self.CP)
    assert not managed_processes["camerad"].should_run(False, self.params, self.CP)

    self.request_capture(now)
    assert managed_processes["camerad"].should_run(False, self.params, self.CP)

    self.params.put_bool("TamperModeEnabled", False, block=True)
    assert not managed_processes["tamperd"].should_run(False, self.params, self.CP)
    assert not managed_processes["sensord"].should_run(False, self.params, self.CP)
    assert not managed_processes["camerad"].should_run(False, self.params, self.CP)

  def test_onroad_processes_ignore_tamper_request(self, monkeypatch):
    now = 100 * 1_000_000_000
    monkeypatch.setattr("openpilot.system.manager.process_config.boottime_ns", lambda: now)
    self.enable_safe_monitoring()
    self.request_capture(now)

    assert not tamper_capture(True, self.params, self.CP)
    assert not managed_processes["tamperd"].should_run(True, self.params, self.CP)
    assert managed_processes["sensord"].should_run(True, self.params, self.CP)
    assert managed_processes["camerad"].should_run(True, self.params, self.CP)

  def test_malformed_deadline_fails_closed(self, monkeypatch):
    class MalformedParams:
      def get_bool(self, key):
        return key in ("TamperModeEnabled", "TamperModeVoltageSafe")

      def get(self, key):
        return object()

    monkeypatch.setattr("openpilot.system.manager.process_config.boottime_ns", lambda: 100 * 1_000_000_000)
    assert not tamper_capture(False, MalformedParams(), self.CP)

  def test_tamperd_clears_deadline_on_start_and_exit(self, monkeypatch):
    class InterruptingSubMaster:
      def update(self, timeout):
        raise KeyboardInterrupt

    self.params.put("TamperModeCaptureRequestedMono", 100, block=True)
    self.params.put("TamperModeCaptureDeadlineMono", 123, block=True)
    monkeypatch.setattr(tamperd, "Params", lambda: self.params)
    monkeypatch.setattr(tamperd.messaging, "SubMaster", lambda *args, **kwargs: InterruptingSubMaster())

    with pytest.raises(KeyboardInterrupt):
      tamperd.main()
    assert self.params.get("TamperModeCaptureRequestedMono") == 0
    assert self.params.get("TamperModeCaptureDeadlineMono") == 0
