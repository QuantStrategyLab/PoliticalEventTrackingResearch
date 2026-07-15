"""Pure guards for the existing RSS workflow boundary."""
from __future__ import annotations

from pathlib import PurePosixPath

CANONICAL_FEEDS = "config/free_rss_feeds.csv"
CANONICAL_ALIASES = "config/core_us_equity_aliases.csv"
CANONICAL_WATCHLIST = "data/live/political_watchlist.csv"


class PathBoundaryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_source_paths(feeds_path: object, aliases_path: object, watchlist_path: object) -> None:
    expected = (CANONICAL_FEEDS, CANONICAL_ALIASES, CANONICAL_WATCHLIST)
    actual = (feeds_path, aliases_path, watchlist_path)
    if any(type(value) is not str or value != expected_value for value, expected_value in zip(actual, expected, strict=True)):
        raise PathBoundaryError("workflow_input_path_invalid")
    for value in actual:
        path = PurePosixPath(value)
        if path.is_absolute() or value != str(path) or any(part in {"", ".", ".."} for part in path.parts) or "\\" in value:
            raise PathBoundaryError("workflow_input_path_invalid")
