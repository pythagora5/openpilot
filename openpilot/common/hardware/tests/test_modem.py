import subprocess
from unittest.mock import MagicMock

import pytest

from openpilot.common.hardware.tici.modem import Modem, PPPSession, State


def mock_state_publish(monkeypatch, modem):
  monkeypatch.setattr(modem, "_publish_state", lambda **kwargs: modem.S.update(kwargs))


@pytest.mark.parametrize("response, expected", [
  ('2,1,"01AB","1234",7', "home"),
  ('2,5,"01AB","1234",7', "roaming"),
  ('1,"01AB","1234",7', "home"),
  ("1", "home"),
  ("", "unknown"),
])
def test_parse_registration(response, expected):
  assert Modem._parse_reg(response) == expected


def test_searching_accepts_eps_registration(monkeypatch):
  modem = Modem()
  mock_state_publish(monkeypatch, modem)
  monkeypatch.setattr(modem, "_is_roaming_allowed", lambda: True)
  atv = MagicMock(return_value='2,1,"01AB","1234",7')
  monkeypatch.setattr(modem, "_atv", atv)

  assert modem._do_searching() == State.CONNECTING
  assert modem.S["registration"] == "home"
  atv.assert_called_once_with("AT+CEREG?", "+CEREG:")


def test_searching_falls_back_to_packet_registration(monkeypatch):
  modem = Modem()
  mock_state_publish(monkeypatch, modem)
  monkeypatch.setattr(modem, "_is_roaming_allowed", lambda: True)
  responses = {
    "AT+CEREG?": "2,0",
    "AT+CGREG?": '2,1,"01AB","1234",2',
  }
  monkeypatch.setattr(modem, "_atv", lambda cmd, _prefix: responses[cmd])

  assert modem._do_searching() == State.CONNECTING
  assert modem.S["registration"] == "home"


def test_searching_blocks_packet_roaming(monkeypatch):
  modem = Modem()
  mock_state_publish(monkeypatch, modem)
  modem._roaming_allowed = False
  monkeypatch.setattr(modem, "_is_roaming_allowed", lambda: False)
  monkeypatch.setattr(modem, "_atv", lambda _cmd, _prefix: '2,5,"01AB","1234",7')

  assert modem._do_searching() == State.SEARCHING
  assert modem.S["registration"] == "roaming"


def test_dns_falls_back_when_modem_does_not_report_servers(monkeypatch):
  modem = Modem()
  monkeypatch.setattr(modem, "_atv", lambda _cmd, _prefix: None)

  assert modem._read_cellular_dns() == ["8.8.8.8", "1.1.1.1"]


def test_interface_is_connected_only_after_routes_and_dns(monkeypatch):
  modem = Modem()
  ip_output = MagicMock(stdout="    inet 10.0.0.2 peer 10.0.0.1/32 scope global ppp0\n")
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.subprocess.run", lambda *_args, **_kwargs: ip_output)
  monkeypatch.setattr(modem._ppp, "maybe_install_routes", MagicMock(return_value=True))
  monkeypatch.setattr(modem._ppp, "maybe_install_dns", MagicMock(return_value=True))
  monkeypatch.setattr(modem, "_read_cellular_dns", lambda: ["8.8.8.8"])

  assert modem._poll_iface() == {"ip_address": "10.0.0.2", "connected": True}


def test_interface_is_not_connected_before_dns_is_ready(monkeypatch):
  modem = Modem()
  ip_output = MagicMock(stdout="    inet 10.0.0.2 peer 10.0.0.1/32 scope global ppp0\n")
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.subprocess.run", lambda *_args, **_kwargs: ip_output)
  monkeypatch.setattr(modem._ppp, "maybe_install_routes", MagicMock(return_value=True))
  monkeypatch.setattr(modem._ppp, "maybe_install_dns", MagicMock(return_value=False))
  monkeypatch.setattr(modem, "_read_cellular_dns", lambda: ["8.8.8.8"])
  kill = MagicMock()
  monkeypatch.setattr(modem._ppp, "kill", kill)

  assert modem._poll_iface() == {}
  kill.assert_not_called()


def test_address_present_does_not_trigger_interface_loss(monkeypatch):
  modem = Modem()
  modem.S["connected"] = True
  ip_output = MagicMock(stdout="    inet 10.0.0.2 peer 10.0.0.1/32 scope global ppp0\n")
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.subprocess.run", lambda *_args, **_kwargs: ip_output)
  monkeypatch.setattr(modem._ppp, "maybe_install_routes", MagicMock(return_value=True))
  monkeypatch.setattr(modem._ppp, "maybe_install_dns", MagicMock(return_value=False))
  monkeypatch.setattr(modem, "_read_cellular_dns", lambda: ["8.8.8.8"])
  kill = MagicMock()
  monkeypatch.setattr(modem._ppp, "kill", kill)

  assert modem._poll_iface() == {"connected": False, "ip_address": ""}
  kill.assert_not_called()


def test_interface_loss_terminates_stuck_ppp(monkeypatch):
  modem = Modem()
  modem.S["connected"] = True
  modem._ppp._routes_ready = True
  modem._ppp._dns_ready = True
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.subprocess.run", lambda *_args, **_kwargs: MagicMock(stdout=""))
  kill = MagicMock()
  monkeypatch.setattr(modem._ppp, "kill", kill)

  assert modem._poll_iface() == {"connected": False, "ip_address": ""}
  kill.assert_called_once()


def test_fresh_ppp_is_not_killed_by_stale_published_state(monkeypatch):
  modem = Modem()
  modem.S["connected"] = True
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.subprocess.run", lambda *_args, **_kwargs: MagicMock(stdout=""))
  kill = MagicMock()
  monkeypatch.setattr(modem._ppp, "kill", kill)

  assert modem._poll_iface() == {}
  kill.assert_not_called()


def test_ppp_connect_watchdog(monkeypatch):
  ppp = PPPSession()
  ppp._proc = MagicMock()
  ppp._proc.poll.return_value = None
  ppp._started_at = 10
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.time.monotonic", lambda: 10 + ppp.CONNECT_TIMEOUT_S)

  assert ppp.connect_timed_out()


def test_ppp_connect_watchdog_stops_after_routes_and_dns(monkeypatch):
  ppp = PPPSession()
  ppp._proc = MagicMock()
  ppp._proc.poll.return_value = None
  ppp._started_at = 10
  ppp._routes_ready = True
  ppp._dns_ready = True
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.time.monotonic", lambda: 10 + ppp.CONNECT_TIMEOUT_S)

  assert not ppp.connect_timed_out()


def test_ppp_kill_waits_for_child(monkeypatch):
  ppp = PPPSession()
  proc = MagicMock()
  proc.poll.return_value = None
  ppp._proc = proc
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.subprocess.run", MagicMock())

  ppp.kill()

  proc.wait.assert_called_once_with(timeout=2)
  assert ppp._proc is None
  assert ppp.has_exited()


def test_ppp_kill_retains_slow_child_for_later_reaping(monkeypatch):
  ppp = PPPSession()
  proc = MagicMock()
  proc.poll.return_value = None
  proc.wait.side_effect = subprocess.TimeoutExpired("pppd", 2)
  ppp._proc = proc
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.subprocess.run", MagicMock())

  ppp.kill()

  assert ppp._stale_procs == [proc]
  assert ppp._proc is None


def test_ppp_reaps_exited_stale_child():
  ppp = PPPSession()
  proc = MagicMock()
  proc.poll.return_value = 0
  ppp._stale_procs = [proc]

  ppp._reap_stale_procs()

  assert ppp._stale_procs == []


def test_ppp_exit_clears_published_connection_before_retry(monkeypatch):
  modem = Modem()
  mock_state_publish(monkeypatch, modem)
  modem.S["connected"] = True
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.os.path.exists", lambda _path: True)
  monkeypatch.setattr(modem._ppp, "record_fail", lambda: False)
  monkeypatch.setattr(modem._ppp, "reset_data_port", lambda: None)
  start = MagicMock()
  monkeypatch.setattr(modem._ppp, "start", start)

  assert modem._handle_pppd_exit() == State.CONNECTED
  assert not modem.S["connected"]
  assert modem.S["ip_address"] == ""
  start.assert_called_once()


def test_connected_watchdog_kills_before_retry(monkeypatch):
  modem = Modem()
  monkeypatch.setattr(modem._ppp, "has_exited", lambda: False)
  monkeypatch.setattr(modem, "_params_changed", lambda: False)
  monkeypatch.setattr("openpilot.common.hardware.tici.modem.os.path.exists", lambda _path: True)
  monkeypatch.setattr(modem, "_poll", lambda: None)
  monkeypatch.setattr(modem._ppp, "connect_timed_out", lambda: True)
  kill = MagicMock()
  retry = MagicMock(return_value=State.CONNECTED)
  monkeypatch.setattr(modem._ppp, "kill", kill)
  monkeypatch.setattr(modem, "_handle_pppd_exit", retry)

  assert modem._do_connected() == State.CONNECTED
  kill.assert_called_once()
  retry.assert_called_once()
