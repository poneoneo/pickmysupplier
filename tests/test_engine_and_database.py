"""Tests for engine_and_database.py against an in-memory SQLite DB.

No real database file, no network — SQLModel/SQLAlchemy handle `:memory:`
natively, so this exercises the real insertion/rollback/lookup logic.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, select

from sourcing_intel_cli.engine_and_database import (
	add_products_to_db,
	add_suppliers_to_db,
	create_db_engine,
	save_all_changes,
)
from sourcing_intel_cli.models import Product, Supplier


@pytest.fixture
def db_engine():
	engine = create_db_engine(db_url="sqlite:///:memory:")
	save_all_changes(engine_db=engine, sql_model=SQLModel)
	yield engine
	engine.dispose()


def _supplier(name="Shenzhen Acme Co."):
	return {
		"name": name,
		"verified_type": "gold",
		"sopi_level": 3,
		"country_name": "chine",
		"gold_supplier_year": 5,
		"supplier_service_score": 4.5,
	}


def _product(name="Wireless earbuds", supplied_by="Shenzhen Acme Co."):
	return {
		"name": name,
		"guaranteed_by_alibaba": True,
		"certifications": "CE",
		"minimum_to_order": 10.0,
		"ordered_or_sold": 100.0,
		"min_price": 1.5,
		"max_price": 3.0,
		"product_score": 4.5,
		"review_count": 20.0,
		"review_score": 4.8,
		"shipping_time_score": 4.9,
		"is_full_promotion": False,
		"customizable": True,
		"instant_order": False,
		"trade_product": True,
		"supplied_by": supplied_by,
	}


class TestAddSuppliersToDb:
	def test_inserts_new_supplier(self, db_engine):
		add_suppliers_to_db([_supplier()], engine_db=db_engine)
		with Session(db_engine) as session:
			result = session.exec(select(Supplier)).all()
		assert len(result) == 1
		assert result[0].name == "Shenzhen Acme Co."
		assert result[0].sopi_level == 3

	def test_duplicate_supplier_is_skipped_not_raised(self, db_engine):
		add_suppliers_to_db([_supplier()], engine_db=db_engine)
		add_suppliers_to_db([_supplier()], engine_db=db_engine)
		with Session(db_engine) as session:
			result = session.exec(select(Supplier)).all()
		assert len(result) == 1


class TestAddProductsToDb:
	def test_inserts_product_linked_to_supplier(self, db_engine):
		add_suppliers_to_db([_supplier()], engine_db=db_engine)
		add_products_to_db([_product()], engine_db=db_engine)
		with Session(db_engine) as session:
			product = session.exec(select(Product)).first()
			supplier = session.exec(select(Supplier)).first()
		assert product is not None
		assert product.supplier_id == supplier.id
		assert product.min_price == 1.5

	def test_duplicate_product_is_skipped_not_raised(self, db_engine):
		add_suppliers_to_db([_supplier()], engine_db=db_engine)
		add_products_to_db([_product()], engine_db=db_engine)
		add_products_to_db([_product()], engine_db=db_engine)
		with Session(db_engine) as session:
			result = session.exec(select(Product)).all()
		assert len(result) == 1

	def test_product_with_unknown_supplier_raises(self, db_engine):
		with pytest.raises(RuntimeError, match="no supplier named"):
			add_products_to_db([_product(supplied_by="Ghost Co.")], engine_db=db_engine)


def test_create_db_engine_defaults_to_sqlite_file_url():
	engine = create_db_engine(db_name="some_db")
	assert str(engine.url) == "sqlite:///some_db.sqlite"
