"""Deterministic data quality checks run before `db-update` writes to the database.

This module never uses an LLM to judge whether a row is valid: every rule is a
plain, explainable, hard-coded check. Its job is to sit between `PageParser`
(scraping output) and `add_suppliers_to_db` / `add_products_to_db` (DB writes),
so a single bad row from a scraped page can never corrupt the database.

Policy: reject only the faulty row, keep and insert everything else, and
produce a report of what was rejected and why.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Sequence

from loguru import logger
from rich.console import Console
from rich.table import Table

from sourcing_intel_cli.typed_datas import ProductDict, SupplierDict

console = Console()

# Fields that must be strictly `bool` on a scraped product (not "true"/"false"
# strings, not 0/1). utils_scrapping.py's is_xxx() helpers already return real
# booleans, but this check protects against any future scraper regression.
_PRODUCT_BOOL_FIELDS = (
	"guaranteed_by_alibaba",
	"is_full_promotion",
	"customizable",
	"instant_order",
	"trade_product",
)

# Numeric fields on a product that must be present and non-negative.
_PRODUCT_NUMERIC_FIELDS = (
	"minimum_to_order",
	"ordered_or_sold",
	"product_score",
	"review_count",
	"review_score",
	"shipping_time_score",
)


@dataclass
class QualityIssue:
	"""A single rejected row, kept for the audit report."""

	entity: str  # "supplier" | "product"
	identifier: str  # row name, for traceability
	field: str
	reason: str


def _is_number(value) -> bool:
	try:
		float(value)
		return True
	except (TypeError, ValueError):
		return False


def validate_suppliers(
	suppliers: Sequence[SupplierDict],
) -> tuple[list[SupplierDict], list[QualityIssue]]:
	"""Apply deterministic quality rules to a batch of scraped suppliers.

	Rules enforced:
	  - `name` must be a non-empty string
	  - `name` must be unique within the batch (first occurrence wins)
	  - `sopi_level` must be a non-negative int
	  - `supplier_service_score` must be a non-negative number
	  - `gold_supplier_year` must be convertible to a non-negative int

	:param suppliers: Raw suppliers as returned by `PageParser.detected_suppliers`.
	:return: (clean_suppliers, issues) — issues lists every rejected row and why.
	"""
	clean: list[SupplierDict] = []
	issues: list[QualityIssue] = []
	seen_names: set[str] = set()

	for supplier in suppliers:
		name = str(supplier.get("name", "")).strip()

		if not name:
			issues.append(
				QualityIssue("supplier", "<empty>", "name", "Missing or empty supplier name")
			)
			continue

		if name in seen_names:
			issues.append(
				QualityIssue("supplier", name, "name", "Duplicate supplier within this batch")
			)
			continue

		row_ok = True

		sopi_level = supplier.get("sopi_level")
		if not isinstance(sopi_level, int) or isinstance(sopi_level, bool) or sopi_level < 0:
			issues.append(
				QualityIssue(
					"supplier",
					name,
					"sopi_level",
					f"Expected a non-negative int, got {sopi_level!r}",
				)
			)
			row_ok = False

		score = supplier.get("supplier_service_score")
		if not _is_number(score) or float(score) < 0:
			issues.append(
				QualityIssue(
					"supplier",
					name,
					"supplier_service_score",
					f"Expected a non-negative number, got {score!r}",
				)
			)
			row_ok = False

		gold_years = supplier.get("gold_supplier_year")
		if not _is_number(gold_years) or int(float(gold_years)) < 0:
			issues.append(
				QualityIssue(
					"supplier",
					name,
					"gold_supplier_year",
					f"Expected a non-negative int, got {gold_years!r}",
				)
			)
			row_ok = False

		if row_ok:
			seen_names.add(name)
			clean.append(supplier)

	return clean, issues


def validate_products(
	products: Sequence[ProductDict],
	valid_supplier_names: set[str],
) -> tuple[list[ProductDict], list[QualityIssue]]:
	"""Apply deterministic quality rules to a batch of scraped products.

	Rules enforced:
	  - `name` must be a non-empty string, unique within the batch
	  - `supplied_by` must match a supplier that already passed validation
	    (this is what guarantees `supplier_id` will never end up null)
	  - `min_price` <= `max_price`, both non-negative numbers
	  - every field in `_PRODUCT_BOOL_FIELDS` must be a strict bool
	  - every field in `_PRODUCT_NUMERIC_FIELDS` must be a non-negative number

	:param products: Raw products as returned by `PageParser.detected_products`.
	:param valid_supplier_names: Names of suppliers that passed `validate_suppliers`
		(or, in a future version, already exist in the DB) — used to enforce the
		`supplier_id` non-null constraint before we ever hit the database.
	:return: (clean_products, issues) — issues lists every rejected row and why.
	"""
	clean: list[ProductDict] = []
	issues: list[QualityIssue] = []
	seen_names: set[str] = set()

	for product in products:
		name = str(product.get("name", "")).strip()

		if not name:
			issues.append(
				QualityIssue("product", "<empty>", "name", "Missing or empty product name")
			)
			continue

		if name in seen_names:
			issues.append(
				QualityIssue("product", name, "name", "Duplicate product within this batch")
			)
			continue

		row_ok = True

		supplied_by = str(product.get("supplied_by", "")).strip()
		if supplied_by not in valid_supplier_names:
			issues.append(
				QualityIssue(
					"product",
					name,
					"supplied_by",
					f"Supplier '{supplied_by}' was not found among validated suppliers "
					"(would violate the supplier_id non-null constraint)",
				)
			)
			row_ok = False

		min_price = product.get("min_price")
		max_price = product.get("max_price")
		if not _is_number(min_price) or not _is_number(max_price):
			issues.append(
				QualityIssue("product", name, "min_price/max_price", "Prices must be numeric")
			)
			row_ok = False
		else:
			min_price_f, max_price_f = float(min_price), float(max_price)
			if min_price_f < 0 or max_price_f < 0:
				issues.append(
					QualityIssue(
						"product", name, "min_price/max_price", "Prices cannot be negative"
					)
				)
				row_ok = False
			elif min_price_f > max_price_f:
				issues.append(
					QualityIssue(
						"product",
						name,
						"min_price/max_price",
						f"min_price ({min_price_f}) is greater than max_price ({max_price_f})",
					)
				)
				row_ok = False

		for bool_field in _PRODUCT_BOOL_FIELDS:
			value = product.get(bool_field)
			if not isinstance(value, bool):
				issues.append(
					QualityIssue(
						"product", name, bool_field, f"Expected a strict bool, got {value!r}"
					)
				)
				row_ok = False

		for numeric_field in _PRODUCT_NUMERIC_FIELDS:
			value = product.get(numeric_field)
			if not _is_number(value) or float(value) < 0:
				issues.append(
					QualityIssue(
						"product",
						name,
						numeric_field,
						f"Expected a non-negative number, got {value!r}",
					)
				)
				row_ok = False

		if row_ok:
			seen_names.add(name)
			clean.append(product)

	return clean, issues


def run_quality_checks(
	suppliers: Sequence[SupplierDict],
	products: Sequence[ProductDict],
) -> tuple[list[SupplierDict], list[ProductDict], list[QualityIssue]]:
	"""Run the full deterministic quality pipeline on a freshly scraped batch.

	Suppliers are validated first so product validation can check `supplied_by`
	against the set of suppliers that will actually be inserted.

	:param suppliers: Raw suppliers from `PageParser.detected_suppliers`.
	:param products: Raw products from `PageParser.detected_products`.
	:return: (clean_suppliers, clean_products, all_issues)
	"""
	logger.info("Running deterministic data quality checks ...")
	clean_suppliers, supplier_issues = validate_suppliers(suppliers)
	valid_supplier_names = {s["name"] for s in clean_suppliers}
	clean_products, product_issues = validate_products(products, valid_supplier_names)
	all_issues = supplier_issues + product_issues
	logger.info(
		f"Data quality check complete: {len(clean_suppliers)}/{len(suppliers)} suppliers "
		f"and {len(clean_products)}/{len(products)} products kept, {len(all_issues)} issue(s) found."
	)
	return clean_suppliers, clean_products, all_issues


def print_quality_report(
	issues: Sequence[QualityIssue], total_suppliers: int, total_products: int
) -> None:
	"""Print a rich table summarizing rejected rows, plus a one-line summary."""
	if not issues:
		console.print("[bold green]Data quality check: no issues found ✓[/bold green]")
		return

	table = Table(title="Data quality report — rejected rows")
	table.add_column("Entity", style="cyan")
	table.add_column("Identifier", style="magenta")
	table.add_column("Field", style="yellow")
	table.add_column("Reason", style="white")

	for issue in issues:
		table.add_row(issue.entity, issue.identifier, issue.field, issue.reason)

	console.print(table)

	rejected_suppliers = len({i.identifier for i in issues if i.entity == "supplier"})
	rejected_products = len({i.identifier for i in issues if i.entity == "product"})
	console.print(
		f"[bold yellow]{rejected_suppliers} supplier row(s) and {rejected_products} product "
		f"row(s) were rejected out of {total_suppliers} suppliers and {total_products} products "
		"scraped. Everything else was inserted normally.[/bold yellow]"
	)


def write_quality_report(
	issues: Sequence[QualityIssue], path: str = "data_quality_report.json"
) -> None:
	"""Persist the quality report to disk as JSON, for audit trail purposes.

	:param issues: Issues returned by `run_quality_checks`.
	:param path: Destination path for the JSON report.
	"""
	with open(path, "w", encoding="utf-8") as f:
		json.dump([asdict(issue) for issue in issues], f, indent=2, ensure_ascii=False)
	logger.info(f"Quality report written to {path}")


if __name__ == "__main__":
	...
