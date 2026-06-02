# 🚀 Tax CPA-Loop Execution Guide

This guide covers how to correctly start the local server and use the Tax Prep Dashboard, as well as how to run it via the terminal.

## Option 1: Web Dashboard (Recommended)

Because this is a locally-hosted web application with a FastAPI backend, you cannot simply double-click `index.html`. You must start the server first.

### Step 1: Start the Backend
Open your terminal (`cmd.exe`) and run:
```cmd
cd "C:\Users\nswitzer\Antigrav Proj\tax_help"
uv run python app.py
```
*Wait until you see "Application startup complete" in the console.*

### Step 2: Open the Dashboard
Open your web browser (Chrome/Edge/Firefox) and navigate directly to:
**[http://127.0.0.1:8000](http://127.0.0.1:8000)**

### Step 3: Run the Pipeline
- In the dashboard, ensure your "Secure Tax Docs Folder" is set.
- Drop your PDFs into the folder if you haven't already.
- Click the **Run** button on the UI. The dashboard will automatically ping the backend, and you will see the logs stream right into the Live Orchestrator Terminal!

---

## Option 2: Terminal / Command Line

If you prefer to run the system without the dashboard, or want to explicitly define which AI model handles the complex tax audits (like `phi4:14b`), run this in your terminal:

```cmd
cd "C:\Users\nswitzer\Antigrav Proj\tax_help"
uv run python orchestrator.py --audit-model phi4:14b
```

> **Performance Note:** We just upgraded the Extractor Agent to completely eliminate truncation. If you upload a massive document, the system will chop it into chunks and read every single piece. This guarantees 100% data retention but may take significantly longer to process.
