import re
import sys
from collections import defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime

from Services.Exceptions.exception import SecurityException
from Services.Logger import logger


class Email_threading:
    SUBJECT_PREFIX_RE = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.IGNORECASE)

    def normalize_subject(self, subject):
        if not subject:
            return ""

        cleaned = self.SUBJECT_PREFIX_RE.sub("", subject.strip())
        return " ".join(cleaned.lower().split())

    def _normalize_address(self, value):
        return (value or "").strip().lower()

    def _participants(self, record):
        participants = set()

        if record.get("from"):
            participants.add(self._normalize_address(record["from"]))

        for field in ("to", "cc"):
            for value in record.get(field, []):
                normalized = self._normalize_address(value)
                if normalized:
                    participants.add(normalized)

        return participants

    def _parse_date(self, value):
        if not value:
            return None

        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError, OverflowError):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None

        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)

        return parsed

    def _date_gap_days(self, left, right):
        if left is None or right is None:
            return None
        return abs((left - right).days)

    def _participant_overlap(self, left, right):
        return bool(left & right)

    def _find(self, parents, index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def _union(self, parents, left, right):
        left_root = self._find(parents, left)
        right_root = self._find(parents, right)

        if left_root != right_root:
            parents[right_root] = left_root

    def _link_by_reply_headers(self, records, parents):
        message_index = {}
        for index, record in enumerate(records):
            message_id = record.get("message_id")
            if message_id:
                message_index[message_id] = index

        for index, record in enumerate(records):
            related_ids = []
            if record.get("in_reply_to"):
                related_ids.append(record["in_reply_to"])
            related_ids.extend(record.get("references", []))

            for related_id in related_ids:
                related_index = message_index.get(related_id)
                if related_index is not None:
                    self._union(parents, index, related_index)

    def _link_by_fallback_signals(self, records, parents):
        subject_buckets = defaultdict(list)

        for index, record in enumerate(records):
            subject_buckets[record["normalized_subject"]].append(index)

        for _, indexes in subject_buckets.items():
            if len(indexes) < 2:
                continue

            ordered_indexes = sorted(indexes, key=lambda item: (records[item]["parsed_date"] or datetime.min))

            for current_index, next_index in zip(ordered_indexes, ordered_indexes[1:]):
                current = records[current_index]
                nxt = records[next_index]
                gap_days = self._date_gap_days(current["parsed_date"], nxt["parsed_date"])
                overlap = self._participant_overlap(current["participants"], nxt["participants"])

                if overlap or gap_days is None or gap_days <= 14:
                    self._union(parents, current_index, next_index)

    def build_thread_mapping(self, records):
        try:
            enriched_records = []
            for record in records:
                enriched = dict(record)
                enriched["normalized_subject"] = self.normalize_subject(record.get("subject"))
                enriched["participants"] = self._participants(record)
                enriched["parsed_date"] = self._parse_date(record.get("date"))
                enriched_records.append(enriched)

            parents = list(range(len(enriched_records)))
            self._link_by_reply_headers(enriched_records, parents)
            self._link_by_fallback_signals(enriched_records, parents)

            root_to_thread_id = {}
            thread_counter = 1
            thread_mapping = {}
            threaded_records = []

            for index, record in enumerate(enriched_records):
                root = self._find(parents, index)

                if root not in root_to_thread_id:
                    root_to_thread_id[root] = f"thread_{thread_counter:04d}"
                    thread_counter += 1

                thread_id = root_to_thread_id[root]
                thread_mapping[record.get("message_id") or f"row_{index}"] = thread_id

                record_output = {
                    "message_id": record.get("message_id"),
                    "subject": record.get("subject"),
                    "date": record.get("date"),
                    "from": record.get("from"),
                    "to": record.get("to", []),
                    "cc": record.get("cc", []),
                    "body": record.get("body"),
                    "clean_body": record.get("clean_body"),
                    "in_reply_to": record.get("in_reply_to"),
                    "references": record.get("references", []),
                    "source_file": record.get("source_file"),
                    "thread_id": thread_id,
                    "normalized_subject": record["normalized_subject"],
                }
                threaded_records.append(record_output)

            logger.info("built %s thread ids across %s records", len(set(thread_mapping.values())), len(threaded_records))
            return thread_mapping, threaded_records

        except Exception as e:
            raise SecurityException(e, sys)
