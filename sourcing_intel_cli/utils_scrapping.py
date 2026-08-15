import json
import pathlib
import re
import unicodedata
from typing import Literal

from loguru import logger
from selectolax.parser import HTMLParser, Node


def safe_float(value, default: float = 0.0) -> float:
	"""Convert a scraped value to float, falling back to `default` if it's
	missing/empty/unparsable (e.g. new suppliers with no rating history yet
	come back with `""` instead of a score).

	:param value: The raw scraped value.
	:param default: The value to return when conversion isn't possible.
	:type default: float
	:return: The parsed float, or `default`.
	:rtype: float
	"""
	try:
		return float(value)
	except (TypeError, ValueError):
		return default


def _strip_currency_symbols(price_as_string: str) -> str:
	"""Drop everything but digits and dots (currency symbol, letters, spaces).

	Alibaba renders prices in whatever currency the visitor's locale resolves
	to (``$``, ``\u20ac``, ``\u00a3``, ...), so stripping a fixed ``"$US"`` char set
	isn't enough \u2014 this keeps only what `float()` can parse.

	:param price_as_string: A price fragment, e.g. ``"\u20ac1.14"`` or ``"$1.14"``.
	:type price_as_string: str
	:return: The numeric-only substring, e.g. ``"1.14"``.
	:rtype: str
	"""
	return re.sub(r"[^\d.]", "", price_as_string)


def _remove_dot_from_price(price_as_string: str) -> float:
	"""Collapse a price with thousands-separator dots (e.g. ``"1.234.56"``,
	from a comma-thousands price like ``"1,234.56"`` after comma->dot
	normalization) down to a plain float — only the last dot is the real
	decimal point, earlier ones are thousands separators.

	:param price_as_string: A price fragment with more than one dot.
	:type price_as_string: str
	:return: The parsed float, e.g. ``1234.56``.
	:rtype: float
	"""
	head, _, tail = price_as_string.rpartition(".")
	return float(re.sub(r"\D", "", head) + "." + tail)


@logger.catch(TypeError)
def get_product_price(all_price_text: str, which: Literal["max", "min"]):
	elt = all_price_text
	if "-" in elt and which == "max":
		max_price = elt.split("-")[1].split("&")[0]
		max_price = unicodedata.normalize("NFKC", max_price)
		max_price = max_price.replace("\u00a0", "").replace(",", ".").replace(" ", "")
		if max_price.count(".") > 1:
			max_price = _remove_dot_from_price(price_as_string=max_price)
			return max_price
		return float(_strip_currency_symbols(max_price))

	elif "-" in elt and which == "min":
		min_price = elt.split("-")[0].split("&")[0]
		min_price = unicodedata.normalize("NFKC", min_price)
		min_price = min_price.replace("\u00a0", "").replace(",", ".").replace(" ", "")
		if min_price.count(".") > 1:
			min_price = _remove_dot_from_price(price_as_string=min_price)
			return min_price
		return float(_strip_currency_symbols(min_price))
	else:
		price = unicodedata.normalize("NFKC", elt)
		price = price.replace("\u00a0", "").replace(",", ".").replace(" ", "")
		if price.count(".") > 1:
			price = _remove_dot_from_price(price_as_string=price)
			return price
		else:
			return float(_strip_currency_symbols(price))


@logger.catch(TypeError)
def is_alibaba_guaranteed(str_status: str):
	if str_status == "false":
		return False
	else:
		return True


@logger.catch(TypeError)
def get_product_certification(offer: dict):
	"""Flatten an offer's `certifications` list into a comma-separated name string.

	Each entry looks like ``{"prefixIcons": [{"name": "CE", ...}], ...}`` — a
	certification can carry more than one icon/name, hence the nested loop.

	:param offer: Raw offer dict from the scraped JSON.
	:type offer: dict
	:return: Comma-separated certification names, e.g. ``"CE,RoHS"``.
	:rtype: str
	"""
	certifications_name = []
	for certification in offer.get("certifications", []):
		for icon in certification.get("prefixIcons", []):
			if icon.get("name"):
				certifications_name.append(icon["name"])

	return ",".join(certifications_name)


@logger.catch(TypeError)
def clean_product_title(raw_title: str) -> str:
	"""Strip embedded HTML (badge `<img>`/`<span>` tags) from a product title.

	Offer titles now come as an HTML fragment, e.g.
	``"<img src='...'/><span> </span>G01 Wireless Neckband Headphone"``.

	:param raw_title: The raw `title` field from a scraped offer.
	:type raw_title: str
	:return: The plain-text title.
	:rtype: str
	"""
	return HTMLParser(raw_title).text().strip()


@logger.catch(TypeError)
def parse_moq_text(moq_text: str) -> float:
	"""Extract the minimum order quantity from a text like "Min. order: 1,000 pieces".

	:param moq_text: The raw `moq`/`moqV2` field from a scraped offer.
	:type moq_text: str
	:return: The minimum order quantity, or 0.0 if it can't be parsed.
	:rtype: float
	"""
	match = re.search(r"[\d,]+(?:\.\d+)?", moq_text)
	if match is None:
		return 0.0
	return float(match.group(0).replace(",", ""))


@logger.catch(TypeError)
def parse_sold_count(sold_text: str | None) -> float:
	"""Extract the number of units sold from a text like "1,699 sold".

	:param sold_text: The raw `soldOrder` field from a scraped offer, or None.
	:type sold_text: str | None
	:return: The number sold, or 0.0 if missing/unparsable.
	:rtype: float
	"""
	if not sold_text:
		return 0.0
	match = re.search(r"[\d,]+(?:\.\d+)?", sold_text)
	if match is None:
		return 0.0
	return float(match.group(0).replace(",", ""))


def is_full_promotion(str_status: str):
	if str_status == "false":
		return False
	else:
		return True


def is_customizable(str_status: str):
	if str_status == "false":
		return False
	else:
		return True


def is_instant_order(str_status: str):
	"""Return True if product is instant order, False otherwise.

	:param str_status: String indicating if product is instant order or not.
	:type str_status: str
	:return: True if product is instant order, False otherwise.
	:rtype: bool
	"""
	if str_status == "false":
		return False
	else:
		return True


def is_trade_product(str_status: str):
	"""Return True if product is trade product, False otherwise.

	:param str_status: String indicating if product is trade product or not.
	:type str_status: str
	:return: True if product is trade product, False otherwise.
	:rtype: bool
	"""
	if str_status == "false":
		return False
	else:
		return True


@logger.catch(TypeError)
def suppliers_status(tags: list[Node], offer: dict):
	"""
	Return the verification status of the supplier (unverified, verified, etc.).

	:param tags: List of product card Node objects to search for the matching supplier.
	:type tags: list[Node]
	:param offer: Dictionary containing the information of the supplier to be searched.
	:type offer: dict
	:return: The verification status of the supplier.
	:rtype: str
	"""
	target_name = offer["companyName"].lower().strip()
	for tag in tags:
		company_name_node = tag.css_first("a[data-spm='d_companyName']")
		if company_name_node is None:
			continue
		if company_name_node.text().strip().lower() != target_name:
			continue
		badge = tag.css_first(".verified-supplier-icon__wrapper")
		if badge is None:
			return "unverified"
		mode = badge.attributes.get("data-aplus-auto-card-mod")
		if not mode:
			return "unverified"
		parts = mode.split("=")
		return parts[2] if len(parts) > 2 else "unverified"
	return "unverified"


@logger.catch(TypeError)
def sopi_level(tag: Node):
	"""
	Return the level of the supplier (from 1 to 5) using the .search-cards-e-star class.

	:param tag: Node object containing the information of the supplier.
	:type tag: Node
	:return: The level of the supplier (from 1 to 5).
	:rtype: int
	"""
	elt = tag.css_first(".search-cards-e-star")
	return len(elt.css(".search-card-e-iconfont"))


@logger.catch(TypeError)
def years_as_supplier_gold(tag: Node):
	"""
	Return the number of years the supplier has been a gold supplier.

	:param tag: Node object containing the information of the supplier.
	:type tag: Node
	:return: The number of years the supplier has been a gold supplier.
	:rtype: int
	"""
	elt = tag.css_first(".search-card-e-supplier__year")
	year = elt.attrs.get("data-aplus-auto-card-mod").split("@@")[1][0]
	return year


def _get_minimum_to_order_tag(tags: list[Node]):
	"""
	Return the tag containing the minimum quantity to order.

	:param tags: List of Node objects containing the information of the supplier.
	:type tags: list[Node]
	:return: The tag containing the minimum quantity to order.
	:rtype: Node
	"""

	for tag in tags:
		element_attr = tag.attrs.get("data-aplus-auto-card-mod")
		# if 'price_negotiated' or "easy_return" not in element_attr:
		#     print(tag.text())
		#     return tag
		if "minimale" in element_attr:
			return tag
		# print(element_attr)


@logger.catch(TypeError)
def minimum_to_order(tag: Node):
	"""
	Return the minimum quantity to order.

	:param tag: Node object containing the information of the product.
	:type tag: Node
	:return: The minimum quantity to order.
	:rtype: int
	"""
	elements = tag.css(".search-card-m-sale-features__item.tow-line")
	if len(elements) != 0:
		element = _get_minimum_to_order_tag(tags=elements)
		if element is None:
			return 0
		number_str = element.text()
		number = number_str.split(":")[1].split()[0].strip()
		return int(number)
	else:
		return 0


def custom_minium_to_oder(scraped_str: str):
	"""
	Return the minimum quantity to order as a float.

	If the scraped string can't be converted to a float, return 0.0.

	:param scraped_str: The scraped string from the page.
	:type scraped_str: str
	:return: The minimum quantity to order.
	:rtype: float
	"""
	try:
		float(scraped_str)
	except ValueError:
		return 0.0
	return float(scraped_str)


@logger.catch(TypeError)
def ordered_or_sold(offer: dict):
	"""
	Return the number of orders or sales of a product.

	:param offer: A dictionary containing the product information.
	:type offer: dict
	:return: The number of orders or sales.
	:rtype: int
	"""
	power_common_info = offer.get("marketingPowerCommon")
	if power_common_info is not None:
		return int(power_common_info["count"])
	else:
		return 0


def _from_abr_to_full_name(country_abr: str):
	"""
	Return the full name of a country from its abbreviation.

	The full name of the country is looked up in the pays_data.json file.

	:param country_abr: The abbreviation of the country (e.g. "FR" for France).
	:type country_abr: str
	:return: The full name of the country in lowercase (e.g. "france" for France).
	:rtype: str
	"""
	p = (pathlib.Path(__file__).parent / "pays_data.json").resolve()
	with open(f"{p}", encoding="utf-8") as f:
		countries = json.load(
			f,
		)
		pays_data = countries["continents_pays"]
		for pays in pays_data:
			# print("two letter code : ", pays["Two_Letter_Country_Code"])
			# print("country abr : ", country_abr)
			if pays["Two_Letter_Country_Code"].lower() == country_abr.lower():
				# print("matched country : ", country_abr)
				return pays["Country_Name"].lower()
			if country_abr.lower() == "uk":
				return "royaume-uni"
		return "unknow"


def country_name(country_min: str):
	"""
	Return the full name of a country from its abbreviation.

	:param country_min: The abbreviation of the country (e.g. "FR" for France).
	:type country_min: str
	:return: The full name of the country in lowercase (e.g. "france" for France).
	:rtype: str
	"""
	return _from_abr_to_full_name(country_abr=country_min)
