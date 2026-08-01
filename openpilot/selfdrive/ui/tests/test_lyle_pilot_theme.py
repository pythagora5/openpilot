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
  monkeypatch.setattr(road_name, "measure_text_cached", lambda font, text, size: rl.Vector2(125, size))
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded_lines_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_line_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_text_ex",
                      lambda font, text, pos, size, spacing, color: text_draws.append((text, pos)))

  rect = rl.Rectangle(18, 18, 2124, 1044)
  renderer._render(rect)

  signature, position = text_draws[-1]
  assert signature == "Lyle Pilot  v0.1.0"
  assert position.x == rect.x + theme.ROAD_BORDER_FADE_WIDTH + 16
  assert position.y == rect.y + rect.height - 30 - theme.ROAD_BORDER_FADE_WIDTH - 16
  bar_width = min(theme.STATUS_BAR_WIDTH, rect.width - 80)
  bar_x = rect.x + (rect.width - bar_width) / 2
  assert position.x + 125 < bar_x


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
  monkeypatch.setattr(road_name, "measure_text_cached", lambda font, text, size: rl.Vector2(125, size))
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_rectangle_rounded_lines_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_line_ex", lambda *args: None)
  monkeypatch.setattr(road_name.rl, "draw_text_ex",
                      lambda font, text, pos, size, spacing, color: text_draws.append((text, pos)))

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
