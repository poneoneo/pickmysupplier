"""Tests for datasets.py — per-search database naming/discovery.

Pure logic + real filesystem operations via pytest's `tmp_path`, no network.
"""

from __future__ import annotations

import time

from sourcing_intel_cli.datasets import DB_PREFIX, dataset_label, discover_databases, slugify


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
