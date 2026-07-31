from types import SimpleNamespace

import pyray as rl
import pytest

from openpilot.selfdrive.ui.onroad import augmented_road_view
from openpilot.selfdrive.ui.sunnypilot.onroad import road_name
from openpilot.selfdrive.ui.ui_state import UIStatus
from openpilot.system.ui.sunnypilot.lib.theme import theme


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
