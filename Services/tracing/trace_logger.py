import json
import os
import sys
import uuid
from datetime import datetime

from Services.Exceptions.exception import SecurityException
from Services.Logger import logger


class Trace_Logger:
    def __init__(self, run_root="runs", run_id=None):
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(run_root, self.run_id)
        self.trace_file = os.path.join(self.run_dir, "trace.jsonl")
        os.makedirs(self.run_dir, exist_ok=True)

    def write_turn(
        self,
        session_id,
        thread_id,
        user_text,
        rewrite,
        retrieved,
        used_items,
        answer,
        citations,
        latency_ms,
        search_outside_thread=False,
        token_counts=None,
    ):
        try:
            trace_id = f"trace_{uuid.uuid4().hex[:12]}"
            payload = {
                "trace_id": trace_id,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "thread_id": thread_id,
                "user_text": user_text,
                "rewrite": rewrite,
                "retrieved": retrieved,
                "used_items": used_items,
                "answer": answer,
                "citations": citations,
                "latency_ms": latency_ms,
                "search_outside_thread": search_outside_thread,
                "token_counts": token_counts or {},
            }

            with open(self.trace_file, "a", encoding="utf-8") as trace_stream:
                trace_stream.write(json.dumps(payload) + "\n")

            logger.info("trace written to %s", self.trace_file)
            return trace_id
        except Exception as e:
            raise SecurityException(e, sys)
