# Lyle Pilot Wellington map pilot v1

This pre-release supplies a temporary, manually installed Wellington-region mapd archive for testing road names and informational speed limits on a comma 3X. It is deliberately separate from sunnypilot's normal map downloader; permanent distribution is deferred.

## Safety status

- Manual and reversible installation only
- Speed Limit mode must remain **Information**, not Warning or Assist
- Smart Cruise Control map input must remain off
- Posted signs and applicable law always take precedence
- Known unresolved source conflict: Kemp Street is 50 km/h in the 2026-08-01 OSM snapshot and 30 km/h in the current NZTA NSLR record

## Verification

- SHA-256: `34cdc77e6b9316a520e2eb27fe0b7e4d963a9b748131056cf8c8438e0afb8db5`
- 64/64 tile files decode
- 50 runtime map-matching samples passed
- seam and duplicate-coverage checks passed
- two independent CI builds were byte-identical
- NZTA sample comparison: 43 matches, 4 without a simple eligible record, 3 reviewed/dispositioned mismatches, 0 undispositioned mismatches

Read `INSTALL.md`, `VALIDATION.md`, `MANIFEST.md`, and `NOTICE.md` before installation.
