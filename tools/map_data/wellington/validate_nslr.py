#!/usr/bin/env python3
"""Compare mapd replay samples with currently effective NZTA NSLR records."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import sys
import time
import urllib.parse
import urllib.request


NSLR_QUERY_URL = (
  "https://services.arcgis.com/CXBb7LAjgIIdcsPt/arcgis/rest/services/"
  "SpeedLimitZoneFull__View/FeatureServer/0/query"
)
NSLR_ITEM_URL = "https://www.arcgis.com/home/item.html?id=aa376f1f2f3643bdac4d18855229239c"
OUT_FIELDS = (
  "OBJECTID,speedCategoryName,speedLimitZoneValue,speedLimitZoneMaxValue,"
  "speedLimitZoneMinValue,speedLimitZoneName,speedLimitZoneStructureTypeName,"
  "speedLimitZoneLanePurposeName,SeperateLaneSpeeds,speedLimitZoneStartDate,"
  "speedLimitZoneEndDate,whenEffective,whenIneffective,rcaZoneReferenceName,GlobalID"
)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("validation_summary", type=pathlib.Path)
  parser.add_argument("output_dir", type=pathlib.Path)
  parser.add_argument("--as-of", help="ISO-8601 timestamp; defaults to now in UTC")
  parser.add_argument("--max-samples", type=int, default=50)
  parser.add_argument(
    "--dispositions",
    type=pathlib.Path,
    help="Reviewed mismatch dispositions. Every entry must match one NSLR mismatch exactly.",
  )
  return parser.parse_args()


def parse_as_of(value: str | None) -> dt.datetime:
  if value is None:
    return dt.datetime.now(dt.timezone.utc)
  parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
  if parsed.tzinfo is None:
    parsed = parsed.replace(tzinfo=dt.timezone.utc)
  return parsed.astimezone(dt.timezone.utc)


def query_nslr(latitude: float, longitude: float) -> list[dict]:
  params = {
    "f": "json",
    "where": "1=1",
    "geometry": json.dumps({"x": longitude, "y": latitude, "spatialReference": {"wkid": 4326}}),
    "geometryType": "esriGeometryPoint",
    "inSR": "4326",
    "spatialRel": "esriSpatialRelIntersects",
    "outFields": OUT_FIELDS,
    "returnGeometry": "false",
  }
  request = urllib.request.Request(f"{NSLR_QUERY_URL}?{urllib.parse.urlencode(params)}")
  request.add_header("User-Agent", "Lyle-Pilot-Wellington-Map-Validator/1")
  with urllib.request.urlopen(request, timeout=30) as response:
    payload = json.load(response)
  if "error" in payload:
    raise RuntimeError(f"NSLR query failed: {payload['error']}")
  return [feature["attributes"] for feature in payload.get("features", [])]


def timestamp_is_active(attributes: dict, as_of_ms: int) -> bool:
  effective = attributes.get("whenEffective")
  if effective is None:
    effective = attributes.get("speedLimitZoneStartDate")
  ineffective = attributes.get("whenIneffective")
  if ineffective is None:
    ineffective = attributes.get("speedLimitZoneEndDate")
  return (effective is None or effective <= as_of_ms) and (ineffective is None or ineffective > as_of_ms)


def simple_permanent_record(attributes: dict, as_of_ms: int) -> tuple[bool, str]:
  if not timestamp_is_active(attributes, as_of_ms):
    return False, "not_current"
  if attributes.get("speedCategoryName") != "Permanent":
    return False, "non_permanent"
  if attributes.get("speedLimitZoneStructureTypeName"):
    return False, "structure_specific"
  if attributes.get("speedLimitZoneLanePurposeName") or attributes.get("SeperateLaneSpeeds"):
    return False, "lane_specific"
  value = attributes.get("speedLimitZoneValue")
  try:
    int(value)
  except (TypeError, ValueError):
    return False, "non_numeric"
  return True, "eligible"


def compare_sample(sample: dict, as_of_ms: int) -> dict:
  expected_kph = int(round(float(sample["speed_mps"]) * 3.6))
  features = query_nslr(float(sample["latitude"]), float(sample["longitude"]))
  eligible = []
  exclusions: dict[str, int] = {}
  for attributes in features:
    include, reason = simple_permanent_record(attributes, as_of_ms)
    if include:
      eligible.append(attributes)
    else:
      exclusions[reason] = exclusions.get(reason, 0) + 1

  current_values = sorted({int(feature["speedLimitZoneValue"]) for feature in eligible})
  if not current_values:
    status = "no_current_simple_record"
  elif len(current_values) > 1:
    status = "ambiguous_current_records"
  elif current_values[0] == expected_kph:
    status = "match"
  else:
    status = "mismatch"

  return {
    "latitude": sample["latitude"],
    "longitude": sample["longitude"],
    "bearing_degrees": sample["bearing_degrees"],
    "road_name": sample["road_name"],
    "mapd_speed_kph": expected_kph,
    "status": status,
    "nslr_current_values_kph": current_values,
    "eligible_record_count": len(eligible),
    "total_intersecting_record_count": len(features),
    "excluded_record_counts": exclusions,
    "eligible_records": eligible,
  }


def disposition_key(result: dict) -> tuple[str, str, str, int, tuple[int, ...]]:
  return (
    f"{float(result['latitude']):.5f}",
    f"{float(result['longitude']):.5f}",
    str(result["road_name"]),
    int(result["mapd_speed_kph"]),
    tuple(int(value) for value in result["nslr_current_values_kph"]),
  )


def apply_dispositions(results: list[dict], path: pathlib.Path | None) -> tuple[int, int]:
  if path is None:
    mismatch_count = sum(result["status"] == "mismatch" for result in results)
    return 0, mismatch_count

  payload = json.loads(path.read_text(encoding="utf-8"))
  entries = payload.get("dispositions")
  if not isinstance(entries, list):
    raise RuntimeError("Disposition file must contain a 'dispositions' list")

  by_key = {}
  for entry in entries:
    key = disposition_key(entry)
    if key in by_key:
      raise RuntimeError(f"Duplicate disposition for {key}")
    if not entry.get("classification") or not entry.get("rationale"):
      raise RuntimeError(f"Disposition for {key} needs classification and rationale")
    by_key[key] = entry

  used = set()
  for result in results:
    if result["status"] != "mismatch":
      continue
    key = disposition_key(result)
    disposition = by_key.get(key)
    if disposition is not None:
      result["review_disposition"] = {
        field: disposition[field]
        for field in ("classification", "rationale", "pilot_decision", "evidence")
        if field in disposition
      }
      used.add(key)

  unused = set(by_key) - used
  if unused:
    raise RuntimeError(f"Disposition entries did not match an NSLR mismatch: {sorted(unused)}")

  reviewed = len(used)
  mismatches = sum(result["status"] == "mismatch" for result in results)
  return reviewed, mismatches - reviewed


def write_csv(path: pathlib.Path, results: list[dict]) -> None:
  with path.open("w", newline="", encoding="utf-8") as file:
    writer = csv.writer(file)
    writer.writerow([
      "latitude", "longitude", "bearing_degrees", "road_name", "mapd_speed_kph", "status",
      "nslr_current_values_kph", "eligible_record_count", "total_intersecting_record_count",
    ])
    for result in results:
      writer.writerow([
        result["latitude"], result["longitude"], result["bearing_degrees"], result["road_name"],
        result["mapd_speed_kph"], result["status"],
        ";".join(str(value) for value in result["nslr_current_values_kph"]),
        result["eligible_record_count"], result["total_intersecting_record_count"],
      ])


def main() -> int:
  args = parse_args()
  as_of = parse_as_of(args.as_of)
  as_of_ms = int(as_of.timestamp() * 1000)
  source_summary = json.loads(args.validation_summary.read_text(encoding="utf-8"))
  samples = [sample for sample in source_summary["samples"] if float(sample["speed_mps"]) > 0]
  samples = samples[:args.max_samples]
  if len(samples) < 20:
    raise RuntimeError(f"Need at least 20 speed-bearing samples; found {len(samples)}")

  results = []
  for index, sample in enumerate(samples, start=1):
    results.append(compare_sample(sample, as_of_ms))
    print(f"queried NSLR sample {index}/{len(samples)}", file=sys.stderr)
    time.sleep(0.05)

  counts: dict[str, int] = {}
  for result in results:
    counts[result["status"]] = counts.get(result["status"], 0) + 1

  reviewed_conflicts, undispositioned_conflicts = apply_dispositions(results, args.dispositions)

  output = {
    "query_timestamp_utc": as_of.isoformat(),
    "nslr_query_url": NSLR_QUERY_URL,
    "nslr_item_url": NSLR_ITEM_URL,
    "method": (
      "Point-in-polygon comparison of mapd samples with currently effective, numeric, permanent NSLR "
      "records. Variable, seasonal, temporary, structure-specific, lane-specific, future, and expired "
      "records are excluded. No NSLR data is embedded in the map archive."
    ),
    "sample_count": len(results),
    "status_counts": counts,
    "reviewed_conflict_count": reviewed_conflicts,
    "undispositioned_conflict_count": undispositioned_conflicts,
    "results": results,
  }
  args.output_dir.mkdir(parents=True, exist_ok=True)
  (args.output_dir / "nslr-comparison.json").write_text(
    json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
  )
  write_csv(args.output_dir / "nslr-comparison.csv", results)

  print(json.dumps({"sample_count": len(results), "status_counts": counts}, sort_keys=True))
  return 1 if undispositioned_conflicts else 0


if __name__ == "__main__":
  raise SystemExit(main())
