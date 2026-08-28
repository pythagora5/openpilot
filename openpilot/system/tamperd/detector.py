import math
from collections import deque
from dataclasses import dataclass


NS = 1_000_000_000
BASELINE_MAX_RMS = 0.2
MAX_CONSECUTIVE_INVALID_SAMPLES = 3


@dataclass(frozen=True)
class SensitivityProfile:
  motion_threshold: float
  impact_threshold: float
  orientation_threshold_deg: float
  active_windows_required: int


SENSITIVITY_PROFILES = {
  0: SensitivityProfile(1.5, 4.0, 8.0, 4),
  1: SensitivityProfile(0.8, 3.0, 5.0, 3),
  2: SensitivityProfile(0.4, 2.0, 3.0, 2),
}


@dataclass(frozen=True)
class DetectionResult:
  triggered: bool = False
  reason: str = ""
  peak_motion: float = 0.
  orientation_change_deg: float = 0.


class TamperDetector:
  def __init__(self, sensitivity: int = 1, baseline_duration_s: float = 5., min_baseline_samples: int = 100,
               window_duration_s: float = 0.1, evidence_duration_s: float = 2., max_sample_gap_s: float = 0.25,
               orientation_tau_s: float = 0.5):
    if sensitivity not in SENSITIVITY_PROFILES:
      raise ValueError(f"invalid tamper sensitivity: {sensitivity}")
    if min(baseline_duration_s, window_duration_s, evidence_duration_s, max_sample_gap_s, orientation_tau_s) <= 0:
      raise ValueError("tamper detector durations must be positive")
    if min_baseline_samples <= 0:
      raise ValueError("tamper baseline sample count must be positive")

    self.profile = SENSITIVITY_PROFILES[sensitivity]
    self.baseline_duration_ns = int(baseline_duration_s * NS)
    self.min_baseline_samples = min_baseline_samples
    self.window_duration_ns = int(window_duration_s * NS)
    self.evidence_duration_ns = int(evidence_duration_s * NS)
    self.max_sample_gap_ns = int(max_sample_gap_s * NS)
    self.orientation_tau_s = orientation_tau_s
    self.reset()

  def reset(self) -> None:
    self.ready = False
    self.last_timestamp_ns: int | None = None
    self.baseline_started_ns: int | None = None
    self.baseline_sum = [0., 0., 0.]
    self.baseline_sum_squares = [0., 0., 0.]
    self.baseline_count = 0
    self.baseline: tuple[float, float, float] | None = None
    self.orientation_vector: list[float] | None = None
    self.window_started_ns: int | None = None
    self.window_peak_motion = 0.
    self.window_peak_orientation = 0.
    self.active_windows: deque[int] = deque()
    self.consecutive_invalid_samples = 0

  @staticmethod
  def _valid_vector(vector: tuple[float, float, float]) -> bool:
    return len(vector) == 3 and all(math.isfinite(value) and abs(value) <= 50. for value in vector)

  @staticmethod
  def _norm(vector) -> float:
    return math.sqrt(sum(value * value for value in vector))

  @classmethod
  def _angle_deg(cls, first, second) -> float:
    first_norm = cls._norm(first)
    second_norm = cls._norm(second)
    if first_norm < 1e-6 or second_norm < 1e-6:
      return 0.
    cosine = sum(a * b for a, b in zip(first, second, strict=True)) / (first_norm * second_norm)
    return math.degrees(math.acos(max(-1., min(1., cosine))))

  def _add_baseline_sample(self, timestamp_ns: int, vector: tuple[float, float, float]) -> None:
    if self.baseline_started_ns is None:
      self.baseline_started_ns = timestamp_ns
    for index, value in enumerate(vector):
      self.baseline_sum[index] += value
      self.baseline_sum_squares[index] += value * value
    self.baseline_count += 1

    enough_time = timestamp_ns - self.baseline_started_ns >= self.baseline_duration_ns
    if enough_time and self.baseline_count >= self.min_baseline_samples:
      baseline = tuple(value / self.baseline_count for value in self.baseline_sum)
      variances = [max(0., total / self.baseline_count - mean * mean)
                   for total, mean in zip(self.baseline_sum_squares, baseline, strict=True)]
      baseline_rms = math.sqrt(sum(variances))
      if 7. <= self._norm(baseline) <= 12.5 and baseline_rms <= BASELINE_MAX_RMS:
        self.baseline = baseline
        self.orientation_vector = list(baseline)
        self.window_started_ns = timestamp_ns
        self.ready = True
      else:
        self.reset()
        self.last_timestamp_ns = timestamp_ns
        self._add_baseline_sample(timestamp_ns, vector)

  def _finalize_window(self, timestamp_ns: int) -> DetectionResult:
    active = (self.window_peak_motion >= self.profile.motion_threshold or
              self.window_peak_orientation >= self.profile.orientation_threshold_deg)
    if active:
      self.active_windows.append(timestamp_ns)

    oldest_allowed = timestamp_ns - self.evidence_duration_ns
    while self.active_windows and self.active_windows[0] < oldest_allowed:
      self.active_windows.popleft()

    triggered = len(self.active_windows) >= self.profile.active_windows_required
    result = DetectionResult(
      triggered=triggered,
      reason="sustained_movement" if triggered else "",
      peak_motion=self.window_peak_motion,
      orientation_change_deg=self.window_peak_orientation,
    )
    if triggered:
      self.active_windows.clear()
    self.window_peak_motion = 0.
    self.window_peak_orientation = 0.
    return result

  def add_sample(self, timestamp_ns: int, vector) -> DetectionResult:
    try:
      vector = tuple(float(value) for value in vector)
    except (TypeError, ValueError):
      self.consecutive_invalid_samples += 1
      if self.consecutive_invalid_samples >= MAX_CONSECUTIVE_INVALID_SAMPLES:
        self.reset()
      return DetectionResult()
    if not self._valid_vector(vector) or timestamp_ns < 0:
      self.consecutive_invalid_samples += 1
      if self.consecutive_invalid_samples >= MAX_CONSECUTIVE_INVALID_SAMPLES:
        self.reset()
      return DetectionResult()
    self.consecutive_invalid_samples = 0

    if self.last_timestamp_ns is not None:
      gap_ns = timestamp_ns - self.last_timestamp_ns
      if -self.max_sample_gap_ns <= gap_ns <= 0:
        return DetectionResult()
      if gap_ns < -self.max_sample_gap_ns or gap_ns > self.max_sample_gap_ns:
        self.reset()
    previous_timestamp_ns = self.last_timestamp_ns
    self.last_timestamp_ns = timestamp_ns

    if not self.ready:
      self._add_baseline_sample(timestamp_ns, vector)
      return DetectionResult()

    assert self.baseline is not None
    assert self.orientation_vector is not None
    assert self.window_started_ns is not None

    dt_s = max(0., (timestamp_ns - (previous_timestamp_ns or timestamp_ns)) / NS)
    alpha = 1. - math.exp(-dt_s / self.orientation_tau_s)
    for index, value in enumerate(vector):
      self.orientation_vector[index] += alpha * (value - self.orientation_vector[index])

    motion = self._norm(tuple(value - base for value, base in zip(vector, self.baseline, strict=True)))
    orientation = self._angle_deg(self.orientation_vector, self.baseline)

    if motion >= self.profile.impact_threshold:
      return DetectionResult(True, "impact", motion, orientation)

    result = DetectionResult()
    if timestamp_ns - self.window_started_ns >= self.window_duration_ns:
      result = self._finalize_window(timestamp_ns)
      self.window_started_ns = timestamp_ns

    self.window_peak_motion = max(self.window_peak_motion, motion)
    self.window_peak_orientation = max(self.window_peak_orientation, orientation)
    return result
