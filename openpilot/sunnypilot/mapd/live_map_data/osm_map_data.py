"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import json
import math
import os
import platform
from pathlib import Path
from time import monotonic

from openpilot.cereal import log
from openpilot.common.hardware.hw import Paths
from openpilot.common.params import Params
from openpilot.sunnypilot.mapd.live_map_data.base_map_data import BaseMapData
from openpilot.sunnypilot.navd.helpers import Coordinate

MAPD_OUTPUT_STALE_SECONDS = 4.0


class OsmMapData(BaseMapData):
  def __init__(self):
    super().__init__()
    self.mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else self.params
    self._last_road_output_mtime_ns: int | None = None
    self._last_road_output_change = monotonic()

  def update_location(self) -> None:
    location = self.sm['liveLocationKalman']
    self.localizer_valid = (location.status == log.LiveLocationKalman.Status.valid) and location.positionGeodetic.valid

    if self.localizer_valid:
      self.last_bearing = math.degrees(location.calibratedOrientationNED.value[2])
      self.last_position = Coordinate(location.positionGeodetic.value[0], location.positionGeodetic.value[1])

    if self.last_position is None:
      return

    params = {
      "latitude": self.last_position.latitude,
      "longitude": self.last_position.longitude,
    }

    if self.last_bearing is not None:
      params['bearing'] = self.last_bearing

    self.mem_params.put("LastGPSPosition", json.dumps(params), block=True)

  def get_current_speed_limit(self) -> float:
    return float(self.mem_params.get("MapSpeedLimit") or 0.0)

  def get_current_road_name(self) -> str:
    return str(self.mem_params.get("RoadName") or "")

  def get_health(self) -> str:
    """Return a coordinate-free diagnostic for the onroad road-name display."""
    if not self.localizer_valid or self.last_position is None:
      return "waiting_gps"

    if not self._current_map_tile_exists():
      return "tile_missing"

    road_name_path = Path(self.mem_params.get_param_path("RoadName"))
    try:
      output_mtime_ns = road_name_path.stat().st_mtime_ns
      if output_mtime_ns != self._last_road_output_mtime_ns:
        self._last_road_output_mtime_ns = output_mtime_ns
        self._last_road_output_change = monotonic()
      elif monotonic() - self._last_road_output_change > MAPD_OUTPUT_STALE_SECONDS:
        return "daemon_stale"
    except OSError:
      return "daemon_stale"

    return "ok" if self.get_current_road_name() else "output_empty"

  def _current_map_tile_exists(self) -> bool:
    if self.last_position is None:
      return False

    area_min_lat = math.floor(self.last_position.latitude * 4) / 4
    area_min_lon = math.floor(self.last_position.longitude * 4) / 4
    group_lat = math.floor(area_min_lat / 2) * 2
    group_lon = math.floor(area_min_lon / 2) * 2
    tile = Path(Paths.mapd_root()) / "offline" / str(group_lat) / str(group_lon) / (
      f"{area_min_lat:.6f}_{area_min_lon:.6f}_{area_min_lat + 0.25:.6f}_{area_min_lon + 0.25:.6f}"
    )
    try:
      return tile.is_file() and os.path.getsize(tile) > 0
    except OSError:
      return False

  def tick(self) -> None:
    super().tick()
    self.mem_params.put("MapdHealth", self.get_health())

  def get_next_speed_limit_and_distance(self) -> tuple[float, float]:
    next_speed_limit_section_str = self.mem_params.get("NextMapSpeedLimit")
    next_speed_limit_section = next_speed_limit_section_str if next_speed_limit_section_str else {}
    next_speed_limit = next_speed_limit_section.get('speedlimit', 0.0)
    next_speed_limit_latitude = next_speed_limit_section.get('latitude')
    next_speed_limit_longitude = next_speed_limit_section.get('longitude')
    next_speed_limit_distance = 0.0

    if next_speed_limit_latitude and next_speed_limit_longitude:
      next_speed_limit_coordinates = Coordinate(next_speed_limit_latitude, next_speed_limit_longitude)
      next_speed_limit_distance = (self.last_position or Coordinate(0, 0)).distance_to(next_speed_limit_coordinates)

    return next_speed_limit, next_speed_limit_distance
