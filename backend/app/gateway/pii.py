"""PII detection and masking with Microsoft Presidio, applied recursively to JSON values.

Two layers:
  1. Field hints: values under keys like "email" or "phone" are masked outright.
  2. Presidio NER + patterns on every other string (names inside free-text notes, etc.)."""

import threading
from collections import Counter
from typing import Any

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider

# What counts as personal data. Company names, dates and URLs are deliberately not masked.
OUTPUT_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "US_SSN",
    "IP_ADDRESS",
    "IN_PAN",
    "IN_AADHAAR",
]
# Tool arguments: only unambiguous identifiers, so names in search queries don't break lookups.
INPUT_ENTITIES = [e for e in OUTPUT_ENTITIES if e != "PERSON"]

FIELD_HINTS = {
    "email": "EMAIL_ADDRESS",
    "email_address": "EMAIL_ADDRESS",
    "phone": "PHONE_NUMBER",
    "phone_number": "PHONE_NUMBER",
    "mobile": "PHONE_NUMBER",
    "contact_name": "PERSON",
    "account_manager": "PERSON",
    "full_name": "PERSON",
    "ssn": "US_SSN",
}
# "name" is only a person when it sits inside a contact/person object.
PERSON_PARENTS = {"contact", "person", "owner", "user", "customer_contact", "primary_contact"}

MIN_SCORE = 0.5

_engine: AnalyzerEngine | None = None
_lock = threading.Lock()


def get_analyzer() -> AnalyzerEngine:
    global _engine
    with _lock:
        if _engine is None:
            nlp = NlpEngineProvider(
                nlp_configuration={
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
                }
            ).create_engine()
            engine = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
            # International numbers with a country code (Presidio's validator rejects 555 test numbers).
            engine.registry.add_recognizer(
                PatternRecognizer(
                    supported_entity="PHONE_NUMBER",
                    patterns=[Pattern("intl_phone", r"\+\d{1,3}(?:[\s.-]?\d{2,5}){2,4}", 0.7)],
                )
            )
            _engine = engine
    return _engine


def mask_text(text: str, entities: list[str], counts: Counter) -> str:
    if not text or not text.strip():
        return text
    results = get_analyzer().analyze(text, language="en", entities=entities, score_threshold=MIN_SCORE)
    # The small spaCy model tags capitalised words like "Dashboard" as people. In free text we only
    # accept multi-word names; fields known to hold names are still masked via FIELD_HINTS.
    results = [r for r in results if r.entity_type != "PERSON" or " " in text[r.start : r.end].strip()]
    if not results:
        return text
    # Keep the highest-scoring, non-overlapping spans; replace right-to-left so offsets stay valid.
    results.sort(key=lambda r: (-r.score, r.start))
    chosen: list = []
    for r in results:
        if all(r.end <= c.start or r.start >= c.end for c in chosen):
            chosen.append(r)
    for r in sorted(chosen, key=lambda r: r.start, reverse=True):
        text = f"{text[: r.start]}<{r.entity_type}>{text[r.end :]}"
        counts[r.entity_type] += 1
    return text


def _hint(key: str | None, parent: str | None) -> str | None:
    if key is None:
        return None
    k = key.lower()
    if k in FIELD_HINTS:
        return FIELD_HINTS[k]
    if k == "name" and parent and parent.lower() in PERSON_PARENTS:
        return "PERSON"
    return None


def mask_value(
    value: Any,
    entities: list[str],
    counts: Counter,
    key: str | None = None,
    parent: str | None = None,
) -> Any:
    if isinstance(value, dict):
        return {k: mask_value(v, entities, counts, key=k, parent=key) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_value(v, entities, counts, key=key, parent=parent) for v in value]
    if isinstance(value, str):
        hinted = _hint(key, parent)
        if hinted and hinted in entities and value.strip():
            counts[hinted] += 1
            return f"<{hinted}>"
        return mask_text(value, entities, counts)
    return value


def mask(value: Any, *, for_input: bool = False) -> tuple[Any, dict[str, int]]:
    """Return (masked copy, {entity_type: count})."""
    counts: Counter = Counter()
    masked = mask_value(value, INPUT_ENTITIES if for_input else OUTPUT_ENTITIES, counts)
    return masked, dict(counts)
