# Lyle Pilot Wellington map pilot v1

This pilot supplies a pinned Wellington-region mapd archive for testing road names and speed limits on a comma 3X. It is bundled in the Lyle Pilot branch and installed by a local pre-manager migration after a normal device Software UI update. It remains separate from sunnypilot's map downloader; permanent distribution is deferred.

## Safety status

- The automatic migration does not change `SpeedLimitMode`, `SpeedLimitPolicy`, `SmartCruiseControlMap`, offsets, or other cruise settings
- The previous Wellington tile group is retained as a versioned backup
- A failed migration does not prevent manager from starting
- Known unresolved source conflict: Kemp Street is 50 km/h in the 2026-08-01 OSM snapshot and 30 km/h in the current NZTA NSLR record

## Verification

- SHA-256: `34cdc77e6b9316a520e2eb27fe0b7e4d963a9b748131056cf8c8438e0afb8db5`
- 64/64 tile files decode
- 50 runtime map-matching samples passed
- seam and duplicate-coverage checks passed
- two independent CI builds were byte-identical
- NZTA sample comparison: 43 matches, 4 without a simple eligible record, 3 reviewed/dispositioned mismatches, 0 undispositioned mismatches

Read `AUTOMATIC_UPDATE.md`, `VALIDATION.md`, `MANIFEST.md`, and `NOTICE.md` before installation. `INSTALL.md` documents the superseded manual release fallback.
