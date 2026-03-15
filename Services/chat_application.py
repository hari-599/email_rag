import sys
import time
from collections import Counter

from Services.Exceptions.exception import SecurityException
from Services.generator import Grounded_Answer_Generator
from Services.Logger import logger
from Services.memory import Memory_Storage, Query_Rewrite, Start_Session, get_session_manager
from Services.preprocessor.ingest import Email_Ingestor, ThreadAwareRetriever
from Services.tracing import Trace_Logger


class Chat_Application:
    def __init__(self):
        try:
            self.session_manager = get_session_manager()
            self.start_session_service = Start_Session(session_manager=self.session_manager)
            self.memory_storage = Memory_Storage(session_manager=self.session_manager, max_turns=5)
            self.query_rewrite = Query_Rewrite(session_manager=self.session_manager)
            self.answer_generator = Grounded_Answer_Generator()
            self.trace_logger = Trace_Logger()

            ingestion_result = Email_Ingestor().ingest()
            self.records = ingestion_result["records"]
            self.chunks = ingestion_result["chunks"]
            self.retriever = ThreadAwareRetriever(self.chunks)
            self.thread_ids = sorted({chunk["thread_id"] for chunk in self.chunks if chunk.get("thread_id")})
            logger.info("chat application initialized with %s threads", len(self.thread_ids))
        except Exception as e:
            raise SecurityException(e, sys)

    def _slim_items(self, items):
        return [
            {
                "doc_id": item.get("doc_id"),
                "thread_id": item.get("thread_id"),
                "message_id": item.get("message_id"),
                "page_no": item.get("page_no"),
                "filename": item.get("filename"),
                "chunk_type": item.get("chunk_type"),
                "score": item.get("score"),
                "subject": item.get("subject"),
                "date": item.get("date"),
                "text_preview": item.get("text_preview") or (item.get("text", "")[:280] if item.get("text") else ""),
            }
            for item in items
        ]

    def list_threads(self):
        try:
            thread_counts = Counter(chunk["thread_id"] for chunk in self.chunks if chunk.get("thread_id"))
            return [
                {
                    "thread_id": thread_id,
                    "message_count": thread_counts.get(thread_id, 0),
                }
                for thread_id in self.thread_ids
            ]
        except Exception as e:
            raise SecurityException(e, sys)

    def start_session(self, thread_id):
        try:
            return self.start_session_service.start_session(thread_id)
        except Exception as e:
            raise SecurityException(e, sys)

    def switch_thread(self, session_id, thread_id):
        try:
            session = self.session_manager.switch_thread(session_id, thread_id)
            return {
                "session_id": session.session_id,
                "thread_id": session.thread_id,
                "history": session.history,
                "entity_notes": session.entity_notes,
            }
        except Exception as e:
            raise SecurityException(e, sys)

    def reset_session(self, session_id):
        try:
            session = self.session_manager.reset_session(session_id)
            return {
                "session_id": session.session_id,
                "thread_id": session.thread_id,
                "history": session.history,
                "entity_notes": session.entity_notes,
            }
        except Exception as e:
            raise SecurityException(e, sys)

    def ask(self, session_id, text, search_outside_thread=False, top_k=5):
        try:
            start_time = time.perf_counter()
            session = self.session_manager.get_session(session_id)
            rewrite_payload = self.query_rewrite.rewrite_query(session_id, text)

            # Always prefer the active thread first. Global search is only a fallback
            # when the user explicitly enables it and the focused thread has no hits.
            retrieved = self.retriever.search(
                rewrite_payload["rewrite"],
                thread_id=session.thread_id,
                top_k=top_k,
            )

            if not retrieved:
                retrieved = self.retriever.get_thread_chunks(session.thread_id, top_k=top_k)

            if not retrieved and search_outside_thread:
                retrieved = self.retriever.search(rewrite_payload["rewrite"], thread_id=None, top_k=top_k)

            answer_payload = self.answer_generator.answer(
                text,
                retrieved,
                thread_id=session.thread_id,
                retrieval_query=rewrite_payload["rewrite"],
            )
            slim_retrieved = self._slim_items(retrieved)
            slim_used_items = self._slim_items(answer_payload["used_items"])

            self.memory_storage.store_turn(
                session_id=session_id,
                user_text=text,
                rewrite=rewrite_payload["rewrite"],
                answer=answer_payload["answer"],
                citations=answer_payload["citations"],
                retrieved=slim_retrieved,
                last_topic=rewrite_payload["rewrite"],
            )

            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            trace_id = self.trace_logger.write_turn(
                session_id=session_id,
                thread_id=session.thread_id,
                user_text=text,
                rewrite=rewrite_payload["rewrite"],
                retrieved=slim_retrieved,
                used_items=slim_used_items,
                answer=answer_payload["answer"],
                citations=answer_payload["citations"],
                latency_ms=latency_ms,
                search_outside_thread=search_outside_thread,
            )

            return {
                "answer": answer_payload["answer"],
                "citations": answer_payload["citations"],
                "rewrite": rewrite_payload["rewrite"],
                "retrieved": slim_retrieved,
                "trace_id": trace_id,
                "latency_ms": latency_ms,
                "thread_id": session.thread_id,
            }
        except Exception as e:
            raise SecurityException(e, sys)
