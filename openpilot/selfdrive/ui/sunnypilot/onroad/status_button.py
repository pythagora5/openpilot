import time

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.sunnypilot.lib.theme import theme
from openpilot.system.ui.widgets import Widget


class MinimalStatusButton(Widget):
  """Experimental-mode control styled as a restrained autonomy status ring."""

  def __init__(self, button_size: int, icon_size: int):
    super().__init__()
    self._params = Params()
    self._experimental_mode = False
    self._engageable = False
    self._hold_duration = 2.0
    self._held_mode: bool | None = None
    self._hold_end_time: float | None = None
    self._wheel = gui_app.texture("icons/chffr_wheel.png", icon_size, icon_size)
    self._experimental = gui_app.texture("icons/experimental.png", icon_size, icon_size)
    self._rect = rl.Rectangle(0, 0, button_size, button_size)

  def _update_state(self) -> None:
    selfdrive_state = ui_state.sm["selfdriveState"]
    self._experimental_mode = selfdrive_state.experimentalMode
    self._engageable = selfdrive_state.engageable or selfdrive_state.enabled

  def _handle_mouse_release(self, _):
    super()._handle_mouse_release(_)
    if self._is_toggle_allowed():
      new_mode = not self._experimental_mode
      self._params.put_bool("ExperimentalMode", new_mode)
      self._held_mode = new_mode
      self._hold_end_time = time.monotonic() + self._hold_duration

  def _render(self, rect: rl.Rectangle) -> None:
    center = rl.Vector2(rect.x + rect.width / 2, rect.y + rect.height / 2)
    radius = rect.width / 2
    status_color = theme.status_color(ui_state.status)

    rl.draw_circle_v(center, radius, theme.GRAPHITE_TRANSLUCENT)
    rl.draw_ring(center, radius - 9, radius - 3, -90, 270, 80, theme.HAIRLINE)

    if self._engageable:
      arc_end = 270 if ui_state.status.value != "disengaged" else 70
      rl.draw_ring(center, radius - 9, radius - 3, -90, arc_end, 80, status_color)

    texture = self._experimental if self._held_or_actual_mode() else self._wheel
    alpha = 170 if self.is_pressed or not self._engageable else 230
    icon_color = rl.Color(theme.WHITE.r, theme.WHITE.g, theme.WHITE.b, alpha)
    rl.draw_texture_ex(texture, rl.Vector2(center.x - texture.width / 2, center.y - texture.height / 2), 0.0, 1.0, icon_color)

  def _held_or_actual_mode(self):
    now = time.monotonic()
    if self._hold_end_time and now < self._hold_end_time:
      return self._held_mode
    if self._hold_end_time and now >= self._hold_end_time:
      self._hold_end_time = self._held_mode = None
    return self._experimental_mode

  def _is_toggle_allowed(self):
    return self._params.get_bool("ExperimentalModeConfirmed") and ui_state.has_longitudinal_control
