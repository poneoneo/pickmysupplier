import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Union
from selectolax.parser import Node

import rich
from loguru import logger
from rich.progress import (
	Progress,
	SpinnerColumn,
)
from selectolax.parser import HTMLParser

from sourcing_intel_cli.typed_datas import ProductDict, SupplierDict

from .html_to_disk import json_hunter
from .utils_scrapping import (
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
		Retrieves all the html files in the targeted folder.

		:raises FileNotFoundError: if the targeted folder does not exist
		:return: A list of all html files in the targeted folder
		:rtype: List[Path]
		"""
		targeted_folder = Path(self.targeted_folder).resolve()
		if not targeted_folder.exists():
			raise FileNotFoundError()
		logger.info(f"getting html files from {targeted_folder} ... ")
		html_files = [html_file for html_file in targeted_folder.glob("*.html")]
		logger.info("Html files list has been returned.")
		return html_files

	def _divs_and_dict(self, selector: str = ".fy26-product-card"):
		"""
		Retrieves the div tags that match the given selector and a dictionary of parsed content from the html file
		containing the div tag.

		:param selector: The css selector to retrieve the div tags.
		:type selector: str
		:return: A list of tuples containing the div tag and its corresponding parsed content.
		:rtype: List[Tuple[selectolax.Selector, Dict]]
		"""
		logger.info(f"Retrieving  div tags with class='{selector}' ...")
		divs_and_dict = [
			(
				HTMLParser(self._retrieve_html_content_as_string(html_file)).css(selector),
				json_hunter(
					self._retrieve_html_content_as_string(html_file),
					css_selector="div[id='root']",
				),
			)
			for html_file in self._html_files_explorer()
		]
		logger.info("All expected divs and dict has been retrived ...")

		new_divs_and_dict = []
		for item in divs_and_dict:
			if item[1] is None or item[1] == "":
				continue
			new_divs_and_dict.append((item[0], json.loads(item[1])))  # type: ignore
		return new_divs_and_dict

	def _suppliers_appender(self, offers_list: Sequence[dict], suppliers: list, divs: list[Node]):
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
					"verified_type": suppliers_status(tags=divs, offer=offer),
					"sopi_level": int(offer["displayStarLevel"]),
					"country_name": country_name(country_min=offer["countryCode"]),
					"gold_supplier_year": offer["goldSupplierYears"].split(" ")[0],
					"supplier_service_score": safe_float(offer["supplierServiceScore"]),
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
				offers_values = offers.get("offerResultData", {}).get("offers", [])
				if not offers_values:
					continue
				self._suppliers_appender(
					offers_list=offers_values, suppliers=suppliers, divs=divs
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
				offers_values = offers.get("offerResultData", {}).get("offers", [])
				if not offers_values:
					continue
				self._produtcs_appender(offers_list=offers_values, products=products)
				progress.update(all_pages_task, advance=100 / len(divs_and_dict))
		# removing products present twice in products list
		unique_products_tuple = list(OrderedDict((str(d), d) for d in products).items())
		unique_products = [product_tuple[1] for product_tuple in unique_products_tuple]
		return unique_products
