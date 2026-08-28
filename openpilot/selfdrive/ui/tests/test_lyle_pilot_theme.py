from types import SimpleNamespace

import pyray as rl
import pytest

from openpilot.selfdrive.ui.layouts import home as home_layout
from openpilot.selfdrive.ui.layouts import main as main_layout
from openpilot.selfdrive.ui.onroad import alert_renderer, augmented_road_view, hud_renderer
from openpilot.selfdrive.ui.mici.onroad.alert_renderer import ALERT_STARTUP_PENDING as ALERT_STARTUP_PENDING_MICI
from openpilot.selfdrive.ui.sunnypilot import ui_state as ui_state_sp
from openpilot.selfdrive.ui.sunnypilot.onroad import hud_renderer as hud_renderer_sp
from openpilot.selfdrive.ui.sunnypilot.onroad import road_name, speed_limit, turn_signal
from openpilot.selfdrive.ui.mici.onroad.alert_renderer import IconSide
from openpilot.selfdrive.ui.ui_state import UIStatus
from openpilot.system.ui.sunnypilot.lib.theme import theme


class FakeParams:
  def __init__(self, offroad_mode=True, boot_mode=1):
    self.offroad_mode = offroad_mode
    self.boot_mode = boot_mode
    self.put_calls = []

  def get_bool(self, key):
    return self.offroad_mode if key == "OffroadMode" else False

  def get(self, key, return_default=False):
    return self.boot_mode if key == "DeviceBootMode" else None

  def put_bool(self, key, value, **kwargs):
    self.put_calls.append((key, value, kwargs))
    if key == "OffroadMode":
      self.offroad_mode = value


def make_onroad_button(state, params=None, clock=lambda: 10.0):
  button = home_layout.OnroadModeButton.__new__(home_layout.OnroadModeButton)
  home_layout.Widget.__init__(button)
  button.params = params or FakeParams(state.always_offroad)
  button.ui_state = state
  button.clock = clock
  button.request_started_at = None
  button.button_state = home_layout.OnroadButtonState.ENABLED
  return button


def test_always_offroad_state_exists_before_first_param_refresh(monkeypatch):
  fake_params = FakeParams(offroad_mode=True, boot_mode=1)
  monkeypatch.setattr(ui_state_sp, "Params", lambda: fake_params)
  monkeypatch.setattr(ui_state_sp, "SunnylinkState", lambda: object())

  state = ui_state_sp.UIStateSP()

  assert state.always_offroad is True
  assert state.boot_offroad_mode == 1


@pytest.mark.parametrize(
  ("always_offroad", "ignition", "expected_state", "enabled"),
  [
    (True, True, home_layout.OnroadButtonState.START, True),
    (True, False, home_layout.OnroadButtonState.IGNITION_REQUIRED, False),
    (False, True, home_layout.OnroadButtonState.STARTING, False),
    (False, False, home_layout.OnroadButtonState.ENABLED, False),
  ],
)
def test_onroad_button_states(monkeypatch, always_offroad, ignition, expected_state, enabled):
  state = SimpleNamespace(always_offroad=always_offroad, ignition=ignition, started=False)
  button = make_onroad_button(state)
  styles = []
  monkeypatch.setattr(home_layout.Button, "set_text", lambda self, text: None)
  monkeypatch.setattr(home_layout.Button, "set_button_style", lambda self, style: styles.append(style))
  monkeypatch.setattr(home_layout.Button, "_update_state", lambda self: None)

  button._update_state()

  assert button.button_state == expected_state
  assert button.enabled is enabled
  assert button.actionable is enabled
  assert styles == [home_layout.ButtonStyle.PRIMARY if enabled else home_layout.ButtonStyle.NO_EFFECT]


def test_onroad_button_makes_one_nonblocking_request():
  now = [10.0]
  params = FakeParams(offroad_mode=True)
  state = SimpleNamespace(always_offroad=True, ignition=True, started=False)
  button = make_onroad_button(state, params=params, clock=lambda: now[0])
  button.button_state = home_layout.OnroadButtonState.START

  button._request_onroad()
  button._request_onroad()

  assert params.put_calls == [("OffroadMode", False, {})]
  assert state.always_offroad is False
  assert button._get_button_state() == home_layout.OnroadButtonState.STARTING

  now[0] += home_layout.STARTUP_TIMEOUT
  assert button._get_button_state() == home_layout.OnroadButtonState.CHECK_ALERTS


def test_onroad_button_recovers_if_always_offroad_returns():
  now = [10.0]
  state = SimpleNamespace(always_offroad=True, ignition=True, started=False)
  button = make_onroad_button(state, clock=lambda: now[0])
  button.button_state = home_layout.OnroadButtonState.START
  button._request_onroad()

  state.always_offroad = True
  now[0] += home_layout.OFFROAD_REVERT_GRACE

  assert button._get_button_state() == home_layout.OnroadButtonState.START
  assert button.request_started_at is None


def test_onroad_button_clears_request_on_successful_transition():
  state = SimpleNamespace(always_offroad=False, ignition=True, started=True)
  button = make_onroad_button(state)
  button.request_started_at = 10.0

  button._handle_offroad_transition()

  assert button.request_started_at is None


def test_onroad_button_does_not_show_delayed_alert_after_ignition_loss():
  now = [20.0]
  state = SimpleNamespace(always_offroad=False, ignition=False, started=False)
  button = make_onroad_button(state, clock=lambda: now[0])
  button.request_started_at = 10.0

  assert button._get_button_state() == home_layout.OnroadButtonState.ENABLED
  assert button.request_started_at is None


def test_home_action_is_large_and_right_aligned():
  class RenderRecorder:
    def __init__(self):
      self.rect = None

    def render(self, rect):
      self.rect = rect

  layout = home_layout.HomeLayout.__new__(home_layout.HomeLayout)
  layout._rect = rl.Rectangle(300, 0, 1860, 1080)
  layout.update_available = False
  layout.header_rect = rl.Rectangle(0, 0, 0, 0)
  layout.content_rect = rl.Rectangle(0, 0, 0, 0)
  layout.right_column_rect = rl.Rectangle(0, 0, 0, 0)
  layout.update_notif_rect = rl.Rectangle(0, 0, 200, home_layout.HEADER_HEIGHT - 10)
  layout.alert_notif_rect = rl.Rectangle(0, 0, 220, home_layout.HEADER_HEIGHT - 10)
  layout._exp_mode_button = RenderRecorder()
  layout._onroad_mode_button = RenderRecorder()

  layout._update_state()
  layout._render_right_column()

  action_rect = layout._onroad_mode_button.rect
  assert action_rect.x >= 2160 / 2
  assert action_rect.width == home_layout.RIGHT_COLUMN_WIDTH
  assert action_rect.height >= 500
  assert not hasattr(home_layout, "PrimeWidget")
  assert not hasattr(home_layout, "SetupWidget")


def test_main_callbacks_do_not_require_removed_setup_widget(monkeypatch):
  class FakeSidebar:
    def set_callbacks(self, **kwargs):
      self.callbacks = kwargs

  class FakeLayout:
    def set_settings_callback(self, callback):
      self.settings_callback = callback

    def set_callbacks(self, **kwargs):
      self.callbacks = kwargs

    def set_click_callback(self, callback):
      self.click_callback = callback

  layout = main_layout.MainLayout.__new__(main_layout.MainLayout)
  layout._sidebar = FakeSidebar()
  layout._home_body_layout = FakeLayout()
  layout._layouts = {
    main_layout.MainState.HOME: FakeLayout(),
    main_layout.MainState.SETTINGS: FakeLayout(),
    main_layout.MainState.ONROAD: FakeLayout(),
  }
  monkeypatch.setattr(main_layout.device, "add_interactive_timeout_callback", lambda callback: None)
  monkeypatch.setattr(main_layout.ui_state, "add_on_body_changed_callbacks", lambda callback: None)

  layout._setup_callbacks()

  assert callable(layout._layouts[main_layout.MainState.HOME].settings_callback)


def test_sunnypilot_driving_hud_disables_experimental_status_ring(monkeypatch):
  class DummyRenderer:
    def __init__(self, *args, **kwargs):
      pass

  monkeypatch.setattr(hud_renderer.HudRenderer, "__init__", lambda self: setattr(self, "_show_exp_button", True))
  for renderer_name in (
    "DeveloperUiRenderer", "RoadNameRenderer", "RocketFuel", "SpeedLimitRenderer",
    "SmartCruiseControlRenderer", "TurnSignalController", "CircularAlertsRenderer",
    "SpeedRenderer", "TorqueBar",
  ):
    monkeypatch.setattr(hud_renderer_sp, renderer_name, DummyRenderer)

  renderer = hud_renderer_sp.HudRendererSP()

  assert renderer._show_exp_button is False
  assert renderer.user_interacting() is False


def test_hidden_experimental_button_is_not_rendered_or_interactive(monkeypatch):
  renderer = hud_renderer.HudRenderer.__new__(hud_renderer.HudRenderer)
  renderer.is_cruise_available = False
  renderer._show_exp_button = False
  renderer._exp_button = SimpleNamespace(
    is_pressed=True,
    render=lambda rect: pytest.fail("hidden experimental button was rendered"),
  )

  monkeypatch.setattr(renderer, "_draw_current_speed", lambda rect: None)
  monkeypatch.setattr(hud_renderer.rl, "draw_rectangle_gradient_v", lambda *args: None)

  renderer._render(rl.Rectangle(0, 0, 2160, 1080))

  assert renderer.user_interacting() is False


@pytest.mark.parametrize("is_metric", (True, False))
def test_max_and_speed_limit_cluster_is_anchored_top_right(monkeypatch, is_metric):
  max_panels = []
  speed_limit_panels = []
  rect = rl.Rectangle(18, 18, 2124, 1044)

  max_renderer = hud_renderer_sp.HudRendererSP.__new__(hud_renderer_sp.HudRendererSP)
  max_renderer.is_cruise_set = False
  max_renderer.set_speed = 0
  max_renderer.show_icbm_status = False
  max_renderer._font_semi_bold = object()
  max_renderer._font_bold = object()
  max_renderer._get_icbm_status = lambda: None

  speed_renderer = speed_limit.SpeedLimitRenderer.__new__(speed_limit.SpeedLimitRenderer)
  speed_renderer._pre_active_fade = SimpleNamespace(alpha=1.0)
  speed_renderer.speed_limit_assist_state = speed_limit.AssistState.disabled
  speed_renderer._draw_sign_main = lambda panel, alpha: speed_limit_panels.append(panel)
  speed_renderer._draw_ahead_info = lambda panel: None

  fake_ui_state = SimpleNamespace(
    is_metric=is_metric,
    speed_limit_mode=speed_limit.SpeedLimitMode.information,
    status=UIStatus.DISENGAGED,
    sm={
      "longitudinalPlanSP": SimpleNamespace(speedLimit=SimpleNamespace(assist=SimpleNamespace(active=False))),
      "carControl": SimpleNamespace(cruiseControl=SimpleNamespace(override=False)),
    },
  )
  monkeypatch.setattr(hud_renderer_sp, "ui_state", fake_ui_state)
  monkeypatch.setattr(speed_limit, "ui_state", fake_ui_state)
  monkeypatch.setattr(hud_renderer_sp, "measure_text_cached", lambda *args: rl.Vector2(40, 40))
  monkeypatch.setattr(hud_renderer_sp.rl, "draw_rectangle_rounded", lambda panel, *args: max_panels.append(panel))
  monkeypatch.setattr(hud_renderer_sp.rl, "draw_rectangle_rounded_lines_ex", lambda *args: None)
  monkeypatch.setattr(hud_renderer_sp.rl, "draw_text_ex", lambda *args: None)

  max_renderer._draw_set_speed(rect)
  speed_renderer._render(rect)

  max_panel = max_panels[0]
  speed_limit_panel = speed_limit_panels[0]
  visual_width = speed_limit.METRIC_SPEED_LIMIT_DIAMETER if is_metric else speed_limit_panel.width
  visual_right = speed_limit_panel.x + speed_limit_panel.width / 2 + visual_width / 2
  visual_left = speed_limit_panel.x + speed_limit_panel.width / 2 - visual_width / 2

  assert max_panel.x + max_panel.width < visual_left
  assert visual_right == rect.x + rect.width - theme.HUD_CLUSTER_RIGHT_MARGIN
  assert max_panel.x > rect.x + rect.width / 2


def test_top_right_speed_assist_arrow_draws_below_sign(monkeypatch):
  draws = []
  renderer = speed_limit.SpeedLimitRenderer.__new__(speed_limit.SpeedLimitRenderer)
  renderer.arrow_blank = object()
  arrow = SimpleNamespace(width=200, height=200)
  monkeypatch.setattr(speed_limit.SpeedLimitAlertRenderer, "speed_limit_pre_active_icon_helper",
                      lambda self: (IconSide.right, arrow, 255, 10, 18))
  monkeypatch.setattr(speed_limit.rl, "draw_texture_ex", lambda texture, pos, *args: draws.append((texture, pos)))

  sign_rect = rl.Rectangle(1891, 39, 200, 216)
  renderer._draw_pre_active_arrow(sign_rect)

  texture, position = draws[0]
  assert texture is arrow
  assert position.x == sign_rect.x
  assert position.y > sign_rect.y + sign_rect.height


def test_startup_pending_alert_uses_fork_name():
  for alert in (alert_renderer.ALERT_STARTUP_PENDING, ALERT_STARTUP_PENDING_MICI):
    assert alert.text1 == "Lyle Pilot is loading..."
    assert alert.text2 == "Waiting to start"
    assert alert.size == alert_renderer.AlertSize.mid
    assert alert.status == alert_renderer.AlertStatus.normal


def test_startup_pending_path_returns_branded_alert(monkeypatch):
  class FakeSubMaster:
    updated = {"selfdriveState": False}
    recv_frame = {"selfdriveState": 9}

    def __getitem__(self, service):
      assert service == "selfdriveState"
      return SimpleNamespace(alertSize=0)

  monkeypatch.setattr(alert_renderer, "ui_state", SimpleNamespace(started_frame=10, started_time=100.0))
  monkeypatch.setattr(alert_renderer, "monotonic", lambda: 106.0)

  alert = alert_renderer.AlertRenderer.get_alert(SimpleNamespace(), FakeSubMaster())

  assert alert is alert_renderer.ALERT_STARTUP_PENDING
  assert alert.text1 == "Lyle Pilot is loading..."


def test_startup_pending_path_waits_five_seconds(monkeypatch):
  class FakeSubMaster:
    updated = {"selfdriveState": False}
    recv_frame = {"selfdriveState": 9}

    def __getitem__(self, service):
      assert service == "selfdriveState"
      return SimpleNamespace(alertSize=0)

  monkeypatch.setattr(alert_renderer, "ui_state", SimpleNamespace(started_frame=10, started_time=100.0))
  monkeypatch.setattr(alert_renderer, "monotonic", lambda: 105.0)

  assert alert_renderer.AlertRenderer.get_alert(SimpleNamespace(), FakeSubMaster()) is None


@pytest.mark.parametrize("status", [UIStatus.ENGAGED, UIStatus.LAT_ONLY, UIStatus.OVERRIDE])
def test_lateral_border_uses_wide_gradient(monkeypatch, status):
  strokes = []
  monkeypatch.setattr(augmented_road_view.gui_app, "sunnypilot_ui", lambda: True)
  monkeypatch.setattr(augmented_road_view, "ui_state", SimpleNamespace(status=status))
  monkeypatch.setattr(augmented_road_view.rl, "draw_rectangle_lines_ex", lambda *args: None)
  monkeypatch.setattr(augmented_road_view.rl, "draw_rectangle_rounded_lines_ex",
                      lambda rect, roundness, segments, width, color:
                        strokes.append((width, (color.r, color.g, color.b, color.a))))

  augmented_road_view.AugmentedRoadView._draw_border(object(), rl.Rectangle(0, 0, 2160, 1080))

  base_color = theme.status_color(status)
  assert strokes == [
    (width, (base_color.r, base_color.g, base_color.b, alpha))
    for _, width, alpha in theme.ROAD_BORDER_FADE_BANDS
  ]
  assert theme.ROAD_BORDER_FADE_WIDTH >= 64
  assert strokes[0][1][3] > strokes[-1][1][3]


def test_non_lateral_border_remains_thin(monkeypatch):
  strokes = []
  monkeypatch.setattr(augmented_road_view.gui_app, "sunnypilot_ui", lambda: True)
  monkeypatch.setattr(augmented_road_view, "ui_state", SimpleNamespace(status=UIStatus.LONG_ONLY))
  monkeypatch.setattr(augmented_road_view.rl, "draw_rectangle_lines_ex", lambda *args: None)
  monkeypatch.setattr(augmented_road_view.rl, "draw_rectangle_rounded_lines_ex",
                      lambda rect, roundness, segments, width, color: strokes.append((width, color.a)))

  augmented_road_view.AugmentedRoadView._draw_border(object(), rl.Rectangle(0, 0, 2160, 1080))

  assert strokes == [(theme.ROAD_BORDER_WIDTH, 0xFF)]


def test_override_border_uses_wide_amber_gradient(monkeypatch):
  strokes = []
  monkeypatch.setattr(augmented_road_view.gui_app, "sunnypilot_ui", lambda: True)
  monkeypatch.setattr(augmented_road_view, "ui_state", SimpleNamespace(status=UIStatus.OVERRIDE))
  monkeypatch.setattr(augmented_road_view.rl, "draw_rectangle_lines_ex", lambda *args: None)
  monkeypatch.setattr(augmented_road_view.rl, "draw_rectangle_rounded_lines_ex",
                      lambda rect, roundness, segments, width, color: strokes.append((width, color)))

  augmented_road_view.AugmentedRoadView._draw_border(object(), rl.Rectangle(0, 0, 2160, 1080))

  assert len(strokes) == len(theme.ROAD_BORDER_FADE_BANDS)
  assert all(width == 3 for width, _ in strokes)
  assert all((color.r, color.g, color.b) == (theme.AMBER.r, theme.AMBER.g, theme.AMBER.b) for _, color in strokes)
  assert [color.a for _, color in strokes] == [alpha for _, _, alpha in theme.ROAD_BORDER_FADE_BANDS]


def test_signature_is_anchored_to_bottom_left(monkeypatch):
  text_draws = []
  texture_draws = []
  renderer = road_name.RoadNameRenderer.__new__(road_name.RoadNameRenderer)
  renderer.road_name = "Test Road"
  renderer.font_demi = object()
  renderer.font_medium = object()
  renderer.vehicle_logo = object()
  renderer._lc_display_state = "disabled"

  fake_ui_state = SimpleNamespace(
    road_name_toggle=True,
    status=UIStatus.ENGAGED,
    sm={
      "selfdriveState": SimpleNamespace(alertSize=0),
      "driverMonitoringState": SimpleNamespace(isRHD=True),
    },
  )
  monkeypatch.setattr(road_name, "ui_state", fake_ui_state)
  monkeypatch.setattr(road_name, "measure_text_cached", lambda font, text, size: rl.Vector2(125, size))
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded_lines_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_line_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_text_ex",
                      lambda font, text, pos, size, spacing, color: text_draws.append((text, pos)))
  monkeypatch.setattr(road_name.rl, "draw_texture_ex",
                      lambda texture, pos, rotation, scale, color: texture_draws.append((texture, pos, scale)))

  rect = rl.Rectangle(18, 18, 2124, 1044)
  renderer._render(rect)

  signature, position = text_draws[-1]
  assert signature == "Lyle Pilot  v0.1.0"
  assert position.x == rect.x + theme.ROAD_BORDER_FADE_WIDTH + 16
  assert position.y == rect.y + rect.height - 30 - theme.ROAD_BORDER_FADE_WIDTH - 16
  bar_width = min(theme.STATUS_BAR_WIDTH, rect.width - 80)
  bar_x = rect.x + (rect.width - bar_width) / 2
  assert position.x + 125 < bar_x
  assert len(texture_draws) == 1
  texture, logo_position, scale = texture_draws[0]
  assert texture is renderer.vehicle_logo
  assert logo_position.x == position.x
  assert logo_position.y == position.y - road_name.VEHICLE_LOGO_GAP - road_name.VEHICLE_LOGO_SIZE
  assert scale == 1.0
  assert road_name.VEHICLE_LOGO_SIZE == 218


def test_signature_draws_without_road_name_and_clears_lhd_driver_icon(monkeypatch):
  text_draws = []
  renderer = road_name.RoadNameRenderer.__new__(road_name.RoadNameRenderer)
  renderer.road_name = ""
  renderer.font_demi = object()
  renderer.font_medium = object()
  renderer.vehicle_logo = object()
  renderer._lc_display_state = "disabled"

  fake_ui_state = SimpleNamespace(
    road_name_toggle=False,
    status=UIStatus.DISENGAGED,
    sm={
      "selfdriveState": SimpleNamespace(alertSize=0),
      "driverMonitoringState": SimpleNamespace(isRHD=False),
    },
  )
  monkeypatch.setattr(road_name, "ui_state", fake_ui_state)
  monkeypatch.setattr(road_name, "measure_text_cached", lambda font, text, size: rl.Vector2(125, size))
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded_lines_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_line_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_text_ex",
                      lambda font, text, pos, size, spacing, color: text_draws.append((text, pos)))
  monkeypatch.setattr(road_name.rl, "draw_texture_ex", lambda *args: None)

  rect = rl.Rectangle(18, 18, 2124, 1044)
  renderer._render(rect)

  signature, position = text_draws[-1]
  assert signature == "Lyle Pilot  v0.1.0"
  assert position.x == rect.x + theme.ROAD_BORDER_FADE_WIDTH + 16
  assert position.y + 30 <= rect.y + rect.height - road_name.UI_BORDER_SIZE - road_name.BTN_SIZE - 28


def test_missing_road_name_shows_coordinate_free_map_health(monkeypatch):
  text_draws = []
  renderer = road_name.RoadNameRenderer.__new__(road_name.RoadNameRenderer)
  renderer.road_name = ""
  renderer.mapd_health = "tile_missing"
  renderer.font_demi = object()
  renderer.font_medium = object()
  renderer._lc_display_state = "disabled"

  fake_ui_state = SimpleNamespace(
    road_name_toggle=True,
    status=UIStatus.DISENGAGED,
    sm={
      "selfdriveState": SimpleNamespace(alertSize=1),
      "driverMonitoringState": SimpleNamespace(isRHD=True),
    },
  )
  monkeypatch.setattr(road_name, "ui_state", fake_ui_state)
  monkeypatch.setattr(road_name, "measure_text_cached", lambda font, text, size: rl.Vector2(len(text) * size / 2, size))
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded_lines_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_line_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_text_ex",
                      lambda font, text, pos, size, spacing, color: text_draws.append(text))

  renderer._render(rl.Rectangle(18, 18, 2124, 1044))

  assert "MAP TILE MISSING" in text_draws


def test_empty_map_tile_has_specific_health_message():
  assert road_name.RoadNameRenderer.MAP_HEALTH_TEXT["tile_empty"] == "MAP TILE EMPTY"


def test_vehicle_logo_is_hidden_during_alerts(monkeypatch):
  renderer = road_name.RoadNameRenderer.__new__(road_name.RoadNameRenderer)
  renderer.road_name = "Test Road"
  renderer.font_demi = object()
  renderer.font_medium = object()
  renderer.vehicle_logo = object()
  renderer._lc_display_state = "disabled"

  fake_ui_state = SimpleNamespace(
    road_name_toggle=True,
    status=UIStatus.ENGAGED,
    sm={
      "selfdriveState": SimpleNamespace(alertSize=1),
      "driverMonitoringState": SimpleNamespace(isRHD=True),
    },
  )
  monkeypatch.setattr(road_name, "ui_state", fake_ui_state)
  monkeypatch.setattr(road_name, "measure_text_cached", lambda font, text, size: rl.Vector2(125, size))
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded_lines_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_line_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_text_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_texture_ex",
                      lambda *args: pytest.fail("vehicle logo was drawn over an active alert"))

  renderer._render(rl.Rectangle(18, 18, 2124, 1044))


def test_turn_and_blind_spot_icons_are_twice_the_original_size(monkeypatch):
  texture_loads = []

  def fake_texture(path, width, height, **kwargs):
    texture_loads.append((path, width, height, kwargs.get("flip_x", False)))
    return SimpleNamespace(width=width, height=height)

  monkeypatch.setattr(turn_signal.gui_app, "texture", fake_texture)
  widget = turn_signal.TurnSignalWidget(IconSide.left)

  assert widget._signal_texture.width == 240
  assert widget._signal_texture.height == 218
  assert widget._blind_spot_texture.width == 240
  assert widget._blind_spot_texture.height == 218
  assert turn_signal.TurnSignalConfig().size == 300
  assert texture_loads == [
    ("icons_mici/onroad/turn_signal_left.png", 240, 218, False),
    ("icons_mici/onroad/blind_spot_left.png", 240, 218, False),
  ]
