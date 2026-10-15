"""Rolling window of telemetry frames (no ground-truth labels are used)."""
from collections import deque
from typing import Deque, List, Optional

from core.contracts import TelemetryFrame


class TelemetryStore:
    def __init__(self, maxlen: int = 600):
        self._frames: Deque[TelemetryFrame] = deque(maxlen=maxlen)

    def add(self, frame: TelemetryFrame) -> None:
        self._frames.append(frame)

    def clear(self) -> None:
        self._frames.clear()

    def __len__(self) -> int:
        return len(self._frames)

    def latest(self) -> Optional[TelemetryFrame]:
        return self._frames[-1] if self._frames else None

    def window(self, n: int) -> List[TelemetryFrame]:
        """The last n frames (fewer if the store holds fewer)."""
        return list(self._frames)[-n:] if n > 0 else []

    def values(self, tag: str, n: int) -> List[float]:
        return [f.values[tag] for f in self.window(n) if tag in f.values]


def slope(series: List[float]) -> float:
    """Least-squares slope per frame (0.0 when fewer than 2 points)."""
    n = len(series)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(series) / n
    num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(series))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den
