import math

from openpilot.system.tamperd.detector import NS, TamperDetector
from openpilot.system.tamperd.state import TamperState, TamperStateMachine


SAMPLE_PERIOD_NS = int(0.01 * NS)
GRAVITY = (0., 0., 9.81)


def establish_baseline(machine: TamperStateMachine, start_ns: int = 0) -> int:
  timestamp_ns = start_ns
  for _ in range(502):
    assert machine.process_sample(timestamp_ns, GRAVITY) is None
    timestamp_ns += SAMPLE_PERIOD_NS
  assert machine.state == TamperState.ARMED
  return timestamp_ns


def test_quiet_vehicle_arms_without_triggering():
  machine = TamperStateMachine()
  timestamp_ns = establish_baseline(machine)

  for _ in range(500):
    assert machine.process_sample(timestamp_ns, GRAVITY) is None
    timestamp_ns += SAMPLE_PERIOD_NS
  assert machine.state == TamperState.ARMED


def test_single_non_impact_bump_does_not_trigger():
  machine = TamperStateMachine()
  timestamp_ns = establish_baseline(machine)

  assert machine.process_sample(timestamp_ns, (1., 0., 9.81)) is None
  timestamp_ns += SAMPLE_PERIOD_NS
  for _ in range(50):
    assert machine.process_sample(timestamp_ns, GRAVITY) is None
    timestamp_ns += SAMPLE_PERIOD_NS
  assert machine.state == TamperState.ARMED


def test_impact_triggers_immediately():
  machine = TamperStateMachine()
  timestamp_ns = establish_baseline(machine)

  event = machine.process_sample(timestamp_ns, (3.5, 0., 9.81))
  assert event is not None
  assert event.reason == "impact"
  assert machine.state == TamperState.COOLDOWN


def test_repeated_movement_triggers():
  machine = TamperStateMachine()
  timestamp_ns = establish_baseline(machine)

  event = None
  for index in range(80):
    vector = (1., 0., 9.81) if index % 12 < 4 else GRAVITY
    event = machine.process_sample(timestamp_ns, vector) or event
    timestamp_ns += SAMPLE_PERIOD_NS

  assert event is not None
  assert event.reason == "sustained_movement"


def test_slow_orientation_change_triggers():
  machine = TamperStateMachine()
  timestamp_ns = establish_baseline(machine)

  event = None
  for index in range(200):
    angle = math.radians(min(10., index * 0.08))
    vector = (9.81 * math.sin(angle), 0., 9.81 * math.cos(angle))
    event = machine.process_sample(timestamp_ns, vector) or event
    timestamp_ns += SAMPLE_PERIOD_NS

  assert event is not None
  assert event.reason == "sustained_movement"


def test_sample_gap_forces_new_baseline():
  machine = TamperStateMachine()
  timestamp_ns = establish_baseline(machine)

  timestamp_ns += int(1. * NS)
  assert machine.process_sample(timestamp_ns, GRAVITY) is None
  assert machine.state == TamperState.BASELINING


def test_unstable_baseline_never_arms():
  machine = TamperStateMachine()
  timestamp_ns = 0
  for index in range(502):
    vector = (1. if index % 2 else -1., 0., 9.81)
    assert machine.process_sample(timestamp_ns, vector) is None
    timestamp_ns += SAMPLE_PERIOD_NS
  assert machine.state == TamperState.BASELINING


def test_cooldown_suppresses_and_then_rebaselines():
  machine = TamperStateMachine(cooldown_s=120.)
  timestamp_ns = establish_baseline(machine)
  assert machine.process_sample(timestamp_ns, (3.5, 0., 9.81)) is not None

  assert machine.process_sample(timestamp_ns + int(119. * NS), (3.5, 0., 9.81)) is None
  assert machine.state == TamperState.COOLDOWN

  assert machine.process_sample(timestamp_ns + int(120. * NS), GRAVITY) is None
  assert machine.state == TamperState.BASELINING


def test_sensitivity_profiles_change_trigger_threshold():
  high = TamperStateMachine(sensitivity=2)
  low = TamperStateMachine(sensitivity=0)
  high_timestamp = establish_baseline(high)
  low_timestamp = establish_baseline(low)

  high_event = None
  low_event = None
  for index in range(50):
    vector = (0.6, 0., 9.81) if index % 12 < 4 else GRAVITY
    high_event = high.process_sample(high_timestamp, vector) or high_event
    low_event = low.process_sample(low_timestamp, vector) or low_event
    high_timestamp += SAMPLE_PERIOD_NS
    low_timestamp += SAMPLE_PERIOD_NS

  assert high_event is not None
  assert low_event is None


def test_invalid_samples_fail_closed():
  detector = TamperDetector()
  assert not detector.add_sample(0, (float("nan"), 0., 9.81)).triggered
  assert not detector.ready
  assert not detector.add_sample(1, (0., 9.81)).triggered
  assert not detector.ready
  assert not detector.add_sample(2, None).triggered
  assert not detector.ready


def test_isolated_invalid_and_duplicate_samples_keep_baseline():
  machine = TamperStateMachine()
  timestamp_ns = establish_baseline(machine)
  last_sample_ns = timestamp_ns - SAMPLE_PERIOD_NS

  assert machine.process_sample(last_sample_ns, GRAVITY) is None
  assert machine.state == TamperState.ARMED
  assert machine.process_sample(timestamp_ns, None) is None
  assert machine.state == TamperState.ARMED

  assert machine.process_sample(timestamp_ns + SAMPLE_PERIOD_NS, None) is None
  assert machine.process_sample(timestamp_ns + 2 * SAMPLE_PERIOD_NS, None) is None
  assert machine.state == TamperState.BASELINING


def test_cooldown_status_is_stable_between_samples():
  machine = TamperStateMachine()
  timestamp_ns = establish_baseline(machine)
  assert machine.process_sample(timestamp_ns, (3.5, 0., 9.81)) is not None

  assert machine.status() == machine.status()
