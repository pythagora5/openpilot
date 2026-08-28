#!/usr/bin/env bash
set -euo pipefail

archive_name="lyle-pilot-wellington-mapd-v1.12.0-osm-2026-08-01-v1.tar.gz"
archive_sha256="34cdc77e6b9316a520e2eb27fe0b7e4d963a9b748131056cf8c8438e0afb8db5"
openpilot_root="/data/openpilot"
map_root="/data/media/0/osm"
target="$map_root/offline/-42/174"
backup="$map_root/offline/-42/174.lyle-pilot-before-v1"
stage="$map_root/.lyle-pilot-wellington-v1.stage"
state="$map_root/lyle-pilot-wellington-v1-install-state.json"

manager_stop_attempted=0
params_changed=0
old_target_moved=0
target_swapped=0

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_device() {
  [[ -f /AGNOS ]] || die "This script is only for an AGNOS comma device."
  [[ -d "$openpilot_root" ]] || die "$openpilot_root is missing."
  [[ -d "$map_root" ]] || die "$map_root is missing."
}

require_offroad() {
  (
    cd "$openpilot_root"
    PYTHONPATH="$openpilot_root" python3 - <<'PY'
from openpilot.common.params import Params
p = Params()
if not p.get_bool("IsOffroad"):
  raise SystemExit("Device is not reporting offroad")
if p.get_bool("IsEngaged"):
  raise SystemExit("Device is reporting engaged")
print("device state gate: offroad and not engaged")
PY
  ) || die "Park with ignition off and wait for the home screen before trying again."
}

stop_manager() {
  sudo systemctl stop comma
  if sudo systemctl is-active --quiet comma; then
    die "comma service did not stop."
  fi
  if pgrep -f 'mapd_manager|third_party/mapd_pfeiferj/mapd' >/dev/null; then
    die "A supervised mapd process remains after stopping comma."
  fi
  echo "manager gate: comma inactive; mapd processes absent"
}

start_manager() {
  sudo systemctl start comma
  for _ in $(seq 1 20); do
    if sudo systemctl is-active --quiet comma; then
      echo "comma service: active"
      return 0
    fi
    sleep 1
  done
  return 1
}

verify_archive() {
  local archive="$1"
  [[ -f "$archive" ]] || die "Archive not found: $archive"
  [[ "$(basename "$archive")" == "$archive_name" ]] || die "Unexpected archive filename."
  local actual
  actual="$(sha256sum "$archive" | awk '{print $1}')"
  [[ "$actual" == "$archive_sha256" ]] || die "Archive SHA-256 mismatch."
  python3 - "$archive" <<'PY'
import pathlib
import sys
import tarfile

archive = pathlib.Path(sys.argv[1])
with tarfile.open(archive, "r:gz") as handle:
  members = handle.getmembers()
  names = [member.name for member in members]
  if len(names) != len(set(names)):
    raise SystemExit("duplicate archive member")
  if len(members) != 65 or sum(member.isfile() for member in members) != 64:
    raise SystemExit("archive must contain one directory and 64 regular files")
  if names[0] != "offline/-42/174":
    raise SystemExit("unexpected archive root")
  for member in members:
    path = pathlib.PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts:
      raise SystemExit(f"unsafe archive path: {member.name}")
    if not (member.isdir() or member.isfile()):
      raise SystemExit(f"unsupported archive member type: {member.name}")
    if member.name != "offline/-42/174" and not member.name.startswith("offline/-42/174/"):
      raise SystemExit(f"archive member is outside the expected tile group: {member.name}")
print("archive gate: checksum, paths, types, and member count valid")
PY
}

save_and_neutralize_params() {
  local target_present="$1"
  PILOT_STATE="$state" PILOT_TARGET_PRESENT="$target_present" PYTHONPATH="$openpilot_root" python3 - <<'PY'
import json
import os
from pathlib import Path
from openpilot.common.params import Params

state_path = Path(os.environ["PILOT_STATE"])
if state_path.exists():
  raise SystemExit(f"install state already exists: {state_path}")

params = Params()
mem_params = Params("/dev/shm/params")
keys = [
  "SpeedLimitMode", "SmartCruiseControlMap", "OsmDbUpdatesCheck", "OsmLocal",
  "OsmLocationName", "OsmLocationTitle", "OsmStateName", "OsmStateTitle",
]
saved = {}
for key in keys:
  value = params.get(key)
  saved[key] = {"present": value is not None, "value": value}

payload = {
  "pilot": "lyle-pilot-wellington-v1",
  "target_present_before": os.environ["PILOT_TARGET_PRESENT"] == "1",
  "params": saved,
}
state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

params.put("SpeedLimitMode", 1, block=True)  # Information only; no warning/assist control.
params.put_bool("SmartCruiseControlMap", False, block=True)
params.put_bool("OsmDbUpdatesCheck", False, block=True)
for key in ("OsmLocal", "OsmLocationName", "OsmLocationTitle", "OsmStateName", "OsmStateTitle"):
  params.remove(key)
for key in ("OSMDownloadLocations", "OSMDownloadBounds", "OSMDownloadProgress"):
  mem_params.remove(key)
print("parameter gate: information-only mode; map control and download triggers disabled")
PY
}

install_cleanup() {
  local status=$?
  local stamp interrupted interrupted_state interrupted_stage
  trap - EXIT
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"

  if [[ "$target_swapped" == "1" && -e "$target" ]]; then
    interrupted="$map_root/offline/-42/174.lyle-pilot-interrupted-$stamp"
    [[ -e "$interrupted" ]] || sudo mv "$target" "$interrupted" || true
  fi
  if [[ "$old_target_moved" == "1" && -e "$backup" && ! -e "$target" ]]; then
    sudo mv "$backup" "$target" || true
  fi
  if [[ -e "$stage" ]]; then
    interrupted_stage="$map_root/.lyle-pilot-wellington-v1.stage.interrupted-$stamp"
    [[ -e "$interrupted_stage" ]] || sudo mv "$stage" "$interrupted_stage" || true
  fi
  if [[ "$params_changed" == "1" && -f "$state" ]]; then
    restore_params || true
    interrupted_state="$state.interrupted-$stamp"
    [[ -e "$interrupted_state" ]] || mv "$state" "$interrupted_state" || true
  fi
  if [[ "$manager_stop_attempted" == "1" ]]; then
    echo "Installation interrupted; baseline restored where possible; restarting comma" >&2
    sudo systemctl start comma || true
  fi
  exit "$status"
}

rollback_cleanup() {
  local status=$?
  trap - EXIT
  if [[ -e "$backup" && ! -e "$target" ]]; then
    sudo mv "$backup" "$target" || true
  fi
  if [[ -f "$state" ]]; then
    restore_params || true
  fi
  if [[ "$manager_stop_attempted" == "1" ]]; then
    echo "Rollback interrupted; baseline restored where possible; restarting comma" >&2
    sudo systemctl start comma || true
  fi
  exit "$status"
}

restore_params() {
  PILOT_STATE="$state" PYTHONPATH="$openpilot_root" python3 - <<'PY'
import json
import os
from openpilot.common.params import Params

state_path = os.environ["PILOT_STATE"]
payload = json.loads(open(state_path, encoding="utf-8").read())
params = Params()
mem_params = Params("/dev/shm/params")
for key, saved in payload["params"].items():
  if saved["present"]:
    params.put(key, saved["value"], block=True)
  else:
    params.remove(key)
for key in ("OSMDownloadLocations", "OSMDownloadBounds", "OSMDownloadProgress"):
  mem_params.remove(key)
PY
}

install_archive() {
  local archive="$1"
  require_device
  require_offroad
  verify_archive "$archive"
  [[ ! -e "$stage" ]] || die "Staging path already exists: $stage"
  [[ ! -e "$backup" ]] || die "Backup path already exists: $backup"
  [[ ! -e "$state" ]] || die "Install state already exists: $state"

  echo
  echo "This will stop Lyle Pilot, retain the current -42/174 group, install the pilot group,"
  echo "disable map-driven speed control, and restart Lyle Pilot."
  read -r -p "Type INSTALL WELLINGTON PILOT to continue: " confirmation
  [[ "$confirmation" == "INSTALL WELLINGTON PILOT" ]] || die "Confirmation did not match."
  require_offroad

  manager_stop_attempted=1
  trap install_cleanup EXIT
  stop_manager
  params_changed=0
  old_target_moved=0
  target_swapped=0
  target_present_before=0

  [[ -e "$target" ]] && target_present_before=1
  params_changed=1
  save_and_neutralize_params "$target_present_before"

  sudo mkdir "$stage"
  sudo tar -xzf "$archive" -C "$stage"
  sudo chown -R "$(id -u):$(id -g)" "$stage"
  local extracted_count
  extracted_count="$(find "$stage/offline/-42/174" -type f | wc -l | tr -d ' ')"
  [[ "$extracted_count" == "64" ]] || die "Extracted tile count is $extracted_count, expected 64."

  sudo mkdir -p "$map_root/offline/-42"
  if [[ "$target_present_before" == "1" ]]; then
    sudo mv "$target" "$backup"
    old_target_moved=1
  fi
  sudo mv "$stage/offline/-42/174" "$target"
  target_swapped=1
  sudo rmdir "$stage/offline/-42" "$stage/offline" "$stage"
  sync

  start_manager || die "comma service did not become active after installation."
  manager_stop_attempted=0
  trap - EXIT

  echo
  echo "Wellington pilot installed. Previous data and parameters are retained for rollback."
  echo "Keep Speed Limit on Information and Smart Cruise Control map input off. Obey posted signs."
}

rollback_archive() {
  require_device
  require_offroad
  [[ -f "$state" ]] || die "No pilot install state found: $state"

  echo
  read -r -p "Type ROLLBACK WELLINGTON PILOT to continue: " confirmation
  [[ "$confirmation" == "ROLLBACK WELLINGTON PILOT" ]] || die "Confirmation did not match."
  require_offroad

  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local removed="$map_root/offline/-42/174.lyle-pilot-removed-$stamp"
  local state_archive="$map_root/lyle-pilot-wellington-v1-install-state.rolled-back-$stamp.json"
  [[ ! -e "$removed" ]] || die "Rollback destination already exists: $removed"
  [[ ! -e "$state_archive" ]] || die "State archive already exists: $state_archive"

  local target_present_before
  target_present_before="$(PILOT_STATE="$state" python3 - <<'PY'
import json
import os
payload = json.loads(open(os.environ["PILOT_STATE"], encoding="utf-8").read())
print("1" if payload["target_present_before"] else "0")
PY
)"
  [[ "$target_present_before" == "0" || "$target_present_before" == "1" ]] || die "Invalid install state."

  manager_stop_attempted=1
  trap rollback_cleanup EXIT
  stop_manager

  if [[ "$target_present_before" == "1" ]]; then
    if [[ -e "$backup" ]]; then
      if [[ -e "$target" ]]; then
        sudo mv "$target" "$removed"
      fi
      sudo mv "$backup" "$target"
    else
      echo "Original tile group is already active; no tile move is required."
    fi
  elif [[ -e "$target" ]]; then
    sudo mv "$target" "$removed"
  fi
  restore_params
  mv "$state" "$state_archive"
  sync

  start_manager || die "comma service did not become active after rollback."
  manager_stop_attempted=0
  trap - EXIT
  echo "Rollback complete. Pilot data was moved to $removed and was not deleted."
}

case "${1:-}" in
  install)
    [[ $# -eq 2 ]] || die "Usage: $0 install /path/to/$archive_name"
    install_archive "$2"
    ;;
  rollback)
    [[ $# -eq 1 ]] || die "Usage: $0 rollback"
    rollback_archive
    ;;
  *)
    die "Usage: $0 {install /path/to/$archive_name|rollback}"
    ;;
esac
