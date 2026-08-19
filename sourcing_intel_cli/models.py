from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Product(SQLModel, table=True):
	# A product name is only unique per supplier, not globally — two
	# different suppliers legitimately post listings with the same/similar
	# title for what a human would call "the same product", each at their
	# own price. A single global unique name would silently drop every
	# supplier but the first to scrape a given title, destroying the exact
	# cross-supplier price comparison this data is meant to support.
	__table_args__ = (UniqueConstraint("name", "supplier_id", name="uq_product_name_supplier"),)

	id: Optional[int] = Field(default=None, primary_key=True)
	name: str = Field(index=True)
	short_name: Optional[str] = None
	alibaba_guranteed: bool
	certifications: str
	minimum_to_order: float
	ordered_or_sold: int
	supplier_id: Optional[int] = Field(default=None, foreign_key="supplier.id")
	min_price: float
	max_price: float
	product_score: float
	review_count: float
	review_score: float
	shipping_time_score: float
	is_full_promotion: bool
	is_customizable: bool
	is_instant_order: bool
	trade_product: bool


class Supplier(SQLModel, table=True):
	id: Optional[int] = Field(default=None, primary_key=True)
	name: str = Field(index=True, unique=True)
	verification_mode: str
	sopi_level: int
	country_name: str
	years_as_gold_supplier: int
	supplier_service_score: float


if __name__ == "__main__":
	...
	# SQLModel.metadata.create_all(engine)
