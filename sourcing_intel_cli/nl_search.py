"""Natural-language search over the products/suppliers DataFrame via `datahorse`.

`datahorse` ships with a hardcoded, publicly-shared Groq API key and a model
id (`llama3-8b-8192`) that Groq has since decommissioned. Both are patched at
call time to use this project's own `GROQ_API_KEY` and a current model, so
`df.chat(...)` (the pandas accessor `datahorse` registers on import) actually
works.
"""

from __future__ import annotations

from groq import Groq

from . import GROQ_API_KEY

GROQ_MODEL = "llama-3.1-8b-instant"


def configure_datahorse() -> None:
	"""Point datahorse's internal Groq client/model at our own key and a live model.

	Must run after `import datahorse` and before any `df.chat(...)` call.
	Safe to call more than once (idempotent).

	:raises RuntimeError: If `GROQ_API_KEY` isn't set.
	"""
	if not GROQ_API_KEY:
		raise RuntimeError(
			"GROQ_API_KEY n'est pas défini — la recherche en langage naturel est "
			"indisponible (la clé Groq intégrée à datahorse est révoquée)."
		)
	import datahorse.core as dh_core

	dh_core.client = Groq(api_key=GROQ_API_KEY)
	dh_core.model = GROQ_MODEL
