# Lyle Pilot Wellington map archive v1

This is a temporary, manual-install pilot archive for Lyle Pilot. It is not part of the normal sunnypilot map downloader and must not be treated as a permanent distribution mechanism.

## Release identity

- Archive: `lyle-pilot-wellington-mapd-v1.12.0-osm-2026-08-01-v1.tar.gz`
- SHA-256: `34cdc77e6b9316a520e2eb27fe0b7e4d963a9b748131056cf8c8438e0afb8db5`
- Size: 5,805,170 bytes
- Intended mapd version: `v1.12.0`
- Intended device: comma 3X running the `lyle-pilot-v0.1.0` branch
- Tile group installed: `/data/media/0/osm/offline/-42/174`
- Geographic group extent: latitude `[-42, -40)`, longitude `[174, 176)`

## Sources

- Map generator: `pfeiferj/openpilot-mapd` tag `v1.12.0`, commit `46cd71ade6f630f1564c83bf1763f9d949a9ff30`
- OSM extract: Geofabrik `new-zealand-260801.osm.pbf`
- OSM extract date: 2026-08-01
- OSM PBF MD5: `6017be7654025cd719d0ebc910923ce3`
- OSM PBF SHA-256: `e01c880f1d30ef667ed47756aa81955fc83227d53db44045dbcddcff53164403`
- Extract bounding box: `173,-43,177,-39`, with complete ways retained
- Highway filter: the exact highway classes used by mapd v1.12.0's upstream generation script

NZTA National Speed Limit Register data was used only as an independent validation source. NSLR records were not merged into the map archive.

## Reproducibility

The archive was built twice in separate GitHub Actions runs and the output was byte-identical. The deterministic archive uses sorted member names, numeric owner/group `0`, normalized permissions, a fixed source timestamp of 2026-08-01, and `gzip -n`.

- Successful validation run: GitHub Actions `30729111401`
- Runner: Ubuntu 24.04 image `20260720.247.2`
- Go: `go1.22.2 linux/amd64`
- Osmium: `1.16.0`
- GNU tar: `1.35`
- gzip: `1.12`

The complete package versions and build environment are included in the release assets as `build-manifest.env` and `installed-packages.txt`.
