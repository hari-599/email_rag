import sys
import uuid

from Services.entity.data_artifact import ChatSession
from Services.Exceptions.exception import SecurityException
from Services.Logger import logger


class Create_Session:
    def __init__(self):
        self.sessions = {}

    def start_session(self, thread_id):
        try:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
            session = ChatSession(session_id=session_id, thread_id=thread_id)
            self.sessions[session_id] = session
            logger.info("started session %s for thread %s", session_id, thread_id)
            return session
        except Exception as e:
            raise SecurityException(e, sys)

    def get_session(self, session_id):
        try:
            session = self.sessions.get(session_id)
            if session is None:
                raise ValueError(f"session not found: {session_id}")
            return session
        except Exception as e:
            raise SecurityException(e, sys)

    def add_turn(self, session_id, user_text, rewrite, answer, citations=None, retrieved=None, last_topic=None):
        try:
            session = self.get_session(session_id)
            turn = session.add_turn(user_text, rewrite, answer, citations=citations, retrieved=retrieved)
            return turn
        except Exception as e:
            raise SecurityException(e, sys)

    def switch_thread(self, session_id, thread_id):
        try:
            session = self.get_session(session_id)
            session.thread_id = thread_id
            session.reset()
            logger.info("switched session %s to thread %s", session_id, thread_id)
            return session
        except Exception as e:
            raise SecurityException(e, sys)

    def reset_session(self, session_id):
        try:
            session = self.get_session(session_id)
            session.reset()
            logger.info("reset session %s", session_id)
            return session
        except Exception as e:
            raise SecurityException(e, sys)


SESSION_MANAGER = Create_Session()


def get_session_manager():
    return SESSION_MANAGER
