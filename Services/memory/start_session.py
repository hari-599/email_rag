import sys

from Services.Exceptions.exception import SecurityException
from Services.Logger import logger
from Services.memory.session_create import get_session_manager


class Start_Session:
    def __init__(self, session_manager=None):
        self.session_manager = session_manager or get_session_manager()

    def start_session(self, thread_id):
        try:
            session = self.session_manager.start_session(thread_id)

            response = {
                "session_id": session.session_id,
                "thread_id": session.thread_id,
                "history": session.history,
                "entity_notes": session.entity_notes,
            }

            logger.info("session created for thread %s with id %s", thread_id, session.session_id)
            return response
        except Exception as e:
            raise SecurityException(e, sys)
