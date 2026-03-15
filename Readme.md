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

## Project Notes

- Dataset details are in `DATASET_SLICE.md`
- Current grounding supports email citations:
  - `[msg: <message_id>]`
- Attachment/page citations are structurally supported but standalone attachment ingestion is not implemented yet
