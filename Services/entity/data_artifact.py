import re
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ChatSession:
    session_id: str
    thread_id: str
    history: list[dict] = field(default_factory=list)
    entity_notes: dict = field(
        default_factory=lambda: {
            "people": [],
            "dates": [],
            "amounts": [],
            "filenames": [],
            "message_ids": [],
            "last_topic": None,
        }
    )
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def add_turn(self, user_text, rewrite, answer, citations=None, retrieved=None, max_turns=5):
        turn = {
            "user_text": user_text,
            "rewrite": rewrite,
            "answer": answer,
            "citations": citations or [],
            "retrieved": retrieved or [],
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.history.append(turn)
        self.history = self.history[-max_turns:]
        self.updated_at = datetime.utcnow().isoformat()
        return turn

    def update_entity_notes(self, text="", citations=None, filenames=None, last_topic=None):
        combined_text = text or ""

        people = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", combined_text)
        dates = re.findall(
            r"\b(?:\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
            combined_text,
        )
        amounts = re.findall(r"(?:\$|USD\s?)\d[\d,]*(?:\.\d+)?", combined_text, re.IGNORECASE)
        message_ids = re.findall(r"<[^>\s]+>", combined_text)

        self._merge_unique("people", people)
        self._merge_unique("dates", dates)
        self._merge_unique("amounts", amounts)
        self._merge_unique("message_ids", message_ids)
        self._merge_unique("filenames", filenames or [])

        if citations:
            cited_ids = [item.get("message_id") for item in citations if item.get("message_id")]
            self._merge_unique("message_ids", cited_ids)

        if last_topic:
            self.entity_notes["last_topic"] = last_topic

        self.updated_at = datetime.utcnow().isoformat()
        return self.entity_notes

    def get_recent_context(self, max_turns=3):
        return self.history[-max_turns:]

    def reset(self):
        self.history = []
        self.entity_notes = {
            "people": [],
            "dates": [],
            "amounts": [],
            "filenames": [],
            "message_ids": [],
            "last_topic": None,
        }
        self.updated_at = datetime.utcnow().isoformat()

    def _merge_unique(self, key, values):
        current_values = self.entity_notes.get(key, [])
        seen = {value for value in current_values if value}

        for value in values:
            if value and value not in seen:
                current_values.append(value)
                seen.add(value)

        self.entity_notes[key] = current_values
