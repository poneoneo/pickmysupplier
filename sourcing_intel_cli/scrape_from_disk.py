import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Union

import rich
from loguru import logger
from rich.progress import (
	Progress,
	SpinnerColumn,
)
from selectolax.lexbor import LexborHTMLParser, LexborNode

from sourcing_intel_cli.typed_datas import ProductDict, SupplierDict

from .html_to_disk import json_hunter
from .utils_scrapping import (
	card_to_offer,
	is_usd_price,
	clean_product_title,
	country_name,
	get_product_certification,
	get_product_price,
	parse_moq_text,
	parse_sold_count,
	safe_float,
	suppliers_status,
)


@dataclass
class PageParser:
	"""Parse each html page downloaded from alibaba and return a list of suppliers and products.

	:raises TypeError: _description_
	:raises FileNotFoundError: if the targeted folder does not exist
	:return: PageParser object
	:rtype: class `PageParser`
	"""

	# folder path that contains all html files to be scraped
	targeted_folder: Union[str, Path]

	def _retrieve_html_content_as_string(self, html_file: Path):
		"""Retrieve html content from a html file and return it as a string.

		:param html_file: The path of the html file to be read.
		:type html_file: str
		:return: The html content as a string.
		:rtype: str
		"""
		logger.info(f"Retrieving html content from file : {html_file}")
		html_content = html_file.read_text(
			encoding="utf-8",
		)
		logger.info("Html content has been retrieved.")
		return html_content

	@logger.catch(FileNotFoundError)
	def _html_files_explorer(self):
		"""
		Retrieves all the saved pages in the targeted folder: `.json` search
		API responses and `.html` result pages.

		:raises FileNotFoundError: if the targeted folder does not exist
		:return: A list of all saved page files in the targeted folder
		:rtype: List[Path]
		"""
		targeted_folder = Path(self.targeted_folder).resolve()
		if not targeted_folder.exists():
			raise FileNotFoundError()
		logger.info(f"getting html files from {targeted_folder} ... ")
		html_files = sorted([*targeted_folder.glob("*.json"), *targeted_folder.glob("*.html")])
		logger.info("Html files list has been returned.")
		return html_files

	def _divs_and_dict(self, selector: str = ".fy26-product-card"):
		"""
		For each saved page, return its product card nodes and its list of offers.

		A `.json` file is a search API response (the current source, see
		`proxies_utils.SEARCH_API_URL`): its `model.offers` are used as is,
		with no card nodes. For an `.html` page, offers come from the
		page's embedded `_offer_list` JSON when it has
		one (the richer source: it carries scores the cards don't show).
		Since 2026-11 the site no longer embeds it and results only exist
		as card HTML — the offers are then rebuilt from the cards with
		`utils_scrapping.card_to_offer`, under the same keys, so both
		appenders work unchanged. Cards that can't be read are skipped.

		:param selector: The css selector of a product card.
		:type selector: str
		:return: One `(card nodes, offers)` tuple per page; pages with no
			offers at all are left out.
		:rtype: List[Tuple[List[LexborNode], List[dict]]]
		"""
		logger.info(f"Retrieving  div tags with class='{selector}' ...")
		pages = []
		for html_file in self._html_files_explorer():
			html = self._retrieve_html_content_as_string(html_file)
			if html_file.suffix == ".json":
				# Search API response: offers already structured, no cards.
				offers = json.loads(html).get("model", {}).get("offers", []) or []
				if offers:
					pages.append(([], offers))
				continue
			divs = LexborHTMLParser(html).css(selector)
			raw_json = json_hunter(html, css_selector="div[id='root']")
			offers = []
			if raw_json:
				offers = json.loads(raw_json).get("offerResultData", {}).get("offers", [])
			if not offers:
				offers = [offer for offer in map(card_to_offer, divs) if offer is not None]
			if offers:
				pages.append((divs, offers))
		logger.info("All expected divs and offers have been retrieved ...")
		return pages

	def _suppliers_appender(self, offers_list: Sequence[dict], suppliers: list, divs: list[LexborNode]):
		"""Parse each offer into a supplier dict, skipping any offer that fails to parse.

		A single malformed offer (unexpected field format, missing key) used to
		blow up the whole scrape — now it's logged and skipped, keeping the rest,
		consistent with `data_quality.run_quality_checks`'s "reject the row, keep
		the batch" policy.
		"""
		for offer in offers_list:
			try:
				suppliers.append({
					"name": offer["companyName"].lower(),
					# The search API has no per-offer "verified" badge (only
					# card HTML shows it): unknown rather than "unverified".
					"verified_type": suppliers_status(tags=divs, offer=offer) if divs else "unknown",
					"sopi_level": int(offer["displayStarLevel"]),
					"country_name": country_name(country_min=offer["countryCode"]),
					"gold_supplier_year": offer["goldSupplierYears"].split(" ")[0],
					# Renamed `supplierService` in the 2026-11 search API.
					"supplier_service_score": safe_float(
						offer["supplierServiceScore"]
						if "supplierServiceScore" in offer
						else offer["supplierService"]
					),
				})
			except (KeyError, TypeError, ValueError) as exc:
				logger.warning(
					f"Fournisseur ignoré (parsing échoué) : {offer.get('companyName', '?')!r} — {exc}"
				)
		return suppliers

	def detected_suppliers(self):
		"""Retrieves the detected suppliers from the divs and offers data.
		Returns a list of unique suppliers with their relevant information.
		"""
		suppliers: Sequence[SupplierDict] = list()
		console = rich.console.Console()
		divs_and_dict = self._divs_and_dict()
		with Progress(
			SpinnerColumn(finished_text="[bold green]finished ✓[/bold green]"),
			*Progress.get_default_columns(),
			console=console,
			transient=True,
		) as progress:
			all_pages_task = progress.add_task(
				description="[blank]Parsing suppliers ...[/blank]",
			)
			for divs, offers in divs_and_dict:
				self._suppliers_appender(
					offers_list=offers, suppliers=suppliers, divs=divs
				)
				progress.update(all_pages_task, advance=100 / len(divs_and_dict))
		# removing supliers present twice in supliers dict
		unique_suppliers_tuple = list(OrderedDict((str(d), d) for d in suppliers).items())
		unique_suppliers = [supplier_tuple[1] for supplier_tuple in unique_suppliers_tuple]
		return unique_suppliers

	def _produtcs_appender(self, offers_list: Sequence[dict], products: Sequence[ProductDict]):
		"""Parse each offer into a product dict, skipping any offer that fails to parse.

		A single malformed offer (e.g. a price format `get_product_price` can't
		handle) used to blow up the whole scrape — now it's logged and skipped,
		keeping the rest, consistent with `data_quality.run_quality_checks`'s
		"reject the row, keep the batch" policy.
		"""
		for offer in offers_list:
			try:
				if not is_usd_price(offer["price"]):
					# Would be stored as if it were dollars: skipped instead.
					logger.warning(
						f"Produit ignoré (prix hors USD) : {offer.get('title', '?')!r} — {offer['price']!r}"
					)
					continue
				products.append({
					"name": clean_product_title(offer["title"]).lower(),
					"max_price": get_product_price(all_price_text=offer["price"], which="max"),
					"min_price": get_product_price(all_price_text=offer["price"], which="min"),
					# guaranteed_by_alibaba/is_full_promotion/customizable/instant_order/
					# trade_product have no equivalent field in the current page JSON
					# (Alibaba's 2026 offer schema dropped halfTrust/isFullPromotion/
					# customizable/halfTrustInstantOrder/tradeProduct). Defaulted to
					# False rather than guessed until a real source field is found.
					"guaranteed_by_alibaba": False,
					"certifications": get_product_certification(offer=offer),
					"minimum_to_order": parse_moq_text(offer["moq"]),
					"ordered_or_sold": parse_sold_count(offer.get("soldOrder")),
					"supplied_by": offer["companyName"].lower(),
					"product_score": safe_float(offer["productScore"]),
					"review_count": safe_float(offer["reviewCount"]),
					"review_score": safe_float(offer["reviewScore"]),
					"shipping_time_score": safe_float(offer["shippingScore"]),
					"is_full_promotion": False,
					"customizable": False,
					"instant_order": False,
					"trade_product": False,
				})
			except (KeyError, TypeError, ValueError) as exc:
				logger.warning(f"Produit ignoré (parsing échoué) : {offer.get('title', '?')!r} — {exc}")
		return products

	def detected_products(self):
		"""Returns a list of unique products with their relevant information."""
		products: Sequence[ProductDict] = list()
		console = rich.console.Console()
		divs_and_dict = self._divs_and_dict()
		with Progress(
			SpinnerColumn(finished_text="[bold green]finished ✓[/bold green]"),
			*Progress.get_default_columns(),
			console=console,
			transient=True,
		) as progress:
			all_pages_task = progress.add_task(description="[blank]Parsing products ...[/blank]")
			for divs, offers in divs_and_dict:
				self._produtcs_appender(offers_list=offers, products=products)
				progress.update(all_pages_task, advance=100 / len(divs_and_dict))
		# removing products present twice in products list
		unique_products_tuple = list(OrderedDict((str(d), d) for d in products).items())
		unique_products = [product_tuple[1] for product_tuple in unique_products_tuple]
		return unique_products
