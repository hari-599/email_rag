import sys

from Services.Exceptions.exception import SecurityException
from Services.Logger import logger
from Services.memory.session_create import get_session_manager
from Services.memory.session_summary import Session_Summary


class Memory_Storage:
    def __init__(self, session_manager=None, max_turns=5):
        self.session_manager = session_manager or get_session_manager()
        self.max_turns = max_turns
        self.session_summary = Session_Summary(session_manager=self.session_manager)

    def store_turn(self, session_id, user_text, rewrite, answer, citations=None, retrieved=None, last_topic=None):
        try:
            turn = self.session_manager.add_turn(
                session_id=session_id,
                user_text=user_text,
                rewrite=rewrite,
                answer=answer,
                citations=citations,
                retrieved=retrieved,
                last_topic=last_topic,
            )

            session = self.session_manager.get_session(session_id)
            session.history = session.history[-self.max_turns:]
            self.session_summary.update_session_notes(
                session_id=session_id,
                user_text=user_text,
                rewrite=rewrite,
                answer=answer,
                citations=citations,
                retrieved=retrieved,
            )

            logger.info("stored turn for session %s; history size=%s", session_id, len(session.history))
            return {
                "session_id": session.session_id,
                "thread_id": session.thread_id,
                "stored_turn": turn,
                "recent_history": session.get_recent_context(max_turns=self.max_turns),
            }
        except Exception as e:
            raise SecurityException(e, sys)

    def get_recent_history(self, session_id, max_turns=None):
        try:
            session = self.session_manager.get_session(session_id)
            turn_limit = max_turns or self.max_turns
            return session.get_recent_context(max_turns=turn_limit)
        except Exception as e:
            raise SecurityException(e, sys)
