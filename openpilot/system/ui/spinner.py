#!/usr/bin/env python3
import pyray as rl
import select
import sys

from openpilot.common.branding import FORK_MODE, FORK_NAME, fork_version_label
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.text import wrap_text
from openpilot.system.ui.widgets import Widget

# Constants
if gui_app.big_ui():
  PROGRESS_BAR_WIDTH = 1000
  PROGRESS_BAR_HEIGHT = 20
  TEXTURE_SIZE = 360
  WRAPPED_SPACING = 50
  CENTERED_SPACING = 150
  BRAND_NAME_SIZE = 92
  BRAND_MODE_SIZE = 48
  BRAND_VERSION_SIZE = 36
  BRAND_TOP_GAP = 275
  BRAND_MODE_OFFSET = 120
  BRAND_VERSION_OFFSET = 70
else:
  PROGRESS_BAR_WIDTH = 268
  PROGRESS_BAR_HEIGHT = 10
  TEXTURE_SIZE = 140
  WRAPPED_SPACING = 10
  CENTERED_SPACING = 20
  BRAND_NAME_SIZE = 30
  BRAND_MODE_SIZE = 18
  BRAND_VERSION_SIZE = 15
  BRAND_TOP_GAP = 80
  BRAND_MODE_OFFSET = 42
  BRAND_VERSION_OFFSET = 26
DEGREES_PER_SECOND = 360.0  # one full rotation per second
MARGIN_H = 100
FONT_SIZE = 96
LINE_HEIGHT = 104
DARKGRAY = (55, 55, 55, 255)


def clamp(value, min_value, max_value):
  return max(min(value, max_value), min_value)


class Spinner(Widget):
  def __init__(self):
    super().__init__()
    self._comma_texture = gui_app.texture("../../sunnypilot/selfdrive/assets/images/spinner_sunnypilot.png", TEXTURE_SIZE, TEXTURE_SIZE)
    self._spinner_texture = gui_app.texture("images/spinner_track.png", TEXTURE_SIZE, TEXTURE_SIZE, alpha_premultiply=True)
    # The build spinner starts before the rest of openpilot is built. Keep all
    # branding on the same early-safe font atlas as the stock spinner text.
    self._brand_font = gui_app.font()
    self._rotation = 0.0
    self._progress: int | None = None
    self._wrapped_lines: list[str] = []

  def set_text(self, text: str) -> None:
    if text.isdigit():
      self._progress = clamp(int(text), 0, 100)
      self._wrapped_lines = []
    else:
      self._progress = None
      self._wrapped_lines = wrap_text(text, FONT_SIZE, gui_app.width - MARGIN_H)

  def _render(self, rect: rl.Rectangle):
    if self._wrapped_lines:
      # Calculate total height required for spinner and text
      spacing = WRAPPED_SPACING
      total_height = TEXTURE_SIZE + spacing + len(self._wrapped_lines) * LINE_HEIGHT
      center_y = (rect.height - total_height) / 2.0 + TEXTURE_SIZE / 2.0
    else:
      # Center spinner vertically
      spacing = CENTERED_SPACING
      center_y = rect.height / 2.0
    y_pos = center_y + TEXTURE_SIZE / 2.0 + spacing

    center = rl.Vector2(rect.width / 2.0, center_y)
    spinner_origin = rl.Vector2(TEXTURE_SIZE / 2.0, TEXTURE_SIZE / 2.0)
    comma_position = rl.Vector2(center.x - TEXTURE_SIZE / 2.0, center.y - TEXTURE_SIZE / 2.0)

    delta_time = rl.get_frame_time()
    self._rotation = (self._rotation + DEGREES_PER_SECOND * delta_time) % 360.0

    # Draw rotating spinner and static comma logo
    rl.draw_texture_pro(self._spinner_texture, rl.Rectangle(0, 0, TEXTURE_SIZE, TEXTURE_SIZE),
                        rl.Rectangle(center.x, center.y, TEXTURE_SIZE, TEXTURE_SIZE),
                        spinner_origin, self._rotation, rl.WHITE)
    rl.draw_texture_v(self._comma_texture, comma_position, rl.WHITE)
    if not self._wrapped_lines:
      self._draw_branding(center)

    # Display the progress bar or text based on user input
    if self._progress is not None:
      bar = rl.Rectangle(center.x - PROGRESS_BAR_WIDTH / 2.0, y_pos, PROGRESS_BAR_WIDTH, PROGRESS_BAR_HEIGHT)
      rl.draw_rectangle_rounded(bar, 1, 10, DARKGRAY)

      bar.width *= self._progress / 100.0
      rl.draw_rectangle_rounded(bar, 1, 10, rl.WHITE)
    elif self._wrapped_lines:
      for i, line in enumerate(self._wrapped_lines):
        text_size = measure_text_cached(gui_app.font(), line, FONT_SIZE)
        rl.draw_text_ex(gui_app.font(), line, rl.Vector2(center.x - text_size.x / 2, y_pos + i * LINE_HEIGHT),
                        FONT_SIZE, 0.0, rl.WHITE)

  def _draw_branding(self, center: rl.Vector2) -> None:
    name_size = measure_text_cached(self._brand_font, FORK_NAME, BRAND_NAME_SIZE)
    name_y = center.y - TEXTURE_SIZE / 2 - BRAND_TOP_GAP
    rl.draw_text_ex(self._brand_font, FORK_NAME, rl.Vector2(center.x - name_size.x / 2, name_y),
                    BRAND_NAME_SIZE, 0.0, rl.WHITE)

    mode_size = measure_text_cached(self._brand_font, FORK_MODE, BRAND_MODE_SIZE)
    # BMFont text height can report as zero on the early Comma build screen.
    # Use fixed, device-scaled baselines so the three lines cannot overlap.
    mode_y = name_y + BRAND_MODE_OFFSET
    rl.draw_text_ex(self._brand_font, FORK_MODE, rl.Vector2(center.x - mode_size.x / 2, mode_y),
                    BRAND_MODE_SIZE, 0.0, rl.Color(0x8E, 0x96, 0x9F, 0xFF))

    version = fork_version_label()
    version_size = measure_text_cached(self._brand_font, version, BRAND_VERSION_SIZE)
    version_y = mode_y + BRAND_VERSION_OFFSET
    rl.draw_text_ex(self._brand_font, version, rl.Vector2(center.x - version_size.x / 2, version_y),
                    BRAND_VERSION_SIZE, 0.0, rl.Color(0x8E, 0x96, 0x9F, 0xB0))


def _read_stdin():
  """Non-blocking read of available lines from stdin."""
  lines = []
  while True:
    rlist, _, _ = select.select([sys.stdin], [], [], 0.0)
    if not rlist:
      break
    line = sys.stdin.readline().strip()
    if line == "":
      break
    lines.append(line)
  return lines


def main():
  gui_app.init_window("Spinner")
  spinner = Spinner()
  for _ in gui_app.render():
    text_list = _read_stdin()
    if text_list:
      spinner.set_text(text_list[-1])

    spinner.render(rl.Rectangle(0, 0, gui_app.width, gui_app.height))


if __name__ == "__main__":
  main()
