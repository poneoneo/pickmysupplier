"""Synthetic demo dataset — same shape as a real scrape, no network involved.

Lets the Streamlit app always have something to display even when live
scraping is unavailable (target site restructured, no proxy credits left,
no internet). Goes through the exact same `run_quality_checks` /
`add_suppliers_to_db` / `add_products_to_db` pipeline as a real scrape, so
it's not a special-cased code path — just a different data source.
"""

from __future__ import annotations

import random

from .typed_datas import ProductDict, SupplierDict
from .utils_scrapping import country_name

_VERIFICATION_MODES = ("verified", "gold", "unverified")
_COUNTRY_CODES = ("CN", "IN", "US", "VN", "DE", "TR", "PK", "KR", "IT", "BD")
_PRODUCT_CATEGORIES = (
	"wireless earbuds",
	"stainless steel water bottle",
	"LED strip light",
	"phone case",
	"office chair",
	"solar power bank",
	"cotton t-shirt",
	"ceramic coffee mug",
	"bluetooth speaker",
	"kids backpack",
)


def _make_supplier(rng: random.Random, index: int) -> SupplierDict:
	return SupplierDict(
		name=f"demo supplier {index:02d}",
		verified_type=rng.choice(_VERIFICATION_MODES),
		sopi_level=rng.randint(1, 5),
		country_name=country_name(country_min=rng.choice(_COUNTRY_CODES)),
		gold_supplier_year=rng.randint(0, 12),
		supplier_service_score=round(rng.uniform(3.0, 5.0), 1),
	)


def _make_product(rng: random.Random, index: int, supplier_name: str) -> ProductDict:
	min_price = round(rng.uniform(0.5, 200.0), 2)
	max_price = round(min_price + rng.uniform(0.0, 50.0), 2)
	category = rng.choice(_PRODUCT_CATEGORIES)
	return ProductDict(
		name=f"{category} - demo model {index:03d}",
		guaranteed_by_alibaba=rng.random() < 0.6,
		certifications=rng.choice(["", "CE", "CE,RoHS", "ISO9001", "FDA,CE"]),
		minimum_to_order=float(rng.choice([1, 5, 10, 20, 50, 100])),
		ordered_or_sold=float(rng.randint(0, 5000)),
		min_price=min_price,
		max_price=max_price,
		product_score=round(rng.uniform(3.0, 5.0), 1),
		review_count=float(rng.randint(0, 800)),
		review_score=round(rng.uniform(3.0, 5.0), 1),
		shipping_time_score=round(rng.uniform(3.0, 5.0), 1),
		is_full_promotion=rng.random() < 0.2,
		customizable=rng.random() < 0.5,
		instant_order=rng.random() < 0.3,
		trade_product=rng.random() < 0.4,
		supplied_by=supplier_name,
	)


def generate_demo_data(
	*, n_suppliers: int = 15, n_products: int = 80, seed: int = 42
) -> tuple[list[SupplierDict], list[ProductDict]]:
	"""Generate a deterministic synthetic dataset shaped like a real scrape.

	:param n_suppliers: Number of suppliers to generate.
	:param n_products: Number of products to generate, spread across suppliers.
	:param seed: Random seed, kept fixed so the demo dataset is reproducible.
	:return: (suppliers, products) — same shapes `PageParser` would return.
	"""
	rng = random.Random(seed)
	suppliers = [_make_supplier(rng, i) for i in range(n_suppliers)]
	products = [
		_make_product(rng, i, rng.choice(suppliers)["name"]) for i in range(n_products)
	]
	return suppliers, products
