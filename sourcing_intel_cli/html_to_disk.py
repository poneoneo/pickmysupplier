import re
from pathlib import Path

import selectolax
from loguru import logger

# Alibaba hydrates the results page incrementally: `window.__page__data_sse<N>`
# starts as `{}` then gets its sub-keys assigned one `<script>` tag at a time.
# The actual offer/supplier listing lives under the `._offer_list` sub-key.
# `<N>` is a per-request counter, hence the `\d*`.
_OFFER_LIST_ASSIGNMENT = re.compile(r"window\.__page__data_sse\d*\._offer_list\s*=\s*")


def _extract_balanced_json(text: str, search_from: int = 0) -> str:
	"""Extract the first balanced `{...}` JSON object found at or after `search_from`.

	String-aware brace counting: braces inside quoted JSON string values (which
	can legitimately contain `{`/`}` characters) are ignored.

	:param text: The text to search in (typically a `<script>` tag's content).
	:param search_from: Index to start searching for the opening `{` from.
	:return: The balanced JSON substring, or `""` if no balanced object is found.
	"""
	start = text.find("{", search_from)
	if start == -1:
		return ""
	depth = 0
	in_string = False
	escaped = False
	for i in range(start, len(text)):
		char = text[i]
		if in_string:
			if escaped:
				escaped = False
			elif char == "\\":
				escaped = True
			elif char == '"':
				in_string = False
			continue
		if char == '"':
			in_string = True
		elif char == "{":
			depth += 1
		elif char == "}":
			depth -= 1
			if depth == 0:
				return text[start : i + 1]
	return ""


def _create_folder(folder_name: str):
	"""Create a folder with the name `folder_name` if it doesn't exist yet

	:param folder_name:
	:type folder_name: str
	:return: Path
	:rtype: Path object
	"""
	logger.info(f"Create folder with {folder_name} as name if not exists yet ...")
	Path(folder_name).mkdir(exist_ok=True)
	return Path(folder_name)


def scripts_hunter(css_selector: str, parser_instance: selectolax.parser.HTMLParser):
	"""Find the `<script>` tag assigning `window.__page__data_sse<N>._offer_list`
	and return its JSON payload as a string.

	:param css_selector: CSS selector to scope the search to (e.g. "div[id='root']").
		Pass "" to search the whole document.
	:param parser_instance: The selectolax HTML parser for the page.
	:return: The JSON payload as a string, `""` if no matching script was found
		within scope, or `None` if `css_selector` itself matched nothing.
	"""
	if css_selector != "":
		div_with_id_root = parser_instance.css_first(css_selector)
		if div_with_id_root is None:
			logger.warning(
				"Something went wrong with the parsing, an empty none value has been returned "
			)
			return None
		else:
			list_scripts = div_with_id_root.css("script")
	else:
		list_scripts = parser_instance.css("script")
	for script in list_scripts:
		script_content = script.text()
		match = _OFFER_LIST_ASSIGNMENT.search(script_content)
		if match is None:
			continue
		json_result = _extract_balanced_json(script_content, match.end())
		if json_result:
			return json_result
	return ""


def json_hunter(html_content: str | bytes, css_selector: str = ""):
	"""Parse the HTML content of the page to find the `window.__page__data_sse*._offer_list`
	JSON payload, scoped to `css_selector` first and falling back to the whole document.

	:param html_content: The HTML content of the page
	:type html_content: str
	:return: The JSON payload as a string, or `""`/`None` if nothing was found.
	:rtype: str | None
	"""
	body_parser = selectolax.parser.HTMLParser(html_content)
	json_result = scripts_hunter(css_selector, body_parser)
	if not json_result:
		json_result = scripts_hunter("", body_parser)
		return json_result
	return json_result.strip()


@logger.catch()
def write_to_disk(folder_name: str, pages_contents: list[str]):
	"""Save the content of each page as a separate HTML file in a folder named `folder_name`.

	:param folder_name: The name of the folder where the HTML pages will be saved
	:type folder_name: str
	:param pages_contents: A list of strings containing the HTML content of each page
	:type pages_contents: list[str]
	:return: None
	"""
	logger.info("Saving your scrapping result in disk...")
	path_obj = _create_folder(folder_name)
	for page_number, content in enumerate(pages_contents):
		with open(
			(path_obj / f"page_{page_number + 1}.html").resolve(),
			"w",
			encoding="utf-8",
		) as file:
			file.write(content)
		logger.info(f"Html content from page {page_number + 1} has been saved succesfully !")


if __name__ == "__name__":
	...
