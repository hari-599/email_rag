import csv
import os
import quopri
import sys
from email.utils import parsedate_to_datetime
from Services.Exceptions.exception import SecurityException
from Services.Logger import logger

csv.field_size_limit(min(sys.maxsize, 2147483647))
class Email_Structure:
    def __init__(self, source_csv_path=None):
        self.source_csv_path = source_csv_path or os.path.join("data", "laptop_slice", "emails.csv")

    def _split_raw_email(self, raw_message):
        if "\n\n" in raw_message:
            return raw_message.split("\n\n", 1)
        return raw_message, ""

    def _extract_headers(self, header_text):
        headers = {}
        current_key = None

        for raw_line in header_text.splitlines():
            if not raw_line.strip():
                continue

            if raw_line[0] in " \t" and current_key:
                headers[current_key] = f"{headers[current_key]} {raw_line.strip()}"
                continue

            if ":" not in raw_line:
                continue

            key, value = raw_line.split(":", 1)
            current_key = key.lower().strip()
            headers[current_key] = value.strip()

        return headers

    def _decode_body(self, body, headers):
        transfer_encoding = headers.get("content-transfer-encoding", "").lower()

        if transfer_encoding == "quoted-printable":
            try:
                return quopri.decodestring(body).decode("utf-8", errors="replace")
            except Exception:
                return quopri.decodestring(body).decode("latin-1", errors="replace")

        return body

    def _normalize_list_field(self, value):
        if not value:
            return []

        parts = [item.strip() for item in value.replace("\n", " ").split(",")]
        return [item for item in parts if item]

    def _normalize_date(self, raw_date):
        if not raw_date:
            return None

        try:
            parsed = parsedate_to_datetime(raw_date)
        except (TypeError, ValueError, IndexError, OverflowError):
            return raw_date

        if parsed is None:
            return raw_date

        return parsed.isoformat()

    def parse_email_row(self, row):
        raw_message = row.get("message", "")
        header_text, body = self._split_raw_email(raw_message)
        headers = self._extract_headers(header_text)
        decoded_body = self._decode_body(body, headers).strip()

        return {
            "message_id": headers.get("message-id"),
            "subject": headers.get("subject"),
            "date": self._normalize_date(headers.get("date")),
            "from": headers.get("from"),
            "to": self._normalize_list_field(headers.get("to")),
            "cc": self._normalize_list_field(headers.get("cc") or headers.get("x-cc")),
            "body": decoded_body,
            "in_reply_to": headers.get("in-reply-to") or headers.get("reply-to"),
            "references": self._normalize_list_field(headers.get("references")),
            "source_file": row.get("file"),
        }

    def build_structured_records(self):
        try:
            structured_records = []

            with open(self.source_csv_path, newline="", encoding="utf-8") as source_file:
                reader = csv.DictReader(source_file)
                for row in reader:
                    structured_records.append(self.parse_email_row(row))

            logger.info("parsed %s structured email records from %s", len(structured_records), self.source_csv_path)
            return structured_records

        except Exception as e:
            raise SecurityException(e, sys)

