import re
import sys

from Services.Exceptions.exception import SecurityException
from Services.generator.t5_helper import T5_Small_Helper
from Services.Logger import logger
from Services.memory.session_create import get_session_manager


class Query_Rewrite:
    PRONOUN_RE = re.compile(
        r"\b(that|it|he|she|they|them|those|these|earlier|previous|same one|that one)\b",
        re.IGNORECASE,
    )
    TOKEN_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9./'-]{2,}\b")
    BAD_REWRITE_RE = re.compile(r"\b(not_duplicate|return one short search query|duplicate)\b", re.IGNORECASE)

    def __init__(self, session_manager=None, t5_helper=None):
        self.session_manager = session_manager or get_session_manager()
        self.t5_helper = t5_helper or T5_Small_Helper()

    def _needs_rewrite(self, user_text):
        lowered = (user_text or "").strip().lower()
        if not lowered:
            return False

        if self.PRONOUN_RE.search(lowered):
            return True

        if lowered.startswith(("who ", "what ", "when ", "where ", "why ", "show ", "summarize ")):
            return False

        return len(lowered.split()) <= 3

    def _recent_reference(self, session):
        recent_turns = session.get_recent_context(max_turns=2)
        if not recent_turns:
            return None

        latest_turn = recent_turns[-1]
        return latest_turn.get("rewrite") or latest_turn.get("answer") or latest_turn.get("user_text")

    def _build_memory_hints(self, session):
        notes = session.entity_notes
        hints = []

        if notes.get("last_topic"):
            hints.append(f"topic: {notes['last_topic']}")

        if notes.get("filenames"):
            hints.append(f"filenames: {', '.join(notes['filenames'][-2:])}")

        if notes.get("message_ids"):
            hints.append(f"message_ids: {', '.join(notes['message_ids'][-2:])}")

        if notes.get("dates"):
            hints.append(f"dates: {', '.join(notes['dates'][-2:])}")

        if notes.get("amounts"):
            hints.append(f"amounts: {', '.join(notes['amounts'][-2:])}")

        if notes.get("people"):
            hints.append(f"people: {', '.join(notes['people'][-2:])}")

        return hints

    def _keyword_tokens(self, text):
        return [token.lower() for token in self.TOKEN_RE.findall(text or "")]

    def _rule_rewrite(self, cleaned_text, recent_reference, memory_hints):
        if not cleaned_text:
            return ""

        if not self._needs_rewrite(cleaned_text):
            return cleaned_text

        parts = [cleaned_text]

        if recent_reference and self.PRONOUN_RE.search(cleaned_text):
            parts.append(recent_reference)

        if memory_hints and self.PRONOUN_RE.search(cleaned_text):
            parts.extend(memory_hints[:2])

        combined = " ".join(part for part in parts if part)
        return combined[:240].strip()

    def _is_valid_model_rewrite(self, original_text, model_rewrite):
        if not model_rewrite:
            return False

        normalized = model_rewrite.strip()
        if not normalized:
            return False

        if self.BAD_REWRITE_RE.search(normalized):
            return False

        original_tokens = set(self._keyword_tokens(original_text))
        rewritten_tokens = set(self._keyword_tokens(normalized))

        if not rewritten_tokens:
            return False

        if original_tokens and not (original_tokens & rewritten_tokens):
            return False

        if len(rewritten_tokens) > 18:
            return False

        return True

    def rewrite_query(self, session_id, user_text):
        try:
            session = self.session_manager.get_session(session_id)
            cleaned_text = (user_text or "").strip()
            recent_reference = self._recent_reference(session)
            memory_hints = self._build_memory_hints(session)
            fallback_rewrite = self._rule_rewrite(cleaned_text, recent_reference, memory_hints)

            if not cleaned_text:
                rewrite = ""
            elif self.t5_helper.available and self._needs_rewrite(cleaned_text):
                prompt_parts = [
                    "rewrite the user question for email retrieval.",
                    f"user question: {cleaned_text}",
                ]
                if recent_reference:
                    prompt_parts.append(f"recent context: {recent_reference}")
                if memory_hints:
                    prompt_parts.append("memory hints: " + "; ".join(memory_hints))
                prompt_parts.append("return one short search query.")

                model_rewrite = self.t5_helper.generate(" ".join(prompt_parts), max_new_tokens=48)
                rewrite = model_rewrite.strip() if self._is_valid_model_rewrite(cleaned_text, model_rewrite) else fallback_rewrite
            else:
                rewrite = fallback_rewrite

            logger.info("rewrote query for session %s", session_id)
            return {
                "session_id": session.session_id,
                "thread_id": session.thread_id,
                "original_query": cleaned_text,
                "rewrite": rewrite,
                "recent_history": session.get_recent_context(max_turns=3),
                "entity_notes": session.entity_notes,
            }
        except Exception as e:
            raise SecurityException(e, sys)
