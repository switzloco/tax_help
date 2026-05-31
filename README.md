# Tax Orchestration Swarm: Multi-Agent Mesh Dashboard

Welcome to the **Multi-Agent Tax Orchestration Workspace**. This repository scaffolds a three-agent mesh designed to automate the intake, extraction, and preparation of complex tax profiles (MFJ, W-2 high-income, rental property depreciation, side-business losses, and post-extension filings) using local LLMs via **Ollama**.

---

## 📂 Repository Structure

```text
tax_help/
├── .agents/
│   ├── skills/
│   │   ├── michigan_rental_rules.md  # IRS Pub 925, MACRS 27.5-year depreciation
│   │   ├── hobby_loss_rules.md       # IRC § 183 & TCJA loss deductibility
│   │   └── extension_filing_rules.md # Post-extension penalties & 110% Safe Harbor
│   └── Modelfile.taxprep             # Local Ollama custom model definition
├── raw_docs/                         # [IGNORED] Place raw PDF/JPG/CSV uploads here
├── processed_data/                   # [IGNORED] Stores structured JSON outputs
├── final_outputs/                    # Stores markdown tax prep reports
├── .gitignore                        # Prevents PII leaks (ignores raw data & JSONs)
├── AGENTS.md                         # Agent routing & Ollama configurations
└── README.md                         # Mission Control Dashboard (This file)
```

---

## 🛠️ Setup & Prerequisites

### 1. Install & Start Ollama
Ensure Ollama is installed on your local machine. Download it from [ollama.com](https://ollama.com).
Start the local server (usually runs automatically in the background on port `11434`).

### 2. Pull / Create Local Models
For classification and extraction:
```cmd
ollama pull gemma2:9b
ollama pull llama3.2-vision
```

For the specialized **Tax Prep Agent** (Advisor), you can build the custom agent model with embedded tax knowledge using the provided Modelfile:
```cmd
ollama create tax-prep-gemma2 -f .agents/Modelfile.taxprep
```

> [!TIP]
> **Model Fine-Tuning Option:** Use the [`fine_tune_unsloth.py`](file:///C:/Users/nswitzer/Antigrav%20Proj/tax_help/fine_tune_unsloth.py) script on Kaggle to fine-tune Gemma 2. The script will automatically run an in-memory accuracy evaluation suite right after training to verify performance. If you add your Hugging Face API key as a Kaggle secret named `HF_TOKEN`, it will then quantize, convert, and push the GGUF model directly to [nswitzer/gemma2-9b-tax-prep-GGUF](https://huggingface.co/nswitzer/gemma2-9b-tax-prep-GGUF) so you can download and use it immediately locally.

---

## 🚀 How to Run the Mesh

This workspace is designed to run locally using the provided Python orchestrator. It automatically detects and resolves models against your local Ollama instance, falling back gracefully to available Gemma models if the target or custom models are not found.

### 1. Dropping Documents
Place your raw tax files in the `raw_docs/` directory:
- W-2 documents (e.g., spouse 1 and spouse 2)
- 1099s or ledger files for the side businesses
- Rental income and expense sheets (Schedule E data)
- Form 4868 (extension request confirmation)

### 2. Execution Flow
To run the mesh using defaults:
```cmd
uv run orchestrator.py
```

To run with a specific basic Gemma model (e.g., if you have `gemma4:e2b` or `gemma4:e4b` installed and want to run it first):
```cmd
uv run orchestrator.py --model gemma4:e2b
```

You can also override models for specific agents if desired:
- `--sorter-model <model_name>`: Override model for Intake Agent
- `--reader-model <model_name>`: Override model for Extraction Agent
- `--audit-model <model_name>`: Override model for Tax Prep Agent

*Note: Since Python is managed by `uv` on this system, always run scripts using `uv run`.*

### 3. Mesh Stages
1. **Intake Agent (Sorter):** Scans `raw_docs/`, renames files cleanly (e.g., `2025_W2_Spouse1.txt`), and cleans the folder structure.
2. **Extraction Agent (Reader):** Parses files and outputs `processed_data/tax_data_2025.json`.
3. **Tax Prep Agent (Advisor):** Examines `tax_data_2025.json`, compares it against rules in `.agents/skills/`, and outputs `final_outputs/tax_prep_report.md`. The final report will contain a banner indicating which model was used.

### 4. Testing Model Accuracy
To evaluate and verify the accuracy of a model against key IRS regulatory requirements and compliance criteria, run the test script.

Evaluate the custom model:
```cmd
uv run test_accuracy.py
```

Evaluate a basic Gemma model to establish a baseline:
```cmd
uv run test_accuracy.py --model gemma4:e2b
```
This runs 5 critical compliance scenarios (e.g. passive loss phase-outs, MACRS depreciation conventions, hobby loss deduction blocks, safe harbors) and computes an overall accuracy score based on key terminology and calculation checks.

---

## 🔒 Security & Privacy (PII Protection)
To comply with strict privacy policies, this repository has a robust `.gitignore` configuration that **never** commits tax documents, spreadsheets, PDFs, or processed JSON files.
- `raw_docs/*` is strictly ignored.
- `processed_data/*` is strictly ignored.
- Markdown rule files in `.agents/skills/` are fully tracked.
- Output tax prep reports in `final_outputs/` are tracked (ensure no raw SSNs/PII are printed to reports).
