from openpilot.selfdrive.ui.widgets import offroad_alerts


class FakeParams:
  def __init__(self):
    self.removed = []

  def remove(self, key):
    self.removed.append(key)


class FakeButton:
  def set_click_callback(self, callback):
    self.callback = callback


def test_closing_offroad_alert_acknowledges_only_tamper_alert():
  alert = offroad_alerts.OffroadAlert.__new__(offroad_alerts.OffroadAlert)
  alert.params = FakeParams()
  alert.dismiss_btn = FakeButton()
  dismissed = []

  alert.set_dismiss_callback(lambda: dismissed.append(True))
  alert.dismiss_btn.callback()

  assert alert.params.removed == ["Offroad_TamperDetected"]
  assert dismissed == [True]
