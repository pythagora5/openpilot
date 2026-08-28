import queue
import threading
import time

from openpilot.cereal import log
from openpilot.common.params import Params, UnknownKeyName
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import button_item, multiple_button_item, text_item, toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.tamperd.config import TAMPER_ARM_DURATION_S, TAMPER_ARM_VOLTAGE_MV, TAMPER_DISARM_VOLTAGE_MV, validate_ntfy_url

if gui_app.sunnypilot_ui():
  from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp as toggle_item
  from openpilot.system.ui.sunnypilot.widgets.list_view import multiple_button_item_sp as multiple_button_item
  from openpilot.system.ui.sunnypilot.widgets.list_view import button_item_sp as button_item

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants
TAMPER_UI_REFRESH_INTERVAL_S = 1.
TAMPER_VOLTAGE_ARMING_STALE_S = 10.
TAMPER_VOLTAGE_IDLE_STALE_S = 40.
TAMPER_STATUS_TEXT = {
  "disabled": tr_noop("Disabled"),
  "voltage": tr_noop("Waiting for safe voltage"),
  "armed": tr_noop("Armed"),
  "baselining": tr_noop("Calibrating"),
  "capturing": tr_noop("Capturing photos"),
  "cooldown": tr_noop("Cooldown"),
  "sensor_unavailable": tr_noop("Sensor unavailable"),
  "starting": tr_noop("Starting"),
  "onroad": tr_noop("Unavailable while on-road"),
  "unavailable": tr_noop("Monitor unavailable"),
  "voltage_arming": tr_noop("Voltage gate arming"),
  "voltage_rearming": tr_noop("Rearming after signal gap"),
  "voltage_unavailable": tr_noop("Voltage data unavailable"),
}
TAMPER_VOLTAGE_TEXT = {
  "arming": tr_noop("{voltage:.1f} V / {remaining:d} s"),
  "below_disarm": tr_noop("{voltage:.1f} V < {threshold:.1f} V cutoff"),
  "below_threshold": tr_noop("{voltage:.1f} V < {threshold:.1f} V"),
  "ignition_on": tr_noop("Ignition on"),
  "safe": tr_noop("{voltage:.1f} V / OK"),
  "stale": tr_noop("Stale data"),
  "timing_unavailable": tr_noop("Timing unavailable"),
  "unavailable": tr_noop("Unavailable"),
  "voltage": tr_noop("{voltage:.1f} V"),
  "waiting": tr_noop("Waiting for data"),
}
NTFY_TEST_RESULT_TEXT = {
  "success": tr_noop("Test notification sent. Confirm it arrived in your ntfy app."),
  "invalid_url": tr_noop("The saved ntfy topic URL is invalid. Enter a complete HTTPS topic URL."),
  "request_failed": tr_noop("Could not reach ntfy. Check the device internet connection and try again."),
  "server_rejected": tr_noop("ntfy rejected the test message. Check the topic or server configuration and try again."),
  "internal_error": tr_noop("The test notification could not be sent. Please try again."),
}

# Description constants
DESCRIPTIONS = {
  "OpenpilotEnabledToggle": tr_noop(
    "Use the sunnypilot system for adaptive cruise control and lane keep driver assistance. " +
    "Your attention is required at all times to use this feature."
  ),
  "DisengageOnAccelerator": tr_noop("When enabled, pressing the accelerator pedal will disengage sunnypilot."),
  "LongitudinalPersonality": tr_noop(
    "Standard is recommended. In aggressive mode, sunnypilot will follow lead cars closer and be more aggressive with the gas and brake. " +
    "In relaxed mode sunnypilot will stay further away from lead cars. On supported cars, you can cycle through these personalities with " +
    "your steering wheel distance button."
  ),
  "IsLdwEnabled": tr_noop(
    "Receive alerts to steer back into the lane when your vehicle drifts over a detected lane line " +
    "without a turn signal activated while driving over 31 mph (50 km/h)."
  ),
  "AlwaysOnDM": tr_noop("Enable driver monitoring even when sunnypilot is not engaged."),
  'RecordFront': tr_noop("Upload data from the driver facing camera and help improve the driver monitoring algorithm."),
  "IsMetric": tr_noop("Display speed in km/h instead of mph."),
  "RecordAudio": tr_noop("Record and store microphone audio while driving. The audio will be included in the dashcam video in comma connect."),
  "TamperModeEnabled": tr_noop(
    "Monitor parked-vehicle movement using the device accelerometer. Monitoring runs only while off-road and vehicle voltage is safely above the cutoff."
  ),
  "TamperModeIncludeDriverCamera": tr_noop(
    "Also attach a driver-facing photo to tamper notifications. Leave this off unless the additional cabin view is wanted."
  ),
}


def ntfy_url_configured(params: Params) -> bool:
  value = params.get("TamperModeNtfyUrl") or ""
  if not isinstance(value, str):
    return False
  try:
    validate_ntfy_url(value)
    return True
  except ValueError:
    return False


def tamper_voltage_status_is_stale(status: dict, now_mono: float | None = None) -> bool:
  updated_at = status.get("updatedAtMonoS")
  if updated_at is None:
    return False
  if isinstance(updated_at, bool) or not isinstance(updated_at, (int, float)):
    return True
  now_mono = time.monotonic() if now_mono is None else now_mono
  age_s = now_mono - float(updated_at)
  max_age_s = TAMPER_VOLTAGE_ARMING_STALE_S if status.get("state") == "arming" else TAMPER_VOLTAGE_IDLE_STALE_S
  return age_s < 0. or age_s > max_age_s


def tamper_status_text(params: Params, started: bool = False, process_running: bool | None = True,
                       now_mono: float | None = None) -> str:
  if not params.get_bool("TamperModeEnabled"):
    return TAMPER_STATUS_TEXT["disabled"]
  if started:
    return TAMPER_STATUS_TEXT["onroad"]
  if not params.get_bool("TamperModeVoltageSafe"):
    voltage_status = params.get("TamperModeVoltageStatus") or {}
    voltage_state = voltage_status.get("state") if isinstance(voltage_status, dict) else None
    if isinstance(voltage_status, dict) and tamper_voltage_status_is_stale(voltage_status, now_mono):
      return TAMPER_STATUS_TEXT["voltage_unavailable"]
    if voltage_state == "arming":
      if voltage_status.get("resetReason") == "sample_gap":
        return TAMPER_STATUS_TEXT["voltage_rearming"]
      return TAMPER_STATUS_TEXT["voltage_arming"]
    if voltage_state == "unavailable":
      return TAMPER_STATUS_TEXT["voltage_unavailable"]
    return TAMPER_STATUS_TEXT["voltage"]
  if process_running is None:
    return TAMPER_STATUS_TEXT["starting"]
  if not process_running:
    return TAMPER_STATUS_TEXT["unavailable"]
  status = params.get("TamperModeStatus") or {}
  state = status.get("state") if isinstance(status, dict) else None
  if not isinstance(state, str):
    state = None
  return TAMPER_STATUS_TEXT.get(state, TAMPER_STATUS_TEXT["starting"])


def tamper_voltage_text(params: Params, now_mono: float | None = None) -> str:
  status = params.get("TamperModeVoltageStatus") or {}
  if not isinstance(status, dict):
    return tr(TAMPER_VOLTAGE_TEXT["waiting"])
  if tamper_voltage_status_is_stale(status, now_mono):
    return tr(TAMPER_VOLTAGE_TEXT["stale"])
  state = status.get("state")
  if state == "ignition_on":
    return tr(TAMPER_VOLTAGE_TEXT["ignition_on"])
  if state == "unavailable":
    return tr(TAMPER_VOLTAGE_TEXT["unavailable"])

  voltage_mv = status.get("voltageMv")
  arm_voltage_mv = status.get("armVoltageMv")
  disarm_voltage_mv = status.get("disarmVoltageMv")
  if isinstance(voltage_mv, bool) or not isinstance(voltage_mv, (int, float)):
    return tr(TAMPER_VOLTAGE_TEXT["waiting"])
  voltage = float(voltage_mv) / 1000.
  if state == "below_disarm" and isinstance(disarm_voltage_mv, (int, float)) and not isinstance(disarm_voltage_mv, bool):
    return tr(TAMPER_VOLTAGE_TEXT["below_disarm"]).format(
      voltage=voltage, threshold=float(disarm_voltage_mv) / 1000.,
    )
  if state == "below_threshold" and isinstance(arm_voltage_mv, (int, float)) and not isinstance(arm_voltage_mv, bool):
    return tr(TAMPER_VOLTAGE_TEXT["below_threshold"]).format(
      voltage=voltage, threshold=float(arm_voltage_mv) / 1000.,
    )
  if state == "arming":
    remaining_s = status.get("remainingS")
    if isinstance(remaining_s, int) and not isinstance(remaining_s, bool) and remaining_s >= 0:
      return tr(TAMPER_VOLTAGE_TEXT["arming"]).format(voltage=voltage, remaining=remaining_s)
    return tr(TAMPER_VOLTAGE_TEXT["timing_unavailable"])
  if state == "safe":
    return tr(TAMPER_VOLTAGE_TEXT["safe"]).format(voltage=voltage)
  return tr(TAMPER_VOLTAGE_TEXT["voltage"]).format(voltage=voltage)


def tamper_voltage_description() -> str:
  return tr(
    "Shows the lower of the instantaneous and smoothed voltage readings used by the safety gate. " +
    "Monitoring requires at least {arm_voltage:.1f} V continuously for {arm_duration:d} seconds and disarms below {disarm_voltage:.1f} V."
  ).format(
    arm_voltage=TAMPER_ARM_VOLTAGE_MV / 1000.,
    arm_duration=int(TAMPER_ARM_DURATION_S),
    disarm_voltage=TAMPER_DISARM_VOLTAGE_MV / 1000.,
  )


def normalize_tamper_sensitivity(value) -> int:
  return value if value in (0, 1, 2) else 1


def tamper_process_running() -> bool | None:
  try:
    if not ui_state.sm.alive["managerState"] or not ui_state.sm.valid["managerState"]:
      return None
    for process in ui_state.sm["managerState"].processes:
      if process.name == "tamperd":
        return True if process.running else (None if process.shouldBeRunning else False)
  except (AttributeError, KeyError):
    return None
  return False


def store_ntfy_url(params: Params, value: str) -> bool:
  value = value.strip()
  if not value:
    params.remove("TamperModeNtfyUrl")
    return True
  try:
    value = validate_ntfy_url(value)
  except ValueError:
    return False
  params.put("TamperModeNtfyUrl", value, block=True)
  return True


def ntfy_test_result_text(error: str | None) -> str:
  if error is None:
    return NTFY_TEST_RESULT_TEXT["success"]
  if error == "invalid_url":
    return NTFY_TEST_RESULT_TEXT["invalid_url"]
  if error == "request_failed":
    return NTFY_TEST_RESULT_TEXT["request_failed"]
  if error.startswith("http_"):
    return NTFY_TEST_RESULT_TEXT["server_rejected"]
  return NTFY_TEST_RESULT_TEXT["internal_error"]


def ntfy_test_enabled(url_configured: bool, offroad: bool, in_progress: bool) -> bool:
  return url_configured and offroad and not in_progress


def ntfy_test_result_visible(result_generation: int, current_generation: int, offroad: bool) -> bool:
  return result_generation == current_generation and offroad


class TogglesLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._is_release = False  # self._params.get_bool("IsReleaseBranch")
    self._tamper_url_button_text = tr("SET")
    self._tamper_status_label = tr(TAMPER_STATUS_TEXT["disabled"])
    self._tamper_voltage_label = tr(TAMPER_VOLTAGE_TEXT["waiting"])
    self._last_tamper_ui_refresh = 0.
    self._tamper_url_configured = False
    self._ntfy_test_in_progress = False
    self._ntfy_test_generation = 0
    self._ntfy_test_results: queue.SimpleQueue[tuple[int, str | None]] = queue.SimpleQueue()
    self._refresh_tamper_ui(force=True)

    # param, title, desc, icon, needs_restart
    self._toggle_defs = {
      "OpenpilotEnabledToggle": (
        lambda: tr("Enable sunnypilot"),
        DESCRIPTIONS["OpenpilotEnabledToggle"],
        "chffr_wheel.png",
        True,
      ),
      "ExperimentalMode": (
        lambda: tr("Experimental Mode"),
        "",
        "experimental_white.png",
        False,
      ),
      "DisengageOnAccelerator": (
        lambda: tr("Disengage on Accelerator Pedal"),
        DESCRIPTIONS["DisengageOnAccelerator"],
        "disengage_on_accelerator.png",
        False,
      ),
      "IsLdwEnabled": (
        lambda: tr("Enable Lane Departure Warnings"),
        DESCRIPTIONS["IsLdwEnabled"],
        "warning.png",
        False,
      ),
      "AlwaysOnDM": (
        lambda: tr("Always-On Driver Monitoring"),
        DESCRIPTIONS["AlwaysOnDM"],
        "monitoring.png",
        False,
      ),
      "RecordFront": (
        lambda: tr("Record and Upload Driver Camera"),
        DESCRIPTIONS["RecordFront"],
        "monitoring.png",
        True,
      ),
      "RecordAudio": (
        lambda: tr("Record and Upload Microphone Audio"),
        DESCRIPTIONS["RecordAudio"],
        "microphone.png",
        True,
      ),
      "IsMetric": (
        lambda: tr("Use Metric System"),
        DESCRIPTIONS["IsMetric"],
        "metric.png",
        False,
      ),
      "TamperModeEnabled": (
        lambda: tr("Parked Tamper Monitoring"),
        DESCRIPTIONS["TamperModeEnabled"],
        "warning.png",
        False,
      ),
      "TamperModeIncludeDriverCamera": (
        lambda: tr("Include Driver Camera Photo"),
        DESCRIPTIONS["TamperModeIncludeDriverCamera"],
        "monitoring.png",
        False,
      ),
    }

    self._long_personality_setting = multiple_button_item(
      lambda: tr("Driving Personality"),
      lambda: tr(DESCRIPTIONS["LongitudinalPersonality"]),
      buttons=[lambda: tr("Aggressive"), lambda: tr("Standard"), lambda: tr("Relaxed")],
      button_width=300,
      callback=self._set_longitudinal_personality,
      selected_index=self._params.get("LongitudinalPersonality", return_default=True),
      icon="speed_limit.png"
    )

    self._toggles = {}
    self._locked_toggles = set()
    for param, (title, desc, icon, needs_restart) in self._toggle_defs.items():
      toggle = toggle_item(
        title,
        desc,
        self._params.get_bool(param),
        callback=lambda state, p=param: self._toggle_callback(state, p),
        icon=icon,
      )

      try:
        locked = self._params.get_bool(param + "Lock")
      except UnknownKeyName:
        locked = False
      toggle.action_item.set_enabled(not locked)

      # Make description callable for live translation
      additional_desc = ""
      if needs_restart and not locked:
        additional_desc = tr("Changing this setting will restart sunnypilot if the car is powered on.")
      toggle.set_description(lambda og_desc=toggle.description, add_desc=additional_desc: tr(og_desc) + (" " + tr(add_desc) if add_desc else ""))

      # track for engaged state updates
      if locked:
        self._locked_toggles.add(param)

      self._toggles[param] = toggle

      # insert longitudinal personality after NDOG toggle
      if param == "DisengageOnAccelerator":
        self._toggles["LongitudinalPersonality"] = self._long_personality_setting

    self._tamper_url_setting = button_item(
      lambda: tr("ntfy Topic URL"),
      lambda: self._tamper_url_button_text,
      lambda: tr("Enter the complete HTTPS ntfy topic URL. Treat the topic URL like a password: anyone who knows it may receive the photos."),
      callback=self._show_tamper_url_dialog,
    )
    self._tamper_test_setting = button_item(
      lambda: tr("Test ntfy Notification"),
      lambda: tr("SENDING") if self._ntfy_test_in_progress else tr("SEND"),
      lambda: tr("Send a text-only test message to confirm this device can reach the configured ntfy topic. This does not capture photos."),
      callback=self._send_ntfy_test,
      enabled=lambda: ntfy_test_enabled(self._tamper_url_configured, ui_state.is_offroad(), self._ntfy_test_in_progress),
    )
    self._tamper_sensitivity_setting = multiple_button_item(
      lambda: tr("Tamper Sensitivity"),
      lambda: tr("Choose how much parked-vehicle movement is required before an alert."),
      buttons=[lambda: tr("Low"), lambda: tr("Medium"), lambda: tr("High")],
      button_width=250,
      callback=lambda value: self._params.put("TamperModeSensitivity", value, block=True),
      selected_index=normalize_tamper_sensitivity(self._params.get("TamperModeSensitivity", return_default=True)),
      icon="warning.png",
    )
    self._tamper_status_setting = text_item(
      lambda: tr("Tamper Monitoring Status"),
      lambda: self._tamper_status_label,
      lambda: tr("Shows whether monitoring is armed or waiting for the vehicle-voltage safety gate."),
    )
    self._tamper_voltage_setting = text_item(
      lambda: tr("Tamper Voltage Safety"),
      lambda: self._tamper_voltage_label,
      tamper_voltage_description,
    )
    self._toggles["TamperModeNtfyUrl"] = self._tamper_url_setting
    self._toggles["TamperModeNtfyTest"] = self._tamper_test_setting
    self._toggles["TamperModeSensitivity"] = self._tamper_sensitivity_setting
    self._toggles["TamperModeStatus"] = self._tamper_status_setting
    self._toggles["TamperModeVoltageStatus"] = self._tamper_voltage_setting

    self._update_experimental_mode_icon()
    self._scroller = Scroller(list(self._toggles.values()), line_separator=True, spacing=0)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    self._handle_ntfy_test_result()
    self._refresh_tamper_ui()
    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._long_personality_setting.action_item.set_selected_button(personality)
      ui_state.personality = personality

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._update_toggles()

  def hide_event(self):
    self._ntfy_test_generation += 1
    super().hide_event()
    self._scroller.hide_event()

  def _update_toggles(self):
    ui_state.update_params()

    e2e_description = tr(
      "sunnypilot defaults to driving in chill mode. Experimental mode enables alpha-level features that aren't ready for chill mode. " +
      "Experimental features are listed below:<br>" +
      "<h4>End-to-End Longitudinal Control</h4><br>" +
      "Let the driving model control the gas and brakes. sunnypilot will drive as it thinks a human would, including stopping for red lights and stop signs. " +
      "Since the driving model decides the speed to drive, the set speed will only act as an upper bound. This is an alpha quality feature; " +
      "mistakes should be expected.<br>" +
      "<h4>New Driving Visualization</h4><br>" +
      "The driving visualization will transition to the road-facing wide-angle camera at low speeds to better show some turns. " +
      "The Experimental mode logo will also be shown in the top right corner."
    )

    if ui_state.CP is not None:
      if ui_state.has_longitudinal_control:
        self._toggles["ExperimentalMode"].action_item.set_enabled(True)
        self._toggles["ExperimentalMode"].set_description(e2e_description)
        self._long_personality_setting.action_item.set_enabled(True)
      else:
        # no long for now
        self._toggles["ExperimentalMode"].action_item.set_enabled(False)
        self._toggles["ExperimentalMode"].action_item.set_state(False)
        self._long_personality_setting.action_item.set_enabled(False)
        self._params.remove("ExperimentalMode")

        unavailable = tr("Experimental mode is currently unavailable on this car since the car's stock ACC is used for longitudinal control.")

        long_desc = unavailable + " " + tr("sunnypilot longitudinal control may come in a future update.")
        if ui_state.CP.alphaLongitudinalAvailable:
          if self._is_release:
            long_desc = unavailable + " " + tr("An alpha version of sunnypilot longitudinal control can be tested, along with " +
                                               "Experimental mode, on non-release branches.")
          else:
            long_desc = tr("Enable the sunnypilot longitudinal control (alpha) toggle to allow Experimental mode.")

        self._toggles["ExperimentalMode"].set_description("<b>" + long_desc + "</b><br><br>" + e2e_description)
    else:
      self._toggles["ExperimentalMode"].set_description(e2e_description)

    self._update_experimental_mode_icon()

    # TODO: make a param control list item so we don't need to manage internal state as much here
    # refresh toggles from params to mirror external changes
    for param in self._toggle_defs:
      self._toggles[param].action_item.set_state(self._params.get_bool(param))
    sensitivity = normalize_tamper_sensitivity(self._params.get("TamperModeSensitivity", return_default=True))
    self._tamper_sensitivity_setting.action_item.set_selected_button(sensitivity)
    self._refresh_tamper_ui(force=True)

    # these toggles need restart, block while engaged
    for toggle_def in self._toggle_defs:
      if self._toggle_defs[toggle_def][3] and toggle_def not in self._locked_toggles:
        self._toggles[toggle_def].action_item.set_enabled(not ui_state.engaged)

  def _render(self, rect):
    self._scroller.render(rect)

  def _update_experimental_mode_icon(self):
    icon = "experimental.png" if self._toggles["ExperimentalMode"].action_item.get_state() else "experimental_white.png"
    self._toggles["ExperimentalMode"].set_icon(icon)

  def _handle_experimental_mode_toggle(self, state: bool):
    confirmed = self._params.get_bool("ExperimentalModeConfirmed")
    if state and not confirmed:
      def confirm_callback(result: DialogResult):
        if result == DialogResult.CONFIRM:
          self._params.put_bool("ExperimentalMode", True, block=True)
          self._params.put_bool("ExperimentalModeConfirmed", True, block=True)
        else:
          self._toggles["ExperimentalMode"].action_item.set_state(False)
        self._update_experimental_mode_icon()

      # show confirmation dialog
      content = (f"<h1>{self._toggles['ExperimentalMode'].title}</h1><br>" +
                 f"<p>{self._toggles['ExperimentalMode'].description}</p>")
      dlg = ConfirmDialog(content, tr("Enable"), rich=True, callback=confirm_callback)
      gui_app.push_widget(dlg)
    else:
      self._update_experimental_mode_icon()
      self._params.put_bool("ExperimentalMode", state, block=True)

  def _toggle_callback(self, state: bool, param: str):
    if param == "ExperimentalMode":
      self._handle_experimental_mode_toggle(state)
      return

    self._params.put_bool(param, state, block=True)
    if self._toggle_defs[param][3]:
      self._params.put_bool("OnroadCycleRequested", True, block=True)

  def _set_longitudinal_personality(self, button_index: int):
    self._params.put("LongitudinalPersonality", button_index, block=True)

  def _show_tamper_url_dialog(self):
    keyboard = Keyboard(max_text_size=255, min_text_size=0, password_mode=True, show_password_toggle=True)
    keyboard.set_title(tr("ntfy Topic URL"), tr("Enter a complete HTTPS topic URL. Leave blank to disable notifications."))
    keyboard.set_text(self._params.get("TamperModeNtfyUrl") or "")

    def handle_result(result: DialogResult):
      if result != DialogResult.CONFIRM:
        return
      if not store_ntfy_url(self._params, keyboard.text):
        gui_app.push_widget(ConfirmDialog(
          tr("Enter a valid HTTPS ntfy topic URL without credentials, query parameters, or fragments."),
          tr("OK"), cancel_text="",
        ))
        return
      self._refresh_tamper_ui(force=True)

    keyboard.set_callback(handle_result)
    gui_app.push_widget(keyboard)

  def _send_ntfy_test(self):
    if self._ntfy_test_in_progress or not ui_state.is_offroad():
      return
    url = self._params.get("TamperModeNtfyUrl") or ""
    if not isinstance(url, str):
      url = ""
    try:
      url = validate_ntfy_url(url)
    except ValueError:
      gui_app.push_widget(ConfirmDialog(tr(ntfy_test_result_text("invalid_url")), tr("OK"), cancel_text=""))
      return

    self._ntfy_test_in_progress = True
    generation = self._ntfy_test_generation

    def worker():
      try:
        from openpilot.system.tamperd.delivery import send_test_notification
        error = send_test_notification(url)
      except Exception:
        error = "internal_error"
      self._ntfy_test_results.put((generation, error))

    try:
      threading.Thread(target=worker, daemon=True, name="ntfy-test").start()
    except Exception:
      self._ntfy_test_in_progress = False
      gui_app.push_widget(ConfirmDialog(tr(ntfy_test_result_text("internal_error")), tr("OK"), cancel_text=""))

  def _handle_ntfy_test_result(self):
    while True:
      try:
        generation, error = self._ntfy_test_results.get_nowait()
      except queue.Empty:
        return
      self._ntfy_test_in_progress = False
      if not ntfy_test_result_visible(generation, self._ntfy_test_generation, ui_state.is_offroad()):
        continue
      gui_app.push_widget(ConfirmDialog(tr(ntfy_test_result_text(error)), tr("OK"), cancel_text=""))
      return

  def _refresh_tamper_ui(self, force: bool = False):
    now = time.monotonic()
    if not force and now - self._last_tamper_ui_refresh < TAMPER_UI_REFRESH_INTERVAL_S:
      return
    self._tamper_url_configured = ntfy_url_configured(self._params)
    self._tamper_url_button_text = tr("EDIT") if self._tamper_url_configured else tr("SET")
    self._tamper_status_label = tr(tamper_status_text(
      self._params, ui_state.started, tamper_process_running(), now_mono=now,
    ))
    self._tamper_voltage_label = tamper_voltage_text(self._params, now_mono=now)
    self._last_tamper_ui_refresh = now
