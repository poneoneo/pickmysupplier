"""Short, human-readable product names for display.

Scraped product titles are often long marketing strings (certifications,
model numbers, superlatives strung together) that don't fit well as chart
axis labels or table cells. `summarize_product_names` asks Groq to rewrite
the ones that are too long into a short name that keeps the product's
actual identity, batched into a single API call rather than one per
product. If that call fails (or the model's answer isn't trustworthy —
missing, empty, or not actually shorter), `truncate_at_word_boundary` is
used instead — a name is never lost, only ever shortened.
"""

from __future__ import annotations

import json

from groq import Groq
from loguru import logger

from . import GROQ_API_KEY

GROQ_MODEL = "llama-3.1-8b-instant"

DEFAULT_MAX_LENGTH = 70

_FILLER_WORDS = {
	"wholesale", "hot", "sale", "new", "oem", "odm", "custom", "customized",
	"factory", "direct", "high", "quality", "best", "top", "hotsale",
}


def should_shorten(name: str, max_length: int = DEFAULT_MAX_LENGTH) -> bool:
	"""Whether `name` is long enough to be worth shortening.

	:param name: A product name.
	:param max_length: Length threshold, in characters.
	:return: True if `name` is longer than `max_length`.
	"""
	return len(name) > max_length


def truncate_at_word_boundary(name: str, max_length: int = DEFAULT_MAX_LENGTH) -> str:
	"""Deterministically shorten `name` without cutting a word in half.

	Drops filler/marketing words first (they carry no identifying meaning),
	then keeps whole words up to `max_length` characters and appends "…".
	The network-free fallback used whenever LLM summarization isn't
	available or can't be trusted.

	:param name: A product name.
	:param max_length: Maximum length of the returned name, including "…".
	:return: `name` unchanged if already short enough, otherwise a
		truncated version ending in "…".
	"""
	if not should_shorten(name, max_length):
		return name

	words = [w for w in name.split() if w.lower().strip(",.-") not in _FILLER_WORDS]
	if not words:
		words = name.split()

	kept: list[str] = []
	length = 0
	for word in words:
		added_length = len(word) + (1 if kept else 0)
		if length + added_length > max_length - 1:  # leave room for "…"
			break
		kept.append(word)
		length += added_length

	if not kept:
		return name[: max_length - 1].rstrip() + "…"
	return " ".join(kept) + "…"


def summarize_product_names(
	names: list[str], max_length: int = DEFAULT_MAX_LENGTH
) -> dict[str, str]:
	"""Shorten every name in `names` that's longer than `max_length`.

	Batches all the names needing shortening into a single Groq call
	(JSON mode) instead of one call per product. Any name the model
	doesn't return a trustworthy answer for (missing, empty, or not
	actually shorter than the original) falls back to
	`truncate_at_word_boundary` individually — this never blocks product
	insertion on an LLM failure.

	:param names: Product names (typically a batch from one scrape).
	:param max_length: Length threshold/target — see `should_shorten`.
	:return: A dict mapping every name in `names` to its display name
		(shortened if it needed it, unchanged otherwise).
	"""
	result = {name: name for name in names if not should_shorten(name, max_length)}
	to_shorten = [name for name in names if should_shorten(name, max_length)]
	if not to_shorten:
		return result

	shortened: dict[str, str] = {}
	if GROQ_API_KEY:
		try:
			client = Groq(api_key=GROQ_API_KEY)
			numbered = "\n".join(f"{i}: {name}" for i, name in enumerate(to_shorten))
			completion = client.chat.completions.create(
				messages=[
					{
						"role": "system",
						"content": (
							"Rewrite each numbered product name as a short, "
							f"human-readable name of at most {max_length} characters "
							"that keeps the product's actual identity (what it is, "
							"its key distinguishing feature) — drop marketing filler, "
							"model-number noise, and redundant certifications. Reply "
							'with ONLY a JSON object {"0": "short name", "1": "short '
							'name", ...} using the same numbers as the input, one '
							"entry per input line."
						),
					},
					{"role": "user", "content": numbered},
				],
				model=GROQ_MODEL,
				response_format={"type": "json_object"},
				temperature=0,
			)
			shortened = json.loads(completion.choices[0].message.content)
		except Exception:  # noqa: BLE001
			logger.exception("Product name summarization failed, falling back to truncation")

	for i, name in enumerate(to_shorten):
		short = shortened.get(str(i)) if isinstance(shortened, dict) else None
		if isinstance(short, str) and 0 < len(short.strip()) < len(name):
			result[name] = short.strip()
		else:
			result[name] = truncate_at_word_boundary(name, max_length)
	return result
