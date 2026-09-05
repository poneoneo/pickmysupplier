"""Per-search dataset naming and discovery.

Each live/demo scrape gets its own SQLite database, named after its search
keywords, so results from different searches never accumulate into the
same table (a shared `sourcing_intel.sqlite` used to mix e.g. a "thinkpad"
search with an earlier "wireless earbuds" one). `slugify` derives the
shared name used for both the scraped-pages folder and the database file;
`discover_databases`/`dataset_label` back the dataset picker in `app.py`.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

DB_PREFIX = "sourcing_intel"


def slugify(keywords: str) -> str:
	"""Turn free-text search keywords into a filesystem-safe slug.

	Shared by the scraped-pages folder and the per-search database file
	name, so a given search's raw HTML and its database stay obviously
	paired (both derived from e.g. "wireless earbuds" -> "wireless_earbuds").

	:param keywords: The raw search keywords typed by the user.
	:return: A slug with spaces replaced by underscores.
	"""
	return keywords.strip().replace(" ", "_")


def discover_databases(root: Path = Path(".")) -> list[Path]:
	"""List every per-search SQLite database under `root`.

	Also returns the legacy single `sourcing_intel.sqlite` (from before
	per-search databases existed — may hold a mix of several old searches)
	if it's still around; `dataset_label` marks it as such.

	:param root: Directory to search in — the project root by default.
	:return: Database paths, most recently modified first.
	"""
	candidates = list(root.glob(f"{DB_PREFIX}_*.sqlite"))
	legacy = root / f"{DB_PREFIX}.sqlite"
	if legacy.exists():
		candidates.append(legacy)
	return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def dataset_label(db_path: Path) -> str:
	"""Human-readable label for a database file, for the dataset selector.

	:param db_path: A database path as returned by `discover_databases`.
	:return: The search keywords it was created for (e.g. "wireless earbuds"),
		or a legacy marker for the pre-per-search `sourcing_intel.sqlite`.
	"""
	stem = db_path.stem
	if stem == DB_PREFIX:
		return f"{DB_PREFIX} (ancien, recherches mélangées)"
	return stem.removeprefix(f"{DB_PREFIX}_").replace("_", " ")


def cleanup_stale_sessions(root: Path = Path("sessions"), max_age_hours: int = 48) -> None:
	"""Delete session directories whose newest file is older than max_age_hours.

	Best-effort disk housekeeping for the per-session storage a live scrape
	creates (see `app.py::page_scraper`) — without this, `sessions/` would
	grow forever on the shared hosting disk, since nothing else ever removes
	a visitor's directory after they leave.

	:param root: Directory containing one subdirectory per session.
	:type root: Path
	:param max_age_hours: A session directory is deleted once its most
		recently modified file is older than this, in hours.
	:type max_age_hours: int
	:return: None
	:rtype: None
	"""
	if not root.exists():
		return
	cutoff = time.time() - max_age_hours * 3600
	for session_dir in root.iterdir():
		if not session_dir.is_dir():
			continue
		newest_mtime = max(
			(p.stat().st_mtime for p in session_dir.rglob("*") if p.is_file()),
			default=session_dir.stat().st_mtime,
		)
		if newest_mtime < cutoff:
			shutil.rmtree(session_dir)
