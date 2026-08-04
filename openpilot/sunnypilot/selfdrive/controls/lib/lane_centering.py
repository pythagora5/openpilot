"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.
Copyright (c) 2026, StarPilot contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The confidence-gated lane-centering algorithm is adapted from StarPilot commit
9f1066ce8380a2602beaf5d43fdb38ee6ec2dcbe, including the turn-signal behavior
from commit 3aa1436ff4895e7ff00fd2fb9d5af49a86de2cc7.
"""
from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from openpilot.cereal import log
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import smooth_value


MIN_V_EGO = 5.0
MIN_LANE_PROB = 0.6
MAX_LANE_STD = 0.3
MIN_LANE_WIDTH = 2.6
MAX_LANE_WIDTH = 4.8
MAX_OFFSET = 0.3
MIN_CENTER_TO_LINE = 1.1
MAX_RAW_CORRECTION = 0.004
MAX_GAIN = 0.30
MAX_CORRECTION = MAX_RAW_CORRECTION * MAX_GAIN
ATTACK_TAU = 0.4
SIGNAL_RELEASE_TAU = 0.20

E2E_MAX_PATH_STD = 0.35
E2E_BREAK_IN_START = 0.25
E2E_BREAK_IN_FULL = 0.75

ACTIVE_CORRECTION_EPSILON = 1e-9


class LaneCenteringState(IntEnum):
  DISABLED = 0
  STANDBY_E2E = 1
  ACTIVE_CENTERING = 2
  PAUSED = 3


@dataclass(frozen=True)
class LaneCenteringSettings:
  enabled: bool = False
  offset: float = 0.0
  e2e_authority: float = 1.0
  pause_on_signal: bool = True

  @classmethod
  def from_params(cls, params: Params) -> "LaneCenteringSettings":
    return cls(
      enabled=cls._read_bool(params, "LaneCentering", False),
      offset=float(np.clip(cls._read_float(params, "LaneCenterOffset", 0.0), -MAX_OFFSET, MAX_OFFSET)),
      e2e_authority=float(np.clip(cls._read_float(params, "LaneCenteringE2EAuthority", 1.0), 0.0, 1.0)),
      pause_on_signal=cls._read_bool(params, "LaneCenteringPauseOnSignal", True),
    )

  @staticmethod
  def _read_bool(params: Params, key: str, default: bool) -> bool:
    try:
      value = params.get(key, return_default=True)
      return default if value is None else bool(value)
    except (TypeError, ValueError):
      return default

  @staticmethod
  def _read_float(params: Params, key: str, default: float) -> float:
    try:
      value = float(params.get(key, return_default=True))
      return value if np.isfinite(value) else default
    except (TypeError, ValueError):
      return default


@dataclass(frozen=True)
class LaneCenteringResult:
  desired_curvature: float
  correction: float
  state: LaneCenteringState


class LaneCenteringController:
  def __init__(self) -> None:
    self._correction = 0.0
    self._state = LaneCenteringState.DISABLED

  @property
  def correction(self) -> float:
    return self._correction

  @property
  def state(self) -> LaneCenteringState:
    return self._state

  def reset(self, state: LaneCenteringState = LaneCenteringState.DISABLED) -> None:
    self._correction = 0.0
    self._state = state

  def update(self, model_curvature, model_v2, v_ego, settings: LaneCenteringSettings, lat_active: bool,
             model_valid: bool, turn_signal_active: bool = False, force_pause: bool = False) -> LaneCenteringResult:
    try:
      model_curvature = float(model_curvature)
      v_ego = float(v_ego)
    except (TypeError, ValueError):
      self.reset(LaneCenteringState.STANDBY_E2E if settings.enabled else LaneCenteringState.DISABLED)
      return LaneCenteringResult(0.0, 0.0, self._state)

    if not settings.enabled:
      return self._reset_result(model_curvature, LaneCenteringState.DISABLED)

    if not np.isfinite([model_curvature, v_ego]).all():
      return self._reset_result(model_curvature, LaneCenteringState.STANDBY_E2E)

    if force_pause:
      return self._reset_result(model_curvature, LaneCenteringState.PAUSED)

    try:
      lane_change_active = model_v2.meta.laneChangeState != log.LaneChangeState.off
    except (AttributeError, TypeError, ValueError):
      return self._reset_result(model_curvature, LaneCenteringState.STANDBY_E2E)

    if lane_change_active:
      return self._reset_result(model_curvature, LaneCenteringState.PAUSED)

    if not model_valid or not lat_active or v_ego < MIN_V_EGO:
      return self._reset_result(model_curvature, LaneCenteringState.STANDBY_E2E)

    if settings.pause_on_signal and turn_signal_active:
      self._correction = float(smooth_value(0.0, self._correction, SIGNAL_RELEASE_TAU, dt=DT_CTRL))
      return self._result(model_curvature, LaneCenteringState.PAUSED)

    valid, raw_correction = self._raw_correction(model_v2, v_ego, settings.offset, settings.e2e_authority)
    if not valid:
      return self._reset_result(model_curvature, LaneCenteringState.STANDBY_E2E)

    target = float(np.clip(raw_correction, -MAX_RAW_CORRECTION, MAX_RAW_CORRECTION)) * MAX_GAIN
    self._update_correction(target)
    state = LaneCenteringState.ACTIVE_CENTERING if abs(self._correction) > ACTIVE_CORRECTION_EPSILON else LaneCenteringState.STANDBY_E2E
    return self._result(model_curvature, state)

  def _update_correction(self, target: float) -> None:
    same_direction = self._correction * target > 0.0
    increasing = abs(target) >= abs(self._correction)
    if self._correction == 0.0 or (same_direction and increasing):
      self._correction = float(smooth_value(target, self._correction, ATTACK_TAU, dt=DT_CTRL))
    else:
      # Release reductions and sign reversals immediately. The combined desired
      # curvature is still rate-limited by clip_curvature downstream.
      self._correction = target

  def _result(self, model_curvature: float, state: LaneCenteringState) -> LaneCenteringResult:
    self._state = state
    return LaneCenteringResult(model_curvature + self._correction, self._correction, state)

  def _reset_result(self, model_curvature: float, state: LaneCenteringState) -> LaneCenteringResult:
    self.reset(state)
    return LaneCenteringResult(model_curvature, 0.0, state)

  @staticmethod
  def _valid_path(x: np.ndarray, y: np.ndarray) -> bool:
    return x.size >= 2 and x.size == y.size and np.isfinite(x).all() and np.isfinite(y).all() and np.all(np.diff(x) > 0)

  @staticmethod
  def _covers(x: np.ndarray, distance: float) -> bool:
    return bool(x[0] <= distance <= x[-1])

  def _raw_correction(self, model_v2, v_ego: float, offset: float, e2e_authority: float) -> tuple[bool, float]:
    try:
      lane_lines = model_v2.laneLines
      probs = np.asarray(model_v2.laneLineProbs, dtype=float)
      stds = np.asarray(model_v2.laneLineStds, dtype=float)
      if len(lane_lines) < 3 or probs.size < 3 or stds.size < 3:
        return False, 0.0
      if not np.isfinite(probs[[1, 2]]).all() or not np.isfinite(stds[[1, 2]]).all():
        return False, 0.0
      if np.any(probs[[1, 2]] < MIN_LANE_PROB) or np.any(probs[[1, 2]] > 1.0):
        return False, 0.0
      if np.any(stds[[1, 2]] < 0.0) or np.any(stds[[1, 2]] > MAX_LANE_STD):
        return False, 0.0

      left_x = np.asarray(lane_lines[1].x, dtype=float)
      left_y = np.asarray(lane_lines[1].y, dtype=float)
      right_x = np.asarray(lane_lines[2].x, dtype=float)
      right_y = np.asarray(lane_lines[2].y, dtype=float)
      pos_x = np.asarray(model_v2.position.x, dtype=float)
      pos_y = np.asarray(model_v2.position.y, dtype=float)
      if not (self._valid_path(left_x, left_y) and self._valid_path(right_x, right_y) and self._valid_path(pos_x, pos_y)):
        return False, 0.0

      lookahead = float(np.clip(v_ego, 8.0, 35.0))
      if not all(self._covers(x, lookahead) for x in (left_x, right_x, pos_x)):
        return False, 0.0

      left = float(np.interp(lookahead, left_x, left_y))
      right = float(np.interp(lookahead, right_x, right_y))
      width = right - left
      if not MIN_LANE_WIDTH <= width <= MAX_LANE_WIDTH:
        return False, 0.0

      max_safe_offset = min(MAX_OFFSET, max(0.0, width * 0.5 - MIN_CENTER_TO_LINE))
      target_y = 0.5 * (left + right) + float(np.clip(offset, -max_safe_offset, max_safe_offset))
      model_y = float(np.interp(lookahead, pos_x, pos_y))
      error = target_y - model_y

      try:
        pos_y_std = np.asarray(model_v2.position.yStd, dtype=float)
        if self._valid_path(pos_x, pos_y_std):
          path_std = float(np.interp(lookahead, pos_x, pos_y_std))
          if 0.0 <= path_std <= E2E_MAX_PATH_STD:
            break_in = np.clip(
              (abs(error) - E2E_BREAK_IN_START) / (E2E_BREAK_IN_FULL - E2E_BREAK_IN_START),
              0.0,
              1.0,
            )
            error *= 1.0 - e2e_authority * float(break_in)
      except (AttributeError, TypeError, ValueError):
        pass

      return True, float(2.0 * error / lookahead ** 2)
    except (AttributeError, IndexError, TypeError, ValueError):
      return False, 0.0
