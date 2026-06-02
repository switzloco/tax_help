"""
Redaction unit tests — all fixtures are synthetic (no real PII).

Run with: uv run python -m pytest tests/test_redaction.py -v
"""

import json
import tempfile
from pathlib import Path

import pytest

from shared.redaction import RedactionEngine, rehydrate

# ── Synthetic known-entities fixture (fake names, no real PII) ───────────────
FAKE_ENTITIES = {
    "persons": ["John Testperson", "Jane Testperson", "Child One"],
    "employers": ["ACME Corp"],
    "businesses": ["Test Side Biz LLC"],
    "addresses": {
        "street": "123 Fake Street",
        "city": "Testville",
        "zip": "00000",
    },
}


def make_engine(tmp_path: Path) -> RedactionEngine:
    entities_file = tmp_path / "known_entities.json"
    entities_file.write_text(json.dumps(FAKE_ENTITIES), encoding="utf-8")
    return RedactionEngine(known_entities_path=entities_file, use_ner=False)


# ── SSN redaction ─────────────────────────────────────────────────────────────

def test_ssn_redacted(tmp_path):
    engine = make_engine(tmp_path)
    text = "Taxpayer SSN: 123-45-6789 on the return."
    sanitized, rmap = engine.redact(text)
    assert "123-45-6789" not in sanitized
    assert "[SSN_1]" in sanitized
    assert rmap["[SSN_1]"] == "123-45-6789"


def test_multiple_ssns_get_distinct_placeholders(tmp_path):
    engine = make_engine(tmp_path)
    text = "Primary: 123-45-6789 Spouse: 987-65-4321"
    sanitized, rmap = engine.redact(text)
    assert "123-45-6789" not in sanitized
    assert "987-65-4321" not in sanitized
    assert len([k for k in rmap if k.startswith("[SSN_")]) == 2


def test_same_ssn_reuses_placeholder(tmp_path):
    engine = make_engine(tmp_path)
    text = "SSN 123-45-6789 appears twice: 123-45-6789"
    sanitized, rmap = engine.redact(text)
    assert sanitized.count("[SSN_1]") == 2
    assert len([k for k in rmap if k.startswith("[SSN_")]) == 1


# ── EIN redaction ─────────────────────────────────────────────────────────────

def test_ein_redacted(tmp_path):
    engine = make_engine(tmp_path)
    text = "Employer EIN: 12-3456789"
    sanitized, rmap = engine.redact(text)
    assert "12-3456789" not in sanitized
    assert any(k.startswith("[EIN_") for k in rmap)


# ── Known-entity redaction ────────────────────────────────────────────────────

def test_person_name_redacted(tmp_path):
    engine = make_engine(tmp_path)
    text = "Filing for John Testperson and spouse Jane Testperson."
    sanitized, rmap = engine.redact(text)
    assert "John Testperson" not in sanitized
    assert "Jane Testperson" not in sanitized
    assert any(k.startswith("[PERSON_") for k in rmap)


def test_employer_redacted(tmp_path):
    engine = make_engine(tmp_path)
    text = "W-2 from ACME Corp, Box 1 wages: $75,000"
    sanitized, rmap = engine.redact(text)
    assert "ACME Corp" not in sanitized
    assert "$75,000" in sanitized  # dollar figures must NOT be stripped


def test_address_redacted(tmp_path):
    engine = make_engine(tmp_path)
    text = "Home address: 123 Fake Street, Testville 00000"
    sanitized, rmap = engine.redact(text)
    assert "123 Fake Street" not in sanitized
    assert "Testville" not in sanitized


# ── Dollar figures are preserved ──────────────────────────────────────────────

def test_dollar_figures_preserved(tmp_path):
    engine = make_engine(tmp_path)
    text = "W-2 wages: $480,000. Federal withheld: $115,000. Rental loss: $4,182."
    sanitized, rmap = engine.redact(text)
    assert "$480,000" in sanitized
    assert "$115,000" in sanitized
    assert "$4,182" in sanitized


# ── JSON object redaction ─────────────────────────────────────────────────────

def test_json_dict_redacted(tmp_path):
    engine = make_engine(tmp_path)
    data = {
        "taxpayer": "John Testperson",
        "ssn": "123-45-6789",
        "wages": 480000,
        "employer": "ACME Corp",
    }
    sanitized, rmap = engine.redact(data)
    assert sanitized["taxpayer"] != "John Testperson"
    assert sanitized["ssn"] != "123-45-6789"
    assert sanitized["wages"] == 480000  # number untouched
    assert "ACME Corp" not in json.dumps(sanitized)


# ── Rehydration roundtrip ─────────────────────────────────────────────────────

def test_rehydration_roundtrip(tmp_path):
    engine = make_engine(tmp_path)
    original = "John Testperson SSN 123-45-6789 at ACME Corp earns $80,000."
    sanitized, rmap = engine.redact(original)
    restored = rehydrate(sanitized, rmap)
    assert restored == original


# ── Tripwire integration ──────────────────────────────────────────────────────

def test_tripwire_clean_bundle(tmp_path):
    from verify_no_pii import verify_bundle
    engine = make_engine(tmp_path)
    data = {"wages": 100000, "note": "Child One is a dependent"}
    sanitized, rmap = engine.redact(data)
    bundle_path = tmp_path / "sanitized_bundle.json"
    map_path = tmp_path / "rehydration_map.json"
    bundle_path.write_text(json.dumps(sanitized), encoding="utf-8")
    map_path.write_text(json.dumps(rmap), encoding="utf-8")
    findings = verify_bundle(bundle_path, map_path)
    assert findings == [], f"Expected clean bundle but got: {findings}"


def test_tripwire_catches_residual_pii(tmp_path):
    from verify_no_pii import verify_bundle
    # Write a bundle that still contains a real SSN
    bundle_path = tmp_path / "sanitized_bundle.json"
    map_path = tmp_path / "rehydration_map.json"
    bundle_path.write_text('{"ssn": "123-45-6789"}', encoding="utf-8")
    map_path.write_text('{"[SSN_1]": "123-45-6789"}', encoding="utf-8")
    findings = verify_bundle(bundle_path, map_path)
    assert len(findings) > 0
