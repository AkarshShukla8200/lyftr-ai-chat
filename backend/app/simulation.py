"""X-Simulate-Failure: request-scoped failure injection for chosen keys.

Format: comma-separated `<key_id>=<status>` pairs, `*` = every key.
Statuses: 429, 500, 502, 503. Honored only when ENABLE_FAILURE_SIMULATION is
exactly "true"; otherwise the header is never parsed.

Implementation choices (the PDF does not specify them):
- Whitespace around pairs and around `=` is tolerated.
- Well-formed but unknown key ids (e.g. key_9) are ignored.
- An explicit key entry overrides `*` for that key.
- Malformed syntax, an unsupported status, an empty pair or a duplicated key
  -> 422 with a JSON `detail` (raised as SimulationHeaderError).
- An empty / whitespace-only header value is treated as absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import litellm

SUPPORTED_STATUSES = (429, 500, 502, 503)
_KEY_ID = re.compile(r"^(\*|key_[1-9][0-9]*)$")

_EXCEPTIONS = {
    429: litellm.RateLimitError,
    500: litellm.InternalServerError,
    502: litellm.BadGatewayError,
    503: litellm.ServiceUnavailableError,
}


class SimulationHeaderError(ValueError):
    """Invalid X-Simulate-Failure value (reported as 422)."""


@dataclass(frozen=True)
class FailureSimulation:
    per_key: dict[str, int] = field(default_factory=dict)
    wildcard: Optional[int] = None

    def status_for(self, key_id: str) -> Optional[int]:
        return self.per_key.get(key_id, self.wildcard)

    def exception_for(self, key_id: str, model: str) -> Optional[Exception]:
        """The LiteLLM exception this key must raise for this request, if any."""
        status = self.status_for(key_id)
        if status is None:
            return None
        return _EXCEPTIONS[status](
            message=f"Simulated {status} via X-Simulate-Failure",
            llm_provider=model.split("/", 1)[0],
            model=model,
        )


def parse_simulation_header(value: Optional[str]) -> Optional[FailureSimulation]:
    if value is None or not value.strip():
        return None
    per_key: dict[str, int] = {}
    wildcard: Optional[int] = None
    for raw_pair in value.split(","):
        pair = raw_pair.strip()
        if not pair:
            raise SimulationHeaderError("X-Simulate-Failure contains an empty entry")
        if pair.count("=") != 1:
            raise SimulationHeaderError(
                "X-Simulate-Failure entries must look like key_1=429 or *=503"
            )
        key_part, status_part = (part.strip() for part in pair.split("="))
        if not _KEY_ID.match(key_part):
            raise SimulationHeaderError(f"X-Simulate-Failure has an invalid key id: {key_part[:40]!r}")
        if status_part not in {str(s) for s in SUPPORTED_STATUSES}:
            raise SimulationHeaderError(
                "X-Simulate-Failure status must be one of 429, 500, 502, 503"
            )
        status = int(status_part)
        if key_part == "*":
            if wildcard is not None:
                raise SimulationHeaderError("X-Simulate-Failure repeats '*'")
            wildcard = status
        else:
            if key_part in per_key:
                raise SimulationHeaderError(f"X-Simulate-Failure repeats {key_part}")
            per_key[key_part] = status
    return FailureSimulation(per_key=per_key, wildcard=wildcard)
