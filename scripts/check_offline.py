"""Run inside the recovery API container; prove external access is unavailable."""

import json
import socket
import urllib.error
import urllib.request
from datetime import UTC, datetime

with socket.socket() as connection:
    connection.settimeout(3)
    external_errno = connection.connect_ex(("1.1.1.1", 443))
    assert external_errno != 0, "External TCP access unexpectedly available"

try:
    urllib.request.urlopen("https://api.openalex.org/works?per_page=1", timeout=3)
except urllib.error.HTTPError as exc:
    raise AssertionError("OpenAlex reachable via HTTP") from exc
except (urllib.error.URLError, TimeoutError, OSError) as exc:
    error_type = type(exc).__name__
else:
    raise AssertionError("OpenAlex unexpectedly reachable")

with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ready", timeout=30) as response:
    ready = json.load(response)
print(
    json.dumps(
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "external_tcp_errno": external_errno,
            "openalex_unreachable": True,
            "error_type": error_type,
            "ready": ready,
        },
        indent=2,
    )
)
