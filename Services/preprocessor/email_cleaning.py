import html
import re
import sys

from Services.Exceptions.exception import SecurityException
from Services.Logger import logger


class Email_Cleaning:
    DISCLAIMER_PATTERNS = (
        r"this e-mail and any attachments?.*",
        r"the information contained in this email.*",
        r"this message may contain confidential.*",
        r"if you are not the intended recipient.*",
        r"legal stuff.*",
        r"this story appeared on.*",
        r"here is the story we were requested to send you.*",
    )
    CUT_OFF_PATTERNS = (
        re.compile(r"^legal stuff$", re.IGNORECASE),
        re.compile(r"^the information contained in this newsletter", re.IGNORECASE),
        re.compile(r"^this story appeared on", re.IGNORECASE),
        re.compile(r"^here is the story we were requested to send you", re.IGNORECASE),
        re.compile(r"^[-_]{10,}$"),
        re.compile(r"^attachment part", re.IGNORECASE),
        re.compile(r"^content-disposition:\s*attachment", re.IGNORECASE),
    )

    FORWARDED_HEADER_RE = re.compile(
        r"^(from|sent|to|cc|subject|date)\s*:",
        re.IGNORECASE,
    )

    HTML_TAG_RE = re.compile(r"<[^>]+>")
    MULTISPACE_RE = re.compile(r"[ \t]+")
    MULTIBLANK_RE = re.compile(r"\n{3,}")

    def _strip_html_artifacts(self, text):
        text = html.unescape(text)
        text = self.HTML_TAG_RE.sub(" ", text)
        return text

    def _remove_disclaimer_blocks(self, text):
        lines = text.splitlines()

        for index, line in enumerate(lines):
            lowered_line = line.strip().lower()
            if any(re.match(pattern, lowered_line) for pattern in self.DISCLAIMER_PATTERNS):
                return "\n".join(lines[:index]).strip()
            if any(pattern.match(line.strip()) for pattern in self.CUT_OFF_PATTERNS):
                return "\n".join(lines[:index]).strip()

        return text

    def _remove_newsletter_noise(self, text):
        lines = []
        skip_prefixes = (
            "welcome new hires",
            "transfers to",
            "nuggets & notes",
            "in the news",
            "enrononline statistics",
        )

        for line in text.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            if not stripped:
                lines.append("")
                continue
            if any(lowered.startswith(prefix) for prefix in skip_prefixes):
                break
            if lowered.startswith("http://") or lowered.startswith("https://"):
                continue
            if lowered.startswith("[no worries"):
                continue
            lines.append(line)

        return "\n".join(lines).strip()

    def _remove_redundant_forward_headers(self, text):
        cleaned_lines = []
        consecutive_header_lines = 0

        for line in text.splitlines():
            stripped = line.strip()
            is_header_line = bool(self.FORWARDED_HEADER_RE.match(stripped))

            if is_header_line:
                consecutive_header_lines += 1
            else:
                consecutive_header_lines = 0

            if consecutive_header_lines >= 3:
                continue

            cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    def _unwrap_broken_lines(self, text):
        lines = text.splitlines()
        rebuilt_lines = []
        buffer = ""

        for line in lines:
            stripped = line.strip()

            if not stripped:
                if buffer:
                    rebuilt_lines.append(buffer.strip())
                    buffer = ""
                rebuilt_lines.append("")
                continue

            if stripped.startswith(">"):
                if buffer:
                    rebuilt_lines.append(buffer.strip())
                    buffer = ""
                rebuilt_lines.append(stripped)
                continue

            if self.FORWARDED_HEADER_RE.match(stripped) or stripped.startswith("-----Original Message-----"):
                if buffer:
                    rebuilt_lines.append(buffer.strip())
                    buffer = ""
                rebuilt_lines.append(stripped)
                continue

            if not buffer:
                buffer = stripped
                continue

            join_with_space = not buffer.endswith((".", "!", "?", ":", ";")) and not stripped.startswith(("-", "*"))
            if join_with_space:
                buffer = f"{buffer} {stripped}"
            else:
                rebuilt_lines.append(buffer.strip())
                buffer = stripped

        if buffer:
            rebuilt_lines.append(buffer.strip())

        return "\n".join(rebuilt_lines)

    def clean_body(self, body):
        if not body:
            return ""

        cleaned = body.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = self._strip_html_artifacts(cleaned)
        cleaned = self._remove_redundant_forward_headers(cleaned)
        cleaned = self._remove_disclaimer_blocks(cleaned)
        cleaned = self._remove_newsletter_noise(cleaned)
        cleaned = self._unwrap_broken_lines(cleaned)
        cleaned = "\n".join(self.MULTISPACE_RE.sub(" ", line).strip() for line in cleaned.splitlines())
        cleaned = self.MULTIBLANK_RE.sub("\n\n", cleaned)
        return cleaned.strip()

    def clean_record(self, record):
        cleaned_record = dict(record)
        cleaned_record["clean_body"] = self.clean_body(record.get("body", ""))
        return cleaned_record

    def clean_records(self, records):
        try:
            cleaned_records = [self.clean_record(record) for record in records]
            logger.info("cleaned %s email bodies", len(cleaned_records))
            return cleaned_records
        except Exception as e:
            raise SecurityException(e, sys)
