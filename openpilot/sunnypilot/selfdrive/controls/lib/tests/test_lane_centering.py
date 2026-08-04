from types import SimpleNamespace

import numpy as np
import pytest

from openpilot.common.params import Params
from openpilot.sunnypilot.selfdrive.controls.lib.lane_centering import (
  MAX_CORRECTION,
  LaneCenteringController,
  LaneCenteringSettings,
  LaneCenteringState,
)


V_EGO = 20.0
XS = np.linspace(0.0, 50.0, 52)
ENABLED = LaneCenteringSettings(enabled=True, e2e_authority=0.0)


def _path(y, y_std=0.1):
  return SimpleNamespace(
    x=XS.copy(),
    y=np.full_like(XS, float(y)),
    yStd=np.full_like(XS, float(y_std)),
  )


def _model(left=-1.8, right=1.8, model_y=0.0, lane_prob=0.9, lane_std=0.1, path_std=0.1, lane_change=0):
  return SimpleNamespace(
    laneLines=[_path(0.0), _path(left), _path(right), _path(0.0)],
    laneLineProbs=[0.0, lane_prob, lane_prob, 0.0],
    laneLineStds=[0.0, lane_std, lane_std, 0.0],
    position=_path(model_y, path_std),
    meta=SimpleNamespace(laneChangeState=lane_change),
  )


def _update(controller, model, *, settings=ENABLED, active=True, valid=True, speed=V_EGO,
            turn_signal=False, force_pause=False):
  return controller.update(0.0, model, speed, settings, active, valid, turn_signal, force_pause)


def _converge(model, *, settings=ENABLED):
  controller = LaneCenteringController()
  result = _update(controller, model, settings=settings)
  for _ in range(300):
    result = _update(controller, model, settings=settings)
  return controller, result


def test_registered_settings_default_off(tmp_path):
  settings = LaneCenteringSettings.from_params(Params(str(tmp_path)))
  assert settings == LaneCenteringSettings(enabled=False, offset=0.0, e2e_authority=1.0, pause_on_signal=True)


class InvalidParams:
  values = {
    "LaneCentering": True,
    "LaneCenterOffset": 12.0,
    "LaneCenteringE2EAuthority": -4.0,
    "LaneCenteringPauseOnSignal": False,
  }

  def get(self, key, return_default=False):
    return self.values[key]


def test_settings_are_clipped_when_loaded():
  settings = LaneCenteringSettings.from_params(InvalidParams())  # type: ignore[arg-type]
  assert settings == LaneCenteringSettings(enabled=True, offset=0.3, e2e_authority=0.0, pause_on_signal=False)


@pytest.mark.parametrize(
  "settings,active,valid,speed,expected_state",
  [
    (LaneCenteringSettings(), True, True, V_EGO, LaneCenteringState.DISABLED),
    (ENABLED, False, True, V_EGO, LaneCenteringState.STANDBY_E2E),
    (ENABLED, True, False, V_EGO, LaneCenteringState.STANDBY_E2E),
    (ENABLED, True, True, 4.9, LaneCenteringState.STANDBY_E2E),
  ],
)
def test_hard_gates_are_noop(settings, active, valid, speed, expected_state):
  result = _update(LaneCenteringController(), _model(left=-1.5, right=2.1),
                   settings=settings, active=active, valid=valid, speed=speed)
  assert result.desired_curvature == 0.0
  assert result.correction == 0.0
  assert result.state == expected_state


def test_lane_change_is_paused_and_resets_immediately():
  controller, active = _converge(_model(left=-1.5, right=2.1))
  assert active.correction > 0.0
  paused = _update(controller, _model(left=-1.5, right=2.1, lane_change=1))
  assert paused.correction == 0.0
  assert paused.state == LaneCenteringState.PAUSED


def test_forced_pause_resets_immediately():
  controller, active = _converge(_model(left=-1.5, right=2.1))
  assert active.correction > 0.0
  paused = _update(controller, _model(left=-1.5, right=2.1), force_pause=True)
  assert paused.correction == 0.0
  assert paused.state == LaneCenteringState.PAUSED


def test_turn_signal_fades_correction_while_lateral_remains_active():
  controller, active = _converge(_model(left=-1.5, right=2.1))
  paused = _update(controller, _model(left=-1.5, right=2.1), turn_signal=True)
  assert 0.0 < paused.correction < active.correction
  assert paused.state == LaneCenteringState.PAUSED


@pytest.mark.parametrize(
  "field,value",
  [
    ("prob", np.nan),
    ("prob", 1.1),
    ("std", np.nan),
    ("std", -0.1),
  ],
)
def test_invalid_lane_confidence_is_rejected(field, value):
  model = _model(left=-1.5, right=2.1)
  values = model.laneLineProbs if field == "prob" else model.laneLineStds
  values[1] = value
  result = _update(LaneCenteringController(), model)
  assert result.correction == 0.0
  assert result.state == LaneCenteringState.STANDBY_E2E


def test_input_must_cover_lookahead():
  model = _model(left=-1.5, right=2.1)
  model.laneLines[1].x = model.laneLines[1].x[:10]
  model.laneLines[1].y = model.laneLines[1].y[:10]
  assert _update(LaneCenteringController(), model).correction == 0.0


def test_lane_center_error_steers_toward_center():
  _, right = _converge(_model(left=-1.5, right=2.1))
  _, left = _converge(_model(left=-2.1, right=1.5))
  assert right.correction > 0.0
  assert left.correction < 0.0


def test_offset_direction():
  _, right = _converge(_model(), settings=LaneCenteringSettings(enabled=True, offset=0.2, e2e_authority=0.0))
  _, left = _converge(_model(), settings=LaneCenteringSettings(enabled=True, offset=-0.2, e2e_authority=0.0))
  assert right.correction > 0.0
  assert left.correction < 0.0


def test_offset_is_reduced_in_narrow_lane():
  narrow = _model(left=-1.3, right=1.3)
  _, at_safe_limit = _converge(narrow, settings=LaneCenteringSettings(enabled=True, offset=0.2, e2e_authority=0.0))
  _, above_safe_limit = _converge(narrow, settings=LaneCenteringSettings(enabled=True, offset=0.3, e2e_authority=0.0))
  assert np.isclose(at_safe_limit.correction, above_safe_limit.correction)


def test_confident_e2e_path_can_fully_break_in():
  model = _model(left=-1.0, right=2.6, path_std=0.1)
  _, lane_authority = _converge(model, settings=LaneCenteringSettings(enabled=True, e2e_authority=0.0))
  _, e2e_authority = _converge(model, settings=LaneCenteringSettings(enabled=True, e2e_authority=1.0))
  assert lane_authority.correction > 0.0
  assert abs(e2e_authority.correction) < 1e-9
  assert e2e_authority.state == LaneCenteringState.STANDBY_E2E


def test_uncertain_e2e_path_does_not_break_in():
  model = _model(left=-1.0, right=2.6, path_std=0.6)
  _, result = _converge(model, settings=LaneCenteringSettings(enabled=True, e2e_authority=1.0))
  assert result.correction > 0.0


def test_confidence_loss_drops_filtered_correction():
  controller, active = _converge(_model(left=-1.5, right=2.1))
  assert active.correction > 0.0
  result = _update(controller, _model(left=-1.5, right=2.1, lane_prob=0.2))
  assert result.correction == 0.0
  assert result.state == LaneCenteringState.STANDBY_E2E


def test_correction_attack_is_smoothed_and_capped():
  controller = LaneCenteringController()
  model = _model(left=0.0, right=3.0, path_std=0.6)
  first = _update(controller, model)
  _, steady = _converge(model)
  assert 0.0 < first.correction < steady.correction
  assert np.isclose(steady.correction, MAX_CORRECTION, atol=1e-6)


def test_smaller_target_releases_immediately():
  controller, active = _converge(_model(left=-1.5, right=2.1))
  released = _update(controller, _model(left=-1.7, right=1.9))
  expected = 2.0 * 0.1 / V_EGO ** 2 * 0.30
  assert 0.0 < released.correction < active.correction
  assert np.isclose(released.correction, expected)


def test_sign_reversal_releases_immediately():
  controller, active = _converge(_model(left=-1.5, right=2.1))
  reversed_result = _update(controller, _model(left=-2.1, right=1.5))
  assert active.correction > 0.0
  assert reversed_result.correction < 0.0
  assert reversed_result.state == LaneCenteringState.ACTIVE_CENTERING
