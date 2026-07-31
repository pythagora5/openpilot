from types import SimpleNamespace

from openpilot.system.ui import spinner


def _base_texture(asset_path: str, width: int, height: int, **kwargs):
  return SimpleNamespace(id=1, width=width, height=height)


def test_missing_brand_texture_keeps_spinner_available(monkeypatch, capsys):
  def missing_brand_texture(asset_path: str, width: int, height: int, **kwargs):
    if asset_path.endswith("spinner_lyle_pilot.png"):
      raise ValueError("missing test wordmark")
    return _base_texture(asset_path, width, height, **kwargs)

  monkeypatch.setattr(spinner.gui_app, "texture", missing_brand_texture)

  build_spinner = spinner.Spinner()

  assert build_spinner._brand_texture is None
  assert "Lyle Pilot wordmark disabled" in capsys.readouterr().err


def test_version_mismatch_skips_brand_texture(monkeypatch, capsys):
  loaded_assets: list[str] = []

  def record_texture(asset_path: str, width: int, height: int, **kwargs):
    loaded_assets.append(asset_path)
    return _base_texture(asset_path, width, height, **kwargs)

  monkeypatch.setattr(spinner.gui_app, "texture", record_texture)
  monkeypatch.setattr(spinner, "fork_version_label", lambda: "v9.9.9")

  build_spinner = spinner.Spinner()

  assert build_spinner._brand_texture is None
  assert not any(path.endswith("spinner_lyle_pilot.png") for path in loaded_assets)
  assert "does not match v9.9.9" in capsys.readouterr().err
