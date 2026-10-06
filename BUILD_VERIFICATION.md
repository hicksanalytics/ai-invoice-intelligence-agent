# Project verification

## Verified locally on Windows
- All 21 automated tests pass after the connection-cleanup and fixture-selection fixes.
- Local AI model: qwen3:4b-instruct-2507-q4_K_M.
- Verified extraction and approval of a clean labeled invoice and a natural-layout text invoice.
- Observed expected findings for incorrect totals, missing invoice numbers, duplicates, large amounts, and unreadable totals.
- Verified a text-based PDF against its source, approved it, and exported the approved record.
- Updated the prompt to restrict extraction notes to unresolved problems and supply the current date.
- Used the local dashboard to review findings and approve verified records.

## Limits
- These checks use a small set of synthetic invoices, not a production accuracy benchmark.
- Image and scanned-document extraction have not been tested with a vision model.
- Automated tests mock Ollama; live extraction was checked separately.
- The app is a localhost demo without user authentication or accounting-system writes.
