"""Shared visual tokens for the minimal automotive sunnypilot theme."""

import pyray as rl


class MinimalTheme:
  # Core palette
  INK = rl.Color(0x0B, 0x0D, 0x10, 0xFF)
  GRAPHITE = rl.Color(0x15, 0x19, 0x1E, 0xF0)
  GRAPHITE_TRANSLUCENT = rl.Color(0x0B, 0x0D, 0x10, 0xD9)
  SURFACE = rl.Color(0x1C, 0x21, 0x27, 0xF2)
  SURFACE_PRESSED = rl.Color(0x25, 0x2B, 0x33, 0xF2)

  WHITE = rl.Color(0xF4, 0xF6, 0xF8, 0xFF)
  WHITE_SOFT = rl.Color(0xF4, 0xF6, 0xF8, 0xC8)
  MUTED = rl.Color(0x8E, 0x96, 0x9F, 0xFF)
  MUTED_DIM = rl.Color(0x8E, 0x96, 0x9F, 0x70)
  HAIRLINE = rl.Color(0xF4, 0xF6, 0xF8, 0x32)

  ACCENT = rl.Color(0x3B, 0x82, 0xF6, 0xFF)
  ACCENT_SOFT = rl.Color(0x8C, 0xC8, 0xFF, 0xFF)
  ACCENT_DIM = rl.Color(0x3B, 0x82, 0xF6, 0x66)
  ACCENT_GHOST = rl.Color(0x3B, 0x82, 0xF6, 0x22)

  AMBER = rl.Color(0xF5, 0xA5, 0x24, 0xFF)
  CRITICAL = rl.Color(0xC9, 0x22, 0x31, 0xFF)

  # Big UI / Comma 3X geometry
  # (inset, width, alpha), ordered from the bezel towards the camera image.
  # The one-pixel overlap prevents seams between the translucent bands.
  ROAD_BORDER_FADE_BANDS = tuple(
    (inset, 3, round(0xF2 * ((64 - inset) / 64) ** 1.35))
    for inset in range(0, 64, 2)
  )
  ROAD_BORDER_FADE_WIDTH = max(inset + width for inset, width, _ in ROAD_BORDER_FADE_BANDS)
  ROAD_BORDER_CORNER_RADIUS = 40
  ROAD_VIEW_INSET = 18
  ROAD_BORDER_WIDTH = 3
  PANEL_RADIUS = 0.22

  # HUD geometry
  SET_SPEED_WIDTH_METRIC = 174
  SET_SPEED_WIDTH_IMPERIAL = 160
  SET_SPEED_HEIGHT = 184
  SET_SPEED_Y = 38
  HUD_CLUSTER_RIGHT_MARGIN = 42
  HUD_CLUSTER_GAP = 42
  STATUS_BAR_WIDTH = 1420
  STATUS_BAR_HEIGHT = 82
  STATUS_BAR_BOTTOM = 30

  STATUS_TEXT = {
    "disengaged": "AVAILABLE",
    "engaged": "ENGAGED",
    "override": "OVERRIDE",
    "lat_only": "LATERAL",
    "long_only": "CRUISE",
  }

  STATUS_COLORS = {
    "disengaged": MUTED,
    "engaged": ACCENT,
    "override": AMBER,
    "lat_only": ACCENT_SOFT,
    "long_only": ACCENT,
  }

  @classmethod
  def status_text(cls, status) -> str:
    return cls.STATUS_TEXT.get(status.value, status.value.upper())

  @classmethod
  def status_color(cls, status) -> rl.Color:
    return cls.STATUS_COLORS.get(status.value, cls.MUTED)

  @classmethod
  def hud_cluster_x(cls, rect: rl.Rectangle, set_speed_width: float, speed_limit_width: float,
                    speed_limit_visual_width: float) -> tuple[float, float]:
    """Return MAX and speed-limit x positions for the top-right HUD cluster."""
    speed_limit_overflow = max(0.0, (speed_limit_visual_width - speed_limit_width) / 2)
    speed_limit_x = rect.x + rect.width - cls.HUD_CLUSTER_RIGHT_MARGIN - speed_limit_width - speed_limit_overflow
    set_speed_x = speed_limit_x - cls.HUD_CLUSTER_GAP - set_speed_width
    return set_speed_x, speed_limit_x


theme = MinimalTheme
