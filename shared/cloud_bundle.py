"""
Builds the sanitized bundle that is safe to hand to a cloud model.

Reads the current pipeline state (extracted tax data), runs it through the
Bouncer (RedactionEngine), writes two files:

  processed_data/sanitized_bundle.json  — PII-free, safe to send to Gemini
  processed_data/rehydration_map.json   — placeholder→real, LOCAL ONLY, gitignored

After writing, the leak tripwire is automatically run.  If any PII is detected
in the outbound bundle, a CloudBundleError is raised and the files are deleted.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

from shared.redaction import RedactionEngine, RedactionError

WORKSPACE_DIR = Path(__file__).parent.parent
PROCESSED_DATA_DIR = WORKSPACE_DIR / "processed_data"
BUNDLE_PATH = PROCESSED_DATA_DIR / "sanitized_bundle.json"
MAP_PATH = PROCESSED_DATA_DIR / "rehydration_map.json"


class CloudBundleError(Exception):
    pass


def build_bundle(state: dict, known_entities_path: Path | None = None) -> Path:
    """
    Redact PII from the pipeline state and write the sanitized bundle.

    Returns the path to sanitized_bundle.json on success.
    Raises CloudBundleError if the tripwire detects residual PII.
    """
    # Pull only the fields the Brain needs — don't send the full state blob
    payload = {
        "meta": {
            "tax_year": state.get("meta", {}).get("tax_year"),
            "generated_at": datetime.utcnow().isoformat() + "Z",
        },
        "filing_details": state.get("extracted", {}).get("filing_details", {}),
        "w2_summary": state.get("extracted", {}).get("w2_summary", {}),
        "rental_property": state.get("extracted", {}).get("rental_property", {}),
        "side_business": state.get("extracted", {}).get("side_business", {}),
        "payments_ledger": state.get("extracted", {}).get("payments_ledger", []),
        "plan": {
            "schedules_to_prepare": state.get("plan", {}).get("schedules_to_prepare", []),
            "gaps_identified": state.get("plan", {}).get("gaps_identified", []),
        },
    }

    engine = RedactionEngine(known_entities_path=known_entities_path)
    try:
        engine.redact_to_files(payload, BUNDLE_PATH, MAP_PATH)
    except RedactionError as exc:
        raise CloudBundleError(f"Redaction engine failed: {exc}") from exc

    # Run the leak tripwire
    from verify_no_pii import verify_bundle
    findings = verify_bundle(BUNDLE_PATH, MAP_PATH)
    if findings:
        # Remove the bundle — do not allow a leaky file to sit on disk
        BUNDLE_PATH.unlink(missing_ok=True)
        raise CloudBundleError(
            f"[BOUNCER] Leak tripwire detected {len(findings)} PII item(s) in the bundle. "
            f"Bundle deleted. Findings: {findings}"
        )

    print(f"[Bouncer] Tripwire passed — bundle is clean. Ready to hand to Antigravity.")
    return BUNDLE_PATH
