"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import platform

import pyray as rl

from openpilot.common.branding import fork_signature
from openpilot.common.params import Params
from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.onroad.driver_state import BTN_SIZE
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.sunnypilot.lib.theme import theme
from openpilot.system.ui.widgets import Widget


class RoadNameRenderer(Widget):
  MAP_HEALTH_TEXT = {
    "starting": "MAP STARTING",
    "waiting_gps": "GPS ACQUIRING",
    "tile_missing": "MAP TILE MISSING",
    "daemon_stale": "MAP SERVICE WAITING",
    "output_empty": "ROAD DATA EMPTY",
  }

  def __init__(self):
    super().__init__()
    self.road_name = ""
    self.is_metric = False
    self.font_demi = gui_app.font(FontWeight.SEMI_BOLD)
    self.font_medium = gui_app.font(FontWeight.MEDIUM)
    self.mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else Params()
    self.mapd_health = "starting"

  def update(self):
    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      return

    self.is_metric = ui_state.is_metric

    if sm.updated["liveMapDataSP"]:
      lmd = sm["liveMapDataSP"]
      self.road_name = lmd.roadName
      self.mapd_health = str(self.mem_params.get("MapdHealth") or "starting")

  def _render(self, rect: rl.Rectangle):
    bar_width = min(theme.STATUS_BAR_WIDTH, rect.width - 80)
    bar = rl.Rectangle(
      rect.x + (rect.width - bar_width) / 2,
      rect.y + rect.height - theme.STATUS_BAR_HEIGHT - theme.STATUS_BAR_BOTTOM,
      bar_width,
      theme.STATUS_BAR_HEIGHT,
    )
    rl.draw_rectangle_rounded(bar, 0.22, 10, theme.GRAPHITE_TRANSLUCENT)
    rl.draw_rectangle_rounded_lines_ex(bar, 0.22, 10, 2, theme.HAIRLINE)

    road_label = "ROAD"
    has_road_name = self.road_name and self.road_name != "?" and ui_state.road_name_toggle
    if has_road_name:
      road_value = self.road_name
    elif ui_state.road_name_toggle:
      road_value = self.MAP_HEALTH_TEXT.get(self.mapd_health, "--")
    else:
      road_value = "--"
    status_label = "STATUS"
    status_value = theme.status_text(ui_state.status)

    road_label_x = bar.x + 120
    road_value_x = bar.x + 310
    status_label_x = bar.x + bar.width * 0.60
    status_value_x = bar.x + bar.width * 0.77
    center_y = bar.y + bar.height / 2

    self._draw_centered_y(road_label, road_label_x, center_y, 30, self.font_medium, theme.MUTED)
    self._draw_centered_y(self._truncate(road_value, 420), road_value_x, center_y, 42, self.font_demi, theme.WHITE)
    self._draw_centered_y(status_label, status_label_x, center_y, 30, self.font_medium, theme.MUTED)
    self._draw_centered_y(status_value, status_value_x, center_y, 42, self.font_demi, theme.status_color(ui_state.status))

    divider_y = bar.y + 17
    rl.draw_line_ex(rl.Vector2(bar.x + bar.width * 0.54, divider_y),
                    rl.Vector2(bar.x + bar.width * 0.54, bar.y + bar.height - 17), 2, theme.HAIRLINE)

    if ui_state.sm["selfdriveState"].alertSize == 0:
      signature = fork_signature()
      signature_font_size = 30
      signature_size = measure_text_cached(self.font_medium, signature, signature_font_size)
      is_rhd = ui_state.sm["driverMonitoringState"].isRHD
      bottom_offset = theme.ROAD_BORDER_FADE_WIDTH + 16 if is_rhd else UI_BORDER_SIZE + BTN_SIZE + 28
      signature_pos = rl.Vector2(rect.x + theme.ROAD_BORDER_FADE_WIDTH + 16,
                                 rect.y + rect.height - signature_size.y - bottom_offset)
      signature_color = rl.Color(theme.WHITE.r, theme.WHITE.g, theme.WHITE.b, 0xA0)
      rl.draw_text_ex(self.font_medium, signature, signature_pos, signature_font_size, 0, signature_color)

  def _draw_centered_y(self, text, x, center_y, size, font, color):
    text_size = measure_text_cached(font, text, size)
    rl.draw_text_ex(font, text, rl.Vector2(x, center_y - text_size.y / 2), size, 0, color)

  def _truncate(self, text: str, max_width: float) -> str:
    candidate = text
    while len(candidate) > 3 and measure_text_cached(self.font_demi, candidate, 42).x > max_width:
      candidate = candidate[:-1]
    return f"{candidate}..." if candidate != text else candidate
