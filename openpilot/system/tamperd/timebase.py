import time


_CLOCK_BOOTTIME = getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC)


def boottime_ns() -> int:
  return time.clock_gettime_ns(_CLOCK_BOOTTIME)
