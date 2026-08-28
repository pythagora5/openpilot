"""Identity metadata for the Lyle Pilot fork."""

FORK_NAME = "Lyle Pilot"
FORK_VERSION = "0.1.0"
FORK_MODE = "Experimental Mode"


def fork_version_label() -> str:
  return f"v{FORK_VERSION}"


def fork_signature() -> str:
  return f"{FORK_NAME}  {fork_version_label()}"
