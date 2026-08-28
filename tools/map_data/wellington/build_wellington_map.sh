#!/usr/bin/env bash
set -euo pipefail

MAPD_TAG="v1.12.0"
MAPD_COMMIT="46cd71ade6f630f1564c83bf1763f9d949a9ff30"
PBF_DATE="2026-08-01"
PBF_URL="https://download.geofabrik.de/australia-oceania/new-zealand-260801.osm.pbf"
PBF_MD5="6017be7654025cd719d0ebc910923ce3"
ARCHIVE_VERSION="v1"
ARCHIVE_NAME="lyle-pilot-wellington-mapd-${MAPD_TAG}-osm-${PBF_DATE}-${ARCHIVE_VERSION}.tar.gz"
SOURCE_DATE_EPOCH="1785542400"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${WELLINGTON_WORK_DIR:-${RUNNER_TEMP:-/tmp}/lyle-pilot-wellington-map}"
OUTPUT_DIR="${WELLINGTON_OUTPUT_DIR:-${WORK_DIR}/output}"
MAPD_DIR="${WORK_DIR}/mapd"

case "${WORK_DIR}" in
  */wellington-map|*/wellington-map/*) ;;
  *)
    echo "Refusing unsafe work directory: ${WORK_DIR}" >&2
    exit 1
    ;;
esac

required_commands=(curl git go gzip md5sum osmium pkg-config sha256sum tar)
for command_name in "${required_commands[@]}"; do
  command -v "${command_name}" >/dev/null
done

rm -rf -- "${WORK_DIR}"
mkdir -p "${WORK_DIR}" "${OUTPUT_DIR}"

git clone --quiet --branch "${MAPD_TAG}" --depth 1 https://github.com/pfeiferj/openpilot-mapd.git "${MAPD_DIR}"
actual_mapd_commit="$(git -C "${MAPD_DIR}" rev-parse HEAD)"
if [[ "${actual_mapd_commit}" != "${MAPD_COMMIT}" ]]; then
  echo "Unexpected mapd commit: ${actual_mapd_commit}" >&2
  exit 1
fi

curl --fail --location --retry 5 --output "${WORK_DIR}/new-zealand.osm.pbf" "${PBF_URL}"
printf '%s  %s\n' "${PBF_MD5}" "${WORK_DIR}/new-zealand.osm.pbf" | md5sum --check --strict
(cd "${WORK_DIR}" && sha256sum new-zealand.osm.pbf) > "${OUTPUT_DIR}/new-zealand.osm.pbf.sha256"
osmium fileinfo --extended "${WORK_DIR}/new-zealand.osm.pbf" > "${OUTPUT_DIR}/source-fileinfo.txt"

rm -f "${WORK_DIR}/filtered.osm.pbf" "${WORK_DIR}/box.osm.pbf" "${MAPD_DIR}/map.osm.pbf"
osmium tags-filter \
  "${WORK_DIR}/new-zealand.osm.pbf" \
  "nw/highway=motorway,trunk,primary,secondary,tertiary,unclassified,residential,motorway_link,trunk_link,primary_link,secondary_link,tertiary_link" \
  --output "${WORK_DIR}/filtered.osm.pbf"
osmium fileinfo --extended "${WORK_DIR}/filtered.osm.pbf" > "${OUTPUT_DIR}/filtered-fileinfo.txt"

# The target group is lon 174..176, lat -42..-40. A one-degree buffer
# reproduces upstream intent without ever exceeding valid coordinate ranges.
MIN_LON=173
MIN_LAT=-43
MAX_LON=177
MAX_LAT=-39
if (( MIN_LON < -180 || MAX_LON > 180 || MIN_LAT < -90 || MAX_LAT > 90 )); then
  echo "Invalid extraction bounds" >&2
  exit 1
fi

osmium extract \
  --strategy complete_ways \
  --bbox "${MIN_LON},${MIN_LAT},${MAX_LON},${MAX_LAT}" \
  "${WORK_DIR}/filtered.osm.pbf" \
  --output "${WORK_DIR}/box.osm.pbf"
osmium fileinfo --extended "${WORK_DIR}/box.osm.pbf" > "${OUTPUT_DIR}/box-fileinfo.txt"

osmium add-locations-to-ways \
  "${WORK_DIR}/box.osm.pbf" \
  --output "${MAPD_DIR}/map.osm.pbf"
osmium fileinfo --extended "${MAPD_DIR}/map.osm.pbf" > "${OUTPUT_DIR}/located-fileinfo.txt"

for report_name in filtered box located; do
  report_path="${OUTPUT_DIR}/${report_name}-fileinfo.txt"
  if ! grep -Eq 'Number of ways:[[:space:]]+[1-9][0-9]*' "${report_path}"; then
    echo "No ways found in ${report_name} data" >&2
    exit 1
  fi
done

(
  cd "${MAPD_DIR}"
  go mod download
  go build -trimpath -o mapd .
  ./mapd --generate --minlat -42 --minlon 174 --maxlat -40 --maxlon 176 --generate-empty-files
  cp "${SCRIPT_DIR}/wellington_validation_test.go" ./wellington_validation_test.go
  WELLINGTON_REPORT_DIR="${OUTPUT_DIR}" go test -run '^TestWellingtonPilot$' -count=1 -v . | tee "${OUTPUT_DIR}/go-validation.log"
  rm ./wellington_validation_test.go
)

tile_dir="${MAPD_DIR}/offline/-42/174"
if [[ "$(find "${tile_dir}" -maxdepth 1 -type f | wc -l | tr -d ' ')" != "64" ]]; then
  echo "Expected exactly 64 tile files" >&2
  exit 1
fi

find "${MAPD_DIR}/offline" -type d -exec chmod 0755 {} +
find "${MAPD_DIR}/offline" -type f -exec chmod 0644 {} +
find "${MAPD_DIR}/offline" -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +

pack_archive() {
  local output_path="$1"
  (
    cd "${MAPD_DIR}"
    tar \
      --sort=name \
      --mtime="@${SOURCE_DATE_EPOCH}" \
      --owner=0 \
      --group=0 \
      --numeric-owner \
      --format=gnu \
      -cf - offline/-42/174 \
      | gzip --no-name --best > "${output_path}"
  )
}

pack_archive "${OUTPUT_DIR}/${ARCHIVE_NAME}"
pack_archive "${OUTPUT_DIR}/${ARCHIVE_NAME}.reproducibility-check"
cmp "${OUTPUT_DIR}/${ARCHIVE_NAME}" "${OUTPUT_DIR}/${ARCHIVE_NAME}.reproducibility-check"
rm "${OUTPUT_DIR}/${ARCHIVE_NAME}.reproducibility-check"

(cd "${OUTPUT_DIR}" && sha256sum "${ARCHIVE_NAME}") > "${OUTPUT_DIR}/${ARCHIVE_NAME}.sha256"
tar -tzvf "${OUTPUT_DIR}/${ARCHIVE_NAME}" > "${OUTPUT_DIR}/archive-members.txt"

{
  echo "archive_name=${ARCHIVE_NAME}"
  echo "archive_version=${ARCHIVE_VERSION}"
  echo "mapd_tag=${MAPD_TAG}"
  echo "mapd_commit=${MAPD_COMMIT}"
  echo "pbf_date=${PBF_DATE}"
  echo "pbf_url=${PBF_URL}"
  echo "pbf_md5=${PBF_MD5}"
  echo "pbf_sha256=$(cut -d ' ' -f 1 "${OUTPUT_DIR}/new-zealand.osm.pbf.sha256")"
  echo "archive_sha256=$(cut -d ' ' -f 1 "${OUTPUT_DIR}/${ARCHIVE_NAME}.sha256")"
  echo "source_date_epoch=${SOURCE_DATE_EPOCH}"
  echo "go_version=$(go version)"
  echo "osmium_version=$(osmium --version | head -1)"
  echo "tar_version=$(tar --version | head -1)"
  echo "gzip_version=$(gzip --version | head -1)"
  echo "runner_image_os=${ImageOS:-unknown}"
  echo "runner_image_version=${ImageVersion:-unknown}"
  if command -v dpkg-query >/dev/null; then
    dpkg-query -W -f='package_${binary:Package}=${Version}\n' osmium-tool golang-go git curl gzip pkg-config tar zlib1g-dev 2>/dev/null || true
  fi
} > "${OUTPUT_DIR}/build-manifest.env"

echo "Built ${OUTPUT_DIR}/${ARCHIVE_NAME}"
