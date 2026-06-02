# Tax CPA-Loop Execution Guide

Set the environment variable `TAX_DOCS_DIR` to point at your tax documents folder
(outside the repo). The pipeline reads from there and writes processed data and
reports inside the repo's `processed_data/` and `final_outputs/` directories
(both gitignored).

```bash
export TAX_DOCS_DIR="/path/to/your/tax/docs"
```

## Option 1: Web Dashboard

Start the FastAPI backend:
```bash
uv run python app.py
```

Wait for "Application startup complete", then open **http://127.0.0.1:8000**.

- Set your "Secure Tax Docs Folder" in the dashboard (or rely on `TAX_DOCS_DIR`).
- Drop PDFs into the folder.
- Click **Run** — logs stream into the Live Orchestrator Terminal.

## Option 2: Terminal

Run the full CPA-loop directly:
```bash
uv run orchestrator.py
```

Override the audit model if desired:
```bash
uv run orchestrator.py --audit-model gemma4:27b
```

## Model overrides

| Flag | Purpose |
|---|---|
| `--model` | Default model for all agents |
| `--sorter-model` | Override Intake Agent model |
| `--reader-model` | Override Extraction Agent model |
| `--audit-model` | Override Tax Prep / Strategist model |

## Testing model accuracy

Evaluate a model against IRS compliance scenarios:
```bash
uv run test_accuracy.py
uv run test_accuracy.py --model gemma4:e2b
```
