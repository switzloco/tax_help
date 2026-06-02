"""
The Bouncer — local PII redaction layer.

Strips all named PII (names, SSNs, DOBs, EINs, bank/routing numbers, addresses,
employer identities) from a text string or JSON-serializable object before any
data is handed to a cloud model.  Real dollar figures are intentionally left in
place so the Brain can reason about thresholds and compute strategy savings.

Two artifacts are produced for every redaction pass:
  - sanitized text / object  (safe to send outbound)
  - rehydration_map dict     (placeholder → real value, stays on-machine)

Defense in depth:
  1. Deterministic regex for structured PII (SSN, EIN, routing, account, DOB).
  2. Known-entities exact-match from config/known_entities.json (names, employers,
     addresses the user has explicitly registered).
  3. Optional local Gemma NER via Ollama for free-text PII the regex/list can miss
     (only called when Ollama is reachable; pipeline continues without it).

Fail-closed: if any unhandled exception occurs during redaction, the caller
receives a RedactionError and nothing is sent outbound.
"""

from __future__ import annotations

import json
import re
import os
from pathlib import Path
from typing import Any

KNOWN_ENTITIES_PATH = Path(__file__).parent.parent / "config" / "known_entities.json"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# ── Regex patterns ────────────────────────────────────────────────────────────
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EIN_RE = re.compile(r"\b\d{2}-\d{7}\b")
# 9-digit routing numbers only when surrounded by non-digit boundaries
_ROUTING_RE = re.compile(r"(?<!\d)\d{9}(?!\d)")
# Longer account numbers (10–17 digits) — only flag with supporting context keyword
_ACCT_CONTEXT_RE = re.compile(
    r"(?i)(?:account\s*(?:number|#|no\.?)|acct\.?\s*(?:#|no\.?))\s*:?\s*(\d{8,17})"
)
# Date-of-birth patterns near a DOB label
_DOB_LABEL_RE = re.compile(
    r"(?i)(?:date\s+of\s+birth|dob|born)\s*:?\s*"
    r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})"
)


class RedactionError(Exception):
    pass


class RedactionEngine:
    """
    Stateless redaction engine.  Each call to redact() is independent.
    """

    def __init__(self, known_entities_path: Path | None = None, use_ner: bool = True):
        path = known_entities_path or KNOWN_ENTITIES_PATH
        self._known: dict = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._known = json.load(f)
            except Exception as e:
                print(f"[Bouncer] Warning: could not load known_entities: {e}")
        self._use_ner = use_ner

    # ── Public API ────────────────────────────────────────────────────────────

    def redact(self, data: Any) -> tuple[Any, dict]:
        """
        Redact all PII from data (str or JSON-serializable dict/list).

        Returns (sanitized_data, rehydration_map) where rehydration_map maps
        every placeholder string to its original value.

        Numbers, booleans, and None are passed through unchanged — only string
        values are examined, preventing false matches inside numeric JSON fields.
        """
        try:
            ctx = _RedactionContext()
            sanitized = self._redact_value(data, ctx)
            return sanitized, ctx.rehydration_map
        except Exception as exc:
            raise RedactionError(f"Redaction failed: {exc}") from exc

    def _redact_value(self, value: Any, ctx: "_RedactionContext") -> Any:
        if isinstance(value, str):
            return self._redact_text(value, ctx)
        if isinstance(value, dict):
            return {k: self._redact_value(v, ctx) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact_value(item, ctx) for item in value]
        return value  # int, float, bool, None — untouched

    def redact_to_files(
        self,
        data: Any,
        bundle_path: Path,
        map_path: Path,
    ) -> None:
        """Redact data and write sanitized_bundle.json + rehydration_map.json.

        Note: rehydration_map.json must never be sent to the cloud.
        """
        sanitized, rmap = self.redact(data)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(bundle_path, "w", encoding="utf-8") as f:
            json.dump(sanitized, f, indent=2, ensure_ascii=False)
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(rmap, f, indent=2, ensure_ascii=False)
        print(f"[Bouncer] Sanitized bundle → {bundle_path}")
        print(f"[Bouncer] Rehydration map  → {map_path} (local only — never send this)")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _redact_text(self, text: str, ctx: "_RedactionContext") -> str:
        text = self._apply_regex(text, ctx)
        text = self._apply_known_entities(text, ctx)
        if self._use_ner:
            text = self._apply_ner(text, ctx)
        return text

    def _apply_regex(self, text: str, ctx: "_RedactionContext") -> str:
        # SSNs
        for m in reversed(list(_SSN_RE.finditer(text))):
            ph = ctx.placeholder("SSN", m.group())
            text = text[: m.start()] + ph + text[m.end() :]

        # EINs
        for m in reversed(list(_EIN_RE.finditer(text))):
            ph = ctx.placeholder("EIN", m.group())
            text = text[: m.start()] + ph + text[m.end() :]

        # Account numbers (context-gated)
        for m in reversed(list(_ACCT_CONTEXT_RE.finditer(text))):
            acct = m.group(1)
            ph = ctx.placeholder("ACCT", acct)
            text = text[: m.start(1)] + ph + text[m.end(1) :]

        # Routing numbers (9-digit standalone)
        for m in reversed(list(_ROUTING_RE.finditer(text))):
            ph = ctx.placeholder("ROUTING", m.group())
            text = text[: m.start()] + ph + text[m.end() :]

        # Dates of birth (label-gated)
        for m in reversed(list(_DOB_LABEL_RE.finditer(text))):
            dob = m.group(1)
            ph = ctx.placeholder("DOB", dob)
            text = text[: m.start(1)] + ph + text[m.end(1) :]

        return text

    def _apply_known_entities(self, text: str, ctx: "_RedactionContext") -> str:
        persons: list[str] = self._known.get("persons", [])
        employers: list[str] = self._known.get("employers", [])
        businesses: list[str] = self._known.get("businesses", [])
        addr = self._known.get("addresses", {})
        address_terms: list[str] = []
        if isinstance(addr, dict):
            address_terms = [v for v in addr.values() if isinstance(v, str) and v]
        elif isinstance(addr, list):
            address_terms = addr

        for name in persons:
            if name and name in text:
                ph = ctx.placeholder("PERSON", name)
                text = text.replace(name, ph)

        for emp in employers:
            if emp and emp in text:
                ph = ctx.placeholder("EMPLOYER", emp)
                text = text.replace(emp, ph)

        for biz in businesses:
            if biz and biz in text:
                ph = ctx.placeholder("BUSINESS", biz)
                text = text.replace(biz, ph)

        for term in address_terms:
            if term and term in text:
                ph = ctx.placeholder("ADDRESS", term)
                text = text.replace(term, ph)

        return text

    def _apply_ner(self, text: str, ctx: "_RedactionContext") -> str:
        """Ask local Gemma to identify remaining named entities (best-effort)."""
        try:
            import urllib.request
            import urllib.error
            url = f"{OLLAMA_HOST}/api/chat"

            system = (
                "You are a named entity recognition assistant. "
                "Your only job is to find personally identifiable information in the text. "
                "Return JSON with a single key 'entities', a list of objects each with "
                "'type' (PERSON, EMPLOYER, ADDRESS) and 'value' (the exact string found). "
                "Do NOT include dollar amounts, dates, or generic nouns. "
                "Only include proper names, employer names, and physical addresses. "
                "If nothing is found, return {\"entities\": []}."
            )
            payload = {
                "model": "gemma3:latest",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Find PII in:\n{text[:4000]}"},
                ],
                "stream": False,
                "options": {"temperature": 0.0, "num_ctx": 4096},
                "format": "json",
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            content = result.get("message", {}).get("content", "{}")
            entities = json.loads(content).get("entities", [])
            for ent in entities:
                val = ent.get("value", "").strip()
                etype = ent.get("type", "ENTITY").upper()
                if val and val in text and len(val) > 2:
                    ph = ctx.placeholder(etype, val)
                    text = text.replace(val, ph)
        except Exception as e:
            print(f"[Bouncer] NER skipped (Ollama unavailable or model not found): {e}")
        return text


class _RedactionContext:
    """Tracks placeholder assignments within a single redaction pass."""

    def __init__(self):
        self.rehydration_map: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._reverse: dict[str, str] = {}

    def placeholder(self, ptype: str, real_value: str) -> str:
        if real_value in self._reverse:
            return self._reverse[real_value]
        n = self._counters.get(ptype, 0) + 1
        self._counters[ptype] = n
        ph = f"[{ptype}_{n}]"
        self.rehydration_map[ph] = real_value
        self._reverse[real_value] = ph
        return ph


def rehydrate(data: Any, rehydration_map: dict) -> Any:
    """Restore placeholder tokens to real values using the rehydration map."""
    if isinstance(data, str):
        for ph, real in rehydration_map.items():
            data = data.replace(ph, real)
        return data
    if isinstance(data, dict):
        return {k: rehydrate(v, rehydration_map) for k, v in data.items()}
    if isinstance(data, list):
        return [rehydrate(item, rehydration_map) for item in data]
    return data
