import re
import sys

from Services.Exceptions.exception import SecurityException
from Services.Logger import logger
from Services.memory.session_create import get_session_manager


class Session_Summary:
    DATE_RE = re.compile(
        r"\b(?:\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b"
    )
    AMOUNT_RE = re.compile(r"(?:\$|USD\s*)\s*\d[\d,]*(?:\.\d+)?", re.IGNORECASE)
    MESSAGE_ID_RE = re.compile(r"<[^>\s]+>")
    PERSON_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
    FILENAME_RE = re.compile(r"\b[\w,\-]+\.(?:pdf|docx?|txt|html?)\b", re.IGNORECASE)
    NOISY_PEOPLE = {"Enron Corp", "Siebel Summary", "Legal Stuff", "Business Highlights"}

    def __init__(self, session_manager=None):
        self.session_manager = session_manager or get_session_manager()

    def _collect_text(self, user_text="", rewrite="", answer=""):
        return " ".join(value for value in (user_text, rewrite, answer) if value)

    def _extract_topic_phrase(self, user_text="", rewrite="", retrieved=None):
        if rewrite:
            return rewrite.strip()

        if user_text:
            return user_text.strip()

        if retrieved:
            first_subject = next((item.get("subject") for item in retrieved if item.get("subject")), None)
            if first_subject:
                return first_subject

        return None

    def extract_notes(self, user_text="", rewrite="", answer="", citations=None, retrieved=None):
        combined_text = self._collect_text(user_text=user_text, rewrite=rewrite, answer=answer)

        filenames = self.FILENAME_RE.findall(combined_text)
        if retrieved:
            filenames.extend(item.get("filename") for item in retrieved if item.get("filename"))

        cited_ids = []
        if citations:
            cited_ids.extend(item.get("message_id") for item in citations if item.get("message_id"))

        people = [value for value in self.PERSON_RE.findall(combined_text) if value not in self.NOISY_PEOPLE]
        if retrieved:
            people.extend(item.get("from") for item in retrieved if item.get("from"))

        notes = {
            "people": [value for value in people if value],
            "dates": self.DATE_RE.findall(combined_text),
            "amounts": self.AMOUNT_RE.findall(combined_text),
            "filenames": [value for value in filenames if value],
            "message_ids": self.MESSAGE_ID_RE.findall(combined_text) + cited_ids,
            "last_topic": self._extract_topic_phrase(user_text=user_text, rewrite=rewrite, retrieved=retrieved),
        }
        return notes

    def update_session_notes(self, session_id, user_text="", rewrite="", answer="", citations=None, retrieved=None):
        try:
            session = self.session_manager.get_session(session_id)
            notes = self.extract_notes(
                user_text=user_text,
                rewrite=rewrite,
                answer=answer,
                citations=citations,
                retrieved=retrieved,
            )

            session.update_entity_notes(
                text=self._collect_text(user_text=user_text, rewrite=rewrite, answer=answer),
                citations=[{"message_id": value} for value in notes["message_ids"] if value],
                filenames=notes["filenames"],
                last_topic=notes["last_topic"],
            )

            logger.info("updated entity notes for session %s", session_id)
            return {
                "session_id": session.session_id,
                "thread_id": session.thread_id,
                "entity_notes": session.entity_notes,
            }
        except Exception as e:
            raise SecurityException(e, sys)
