import hashlib
import io
import fcntl
from pathlib import Path
import stat
import tarfile

import pytest

from openpilot.sunnypilot.mapd import wellington_map_migration as migration


def build_archive(tmp_path: Path, names: tuple[str, ...] = ("tile-a", "tile-b")) -> tuple[Path, str, str]:
  archive_path = tmp_path / "test-map.tar.gz"
  file_digests = []
  with tarfile.open(archive_path, "w:gz") as archive:
    directory = tarfile.TarInfo(migration.GROUP_MEMBER.as_posix())
    directory.type = tarfile.DIRTYPE
    directory.mode = 0o755
    archive.addfile(directory)
    for name in names:
      data = f"map data for {name}".encode()
      member = tarfile.TarInfo(f"{migration.GROUP_MEMBER.as_posix()}/{name}")
      member.size = len(data)
      member.mode = 0o644
      archive.addfile(member, io.BytesIO(data))
      file_digests.append((name, hashlib.sha256(data).digest()))

  group_digest = hashlib.sha256()
  for name, digest in sorted(file_digests):
    group_digest.update(name.encode())
    group_digest.update(b"\0")
    group_digest.update(digest)
  return archive_path, migration._sha256(archive_path), group_digest.hexdigest()


def install_test_archive(archive: Path, archive_digest: str, group_digest: str, map_root: Path, **kwargs) -> str:
  return migration.install_wellington_map(
    archive,
    map_root,
    expected_archive_sha256=archive_digest,
    expected_group_digest=group_digest,
    expected_file_count=2,
    **kwargs,
  )


def target_path(map_root: Path) -> Path:
  return map_root / migration.GROUP_RELATIVE


def backup_path(map_root: Path) -> Path:
  target = target_path(map_root)
  return target.with_name(f"{target.name}.{migration.MIGRATION_ID}.backup")


def state_path(map_root: Path, suffix: str) -> Path:
  return map_root / f".{migration.MIGRATION_ID}.{suffix}"


def make_old_target(map_root: Path) -> Path:
  target = target_path(map_root)
  target.mkdir(parents=True)
  (target / "old-tile").write_text("original map data")
  return target


def test_install_when_target_is_absent(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  assert sorted(path.name for path in target_path(map_root).iterdir()) == ["tile-a", "tile-b"]
  assert not backup_path(map_root).exists()
  assert stat.S_IMODE(target_path(map_root).stat().st_mode) == 0o755
  assert all(stat.S_IMODE(path.stat().st_mode) == 0o644 for path in target_path(map_root).iterdir())


def test_existing_target_is_retained_as_backup(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  make_old_target(map_root)

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  assert (backup_path(map_root) / "old-tile").read_text() == "original map data"
  assert sorted(path.name for path in target_path(map_root).iterdir()) == ["tile-a", "tile-b"]


def test_second_invocation_is_idempotent(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  make_old_target(map_root)
  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  backup_contents = (backup_path(map_root) / "old-tile").read_text()

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "already_installed"
  assert (backup_path(map_root) / "old-tile").read_text() == backup_contents


def test_second_invocation_uses_verified_marker_without_rereading_archive(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  archive.unlink()

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "already_installed"


def test_malformed_marker_file_list_is_replaced(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  marker = state_path(map_root, "installed.json")
  payload = migration._read_json(marker)
  payload["files"] = [{"not": "a filename"}, "tile-b"]
  migration._atomic_json(marker, payload)

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "already_installed"
  assert migration._read_json(marker)["files"] == ["tile-a", "tile-b"]


def test_bad_archive_checksum_does_not_change_target(tmp_path):
  archive, _, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  target = make_old_target(map_root)

  with pytest.raises(migration.MigrationError, match="SHA-256 mismatch"):
    install_test_archive(archive, "0" * 64, group_digest, map_root)
  assert (target / "old-tile").read_text() == "original map data"
  assert not backup_path(map_root).exists()


@pytest.mark.parametrize("member_name", ("offline/-42/outside", "/offline/-42/174/absolute", "offline/-42/174/../escape"))
def test_unsafe_archive_member_is_rejected(tmp_path, member_name):
  archive_path = tmp_path / "unsafe.tar.gz"
  with tarfile.open(archive_path, "w:gz") as archive:
    directory = tarfile.TarInfo(migration.GROUP_MEMBER.as_posix())
    directory.type = tarfile.DIRTYPE
    archive.addfile(directory)
    data = b"unsafe"
    member = tarfile.TarInfo(member_name)
    member.size = len(data)
    archive.addfile(member, io.BytesIO(data))

  with pytest.raises(migration.MigrationError, match="Unsafe archive path|outside the expected tile group"):
    migration.install_wellington_map(
      archive_path,
      tmp_path / "osm",
      expected_archive_sha256=migration._sha256(archive_path),
      expected_group_digest="unused",
      expected_file_count=1,
    )


def test_duplicate_archive_member_is_rejected(tmp_path):
  archive_path = tmp_path / "duplicate.tar.gz"
  with tarfile.open(archive_path, "w:gz") as archive:
    directory = tarfile.TarInfo(migration.GROUP_MEMBER.as_posix())
    directory.type = tarfile.DIRTYPE
    archive.addfile(directory)
    for _ in range(2):
      data = b"duplicate"
      member = tarfile.TarInfo(f"{migration.GROUP_MEMBER.as_posix()}/tile-a")
      member.size = len(data)
      archive.addfile(member, io.BytesIO(data))

  with pytest.raises(migration.MigrationError, match="duplicate member names"):
    migration.install_wellington_map(
      archive_path,
      tmp_path / "osm",
      expected_archive_sha256=migration._sha256(archive_path),
      expected_group_digest="unused",
      expected_file_count=2,
    )


@pytest.mark.parametrize("member_type", (tarfile.SYMTYPE, tarfile.CHRTYPE))
def test_special_archive_member_type_is_rejected(tmp_path, member_type):
  archive_path = tmp_path / "special.tar.gz"
  with tarfile.open(archive_path, "w:gz") as archive:
    directory = tarfile.TarInfo(migration.GROUP_MEMBER.as_posix())
    directory.type = tarfile.DIRTYPE
    archive.addfile(directory)
    member = tarfile.TarInfo(f"{migration.GROUP_MEMBER.as_posix()}/not-a-regular-file")
    member.type = member_type
    if member_type == tarfile.SYMTYPE:
      member.linkname = "tile-a"
    archive.addfile(member)

  with pytest.raises(migration.MigrationError, match="Unsupported archive member type"):
    migration.install_wellington_map(
      archive_path,
      tmp_path / "osm",
      expected_archive_sha256=migration._sha256(archive_path),
      expected_group_digest="unused",
      expected_file_count=1,
    )


def test_wrong_group_digest_restores_unchanged_target(tmp_path):
  archive, archive_digest, _ = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  target = make_old_target(map_root)

  with pytest.raises(migration.MigrationError, match="digest mismatch"):
    install_test_archive(archive, archive_digest, "0" * 64, map_root)
  assert (target / "old-tile").read_text() == "original map data"
  assert not backup_path(map_root).exists()


def test_restart_recovers_interruption_after_old_target_move(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  make_old_target(map_root)

  with pytest.raises(migration.SimulatedPowerLoss, match="after_old_target_move"):
    install_test_archive(archive, archive_digest, group_digest, map_root, failpoint="after_old_target_move")
  assert not target_path(map_root).exists()
  assert (backup_path(map_root) / "old-tile").read_text() == "original map data"

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  assert (backup_path(map_root) / "old-tile").read_text() == "original map data"
  assert sorted(path.name for path in target_path(map_root).iterdir()) == ["tile-a", "tile-b"]


def test_restart_recovers_interruption_after_prepared_transaction(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  make_old_target(map_root)

  with pytest.raises(migration.SimulatedPowerLoss, match="after_prepared"):
    install_test_archive(archive, archive_digest, group_digest, map_root, failpoint="after_prepared")
  assert (target_path(map_root) / "old-tile").read_text() == "original map data"

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  assert (backup_path(map_root) / "old-tile").read_text() == "original map data"


def test_restart_recovers_interruption_without_a_prior_target(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"

  with pytest.raises(migration.SimulatedPowerLoss, match="after_old_target_move"):
    install_test_archive(archive, archive_digest, group_digest, map_root, failpoint="after_old_target_move")
  assert not target_path(map_root).exists()
  assert not backup_path(map_root).exists()

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  assert not backup_path(map_root).exists()


def test_restart_finalizes_interruption_after_target_swap(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  make_old_target(map_root)

  with pytest.raises(migration.SimulatedPowerLoss, match="after_target_swap"):
    install_test_archive(archive, archive_digest, group_digest, map_root, failpoint="after_target_swap")
  assert sorted(path.name for path in target_path(map_root).iterdir()) == ["tile-a", "tile-b"]
  assert (backup_path(map_root) / "old-tile").read_text() == "original map data"

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "already_installed"
  assert (backup_path(map_root) / "old-tile").read_text() == "original map data"


def test_existing_backup_without_marker_self_heals_without_overwrite(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  target = make_old_target(map_root)
  backup = backup_path(map_root)
  backup.mkdir(parents=True)
  (backup / "sentinel").write_text("keep me")

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  assert (backup / "sentinel").read_text() == "keep me"
  collision = target.with_name(f"{target.name}.backup-collision-target")
  assert (collision / "old-tile").read_text() == "original map data"
  assert sorted(path.name for path in target.iterdir()) == ["tile-a", "tile-b"]


def test_changed_installed_group_is_repaired_without_overwriting_backup(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  make_old_target(map_root)
  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  backup_contents = (backup_path(map_root) / "old-tile").read_text()
  (target_path(map_root) / "tile-a").write_text("changed by another downloader")

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  assert (backup_path(map_root) / "old-tile").read_text() == backup_contents
  assert migration._group_digest(target_path(map_root), {"tile-a", "tile-b"}, 2) == group_digest


def test_repeated_failures_do_not_accumulate_staging_directories(tmp_path):
  archive, archive_digest, _ = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  make_old_target(map_root)

  for _ in range(3):
    with pytest.raises(migration.MigrationError, match="digest mismatch"):
      install_test_archive(archive, archive_digest, "0" * 64, map_root)

  assert not state_path(map_root, "stage").exists()
  assert not list(map_root.glob(f".{migration.MIGRATION_ID}.stage*"))


def test_nonblocking_lock_does_not_delay_startup(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  map_root.mkdir()
  lock_path = state_path(map_root, "lock")

  with lock_path.open("a+") as held_lock:
    fcntl.flock(held_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(migration.MigrationError, match="already running"):
      install_test_archive(archive, archive_digest, group_digest, map_root)


def test_foreign_transaction_is_bounded_and_does_not_wedge_install(tmp_path):
  archive, archive_digest, group_digest = build_archive(tmp_path)
  map_root = tmp_path / "osm"
  make_old_target(map_root)
  transaction = state_path(map_root, "transaction.json")
  transaction.write_text('{"migration": "foreign"}')

  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "installed"
  preserved = state_path(map_root, "transaction.json.unrecognized-transaction")
  assert preserved.is_file()
  assert install_test_archive(archive, archive_digest, group_digest, map_root) == "already_installed"
  assert len(list(map_root.glob(f".{migration.MIGRATION_ID}.transaction.json.unrecognized-transaction*"))) == 1


def test_launch_continues_after_migration_failure():
  launch = (Path(migration.BASEDIR) / "launch_chffrplus.sh").read_text()
  migration_call = 'if ! PYTHONPATH="$DIR" python3 "$DIR/openpilot/sunnypilot/mapd/wellington_map_migration.py"; then'
  assert migration_call in launch
  assert "continuing with existing map data" in launch
  assert launch.index(migration_call) < launch.index("# start manager")


def test_migration_does_not_reference_cruise_parameters():
  source = Path(migration.__file__).read_text()
  for forbidden in ("openpilot.common.params", "SpeedLimitMode", "SpeedLimitPolicy", "SmartCruiseControlMap"):
    assert forbidden not in source


def test_real_bundled_archive_installs_and_matches_digest(tmp_path):
  assert migration.ARCHIVE_PATH.is_file()
  map_root = tmp_path / "osm"
  assert migration.install_wellington_map(migration.ARCHIVE_PATH, map_root) == "installed"
  files = tuple(target_path(map_root).iterdir())
  assert len(files) == migration.EXPECTED_FILE_COUNT
  assert migration._group_digest(target_path(map_root), {path.name for path in files}, migration.EXPECTED_FILE_COUNT) == migration.GROUP_DIGEST
