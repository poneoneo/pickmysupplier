"""Tests for engine_and_database.py against an in-memory SQLite DB.

No real database file, no network — SQLModel/SQLAlchemy handle `:memory:`
natively, so this exercises the real insertion/rollback/lookup logic.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, select

from sourcing_intel_cli.engine_and_database import (
	_ensure_product_short_name_column,
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

	def test_same_product_name_from_different_supplier_is_not_skipped(self, db_engine):
		# The unique constraint is (name, supplier_id), not name alone — two
		# suppliers legitimately post a product with the same/similar title,
		# each at their own price, and both must land in the DB so the price
		# comparison across suppliers is actually possible.
		add_suppliers_to_db(
			[_supplier(name="Shenzhen Acme Co."), _supplier(name="Guangzhou Beta Co.")],
			engine_db=db_engine,
		)
		add_products_to_db(
			[
				_product(name="Wireless earbuds", supplied_by="Shenzhen Acme Co."),
				_product(name="Wireless earbuds", supplied_by="Guangzhou Beta Co."),
			],
			engine_db=db_engine,
		)
		with Session(db_engine) as session:
			products = session.exec(select(Product)).all()
			suppliers = session.exec(select(Supplier)).all()
		assert len(products) == 2
		assert all(p.name == "Wireless earbuds" for p in products)
		# Both rows survived, each linked to its own (distinct) supplier.
		assert {p.supplier_id for p in products} == {s.id for s in suppliers}

	def test_product_with_unknown_supplier_raises(self, db_engine):
		with pytest.raises(RuntimeError, match="no supplier named"):
			add_products_to_db([_product(supplied_by="Ghost Co.")], engine_db=db_engine)

	def test_short_name_is_stored_when_provided(self, db_engine):
		add_suppliers_to_db([_supplier()], engine_db=db_engine)
		add_products_to_db(
			[{**_product(), "short_name": "Earbuds"}], engine_db=db_engine
		)
		with Session(db_engine) as session:
			product = session.exec(select(Product)).first()
		assert product.short_name == "Earbuds"

	def test_missing_short_name_falls_back_to_full_name(self, db_engine):
		add_suppliers_to_db([_supplier()], engine_db=db_engine)
		add_products_to_db([_product(name="Wireless earbuds")], engine_db=db_engine)
		with Session(db_engine) as session:
			product = session.exec(select(Product)).first()
		assert product.short_name == "Wireless earbuds"


class TestEnsureProductShortNameColumn:
	def test_fresh_table_from_create_all_already_has_the_column(self, db_engine):
		inspector = inspect(db_engine)
		columns = {col["name"] for col in inspector.get_columns("product")}
		assert "short_name" in columns

	def test_adds_missing_column_to_a_legacy_table(self):
		engine = create_db_engine(db_url="sqlite:///:memory:")
		# Simulate a database created before this feature existed: a
		# `product` table with no `short_name` column.
		with engine.connect() as conn:
			conn.execute(text("CREATE TABLE product (id INTEGER PRIMARY KEY, name TEXT)"))
			conn.commit()
		inspector = inspect(engine)
		assert "short_name" not in {col["name"] for col in inspector.get_columns("product")}

		_ensure_product_short_name_column(engine)

		inspector = inspect(engine)
		assert "short_name" in {col["name"] for col in inspector.get_columns("product")}
		engine.dispose()

	def test_is_idempotent(self):
		engine = create_db_engine(db_url="sqlite:///:memory:")
		with engine.connect() as conn:
			conn.execute(text("CREATE TABLE product (id INTEGER PRIMARY KEY, name TEXT)"))
			conn.commit()
		_ensure_product_short_name_column(engine)
		_ensure_product_short_name_column(engine)  # must not raise on the second call
		engine.dispose()

	def test_no_op_when_product_table_does_not_exist(self):
		engine = create_db_engine(db_url="sqlite:///:memory:")
		_ensure_product_short_name_column(engine)  # must not raise
		engine.dispose()


def test_create_db_engine_defaults_to_sqlite_file_url():
	engine = create_db_engine(db_name="some_db")
	assert str(engine.url) == "sqlite:///some_db.sqlite"
