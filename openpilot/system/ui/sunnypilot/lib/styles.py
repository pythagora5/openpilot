"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from dataclasses import dataclass

import pyray as rl

from openpilot.system.ui.sunnypilot.lib.theme import theme


@dataclass
class Base:
  # Widget/Control Base Dimensions
  ITEM_BASE_HEIGHT = 170
  ITEM_PADDING = 20
  ITEM_TEXT_FONT_SIZE = 50
  ITEM_DESC_FONT_SIZE = 40
  ITEM_DESC_V_OFFSET = 150
  ITEM_TEXT_VALUE_COLOR = rl.Color(170, 170, 170, 255)
  CLOSE_BTN_SIZE = 160

  TEXT_PADDING = 20

  # Toggle Control
  TOGGLE_HEIGHT = 120
  TOGGLE_WIDTH = int(TOGGLE_HEIGHT * 1.75)
  TOGGLE_BG_HEIGHT = TOGGLE_HEIGHT - 20

  # Button Control
  BUTTON_ACTION_WIDTH = 300
  BUTTON_HEIGHT = 120

  # Simple Button Control
  SIMPLE_BUTTON_WIDTH = 800
  SIMPLE_BUTTON_HEIGHT = 150


@dataclass
class DefaultStyleSP(Base):
  # Base Colors
  BASE_BG_COLOR = theme.SURFACE
  ON_BG_COLOR = theme.ACCENT
  OFF_BG_COLOR = BASE_BG_COLOR
  ON_HOVER_BG_COLOR = rl.Color(0x2F, 0x6E, 0xD2, 0xFF)
  OFF_HOVER_BG_COLOR = theme.SURFACE_PRESSED
  DISABLED_ON_BG_COLOR = rl.Color(0x24, 0x47, 0x79, 0xFF)
  DISABLED_OFF_BG_COLOR = theme.INK
  ITEM_TEXT_COLOR = theme.WHITE
  ITEM_DISABLED_TEXT_COLOR = theme.MUTED_DIM
  ITEM_DESC_TEXT_COLOR = theme.MUTED

  # Toggle Control
  TOGGLE_ON_COLOR = ON_BG_COLOR
  TOGGLE_OFF_COLOR = OFF_BG_COLOR
  TOGGLE_KNOB_COLOR = theme.WHITE
  TOGGLE_DISABLED_ON_COLOR = DISABLED_ON_BG_COLOR
  TOGGLE_DISABLED_OFF_COLOR = DISABLED_OFF_BG_COLOR
  TOGGLE_DISABLED_KNOB_COLOR = rl.Color(88, 88, 88, 255)  # Lighter Grey

  # Multi Button Control
  MBC_TRANSPARENT = rl.Color(255, 255, 255, 0)
  MBC_BG_CHECKED_ENABLED = theme.ACCENT
  MBC_DISABLED = rl.Color(0xFF, 0xFF, 0xFF, 0x33)

  # Option Control
  OPTION_CONTROL_CONTAINER_BG = theme.GRAPHITE
  OPTION_CONTROL_BTN_ENABLED = theme.SURFACE
  OPTION_CONTROL_BTN_PRESSED = theme.SURFACE_PRESSED
  OPTION_CONTROL_BTN_DISABLED = DISABLED_OFF_BG_COLOR
  OPTION_CONTROL_TEXT_ENABLED = theme.WHITE
  OPTION_CONTROL_TEXT_PRESSED = theme.WHITE
  OPTION_CONTROL_TEXT_DISABLED = ITEM_DISABLED_TEXT_COLOR

  # Tree Button Colors
  BUTTON_PRIMARY_COLOR = theme.ACCENT
  BUTTON_NEUTRAL_GRAY = theme.SURFACE
  BUTTON_DISABLED_BG_COLOR = theme.INK
  TREE_DIALOG_TRANSPARENT = rl.Color(0, 0, 0, 0)
  TREE_DIALOG_SEARCH_BUTTON_PRESSED = rl.Color(0x69, 0x68, 0x68, 0xFF)
  TREE_DIALOG_SEARCH_BUTTON_BORDER = rl.Color(150, 150, 150, 200)

  # Vehicle Description Colors
  GREEN = rl.Color(0, 241, 0, 255)
  BLUE = rl.Color(0, 134, 233, 255)
  YELLOW = rl.Color(255, 213, 0, 255)

  # Button Colors
  BUTTON_ENABLED_OFF = theme.SURFACE
  BUTTON_OFF_PRESSED = theme.SURFACE_PRESSED
  BUTTON_DISABLED = theme.INK
  BUTTON_TEXT_DISABLED = theme.MUTED_DIM


style = DefaultStyleSP
