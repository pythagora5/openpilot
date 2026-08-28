# Validation report

## Result

The archive passed structural, decoder, map-matching, boundary, reproducibility, and path-safety checks. It is ready for on-device Wellington testing. It is not a legally authoritative speed-limit database.

## Archive and tile checks

- 65 archive members: one expected directory and exactly 64 regular tile files
- No absolute paths, parent traversal, duplicate paths, links, devices, or other special members
- All 64 quarter-degree tiles decode with mapd v1.12.0 schemas
- 39 tiles contain road data; the remaining 25 are legitimate ocean/empty tiles
- 23,432 unique ways
- 21,232 named or referenced ways (90.61%)
- 14,601 ways with explicit speed data (62.31%)
- 50 speed-bearing runtime map-matching samples passed
- Five vertical-seam and five horizontal-seam replay checks passed
- 26,486 duplicate-coverage checks passed
- Two independent CI builds produced the same SHA-256

## NZTA NSLR comparison

At `2026-08-02T02:38:20Z`, 50 mapd speed-bearing samples were compared by location with current, numeric, permanent records from the NZTA National Speed Limit Register. Variable, seasonal, temporary, structure-specific, lane-specific, future, and expired records were excluded.

- 43 direct matches
- 4 locations with no eligible simple current record
- 3 mismatches, all individually investigated and dispositioned
- 0 undispositioned mismatches

The complete query evidence is in `nslr-comparison.json` and `nslr-comparison.csv`.

### Reviewed mismatches

1. **Kemp Street — mapd/OSM 50 km/h; NSLR 30 km/h.** Live OSM way `334266271` remains tagged 50 km/h while the current NSLR record identifies the relevant Kemp Street segment as 30 km/h. This is an unresolved source conflict and a known pilot limitation. Posted signs take precedence. It must be resolved before permanent distribution.
2. **Newhaven Way — mapd/OSM 10 km/h; NSLR 50 km/h.** Live OSM way `1016029447` is private access and tagged 10 km/h. The NSLR result is a generic Porirua urban-area polygon. The more specific private-road value is retained for this pilot.
3. **Paekakariki SH59/Beach Road interchange — mapd 30 km/h; NSLR 70 km/h.** The map matcher selected an overlapping local tertiary/link way while the coordinate-only NSLR polygon query returned the SH59 zone. This is a road-level/interchange geometry ambiguity, not evidence that either road's source value should be overwritten.

## Limits of validation

- No field-signage survey has been completed.
- Point-in-polygon NSLR checks cannot reliably distinguish stacked roads, ramps, direction, or adjacent overlapping carriageways.
- Permanent records were compared; active variable, temporary, emergency, seasonal, lane-specific, and structure-specific limits were deliberately excluded.
- Road data can become stale after the 2026-08-01 OSM snapshot.
- On-device testing is still required to confirm the released binary reads these files correctly on a comma 3X.

The automatic migration leaves all speed-limit and Smart Cruise Control settings unchanged. The known source-data limits above therefore apply to whichever existing settings are enabled during on-device testing.
