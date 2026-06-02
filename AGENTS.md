# Multi-Agent Swarm Configuration (AGENTS.md)

This file defines the routing, responsibilities, architecture, and execution environment for the tax orchestration mesh. The mesh is designed to run locally using **Ollama** and supports local fine-tuned models for specialized tax reasoning.

---

## Mesh Architecture Overview

```mermaid
graph TD
    User([User Drops Docs]) -->|raw uploads| RawDocs[/raw_docs/]
    RawDocs -->|Trigger| Sorter[Intake Agent: Sorter]
    Sorter -->|Classify & Rename| SorterOutput[/raw_docs/ Renamed Files]
    SorterOutput -->|Read| Reader[Extraction Agent: Reader]
    Reader -->|Extract JSON| ProcessedData[/processed_data/tax_data_2025.json]
    ProcessedData -->|Evaluate| Advisor[Tax Prep Agent: Advisor]
    Advisor -.->|Reference Rules| Skills[.agents/skills/]
    Advisor -->|Output Tax Prep Report| FinalOutputs[/final_outputs/tax_prep_report.md]
```

---

## Agent Specifications & Routing

### 1. Intake Agent (Sorter)
* **Role:** Document Sorter & Classifier
* **Responsibilities:**
  - Scan `/raw_docs/` for new, unstructured file uploads (PDFs, scans, CSVs).
  - Classify document types (W-2, Form 1099-NEC, Rental Schedule E records, Schedule C ledger, Form 4868, **IRS payment receipts** [Direct Pay confirmations, EFTPS receipts, 1040-ES vouchers, bank debit confirmations], **state extension vouchers** [e.g., CA Form 3519], etc.).
  - Rename files to a strict, predictable naming convention: `[YYYY]_[DocType]_[Entity/Spouse].ext` (e.g., `2025_W2_Spouse1.pdf`, `2025_1099NEC_SideBusiness.pdf`, `2025_PaymentReceipt_IRS_April.pdf`, `2025_Extension_CA.pdf`).
* **Ollama Model Configuration:**
  - **Model:** `llama3:8b` or `mistral` (Standard local models; fast processing, low footprint).
  - **Temperature:** `0.0` (Deterministic classification).
  - **System Prompt Reference:** `.agents/prompts/intake_agent.txt`

### 2. Extraction Agent (Reader)
* **Role:** Data Extraction & Structuring
* **Responsibilities:**
  - Parse the structured names from `/raw_docs/`.
  - Extract relevant financial data fields (W-2 Box 1, Box 2, federal/state tax withheld; rental income, rental expenses; side business revenue, side business expenses).
  - **Build a payments ledger** — an array of all tax payments made, each with: `date`, `amount`, `method` (Direct Pay, EFTPS, check, payroll withholding), `confirmation_number` (if available), `jurisdiction` (federal or state abbreviation), and `payment_type` (extension, estimated Q1–Q4, withholding). This replaces a single "amount paid" scalar and enables full reconciliation downstream.
  - Extract extension filing metadata: filing date, form used (4868 federal, state-specific forms), and amounts paid with the extension.
  - Compile the extracted values into a unified, clean JSON format at `processed_data/tax_data_2025.json` (path controlled by `TAX_DOCS_DIR` / workspace env vars).
* **Ollama Model Configuration:**
  - **Model:** `llama3.2-vision` (for OCR and visual PDF parsing) or a local document-extraction pipeline using a high-context model like `llama3.3:70b` (if hardware permits) or `phi3:medium` structured with JSON schema modes.
  - **JSON Mode:** Enabled (`format: "json"` in Ollama API) to guarantee schema compliance.
  - **System Prompt Reference:** `.agents/prompts/extraction_agent.txt`

### 3. Tax Prep Agent (Advisor)
* **Role:** Rules-Based Tax Advisor & Planner
* **Responsibilities:**
  - Evaluate `tax_data_2025.json` against the IRS rules stored in `.agents/skills/`.
  - Validate income against phase-out thresholds and enforce the $25,000 passive rental loss allowance phase-out (IRC § 469). Ensure rental depreciation is correctly calculated using MACRS 27.5-year straight-line rules and that land value is excluded.
  - Apply hobby loss tests (IRC § 183) to side businesses claiming losses. Verify if the business has losses year-over-year (failing 3-out-of-5-year profit test) and suggest restructuring to protect business deductions instead of losing them under hobby classification.
  - Evaluate extension filing timelines (October 15), calculate any potential failure-to-pay/file interest and penalties, and check if tax payments met the 110% safe harbor rule for high-income filers.
  - **Document completeness check:** Before producing the final report, cross-reference all extracted data against expected document types. Flag missing items explicitly (e.g., *"Form 4868 detected but no corresponding payment receipt found — please upload IRS Direct Pay or EFTPS confirmation"*). The report must include a **"Missing / Requested Documents"** section listing any gaps.
  - **Payment reconciliation:** Sum all entries in the payments ledger (withholding + estimated + extension payments) and compare against estimated total tax liability. Report the **total paid**, **estimated remaining balance**, and any **accrued interest or penalties** on the unpaid portion from the extension date through the current date.
  - **State extension handling:** If state extension vouchers or state payment receipts are present, evaluate state-specific filing deadlines, payment requirements, and any state-level penalties or interest separately from federal. If no state extension docs are found but W-2s show state withholding, flag this as a potential gap.
  - Generate a detailed markdown tax prep report at `final_outputs/tax_prep_report.md`.
* **Ollama Model Configuration (Fine-tuned / Specialized LLM):**
  - **Model:** Local custom model `tax-prep-gemma2` (A fine-tuned or heavily prompt-engineered model built on Gemma 2, specialized on Title 26 of the United States Code [IRC] and IRS publications).
  - **Modelfile Configuration:** Uses a custom system message loading rules dynamically and pre-loading tax code contexts.
  - **Temperature:** `0.1` (Allows analytical reasoning while maintaining strict rule compliance).
  - **System Prompt Reference:** `.agents/prompts/taxprep_agent.txt`

---

## Local Ollama Modelfile & Fine-Tuning Setup

For the **Tax Prep Agent**, using a model configured with a custom Modelfile containing specific system-level planning knowledge is highly recommended.

### Example Ollama Modelfile (`.agents/Modelfile.taxprep`)
To run the Tax Prep Agent with local planning guidelines, build the custom model using Ollama:

```dockerfile
# Create a specialized tax prep model on top of Gemma 2
FROM gemma2:27b

# Set low temperature for logical tax planning consistency
PARAMETER temperature 0.1
PARAMETER top_p 0.9

# Load system instructions for IRS Tax Prep and Planning
SYSTEM """
You are the tax preparation specialist agent (Advisor). Your job is to review tax data and apply strict IRC rules:
1. Under TCJA, hobby losses are not deductible. Deducting Schedule C losses for hobby businesses is forbidden. Note hobby loss risks and recommend establishing profit motive documentation.
2. For high-income taxpayers (MAGI > $150,000), rental passive losses must be 100% suspended under Pub 925. Suggest short-term rental (STR) or REPS optimization strategies.
3. Residential real estate depreciation must use MACRS GDS 27.5-year straight-line. Land value must be carved out.
4. For taxpayers with prior year AGI > $150k, the safe harbor is 110% of prior year tax to avoid estimated tax penalties.
5. Post-extension deadline is Oct 15. Late payments accrue interest + 0.5%/month penalty.
6. DOCUMENT COMPLETENESS: Before producing your report, verify that all expected supporting documents are present. If a Form 4868 exists but no payment receipt, flag it. If W-2s show state withholding but no state extension docs exist, flag it. Include a "Missing / Requested Documents" section.
7. PAYMENT RECONCILIATION: Sum ALL payments in the payments ledger (withholding, estimated, extension) and compare to estimated total liability. Report total paid, remaining balance, and accrued interest/penalties from the extension date to the current date.
8. STATE EXTENSIONS: Evaluate state extension deadlines and payment requirements separately. Apply state-specific penalty rules where state docs are present.
Ensure all calculations, planning options, and citations refer exactly to the rule files provided in `.agents/skills/`.
Provide constructive next steps.
"""
```

To build this model locally:
```bash
ollama create tax-prep-gemma2 -f .agents/Modelfile.taxprep
```
