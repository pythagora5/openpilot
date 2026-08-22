#!/usr/bin/env python3

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params


def clear_capture_deadline(params: Params) -> None:
  params.put("TamperModeCaptureRequestedMono", 0, block=True)
  params.put("TamperModeCaptureDeadlineMono", 0, block=True)


def main() -> None:
  params = Params()
  clear_capture_deadline(params)
  try:
    sm = messaging.SubMaster(["accelerometer"], poll="accelerometer")
    while True:
      sm.update(1000)
  finally:
    clear_capture_deadline(params)


if __name__ == "__main__":
  main()
