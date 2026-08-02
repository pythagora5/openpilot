# Superseded manual comma 3X fallback

This is the procedure shipped with the earlier `wellington-map-v1.0.0` release asset. It is retained as historical fallback documentation and is not used by the current Lyle Pilot branch. The supported current path is the normal device Software UI flow documented in `AUTOMATIC_UPDATE.md`.

Unlike the current automatic migration, this legacy script changes speed-limit and Smart Cruise Control parameters. Do not use it when the requirement is to preserve the device's existing cruise settings.

This procedure is intentionally manual and reversible. Do it only while the vehicle is parked, ignition is off, the comma 3X is at its home screen, and the device has reliable power. Do not perform it during a drive.

The installer enforces these gates:

- device reports offroad and not engaged before any change
- archive SHA-256 and member paths are verified before extraction
- the full `comma` service is stopped and both `mapd` processes are verified absent
- the upstream map-download triggers are cleared
- Speed Limit mode is set to **Information** (`1`), not Warning or Assist
- Smart Cruise Control map input is disabled
- extraction and swap occur on the `/data/media/0/osm` filesystem
- the previous `-42/174` group and affected parameter values are retained for rollback

## 1. Enable and test SSH

On the comma 3X, enable SSH and enter the GitHub username that holds your public SSH key. From the Mac, connect using the device's Wi-Fi IP:

```sh
ssh comma@DEVICE_IP
```

Comma's current connection guide is https://docs.comma.ai/how-to/connect-to-comma/.

## 2. Download on the Mac and verify the second trust channel

Download these release assets into one local folder:

- `lyle-pilot-wellington-mapd-v1.12.0-osm-2026-08-01-v1.tar.gz`
- `device_wellington_pilot.sh`

Verify the archive against `tools/map_data/wellington/pilot-v1/SHA256SUMS` in the checked-out Lyle Pilot repository—not only against the checksum attached to the same GitHub release:

```sh
cd /path/to/the/download-folder
shasum -a 256 -c /Users/lyle/Documents/code/lyle-pilot/tools/map_data/wellington/pilot-v1/SHA256SUMS
```

Expected archive digest:

```text
34cdc77e6b9316a520e2eb27fe0b7e4d963a9b748131056cf8c8438e0afb8db5
```

## 3. Copy both files to the comma 3X

```sh
scp lyle-pilot-wellington-mapd-v1.12.0-osm-2026-08-01-v1.tar.gz device_wellington_pilot.sh comma@DEVICE_IP:/tmp/
```

## 4. Run the guarded installation over SSH

```sh
ssh comma@DEVICE_IP
bash /tmp/device_wellington_pilot.sh install /tmp/lyle-pilot-wellington-mapd-v1.12.0-osm-2026-08-01-v1.tar.gz
```

Read the preflight summary and type the exact confirmation requested by the script. If any gate fails, stop and investigate; do not work around it.

## 5. Stationary verification

After the service restarts, confirm:

- the home screen loads normally
- Settings > Cruise > Speed Limit shows **Information**, not Warning or Assist
- Smart Cruise Control map input remains off
- no map download is in progress
- `/data/media/0/osm/offline/-42/174` contains 64 files

The first onroad test should be a short, familiar route with posted signs. Treat the speed-limit circle as informational only. Kemp Street is a known 50-versus-30 source conflict in this snapshot; obey the signs.

## Rollback

Park offroad and run:

```sh
ssh comma@DEVICE_IP
bash /tmp/device_wellington_pilot.sh rollback
```

AGNOS clears `/tmp` on reboot. If the script is no longer present, copy the same `device_wellington_pilot.sh` release asset back to `/tmp` with `scp` before running rollback.

Rollback moves the pilot group aside, restores the exact previous tile group if one existed, restores the saved parameters, and restarts the `comma` service. It does not permanently delete either dataset.
