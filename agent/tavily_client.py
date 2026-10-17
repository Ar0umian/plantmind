"""Tavily web search for context on an incident (FR-OPS-06).

Offline (MOCK_TAVILY=1, the default) it returns clearly labelled example references
that point only to MITRE ATT&CK technique pages. Live, it calls the Tavily API.
A failed or empty search never blocks a report (NFR-REL-03). Results are cached and
the number of live searches per run is limited.
"""
from typing import Callable, Dict, List, Optional, Tuple

from core.config import get_settings
from core.contracts import ReferenceLink

# Search phrasing per cause label (security-related causes look for advisories).
QUERIES: Dict[str, str] = {
    "logic_tampering": "PLC logic tampering water utility industrial control system advisory",
    "spoofing": "sensor reading spoofing manipulation of view water treatment SCADA advisory",
    "command_abuse": "unauthorized command message PLC water utility SCADA advisory",
    "sensor_fault": "chlorine residual analyzer failure troubleshooting water treatment",
    "process_upset": "water treatment process upset troubleshooting intake pump tank level",
    "unknown": "water utility SCADA anomaly industrial control system advisory",
}

# Offline example references per label: MITRE technique pages only.
_MOCK: Dict[str, List[Tuple[str, str]]] = {
    "logic_tampering": [("T0889 Modify Program", "https://attack.mitre.org/techniques/T0889/"),
                        ("T0836 Modify Parameter", "https://attack.mitre.org/techniques/T0836/")],
    "spoofing": [("T0832 Manipulation of View", "https://attack.mitre.org/techniques/T0832/"),
                 ("T0856 Spoof Reporting Message", "https://attack.mitre.org/techniques/T0856/")],
    "command_abuse": [("T0855 Unauthorized Command Message", "https://attack.mitre.org/techniques/T0855/"),
                      ("T0831 Manipulation of Control", "https://attack.mitre.org/techniques/T0831/")],
}

SearchFn = Callable[[str, int], List[dict]]


class TavilyClient:
    def __init__(self, search_fn: Optional[SearchFn] = None, mock: Optional[bool] = None,
                 max_live_searches: int = 20, min_score: float = 0.2):
        settings = get_settings()
        self.mock = settings.mock_tavily if mock is None else mock
        self._api_key = settings.tavily_api_key
        self._search_fn = search_fn
        self.max_live_searches = max_live_searches
        self.min_score = min_score
        self.stats: Dict[str, int] = {"live_searches": 0, "cache_hits": 0, "failures": 0}
        self._cache: Dict[str, List[ReferenceLink]] = {}

    def _live_search(self, query: str, max_results: int) -> List[dict]:
        if self._search_fn is not None:
            return self._search_fn(query, max_results)
        if not self._api_key:
            raise RuntimeError("TAVILY_API_KEY is not set in .env")
        from tavily import TavilyClient as SdkClient
        response = SdkClient(api_key=self._api_key).search(query=query, max_results=max_results)
        return list(response.get("results", []))

    def references_for(self, label: str, max_results: int = 3) -> List[ReferenceLink]:
        """References relevant to a cause label; [] when nothing is available."""
        query = QUERIES.get(label, QUERIES["unknown"])
        if self.mock:
            return [ReferenceLink(title=f"[offline example] {title}", url=url)
                    for title, url in _MOCK.get(label, [])][:max_results]
        if query in self._cache:
            self.stats["cache_hits"] += 1
            return self._cache[query]
        if self.stats["live_searches"] >= self.max_live_searches:
            return []
        self.stats["live_searches"] += 1
        try:
            raw = self._live_search(query, max_results)
        except Exception:
            self.stats["failures"] += 1
            return []
        links: List[ReferenceLink] = []
        for item in raw:
            url, title = str(item.get("url", "")).strip(), " ".join(str(item.get("title", "")).split())
            score = item.get("score")
            if not url.startswith(("http://", "https://")) or not title:
                continue
            if isinstance(score, (int, float)) and score < self.min_score:
                continue
            links.append(ReferenceLink(title=title[:160], url=url))
        links = links[:max_results]
        self._cache[query] = links
        return links
