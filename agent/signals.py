"""A Signal is one currently-true finding from a deterministic check."""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Signal:
    key: str                 # stable identity of the episode, e.g. "interlock:IL-04"
    kind: str                # an Evidence kind (see core.contracts.Evidence)
    summary: str             # plain-language statement of what is inconsistent
    tags: Tuple[str, ...]    # tags involved
