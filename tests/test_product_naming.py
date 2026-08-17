"""Tests for product_naming.py.

`should_shorten`/`truncate_at_word_boundary` are pure logic — no network.
`summarize_product_names` mocks the Groq client — no real API call, except
where explicitly testing the no-API-key / network-failure fallback paths.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from sourcing_intel_cli.product_naming import (
	should_shorten,
	summarize_product_names,
	truncate_at_word_boundary,
)

LONG_NAME = (
	"wholesale hot sale new OEM 10.1 inch rugged android 16 tablet PC IP68 "
	"waterproof industrial handheld PDA barcode scanner with high quality"
)
SHORT_NAME = "Wireless earbuds pro X"


class TestShouldShorten:
	def test_short_name_does_not_need_shortening(self):
		assert should_shorten(SHORT_NAME) is False

	def test_long_name_needs_shortening(self):
		assert should_shorten(LONG_NAME) is True

	def test_respects_custom_max_length(self):
		assert should_shorten("exactly ten", max_length=5) is True
		assert should_shorten("short", max_length=50) is False


class TestTruncateAtWordBoundary:
	def test_short_name_returned_unchanged(self):
		assert truncate_at_word_boundary(SHORT_NAME) == SHORT_NAME

	def test_long_name_is_shortened(self):
		result = truncate_at_word_boundary(LONG_NAME, max_length=40)
		assert len(result) <= 40
		assert result.endswith("…")

	def test_never_cuts_a_word_in_half(self):
		result = truncate_at_word_boundary(LONG_NAME, max_length=40)
		body = result[:-1].strip()  # drop the "…"
		assert body == "" or body in LONG_NAME

	def test_drops_filler_marketing_words(self):
		result = truncate_at_word_boundary(LONG_NAME, max_length=60)
		assert "wholesale" not in result.lower()
		assert "hot" not in result.lower()

	def test_handles_a_single_very_long_word(self):
		name = "a" * 100
		result = truncate_at_word_boundary(name, max_length=20)
		assert len(result) <= 20
		assert result.endswith("…")


class TestSummarizeProductNames:
	def test_short_names_pass_through_unchanged_without_any_api_call(self):
		with patch("sourcing_intel_cli.product_naming.Groq") as mock_groq:
			result = summarize_product_names([SHORT_NAME])
		mock_groq.assert_not_called()
		assert result == {SHORT_NAME: SHORT_NAME}

	def test_long_names_use_the_model_response(self):
		response = {"0": "Rugged Android Tablet PDA Scanner"}
		client = MagicMock()
		completion = MagicMock()
		completion.choices = [MagicMock(message=MagicMock(content=json.dumps(response)))]
		client.chat.completions.create.return_value = completion
		with (
			patch("sourcing_intel_cli.product_naming.GROQ_API_KEY", "test-key"),
			patch("sourcing_intel_cli.product_naming.Groq", return_value=client),
		):
			result = summarize_product_names([LONG_NAME])
		assert result[LONG_NAME] == "Rugged Android Tablet PDA Scanner"

	def test_falls_back_to_truncation_when_api_key_missing(self):
		with patch("sourcing_intel_cli.product_naming.GROQ_API_KEY", ""):
			result = summarize_product_names([LONG_NAME])
		assert result[LONG_NAME] == truncate_at_word_boundary(LONG_NAME)

	def test_falls_back_to_truncation_on_api_error(self):
		client = MagicMock()
		client.chat.completions.create.side_effect = RuntimeError("Groq is down")
		with (
			patch("sourcing_intel_cli.product_naming.GROQ_API_KEY", "test-key"),
			patch("sourcing_intel_cli.product_naming.Groq", return_value=client),
		):
			result = summarize_product_names([LONG_NAME])
		assert result[LONG_NAME] == truncate_at_word_boundary(LONG_NAME)

	def test_falls_back_to_truncation_when_model_response_is_not_shorter(self):
		# The model returned something at least as long as the original —
		# defeats the purpose, must not be trusted as-is.
		response = {"0": LONG_NAME + " even longer than before"}
		client = MagicMock()
		completion = MagicMock()
		completion.choices = [MagicMock(message=MagicMock(content=json.dumps(response)))]
		client.chat.completions.create.return_value = completion
		with (
			patch("sourcing_intel_cli.product_naming.GROQ_API_KEY", "test-key"),
			patch("sourcing_intel_cli.product_naming.Groq", return_value=client),
		):
			result = summarize_product_names([LONG_NAME])
		assert result[LONG_NAME] == truncate_at_word_boundary(LONG_NAME)

	def test_falls_back_to_truncation_when_model_omits_an_entry(self):
		client = MagicMock()
		completion = MagicMock()
		completion.choices = [MagicMock(message=MagicMock(content="{}"))]
		client.chat.completions.create.return_value = completion
		with (
			patch("sourcing_intel_cli.product_naming.GROQ_API_KEY", "test-key"),
			patch("sourcing_intel_cli.product_naming.Groq", return_value=client),
		):
			result = summarize_product_names([LONG_NAME])
		assert result[LONG_NAME] == truncate_at_word_boundary(LONG_NAME)

	def test_mixed_batch_only_calls_api_for_long_names(self):
		response = {"0": "Rugged Android Tablet PDA Scanner"}
		client = MagicMock()
		completion = MagicMock()
		completion.choices = [MagicMock(message=MagicMock(content=json.dumps(response)))]
		client.chat.completions.create.return_value = completion
		with (
			patch("sourcing_intel_cli.product_naming.GROQ_API_KEY", "test-key"),
			patch("sourcing_intel_cli.product_naming.Groq", return_value=client),
		):
			result = summarize_product_names([SHORT_NAME, LONG_NAME])
		assert result[SHORT_NAME] == SHORT_NAME
		assert result[LONG_NAME] == "Rugged Android Tablet PDA Scanner"
		# only the one long name was sent to the model
		sent = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
		assert SHORT_NAME not in sent
		assert LONG_NAME in sent

	def test_empty_input_returns_empty_dict(self):
		assert summarize_product_names([]) == {}
