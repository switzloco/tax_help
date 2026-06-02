"""
Leak tripwire — verify that a sanitized bundle contains no residual PII.

Usage:
  uv run verify_no_pii.py                           # uses default paths
  uv run verify_no_pii.py --bundle path/to/bundle.json --map path/to/map.json

Returns exit code 0 if clean, 1 if PII found (fail-closed).
Can also be imported and called as verify_bundle().
"""

from __future__ import annotations

import json
import re
import sys
import argparse
from pathlib import Path

WORKSPACE_DIR = Path(__file__).parent
PROCESSED_DATA_DIR = WORKSPACE_DIR / "processed_data"
DEFAULT_BUNDLE = PROCESSED_DATA_DIR / "sanitized_bundle.json"
DEFAULT_MAP = PROCESSED_DATA_DIR / "rehydration_map.json"
KNOWN_ENTITIES_PATH = WORKSPACE_DIR / "config" / "known_entities.json"

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EIN_RE = re.compile(r"\b\d{2}-\d{7}\b")
_ROUTING_RE = re.compile(r"(?<!\d)\d{9}(?!\d)")


def verify_bundle(
    bundle_path: Path = DEFAULT_BUNDLE,
    map_path: Path = DEFAULT_MAP,
) -> list[str]:
    """
    Scan the sanitized bundle for residual PII.

    Returns a list of finding strings.  Empty list = clean.
    """
    findings: list[str] = []

    if not bundle_path.exists():
        return [f"Bundle file not found: {bundle_path}"]

    with open(bundle_path, "r", encoding="utf-8") as f:
        bundle_text = f.read()

    # 1. Regex checks — these should NEVER appear in a sanitized bundle
    for m in _SSN_RE.finditer(bundle_text):
        findings.append(f"SSN pattern found: {m.group()}")
    for m in _EIN_RE.finditer(bundle_text):
        findings.append(f"EIN pattern found: {m.group()}")
    for m in _ROUTING_RE.finditer(bundle_text):
        # Routing numbers are 9-digit — only flag if they look structural
        val = m.group()
        # Skip numbers that look like dollar amounts or zip codes (< 100000)
        if int(val) > 100000:
            findings.append(f"Possible routing/account number: {val}")

    # 2. Check no real values from the rehydration map are still present
    if map_path.exists():
        with open(map_path, "r", encoding="utf-8") as f:
            rmap: dict = json.load(f)
        for placeholder, real_value in rmap.items():
            if isinstance(real_value, str) and len(real_value) > 2:
                if real_value in bundle_text:
                    findings.append(
                        f"Unredacted value still present (should be {placeholder}): '{real_value}'"
                    )

    # 3. Check known entities list (belt-and-suspenders)
    if KNOWN_ENTITIES_PATH.exists():
        with open(KNOWN_ENTITIES_PATH, "r", encoding="utf-8") as f:
            known: dict = json.load(f)
        for name in known.get("persons", []):
            if name and isinstance(name, str) and name in bundle_text:
                findings.append(f"Known person name found in bundle: '{name}'")
        for emp in known.get("employers", []):
            if emp and isinstance(emp, str) and emp in bundle_text:
                findings.append(f"Known employer found in bundle: '{emp}'")
        addr = known.get("addresses", {})
        terms = addr.values() if isinstance(addr, dict) else addr
        for term in terms:
            if term and isinstance(term, str) and term in bundle_text:
                findings.append(f"Known address term found in bundle: '{term}'")

    return findings


def main():
    parser = argparse.ArgumentParser(description="PII leak tripwire for sanitized bundle")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    args = parser.parse_args()

    print(f"[Tripwire] Scanning {args.bundle} ...")
    findings = verify_bundle(args.bundle, args.map)

    if findings:
        print(f"\n[FAIL] {len(findings)} PII item(s) detected — DO NOT send this bundle to the cloud:\n")
        for f in findings:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("[PASS] Bundle is clean. Safe to hand to Antigravity / Gemini Pro.")
        sys.exit(0)


if __name__ == "__main__":
    main()
