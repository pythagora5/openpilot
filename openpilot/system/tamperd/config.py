import unicodedata
from urllib.parse import urlsplit

TAMPER_ARM_VOLTAGE_MV = 12.4e3
TAMPER_DISARM_VOLTAGE_MV = 12.1e3
TAMPER_ARM_DURATION_S = 60.


def validate_ntfy_url(value: str) -> str:
  value = value.strip()
  if not value or len(value) > 2048 or any(char.isspace() or unicodedata.category(char).startswith("C") for char in value):
    raise ValueError("invalid ntfy URL")
  parsed = urlsplit(value)
  try:
    port = parsed.port
  except ValueError as exc:
    raise ValueError("invalid ntfy URL") from exc
  if (parsed.scheme != "https" or not parsed.hostname or not parsed.path.strip("/") or
      parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
    raise ValueError("invalid ntfy URL")
  if port is not None and not 1 <= port <= 65535:
    raise ValueError("invalid ntfy URL")
  return value.rstrip("/")
