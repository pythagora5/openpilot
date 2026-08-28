# Automatic comma 3X update

The Wellington pilot archive is bundled directly in the `lyle-pilot-v0.1.0` branch. No separate download, SSH session, release asset, or upstream map-data service is required for this update.

## Device update flow

1. On the comma 3X home screen, open **Settings → Software**.
2. Select **Check** and wait for the `lyle-pilot-v0.1.0` update to appear.
3. Select **Install Update** and allow the device to reboot.
4. During startup, Lyle Pilot verifies and installs the bundled Wellington group before manager and mapd start.
5. After the home screen returns, the update is complete. Existing speed-limit, policy, offset, and Smart Cruise Control settings are unchanged.

## Migration behavior

- Verifies the archive SHA-256 before changing the active group.
- Accepts only the exact `offline/-42/174` directory and 64 direct regular files.
- Extracts and verifies the uncompressed group on `/data/media/0/osm`.
- Atomically swaps the verified group into `/data/media/0/osm/offline/-42/174`.
- Retains a pre-existing group at `174.lyle-pilot-wellington-map-v1.backup`.
- Records a versioned installed marker and verifies the installed group on later boots.
- Repairs an altered Wellington group from the bundled archive without overwriting the retained original backup.
- Continues normal device startup if migration fails.

The migration neither triggers the sunnypilot map downloader nor reads or writes cruise-related Params.

## Data identity

- Archive SHA-256: `34cdc77e6b9316a520e2eb27fe0b7e4d963a9b748131056cf8c8438e0afb8db5`
- Extracted group digest: `a59a7e4d25dbbc51e1d0e4ad42d2fa5ec3db90e5b12830201c105d150225e0e4`
- Expected files: 64
- Source snapshot: Geofabrik New Zealand OSM, 2026-08-01

See `VALIDATION.md` for coverage and the known Kemp Street source conflict.
