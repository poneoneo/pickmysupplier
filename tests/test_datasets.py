"""Tests for datasets.py — per-search database naming/discovery.

Pure logic + real filesystem operations via pytest's `tmp_path`, no network.
"""

from __future__ import annotations

import os
import time

from sourcing_intel_cli.datasets import DB_PREFIX, cleanup_stale_sessions, dataset_label, discover_databases, slugify


class TestSlugify:
	def test_replaces_spaces_with_underscores(self):
		assert slugify("wireless earbuds") == "wireless_earbuds"

	def test_strips_surrounding_whitespace(self):
		assert slugify("  thinkpad  ") == "thinkpad"

	def test_single_word_unchanged(self):
		assert slugify("thinkpad") == "thinkpad"


class TestDiscoverDatabases:
	def test_finds_per_search_databases(self, tmp_path):
		(tmp_path / f"{DB_PREFIX}_wireless_earbuds.sqlite").touch()
		(tmp_path / f"{DB_PREFIX}_thinkpad.sqlite").touch()
		found = discover_databases(tmp_path)
		assert len(found) == 2

	def test_ignores_unrelated_files(self, tmp_path):
		(tmp_path / f"{DB_PREFIX}_thinkpad.sqlite").touch()
		(tmp_path / "not_a_database.sqlite").touch()
		(tmp_path / "random.txt").touch()
		found = discover_databases(tmp_path)
		assert len(found) == 1

	def test_includes_legacy_single_database(self, tmp_path):
		(tmp_path / f"{DB_PREFIX}.sqlite").touch()
		found = discover_databases(tmp_path)
		assert len(found) == 1
		assert found[0].name == f"{DB_PREFIX}.sqlite"

	def test_no_databases_returns_empty_list(self, tmp_path):
		assert discover_databases(tmp_path) == []

	def test_most_recently_modified_first(self, tmp_path):
		older = tmp_path / f"{DB_PREFIX}_thinkpad.sqlite"
		older.touch()
		time.sleep(0.05)
		newer = tmp_path / f"{DB_PREFIX}_wireless_earbuds.sqlite"
		newer.touch()
		found = discover_databases(tmp_path)
		assert found[0] == newer
		assert found[1] == older


class TestDatasetLabel:
	def test_per_search_database_label_is_the_keywords(self):
		from pathlib import Path

		assert dataset_label(Path(f"{DB_PREFIX}_wireless_earbuds.sqlite")) == "wireless earbuds"

	def test_legacy_database_gets_a_distinct_marker(self):
		from pathlib import Path

		label = dataset_label(Path(f"{DB_PREFIX}.sqlite"))
		assert label != "sourcing_intel"
		assert DB_PREFIX in label
		assert "mélangé" in label or "ancien" in label


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
