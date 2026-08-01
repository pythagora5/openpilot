from pathlib import Path

from openpilot.common.hardware.hw import Paths
from openpilot.sunnypilot.mapd.live_map_data import osm_map_data
from openpilot.sunnypilot.mapd.live_map_data.osm_map_data import MAPD_OUTPUT_STALE_SECONDS, OsmMapData
from openpilot.sunnypilot.navd.helpers import Coordinate
from openpilot.system.manager.process_config import managed_processes


class FakeMemParams:
  def __init__(self, root: Path, road_name: str = ""):
    self.root = root
    self.road_name = road_name

  def get_param_path(self, key: str) -> str:
    return str(self.root / key)

  def get(self, key: str):
    assert key == "RoadName"
    return self.road_name


def make_map_data(tmp_path: Path, monkeypatch, road_name: str = "") -> OsmMapData:
  monkeypatch.setattr(Paths, "mapd_root", staticmethod(lambda: str(tmp_path / "osm")))
  map_data = OsmMapData.__new__(OsmMapData)
  map_data.localizer_valid = True
  map_data.last_position = Coordinate(-41.2866, 174.7756)
  map_data.mem_params = FakeMemParams(tmp_path / "params", road_name)
  map_data._last_road_output_mtime_ns = None
  map_data._last_road_output_change = 0.0
  return map_data


def create_current_tile(map_data: OsmMapData, tmp_path: Path) -> None:
  tile = tmp_path / "osm/offline/-42/174/-41.500000_174.750000_-41.250000_175.000000"
  tile.parent.mkdir(parents=True)
  tile.write_bytes(b"map data")
  assert map_data._current_map_tile_exists()


def create_road_output(tmp_path: Path) -> Path:
  output = tmp_path / "params/RoadName"
  output.parent.mkdir(parents=True)
  output.write_text("")
  return output


def test_mapd_restarts_after_a_crash():
  assert managed_processes["mapd"].restart_if_crash


def test_map_health_waits_for_valid_gps(tmp_path, monkeypatch):
  map_data = make_map_data(tmp_path, monkeypatch)
  map_data.localizer_valid = False
  assert map_data.get_health() == "waiting_gps"


def test_map_health_reports_missing_current_tile(tmp_path, monkeypatch):
  map_data = make_map_data(tmp_path, monkeypatch)
  assert map_data.get_health() == "tile_missing"


def test_map_health_reports_stale_daemon_output(tmp_path, monkeypatch):
  map_data = make_map_data(tmp_path, monkeypatch)
  create_current_tile(map_data, tmp_path)
  create_road_output(tmp_path)
  monkeypatch.setattr(osm_map_data, "monotonic", lambda: 0.0)
  assert map_data.get_health() == "output_empty"
  monkeypatch.setattr(osm_map_data, "monotonic", lambda: MAPD_OUTPUT_STALE_SECONDS + 1)
  assert map_data.get_health() == "daemon_stale"


def test_map_health_distinguishes_empty_and_named_road(tmp_path, monkeypatch):
  map_data = make_map_data(tmp_path, monkeypatch)
  create_current_tile(map_data, tmp_path)
  create_road_output(tmp_path)
  assert map_data.get_health() == "output_empty"

  map_data.mem_params.road_name = "Aro Street"
  assert map_data.get_health() == "ok"
