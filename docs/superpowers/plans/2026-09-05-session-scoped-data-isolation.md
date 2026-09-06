# Session-Scoped Data Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop one public visitor's scraped data, downloadable results, and ScrapingBee-key usage from being visible to or shared with any other visitor, and fix a module-global race condition in the scraper's HTML-collection loop.

**Architecture:** Namespace every artifact a live scrape produces (raw HTML, SQLite DB) under `sessions/<session_id>/`, where `session_id` is generated once per Streamlit session and stored in `st.session_state`. The Explorer page's dataset picker only ever looks inside the current session's own directory (plus the shared, synthetic demo dataset). A process-wide, TTL-cached cleanup call deletes session directories older than 48h so the shared disk doesn't grow forever. Separately, replace the module-global `HTML_PAGE_RESULT` list in the scraper's page-collection loop with a value returned from the function call, removing a real cross-visitor race condition.

**Tech Stack:** Python, Streamlit (`st.session_state`, `st.cache_resource`), SQLModel/SQLAlchemy (SQLite), pytest, `pathlib`.

**Spec:** `docs/superpowers/specs/2026-09-05-session-scoped-data-isolation-design.md`

## Global Constraints

- No user accounts, login, or authentication — explicitly excluded by the spec.
- No cron job or external scheduler for cleanup — best-effort only, via `st.cache_resource(ttl=...)`.
- The demo dataset (`sourcing_intel_demo.sqlite`) stays shared/unscoped — it's synthetic (seed=42) and identical for every visitor, no privacy concern.
- Indentation is tabs, not spaces (existing project convention — match surrounding code).
- Docstrings are Sphinx/reST style: `:param x:`, `:type x:`, `:return:`, `:rtype:`.
- Type hints on all function signatures.
- Logging via `loguru.logger`; no `print()` outside `app.py` (which uses Streamlit's `st.*` display primitives instead).
- Always run `python -m pytest` and `python -m ruff check .` — never bare `pytest`/`ruff` (the package isn't installed, so only `python -m` puts the repo root on `sys.path`).

---

### Task 1: Remove the `HTML_PAGE_RESULT` global race condition

**Files:**
- Modify: `sourcing_intel_cli/proxies_utils.py`
- Modify: `sourcing_intel_cli/proxies_providers.py`
- Test: `tests/test_proxies_providers.py`

**Interfaces:**
- Produces: `_collect_html_pages(api_request, endpoint: str, api_key: str, key_words: str, page_results: int, progress, task) -> list[str]` — module-level function in `proxies_providers.py`, used by `ScrapingBeeProxyProvider.sync_scraper` (Task 4/5 do not touch this — no other task depends on this interface, but it must exist for `sync_scraper` to keep working).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_proxies_providers.py`, after the existing `TestFetchViaScrapingbee` class:

```python
from sourcing_intel_cli.proxies_providers import _collect_html_pages  # add to the existing import block from sourcing_intel_cli.proxies_providers


class _SequentialStubAPIRequest:
	"""Returns a different stubbed response for each successive `.get()` call."""

	def __init__(self, responses):
		self._responses = list(responses)
		self.urls_requested = []

	def get(self, url, params=None, timeout=None):
		self.urls_requested.append(url)
		return self._responses[len(self.urls_requested) - 1]


class _NoOpProgress:
	def start_task(self, task):
		pass

	def update(self, task, advance):
		pass


class TestCollectHtmlPages:
	def test_collects_html_from_each_successful_page(self):
		stub = _SequentialStubAPIRequest(
			[_StubResponse(200, "<html>page1</html>"), _StubResponse(200, "<html>page2</html>")]
		)
		pages = _collect_html_pages(
			stub, "https://endpoint.example", "my-key", "wireless earbuds", 2, _NoOpProgress(), task=None
		)
		assert pages == ["<html>page1</html>", "<html>page2</html>"]

	def test_skips_failed_pages_without_raising(self):
		stub = _SequentialStubAPIRequest([_StubResponse(500), _StubResponse(200, "<html>page2</html>")])
		pages = _collect_html_pages(
			stub, "https://endpoint.example", "my-key", "wireless earbuds", 2, _NoOpProgress(), task=None
		)
		assert pages == ["<html>page2</html>"]

	def test_two_calls_do_not_share_state(self):
		# Regression test: this loop used to accumulate into a module-global
		# list (`HTML_PAGE_RESULT`) shared by every call — a second scrape
		# (a different site visitor, running concurrently) would see the
		# first scrape's pages mixed into its own results. Each call must
		# return its own independent list.
		first_stub = _SequentialStubAPIRequest([_StubResponse(200, "<html>first</html>")])
		first_pages = _collect_html_pages(
			first_stub, "https://endpoint.example", "my-key", "thinkpad", 1, _NoOpProgress(), task=None
		)

		second_stub = _SequentialStubAPIRequest([_StubResponse(200, "<html>second</html>")])
		second_pages = _collect_html_pages(
			second_stub, "https://endpoint.example", "my-key", "wireless earbuds", 1, _NoOpProgress(), task=None
		)

		assert first_pages == ["<html>first</html>"]
		assert second_pages == ["<html>second</html>"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_proxies_providers.py::TestCollectHtmlPages -v`
Expected: FAIL with `ImportError: cannot import name '_collect_html_pages'`

- [ ] **Step 3: Extract `_collect_html_pages` and remove the global**

In `sourcing_intel_cli/proxies_providers.py`, change the import line:

```python
from .proxies_utils import urls_pusher, HTML_PAGE_RESULT
```

to:

```python
from .proxies_utils import urls_pusher
```

Add this new module-level function right before `class ScrapingBeeProxyProvider:`:

```python
def _collect_html_pages(
	api_request,
	endpoint: str,
	api_key: str,
	key_words: str,
	page_results: int,
	progress,
	task,
) -> list[str]:
	"""Fetch every result page's HTML into a list local to this call.

	A local list instead of the old module-global `HTML_PAGE_RESULT` — two
	scrapes running at once (two different site visitors) used to share
	and clobber the same global list; each call now gets its own.

	:param api_request: A Playwright `APIRequestContext` (or a stub, see
		`tests/test_proxies_providers.py`).
	:param endpoint: The ScrapingBee REST endpoint.
	:type endpoint: str
	:param api_key: The resolved ScrapingBee API key.
	:type api_key: str
	:param key_words: The search term(s) for finding products.
	:type key_words: str
	:param page_results: The number of pages to scrape.
	:type page_results: int
	:param progress: The `rich.progress.Progress` bar to advance as pages complete.
	:param task: The `Progress` task id returned by `progress.add_task`.
	:return: The HTML content of every page that responded OK, in order.
	:rtype: list[str]
	"""
	html_pages: list[str] = []
	for url in urls_pusher(words=key_words, stop_at=page_results):
		logger.info(f"Loading page {url.split('page=')[1]} ... ")
		response = _fetch_via_scrapingbee(api_request, endpoint, api_key, url)
		if not response.ok:
			logger.warning(
				f"ScrapingBee request failed for page {url.split('page=')[1]} "
				f"(status {response.status}), skipping it."
			)
			continue
		logger.info(
			f"Returns the text representation of response body from page {url.split('page=')[1]} ... "
		)
		progress.start_task(task)
		html_pages.append(response.text())
		progress.update(task, advance=100 / page_results)
		logger.info(f"Closing the page {url.split('page=')[1]} ... ")
	return html_pages
```

Then replace the body of `ScrapingBeeProxyProvider.sync_scraper` — remove the `global HTML_PAGE_RESULT` / `HTML_PAGE_RESULT.clear()` line and the inline for-loop, and call the new function instead. The method becomes:

```python
	@classmethod
	def sync_scraper(
		cls, *, save_in: str, key_words: str, page_results: int, api_key: str | None = None
	) -> None:
		"""
		Initiates synchronous scraping via the ScrapingBee API based on the provided keywords.

		ScrapingBee renders the target page server-side (JS execution included) and returns
		the resulting HTML in the response body, so no local browser navigation is needed —
		Playwright's request context is used purely as an HTTP client.

		:param save_in: The directory to store the raw HTML files.
		:type save_in: str
		:param key_words: The search term(s) for finding products on Alibaba.
		:type key_words: str
		:param page_results: The number of pages to scrape.
		:type page_results: int
		:param api_key: A visitor-supplied ScrapingBee key to use instead of the
			owner's `SCRAPINGBEE_API_KEY` from `.env`, if provided.
		:type api_key: str | None
		:return: None
		:rtype: None
		:raises RuntimeError: If no API key is set (neither `api_key` nor the
			owner's `.env` key).
		:raises ScrapingBeeKeyError: If ScrapingBee reports the resolved key
			is out of credits (HTTP 429) or invalid/revoked/expired (HTTP
			401) — callers should catch this before the generic
			`RuntimeError` to show a specific "your key isn't working"
			message rather than a generic scraping-failed one.
		"""
		resolved_key = _resolve_scrapingbee_key(api_key, cls.SB_API_KEY)
		if resolved_key == "":
			rprint("[red]You need to set your  API key to use ScrapingBee proxies ... [/red]")
			raise RuntimeError("You need to set your ScrapingBee API key to use ScrapingBee proxies.")
		with Progress(
			SpinnerColumn(finished_text="[bold green]finished ✓[/bold green]"),
			*Progress.get_default_columns(),
			transient=True,
		) as progress:
			task = progress.add_task(
				"[green blink] Sync Scraping...",
				start=False,
			)
			playwright = sync_playwright().start()
			api_request = playwright.request.new_context()
			try:
				html_pages = _collect_html_pages(
					api_request, cls.ENDPOINT, resolved_key, key_words, page_results, progress, task
				)
			finally:
				api_request.dispose()
				playwright.stop()
		write_to_disk(save_in, html_pages)
```

In `sourcing_intel_cli/proxies_utils.py`, remove the `HTML_PAGE_RESULT = []` line entirely — the file should contain only the `urls_pusher` function afterward.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_proxies_providers.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 5: Lint and commit**

Run: `python -m ruff check .`
Expected: no new errors.

```bash
git add sourcing_intel_cli/proxies_providers.py sourcing_intel_cli/proxies_utils.py tests/test_proxies_providers.py
git commit -m "fix: remove HTML_PAGE_RESULT global race in scraper page collection"
```

---

### Task 2: `create_db_engine` creates missing parent directories

**Files:**
- Modify: `sourcing_intel_cli/engine_and_database.py`
- Test: `tests/test_engine_and_database.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `create_db_engine(db_name: str = "", db_url: str = "")` now also creates any missing parent directories of the resulting `.sqlite` file when `db_name` is used (unchanged signature/return — Task 4 relies on this so `db_name="sessions/<id>/db/sourcing_intel_<slug>"` works without a pre-existing directory).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_engine_and_database.py`, after the `db_engine` fixture:

```python
class TestCreateDbEngine:
	def test_creates_missing_parent_directories_for_db_name(self, tmp_path, monkeypatch):
		monkeypatch.chdir(tmp_path)
		engine = create_db_engine(db_name="sessions/abc123/db/sourcing_intel_thinkpad")
		save_all_changes(engine_db=engine, sql_model=SQLModel)
		assert (tmp_path / "sessions" / "abc123" / "db" / "sourcing_intel_thinkpad.sqlite").exists()
		engine.dispose()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_engine_and_database.py::TestCreateDbEngine -v`
Expected: FAIL — `sqlalchemy.exc.OperationalError` (unable to open database file), since `sessions/abc123/db/` doesn't exist yet.

- [ ] **Step 3: Implement the minimal fix**

In `sourcing_intel_cli/engine_and_database.py`, add the import:

```python
from pathlib import Path
```

(add it near the top, alongside `from typing import Sequence`).

Change `create_db_engine`:

```python
def create_db_engine(db_name: str = "", db_url: str = ""):
	"""This function creates a new database engine using SQLAlchemy's create_engine method.

	The function takes two arguments: db_name and db_url. db_name is the name of the database
	and db_url is the connection string for the database. If db_url is not provided, the
	function will use a default connection string based on db_name.

	The function returns a new database engine object.

	:param db_name: The name of the database.
	:type db_name: str
	:param db_url: The connection string for the database.
	:type db_url: str
	:return: A new database engine object.
	:rtype: sqlalchemy.engine.Engine
	"""
	if not db_url:
		Path(f"{db_name}.sqlite").parent.mkdir(parents=True, exist_ok=True)
	db_url = db_url if db_url else f"sqlite:///{db_name}.sqlite"
	return create_engine(db_url)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_engine_and_database.py -v`
Expected: PASS (all tests, including pre-existing ones — `db_url="sqlite:///:memory:"` usage is untouched since the `mkdir` only runs when `db_url` is empty)

- [ ] **Step 5: Lint and commit**

Run: `python -m ruff check .`

```bash
git add sourcing_intel_cli/engine_and_database.py tests/test_engine_and_database.py
git commit -m "fix: create_db_engine creates missing parent directories for db_name"
```

---

### Task 3: `cleanup_stale_sessions` in `datasets.py`

**Files:**
- Modify: `sourcing_intel_cli/datasets.py`
- Test: `tests/test_datasets.py`

**Interfaces:**
- Produces: `cleanup_stale_sessions(root: Path = Path("sessions"), max_age_hours: int = 48) -> None` — used by `app.py` (Task 6).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_datasets.py`:

```python
import os

from sourcing_intel_cli.datasets import cleanup_stale_sessions


class TestCleanupStaleSessions:
	def test_deletes_session_dir_older_than_max_age(self, tmp_path):
		old_session = tmp_path / "old123"
		old_file = old_session / "db" / "sourcing_intel_thinkpad.sqlite"
		old_file.parent.mkdir(parents=True)
		old_file.touch()
		old_time = time.time() - 49 * 3600
		os.utime(old_file, (old_time, old_time))

		cleanup_stale_sessions(root=tmp_path, max_age_hours=48)

		assert not old_session.exists()

	def test_keeps_recent_session_dir(self, tmp_path):
		recent_session = tmp_path / "recent456"
		recent_session.mkdir()
		(recent_session / "marker.txt").touch()

		cleanup_stale_sessions(root=tmp_path, max_age_hours=48)

		assert recent_session.exists()

	def test_missing_root_does_not_raise(self, tmp_path):
		cleanup_stale_sessions(root=tmp_path / "does_not_exist", max_age_hours=48)


class TestDiscoverDatabasesIsolation:
	def test_does_not_see_files_in_a_different_root(self, tmp_path):
		# Regression coverage for the session-scoping fix: two visitors get
		# two different `root` directories, and one must never see the
		# other's databases — `discover_databases` already only globs the
		# given `root`, this pins that behavior down explicitly.
		root_a = tmp_path / "session_a" / "db"
		root_b = tmp_path / "session_b" / "db"
		root_a.mkdir(parents=True)
		root_b.mkdir(parents=True)
		(root_a / f"{DB_PREFIX}_thinkpad.sqlite").touch()

		assert discover_databases(root_b) == []
```

(`time` is already imported at the top of `tests/test_datasets.py` for `TestDiscoverDatabases.test_most_recently_modified_first` — add the `import os` line and the new import from `sourcing_intel_cli.datasets` alongside the existing ones.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_datasets.py::TestCleanupStaleSessions -v`
Expected: FAIL with `ImportError: cannot import name 'cleanup_stale_sessions'`

- [ ] **Step 3: Implement `cleanup_stale_sessions`**

In `sourcing_intel_cli/datasets.py`, add imports at the top:

```python
import shutil
import time
from pathlib import Path
```

(replacing the current single `from pathlib import Path` line with these three).

Add the function at the end of the file:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_datasets.py -v`
Expected: PASS (all tests, including pre-existing ones)

- [ ] **Step 5: Lint and commit**

Run: `python -m ruff check .`

```bash
git add sourcing_intel_cli/datasets.py tests/test_datasets.py
git commit -m "feat: add cleanup_stale_sessions for per-session storage housekeeping"
```

---

### Task 4: Session-scoped storage for the live scraper (`app.py::page_scraper`)

No pytest coverage exists for `app.py` (Streamlit UI code — see `tests/` directory, no `test_app.py`; this matches the existing project convention of verifying UI changes by running the app, per CLAUDE.md). This task is verified manually by running the app.

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `create_db_engine` (Task 2, now creates missing dirs).
- Produces: `_get_session_id() -> str` — module-level helper in `app.py`, also used by Task 5 (`page_explorer`).

- [ ] **Step 1: Add the `uuid` import**

In `app.py`, change:

```python
import json
from pathlib import Path
```

to:

```python
import json
import uuid
from pathlib import Path
```

- [ ] **Step 2: Add the `_get_session_id` helper**

In `app.py`, insert this new section right after the imports (before the existing `# Data access (read-only for the search/charts section)` section, i.e. right after the `from sourcing_intel_cli.typed_datas import ProductDict, SupplierDict` import line and its two blank lines):

```python
# ---------------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------------


def _get_session_id() -> str:
	"""Stable per-visit identifier used to namespace a visitor's scraped data.

	Generated once per Streamlit session and cached in `st.session_state` —
	scraped HTML and per-search databases are stored under
	`sessions/<session_id>/` so one visitor never sees another's data (see
	docs/superpowers/specs/2026-09-05-session-scoped-data-isolation-design.md).

	:return: A short hex id, stable for the lifetime of this browser session.
	:rtype: str
	"""
	return st.session_state.setdefault("session_id", uuid.uuid4().hex[:12])
```

- [ ] **Step 3: Namespace the live-scrape storage paths**

In `page_scraper()`, change:

```python
	if st.button("Scrape live", type="primary", disabled=not keywords):
		slug = slugify(keywords)
		save_in_folder = f"scraped_pages/{slug}"
```

to:

```python
	if st.button("Scrape live", type="primary", disabled=not keywords):
		session_id = _get_session_id()
		slug = slugify(keywords)
		save_in_folder = f"sessions/{session_id}/scraped_pages/{slug}"
```

And change:

```python
		_validate_and_insert(raw_suppliers, raw_products, db_name=f"{DB_PREFIX}_{slug}")
```

to:

```python
		_validate_and_insert(
			raw_suppliers, raw_products, db_name=f"sessions/{session_id}/db/{DB_PREFIX}_{slug}"
		)
```

Leave the demo-dataset button (`db_name=f"{DB_PREFIX}_demo"`) untouched — it stays shared/unscoped by design.

- [ ] **Step 4: Manual verification**

Run: `streamlit run app.py`

1. Go to the **Scraper** page, enter keywords (e.g. "thinkpad"), set pages to 1, and click **Scrape live** (needs a working ScrapingBee key — your own or the site's `.env` demo key).
2. After it finishes, check on disk that the files landed under a session folder, not the old shared location:
   - `sessions/<some-hex-id>/scraped_pages/thinkpad/page_1.html` exists.
   - `sessions/<some-hex-id>/db/sourcing_intel_thinkpad.sqlite` exists.
   - No new file was created directly at `scraped_pages/thinkpad/` or `sourcing_intel_thinkpad.sqlite` (project root).
3. Confirm the page still shows the "N supplier(s) and N product(s) added" success message as before.

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: scope live-scrape storage under a per-session directory"
```

---

### Task 5: Session-scoped dataset discovery + shared demo dataset (`app.py::page_explorer`)

No pytest coverage exists for `app.py` — verified manually, same as Task 4.

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `_get_session_id()` (Task 4), `discover_databases(root: Path)` (unchanged signature, already supports an arbitrary `root` — see `tests/test_datasets.py::TestDiscoverDatabases`), `dataset_label(Path) -> str` (unchanged).

- [ ] **Step 1: Scope the dataset picker to the current session, plus the shared demo dataset**

In `page_explorer()`, change:

```python
def page_explorer() -> None:
	"""Dataset picker + natural-language search + charts."""
	st.title("Explore")
	databases = discover_databases()

	if not databases:
```

to:

```python
def page_explorer() -> None:
	"""Dataset picker + natural-language search + charts."""
	st.title("Explore")
	session_id = _get_session_id()
	databases = discover_databases(root=Path(f"sessions/{session_id}/db"))
	demo_db = Path(f"{DB_PREFIX}_demo.sqlite")
	if demo_db.exists():
		databases.append(demo_db)

	if not databases:
```

- [ ] **Step 2: Manual verification**

Run: `streamlit run app.py` (if not already running from Task 4).

1. Go to the **Explorer** page. If you ran the Task 4 verification scrape earlier in the same browser session, "thinkpad" should appear in the dataset picker.
2. Go to the **Scraper** page and click **Load the demo dataset**. Return to **Explorer** — "demo" should now also appear in the picker.
3. Open the app in a **second, separate browser session** (a private/incognito window, or a different browser) and go straight to **Explorer** without scraping anything there first: it should show only "demo" (shared), never "thinkpad" — confirming the previous session's live-scrape data isn't visible.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: scope Explorer's dataset picker to the current session"
```

---

### Task 6: Wire `cleanup_stale_sessions` into app startup

No pytest coverage exists for `app.py` — verified manually, same as Tasks 4/5.

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `cleanup_stale_sessions` (Task 3).

- [ ] **Step 1: Import `cleanup_stale_sessions`**

Change:

```python
from sourcing_intel_cli.datasets import DB_PREFIX, dataset_label, discover_databases, slugify
```

to:

```python
from sourcing_intel_cli.datasets import (
	DB_PREFIX,
	cleanup_stale_sessions,
	dataset_label,
	discover_databases,
	slugify,
)
```

- [ ] **Step 2: Call it once per hour at startup**

In the `# Navigation` section, change:

```python
st.set_page_config(page_title="PickMySupplier", page_icon="🤏🛒", layout="wide")

PAGE_ACCUEIL = st.Page(page_accueil, title="Home", icon="🏠", default=True)
```

to:

```python
st.set_page_config(page_title="PickMySupplier", page_icon="🤏🛒", layout="wide")


@st.cache_resource(ttl=3600)
def _cleanup_stale_sessions_once() -> None:
	"""Run `cleanup_stale_sessions` at most once per hour across all visitors.

	`st.cache_resource` caches at the process level (shared by every
	visitor, unlike `st.session_state`) — with a 1-hour TTL this runs the
	disk housekeeping once per hour for the whole site, no matter how many
	concurrent sessions there are, without a separate scheduler.

	:return: None
	:rtype: None
	"""
	cleanup_stale_sessions()


_cleanup_stale_sessions_once()

PAGE_ACCUEIL = st.Page(page_accueil, title="Home", icon="🏠", default=True)
```

- [ ] **Step 3: Manual verification**

Run: `streamlit run app.py`.

1. Manually create a stale session directory to confirm the wiring works end to end:
   ```bash
   mkdir -p sessions/stale_test_id/db
   touch sessions/stale_test_id/db/sourcing_intel_old.sqlite
   ```
   Then set that file's modified time to 49 hours ago (e.g. `python -c "import os, time; os.utime('sessions/stale_test_id/db/sourcing_intel_old.sqlite', (time.time()-49*3600,)*2)"`).
2. Restart the Streamlit app (a plain browser refresh reruns the script but `st.cache_resource` may already be warm from an earlier run in this dev session — restart the `streamlit run` process to force a fresh cache) and load any page.
3. Confirm `sessions/stale_test_id/` no longer exists on disk.
4. Confirm your own session's directory (from Task 4/5 verification) is untouched if it's less than 48h old.

- [ ] **Step 4: Full test suite + lint, then commit**

Run: `python -m pytest` and `python -m ruff check .`
Expected: all tests pass, no new lint errors.

```bash
git add app.py
git commit -m "feat: purge stale per-session directories on a 1-hour cadence"
```
