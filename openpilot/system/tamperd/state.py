from dataclasses import dataclass
from enum import StrEnum

from openpilot.system.tamperd.detector import DetectionResult, NS, TamperDetector


class TamperState(StrEnum):
  BASELINING = "baselining"
  ARMED = "armed"
  COOLDOWN = "cooldown"


@dataclass(frozen=True)
class TamperEvent:
  detected_at_ns: int
  reason: str
  peak_motion: float
  orientation_change_deg: float

class TamperStateMachine:
  def __init__(self, sensitivity: int = 1, cooldown_s: float = 120., detector: TamperDetector | None = None):
    if cooldown_s < 0:
      raise ValueError("tamper cooldown must be non-negative")
    self.detector = detector or TamperDetector(sensitivity=sensitivity)
    self.cooldown_ns = int(cooldown_s * NS)
    self.state = TamperState.BASELINING
    self.cooldown_until_ns = 0

  def reset(self) -> None:
    self.detector.reset()
    self.state = TamperState.BASELINING
    self.cooldown_until_ns = 0

  def process_sample(self, timestamp_ns: int, vector) -> TamperEvent | None:
    if self.state == TamperState.COOLDOWN:
      if timestamp_ns < self.cooldown_until_ns:
        return None
      self.detector.reset()
      self.state = TamperState.BASELINING

    result: DetectionResult = self.detector.add_sample(timestamp_ns, vector)
    if not self.detector.ready:
      self.state = TamperState.BASELINING
    elif self.state == TamperState.BASELINING:
      self.state = TamperState.ARMED

    if not result.triggered:
      return None

    self.state = TamperState.COOLDOWN
    self.cooldown_until_ns = timestamp_ns + self.cooldown_ns
    return TamperEvent(timestamp_ns, result.reason, result.peak_motion, result.orientation_change_deg)

  def status(self) -> dict:
    status = {"state": self.state.value}
    if self.state == TamperState.COOLDOWN:
      status["cooldownUntilMono"] = self.cooldown_until_ns
    return status
