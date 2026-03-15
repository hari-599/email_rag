import os
import sys

from Services.Exceptions.exception import SecurityException
from Services.Logger import logger


class T5_Small_Helper:
    def __init__(self, model_name="t5-small", enabled=None):
        self.model_name = model_name
        self.enabled = enabled if enabled is not None else os.getenv("USE_T5_SMALL", "true").lower() == "true"
        self._model = None
        self._tokenizer = None
        self._load_error = None

        if self.enabled:
            self._load_pipeline()

    def _load_pipeline(self):
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
            logger.info("loaded %s for rewrite/compression", self.model_name)
        except Exception as error:
            self._load_error = str(error)
            self._model = None
            self._tokenizer = None
            logger.warning("t5-small unavailable, falling back to rules: %s", self._load_error)

    @property
    def available(self):
        return self._model is not None and self._tokenizer is not None

    def generate(self, prompt, max_new_tokens=64):
        try:
            if not self.available:
                return None

            inputs = self._tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=512,
            )

            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
            )
            if output_ids is None or len(output_ids) == 0:
                return None

            return self._tokenizer.decode(
                output_ids[0],
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True,
            ).strip()
        except Exception as e:
            raise SecurityException(e, sys)
