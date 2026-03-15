# NexusOcean

Small, grounded email-thread RAG prototype built on a laptop-sized Enron slice.

## What It Does

- parses raw email rows from `data/laptop_slice/emails.csv`
- cleans noisy email text
- infers `thread_id` values
- builds per-message retrievable chunks
- runs thread-scoped lexical retrieval
- keeps short conversation memory
- rewrites vague follow-up questions
- answers with inline message citations
- exposes a Flask API and tiny built-in UI
- writes one JSON trace record per turn to `runs/<timestamp>/trace.jsonl`

## What It Does Not Do

- It does **not** ingest standalone attachment files.
- It does **not** answer from attachment contents such as PDF, DOC, image, or scanned files.
- If an email mentions an attachment, that signal may still appear in the raw email text, but retrieval is grounded only in the email message content itself.

## Run Locally

```powershell
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Open:

- `http://127.0.0.1:8000`

## API

### `GET /threads`

Returns available thread IDs and message counts.

### `POST /start_session`

```json
{ "thread_id": "thread_0001" }
```

### `POST /ask?search_outside_thread=false`

```json
{ "session_id": "sess_...", "text": "Who won the newsletter contest?" }
```

Response shape:

```json
{
  "answer": "...",
  "citations": [...],
  "rewrite": "...",
  "retrieved": [...],
  "trace_id": "..."
}
```

### `POST /switch_thread`

```json
{ "session_id": "sess_...", "thread_id": "thread_0002" }
```

### `POST /reset_session`

```json
{ "session_id": "sess_..." }
```

## Docker

```powershell
docker compose up --build
```

## Retrieval Approach

- Baseline retrieval uses a lexical BM25-style scorer implemented in `ThreadAwareRetriever` inside `Services/preprocessor/ingest.py`
- Documents are built as email chunks containing:
  - subject
  - sender
  - recipients
  - cc
  - cleaned email body
- Retrieval is thread-aware:
  - the active thread is searched first
  - if no useful hit is found and outside-thread search is enabled, global retrieval can be used as a fallback
- No dense vector store is used in the current version
- No neural reranker is used in the current version
- Optional `t5-small` support is used only for:
  - query rewriting
  - short answer compression
- Final answers are grounded in retrieved email evidence and returned with message-level citations

## Design Choices

- Used a small laptop-friendly Enron slice so the project can run locally without heavy infrastructure
- Used thread-aware retrieval because the assignment focuses on email-thread understanding, not generic document search
- Used lexical BM25-style retrieval because it is lightweight, transparent, and easy to debug
- Kept session memory in-process and simple so follow-up question handling stays understandable
- Used a rule-guided answer generator to keep answers grounded and citation-friendly
- Added optional `t5-small` only as a helper rather than making the whole system model-dependent
- Logged every turn to `runs/<timestamp>/trace.jsonl` so retrieval, rewrites, citations, and latency can be inspected later

## Known Limitations

- Retrieval is lexical, so semantic matching is weaker than a vector-based system
- Threading is heuristic and may occasionally merge or split conversations imperfectly
- The answer generator is rule-heavy and can be brittle for unusual question phrasing
- Optional T5 rewrite/compression can still be unstable if prompts drift outside expected patterns
- Session storage is in-memory only and resets when the app restarts
- Standalone attachment files are not ingested or used as evidence in this version
- When outside-thread retrieval is enabled, answer quality can drop if unrelated threads score higher than the focused thread

## How To Test

1. Install dependencies and start the app:

```powershell
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

2. Open:

- `http://127.0.0.1:8000`

3. Choose `thread_0005`

4. Start a new session

5. Keep `Search outside thread` disabled for thread-focused evaluation

6. Ask the following sample questions

## Sample Test Questions

### Thread 005

- What is the summary of this thread?
- What specific decision, request, or proposal is being discussed?
- Why was this email forwarded?
- What meeting is being referred to here?
- Where is the meeting connected to?
- Who are the main people involved in this conversation?

## Expected Behavior For Thread 005

- Answers should stay focused on the Calpine pre-meeting / November 27 coordination thread
- Citations should point to message IDs from `thread_0005`
- Summary and request questions should reference the forwarded meeting coordination context
- Meeting and location questions should reference the Governor's office / Los Angeles context
- People questions should return participants from the actual thread, not unrelated newsletter threads
- A sample conversation trace should appear in `runs/<timestamp>/trace.jsonl`

## Project Notes

- Dataset details are in `DATASET_SLICE.md`
- Current grounding supports email citations:
  - `[msg: <message_id>]`
- Attachment/page citation fields exist in the trace and response schema, but standalone attachment ingestion is not implemented in this version
- In practice, this project uses email-message evidence only, not attachment-file evidence
