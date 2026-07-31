from types import SimpleNamespace

import pyray as rl
import pytest

from openpilot.selfdrive.ui.onroad import alert_renderer, augmented_road_view
from openpilot.selfdrive.ui.mici.onroad.alert_renderer import ALERT_STARTUP_PENDING as ALERT_STARTUP_PENDING_MICI
from openpilot.selfdrive.ui.sunnypilot.onroad import road_name
from openpilot.selfdrive.ui.ui_state import UIStatus
from openpilot.system.ui.sunnypilot.lib.theme import theme


def test_startup_pending_alert_uses_fork_name():
  for alert in (alert_renderer.ALERT_STARTUP_PENDING, ALERT_STARTUP_PENDING_MICI):
    assert alert.text1 == "Lyle Pilot Unavailable"
    assert alert.text2 == "Waiting to start"
    assert alert.size == alert_renderer.AlertSize.mid
    assert alert.status == alert_renderer.AlertStatus.normal


@pytest.mark.parametrize(("localized", "expected"), [
  ("SUNNYPILOT indisponible", "Lyle Pilot indisponible"),
  ("Service indisponible", "Lyle Pilot Unavailable"),
])
def test_startup_pending_brand_localization_fallback(localized, expected):
  assert alert_renderer._brand_startup_unavailable(localized) == expected


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
  assert alert.text1 == "Lyle Pilot Unavailable"


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


@pytest.mark.parametrize("status", [UIStatus.ENGAGED, UIStatus.LAT_ONLY])
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
    for width, alpha in theme.ROAD_BORDER_LAYERS
  ]
  max_layer_width = max(width for width, _ in theme.ROAD_BORDER_LAYERS)
  assert theme.ROAD_VIEW_INSET / 2 >= max_layer_width / 2


def test_non_lateral_border_remains_thin(monkeypatch):
  strokes = []
  monkeypatch.setattr(augmented_road_view.gui_app, "sunnypilot_ui", lambda: True)
  monkeypatch.setattr(augmented_road_view, "ui_state", SimpleNamespace(status=UIStatus.LONG_ONLY))
  monkeypatch.setattr(augmented_road_view.rl, "draw_rectangle_lines_ex", lambda *args: None)
  monkeypatch.setattr(augmented_road_view.rl, "draw_rectangle_rounded_lines_ex",
                      lambda rect, roundness, segments, width, color: strokes.append((width, color.a)))

  augmented_road_view.AugmentedRoadView._draw_border(object(), rl.Rectangle(0, 0, 2160, 1080))

  assert strokes == [(theme.ROAD_BORDER_WIDTH, 0xFF)]


def test_override_border_remains_thin_and_amber(monkeypatch):
  strokes = []
  monkeypatch.setattr(augmented_road_view.gui_app, "sunnypilot_ui", lambda: True)
  monkeypatch.setattr(augmented_road_view, "ui_state", SimpleNamespace(status=UIStatus.OVERRIDE))
  monkeypatch.setattr(augmented_road_view.rl, "draw_rectangle_lines_ex", lambda *args: None)
  monkeypatch.setattr(augmented_road_view.rl, "draw_rectangle_rounded_lines_ex",
                      lambda rect, roundness, segments, width, color: strokes.append((width, color)))

  augmented_road_view.AugmentedRoadView._draw_border(object(), rl.Rectangle(0, 0, 2160, 1080))

  assert len(strokes) == 1
  assert strokes[0][0] == theme.ROAD_BORDER_WIDTH
  color = strokes[0][1]
  assert (color.r, color.g, color.b, color.a) == (theme.AMBER.r, theme.AMBER.g, theme.AMBER.b, theme.AMBER.a)


def test_signature_is_anchored_to_bottom_left(monkeypatch):
  text_draws = []
  renderer = road_name.RoadNameRenderer.__new__(road_name.RoadNameRenderer)
  renderer.road_name = "Test Road"
  renderer.font_demi = object()
  renderer.font_medium = object()

  fake_ui_state = SimpleNamespace(
    road_name_toggle=True,
    status=UIStatus.ENGAGED,
    sm={
      "selfdriveState": SimpleNamespace(alertSize=0),
      "driverMonitoringState": SimpleNamespace(isRHD=True),
    },
  )
  monkeypatch.setattr(road_name, "ui_state", fake_ui_state)
  monkeypatch.setattr(road_name, "measure_text_cached", lambda font, text, size: rl.Vector2(100, 24))
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded_lines_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_line_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_text_ex",
                      lambda font, text, pos, size, spacing, color: text_draws.append((text, pos)))

  rect = rl.Rectangle(18, 18, 2124, 1044)
  renderer._render(rect)

  signature, position = text_draws[-1]
  assert signature == "Lyle Pilot  v0.1.0"
  assert position.x == rect.x + 28
  assert position.y == rect.y + rect.height - 24 - 28
  bar_width = min(theme.STATUS_BAR_WIDTH, rect.width - 80)
  bar_x = rect.x + (rect.width - bar_width) / 2
  assert position.x + 100 < bar_x


def test_signature_draws_without_road_name_and_clears_lhd_driver_icon(monkeypatch):
  text_draws = []
  renderer = road_name.RoadNameRenderer.__new__(road_name.RoadNameRenderer)
  renderer.road_name = ""
  renderer.font_demi = object()
  renderer.font_medium = object()

  fake_ui_state = SimpleNamespace(
    road_name_toggle=False,
    status=UIStatus.DISENGAGED,
    sm={
      "selfdriveState": SimpleNamespace(alertSize=0),
      "driverMonitoringState": SimpleNamespace(isRHD=False),
    },
  )
  monkeypatch.setattr(road_name, "ui_state", fake_ui_state)
  monkeypatch.setattr(road_name, "measure_text_cached", lambda font, text, size: rl.Vector2(100, 24))
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded_lines_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_line_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_text_ex",
                      lambda font, text, pos, size, spacing, color: text_draws.append((text, pos)))

  rect = rl.Rectangle(18, 18, 2124, 1044)
  renderer._render(rect)

  signature, position = text_draws[-1]
  assert signature == "Lyle Pilot  v0.1.0"
  assert position.x == rect.x + 28
  assert position.y + 24 <= rect.y + rect.height - road_name.UI_BORDER_SIZE - road_name.BTN_SIZE - 28
