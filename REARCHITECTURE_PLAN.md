# Tax Help — Re-Architecture Plan (Bouncer / Brain / Hands)

**Status:** DRAFT — awaiting approval before any code changes.
**Branch:** `claude/compassionate-mayer-HJLJi`
**Goal:** Strip the synthetic test situation out of the pipeline, and re-architect
into a three-tier model mesh that keeps PII off the cloud while letting a strong
cloud model do the heavy tax reasoning — so we can finish filing fast and safely.

---

## 1. Decisions locked in (from review)

| Decision | Choice |
|---|---|
| **Number boundary** | **Named PII redacted; real dollar figures pass through.** A dollar figure alone (e.g. `$480,000`) is not PII — it can't identify you without names/SSN/employer to link it to. The Bouncer strips all identifying fields and lets numbers cross. The Brain can then compute directly (safe-harbor math, penalty calc, marginal-rate strategy savings). This was refined from the original "tokenize everything" approach after confirming that numbers without identity context are safe. |
| **Who calls the cloud** | **This repo only prepares the sanitized bundle.** Antigravity (the Hands) makes the actual Gemini calls on your machine. No Gemini API keys live in this repo. |
| **Scope of this doc** | **Plan only.** Nothing below is implemented yet. On approval I execute it on the branch. |

---

## 2. Why the current pipeline needs the overhaul

The repo today is a **strictly-local Ollama mesh** with a hard "privacy firewall"
(`_assert_local_host` aborts anything non-localhost). That firewall is good
instinct, but two things are wrong:

1. **There is no cloud tier and no redaction layer at all.** To use a cloud Brain
   safely we must *build* the Bouncer first — it doesn't exist yet.
2. **A synthetic test case is hard-coded into the "real" pipeline**, so the system
   produces the same canned answer regardless of your actual documents.

### 2.1 The synthetic remnants to remove (exact locations)

These all describe a fictional taxpayer ($480k W-2, $98k prior tax, $8,000 balance,
STR loophole worth $1,515.98, hobby savings $4,350, $280k/$70k MACRS split). They
must come out of the production path:

- **`run_filing.py`**
  - Lines ~256–295: the entire `system_prompt` hard-codes the fake numbers *as facts*
    ("Prior year tax liability was $98,000", "safe harbor … $107,800", "rental loss
    of $4,182", "Potential Tax Savings: $1,515.98", "$4,350.00").
  - `score_report()` (lines ~143–207): "scores" a report by keyword-matching those
    magic numbers (`107,800`, `4,182`, `1,515.98`, `4,350`, `70,000`). This rewards
    *reciting the synthetic answer*, not reading your docs. The whole multi-run
    "pick the best candidate" mechanism is built on this and should be retired.
- **`agents/intake.py`** line ~16: hard-codes employer names `KEYSIGHT` / `STRYKER`
  as classification hints. (Keysight is real to you, but it must never be a code
  literal — that's exactly the link we want redacted.)
- **`app.py`**: hard-codes `C:\Users\nswitzer\Antigrav Proj` as the only allowed
  root (lines ~54, 169–179), the uv path (line ~236), and blocks filenames
  containing `Stryker`/`OneDrive` (lines ~149, 178).
- **`fine_tune_unsloth.py`**, **`test_accuracy.py`**, **`.agents/skills/*.md`**,
  **`AGENTS.md`**: the $480k profile is woven into training data, the accuracy
  suite, and the rule docs. These get scrubbed of the specific fictional figures
  while keeping the *general* IRC rules (passive-loss phase-out, MACRS 27.5yr,
  hobby-loss §183, 110% safe harbor) which are legitimately useful.
- Windows-absolute paths everywhere → replaced with config / env vars so docs can
  live outside the repo (you said your real docs already do).

> Net effect: rules stay, the fake taxpayer leaves. Strategy numbers will be
> *computed from your documents*, never recited from a prompt.

---

## 3. Target architecture

```
        ┌─────────────────────────── YOUR MACHINE (private) ───────────────────────────┐
        │                                                                               │
  raw   │   ┌──────────┐    ┌─────────────────────┐    ┌──────────────────────────┐     │
  docs ─┼─► │  INTAKE   │──► │  THE BOUNCER         │──► │  sanitized_bundle.json   │ ────┼──► THE BRAIN
 (out   │   │ (Hands/   │    │  Gemma local, 8-bit  │    │  (named PII removed,     │     │   Gemini 3.1 Pro
  of    │   │  local)   │    │  NER redaction +     │    │   real $ figures kept)   │     │   (via Antigravity)
  repo) │   └──────────┘    │  regex backstop      │    └──────────────────────────┘     │        │
        │                   │  FAIL-CLOSED         │                                      │        │ tax-logic
        │                   └─────────┬────────────┘                                      │        ▼ JSON map
        │                             │ writes (never leaves machine)                     │   ┌──────────┐
        │                             ▼                                                   │   │  placeholders │
        │                   ┌──────────────────────┐                                      │   │  + rules +    │
        │                   │ rehydration_map.json │◄─── re-hydrate ──────────────────────┼───│  strategy     │
        │                   │ (placeholder→real,   │                                      │   └──────────┘
        │                   │  gitignored, local)  │                                      │
        │                   └──────────┬───────────┘                                      │
        │                              ▼                                                  │
        │   ┌──────────────────────────────────────────┐                                 │
        │   │  THE HANDS — Gemini 3.5 Flash / Antigravity│  categorize files, run python,  │
        │   │  fill PDFs locally with REAL values,       │  drive browser/PDF editor       │
        │   │  QA, savings, comms                        │                                 │
        │   └──────────────────────────────────────────┘                                 │
        └───────────────────────────────────────────────────────────────────────────────┘
```

### Tier roles

- **The Bouncer — Gemma, strictly local (8-bit quant via Ollama).**
  Single job: Named Entity Recognition to find and redact the PII checklist below,
  then emit (a) the sanitized bundle that may leave the machine and (b) a local-only
  rehydration map. **Fail-closed**: if the model is unavailable or redaction
  confidence is low, the pipeline aborts and *nothing* is sent outward.
- **The Brain — Gemini 3.1 Pro (called by Antigravity, not this repo).**
  Receives only the sanitized bundle. Parses the rules, runs the tax logic, returns
  a structured JSON "map" (schedules, line items, strategies, open questions) that
  references placeholders for any redacted entity.
- **The Hands — Gemini 3.5 Flash via Antigravity.**
  Repetitive execution: categorize/rename files, run the python math + form-fill,
  physically drive the browser/PDF editor. Runs locally, so it works with the
  *re-hydrated* real values.

---

## 4. The redaction contract (the part that keeps the cloud blind)

This is the security boundary; it gets the most rigor. Defense in depth = the
local Gemma NER **plus** a deterministic regex/structured backstop, because regex
never misses a well-formed SSN and NER catches the free-text names/employer/address.

### 4.1 PII checklist → handling

| Item | Examples (from your note) | Method | Goes to cloud? |
|---|---|---|---|
| Names | You, Marlo, Alma, Valentine, Hugo | NER + known-names list → `[PERSON_n]` | No (placeholder) |
| SSNs / ITINs | all five | regex `\d{3}-\d{2}-\d{4}` + NER → `[SSN_n]` | No |
| Dates of birth | dependents section | regex date near "DOB/born" + NER → `[DOB_n]` | No |
| EINs | W-2 employer IDs | regex `\d{2}-\d{7}` → `[EIN_n]` | No |
| Employer link | anything tying Marlo↔Keysight | NER + employer list → `[EMPLOYER_n]` | No |
| Bank routing/acct | direct deposit / payments | regex (routing 9-digit, acct) → `[BANK_n]` | No |
| Home address | Union Avenue | NER address + street regex → `[ADDRESS_n]` | No |
| Brokerage/1099 acct # | account numbers on 1099s | regex + NER → `[ACCT_n]` | No |
| **Dollar figures** | wages, rental, withheld, etc. | **kept as-is** | **Yes — safe without identity context** |

Placeholders are *consistent and reversible*: the same real value always maps to
the same token within a run, so the Brain can reason ("filer has $480k in wages,
which fully phases out the $25k passive-loss allowance") and compute concrete
strategy savings, penalty amounts, and safe-harbor thresholds from real data.

### 4.2 Two artifacts, one boundary

- `processed_data/sanitized_bundle.json` — safe to hand to Antigravity/Gemini.
- `processed_data/rehydration_map.json` — placeholder→real value. **Never leaves
  the machine.** Added to `.gitignore`; used only locally by the Hands to fill the
  real PDFs.

### 4.3 Leak tripwire (verification, not vibes)

A `verify_no_pii.py` check scans the sanitized bundle right before it is allowed
to leave, and the pipeline refuses to proceed if any of these are still present:

- any `\d{3}-\d{2}-\d{4}` (SSN), any `\d{2}-\d{7}` (EIN), any 9-digit routing number,
- any name from the known-names list, the employer list, or the street address.

This runs as a hard gate (fail-closed) and as a unit test with synthetic fixtures
(no real PII in the repo).

---

## 5. Data flow, end to end

1. **Intake (local).** Point at your external docs dir via `TAX_DOCS_DIR` (no more
   hard-coded `C:\Users\...`). Classify/rename — employer hints come from a local,
   gitignored `config/known_entities.json`, not source literals.
2. **Extract (local).** Pull figures into `extracted` (real values, real PII).
3. **Bouncer (local).** Produce `sanitized_bundle.json` + `rehydration_map.json`.
   Run the leak tripwire. Fail-closed on any hit.
4. **Brain (Antigravity → Gemini Pro).** Sanitized bundle in → tax-logic JSON map
   out. Strategies/penalties/safe-harbor are *computed from your numbers*, with the
   IRC rules as reference. Open questions for you are listed here.
5. **Re-hydrate (local).** Swap `[PERSON_n]` / `[SSN_n]` / `[EIN_n]` etc. back to
   real values using the local rehydration map before anything lands on a form.
6. **Hands (Antigravity → Gemini Flash).** Fill the actual PDFs with real values,
   run QA + savings + comms, surface "docs still needed / questions / ready-to-file."
7. **Loop** until ready, then hand the prepped package to your CPA.

The existing CPA-loop in `orchestrator.py` (intake→planner→extractor→strategist→
form_proxy→qa→savings→comms, iterating until `ready_to_file`) is the right skeleton
and is **kept** — we re-point its "advisor/strategist" brain at the sanitized-bundle
boundary instead of local-only Ollama, and delete the synthetic `run_filing.py`
scoring path.

---

## 6. File-by-file change list (on approval)

**New**
- `shared/redaction.py` — Bouncer: NER (Gemma) + regex backstop, placeholder mgmt.
- `shared/cloud_bundle.py` — builds `sanitized_bundle.json` + `rehydration_map.json`.
- `verify_no_pii.py` — leak tripwire (CLI + importable gate).
- `config/known_entities.example.json` — template for names/employers/street (real
  one is gitignored).
- `tests/test_redaction.py` — synthetic-fixture leak tests.
- `ARCHITECTURE.md` — Bouncer/Brain/Hands diagram + the redaction contract (replaces
  the stale local-only framing in `AGENTS.md`/`README.md`).

**Modified**
- `agents/intake.py` — drop `KEYSIGHT`/`STRYKER` literals → read from local config.
- `orchestrator.py` — insert Bouncer step after extract; emit sanitized bundle;
  drop hard-coded Windows path default.
- `agents/strategist.py` / `agents/comms.py` — consume the sanitized bundle; the
  Brain's role is documented as the Antigravity/Gemini hand-off point.
- `app.py` — configurable docs root (env-driven), remove `nswitzer`/`Stryker`/uv
  literals; update the chat system prompt to describe the new 3-tier mesh.
- `README.md`, `AGENTS.md`, `RUN_GUIDE.md` — rewrite for the new architecture;
  remove `C:\Users\nswitzer\...` paths and the $480k profile.
- `.gitignore` — add `rehydration_map.json`, `config/known_entities.json`,
  `sanitized_bundle.json` (defense in depth; it shouldn't contain PII, but belt-and-suspenders).
- `.agents/skills/*.md`, `fine_tune_unsloth.py`, `test_accuracy.py` — keep the
  general IRC rules, strip the specific fictional taxpayer numbers.

**Retired**
- `run_filing.py` synthetic prompt + `score_report()` magic-number rubric.

---

## 7. Phased milestones (each independently shippable)

- **Phase 0 — De-synthesize.** Remove the fake taxpayer + hard-coded paths/employers.
  Pipeline still runs fully local, just honest. *Low risk, high clarity.*
- **Phase 1 — Build the Bouncer + tripwire.** Redaction module, sanitized bundle,
  rehydration map, leak tests. No cloud yet. *This is the safety foundation.*
- **Phase 2 — Brain hand-off.** Define the sanitized-bundle schema + the JSON map
  the Brain returns; wire the orchestrator to read/write at that boundary and
  document the Antigravity/Gemini-Pro call. *Cloud enters, but only behind the Bouncer.*
- **Phase 3 — Hands.** Re-hydrate + form-fill with real values; QA/savings/comms;
  ready-to-file packaging for your CPA.

---

## 8. Risks & how we de-risk

- **Redaction miss → PII leak.** Mitigated by NER+regex defense-in-depth, the
  fail-closed tripwire, and the rule that the bundle is built locally and only
  *handed to* Antigravity (you stay in the loop at the boundary).
- **Numbers cross; identity stays home.** A bare dollar figure with no name/SSN/
  employer attached is not PII. The Brain gets real numbers and can reason fully.
  The only risk is if Gemini logs your income level in aggregate — acceptable given
  that it has no idea *whose* income it is.
- **Cloud model availability / keys.** Out of this repo's scope by design — the repo
  produces the bundle; Antigravity owns the Gemini calls.
- **Serial-agent latency / context windows** (your 4-hour target): each tier passes
  compact JSON, not raw docs, keeping contexts small; the loop is the only repeated
  cost and it short-circuits once `ready_to_file`.

---

## 9. What I need from you to start

1. **Approve this plan** (or redline any tier/boundary).
2. Confirm Phase 0 can delete the `run_filing.py` synthetic scoring path outright
   (vs. keeping it behind a `--demo` flag).
3. Confirm the local `config/known_entities.json` approach for your names/employers/
   street is acceptable (it's the cleanest way to feed the Bouncer without putting
   your family in source code).

Once approved, I'll execute Phase 0 first and commit it on its own so you can see
the de-synthesized pipeline before the cloud tier goes in.
