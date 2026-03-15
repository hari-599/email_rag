import math
import re
import sys
from collections import Counter, defaultdict

from Services.Exceptions.exception import SecurityException
from Services.Logger import logger
from Services.preprocessor.email_cleaning import Email_Cleaning
from Services.preprocessor.email_structure import Email_Structure
from Services.preprocessor.email_thread import Email_threading


class Email_Ingestor:
    TOKEN_RE = re.compile(r"\b\w+\b")
    MAX_EMAIL_CHUNK_TOKENS = 220

    def __init__(self, source_csv_path=None):
        self.source_csv_path = source_csv_path
        self.email_parser = Email_Structure(source_csv_path=source_csv_path)
        self.email_cleaner = Email_Cleaning()
        self.email_threader = Email_threading()

    def _tokenize(self, text):
        return self.TOKEN_RE.findall((text or "").lower())

    def _build_chunk_text(self, record):
        fields = [
            record.get("subject", ""),
            record.get("from", ""),
            " ".join(record.get("to", [])),
            " ".join(record.get("cc", [])),
            record.get("clean_body") or record.get("body", ""),
        ]
        return "\n".join(value for value in fields if value).strip()

    def _split_long_text(self, text):
        paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
        if not paragraphs:
            return [text]

        sections = []
        current = []
        current_tokens = 0

        for paragraph in paragraphs:
            paragraph_tokens = len(self._tokenize(paragraph))
            if current and current_tokens + paragraph_tokens > self.MAX_EMAIL_CHUNK_TOKENS:
                sections.append("\n\n".join(current))
                current = [paragraph]
                current_tokens = paragraph_tokens
            else:
                current.append(paragraph)
                current_tokens += paragraph_tokens

        if current:
            sections.append("\n\n".join(current))

        return sections

    def _build_email_chunks(self, record, index):
        base_text = self._build_chunk_text(record)
        message_id = record.get("message_id") or f"row_{index}"
        sections = self._split_long_text(base_text)
        chunks = []

        for section_index, chunk_text in enumerate(sections, start=1):
            chunks.append(
                {
                    "doc_id": f"email_{index:04d}_{section_index:02d}",
                    "thread_id": record.get("thread_id"),
                    "message_id": message_id,
                    "page_no": None,
                    "filename": None,
                    "chunk_type": "email",
                    "subject": record.get("subject"),
                    "date": record.get("date"),
                    "from": record.get("from"),
                    "to": record.get("to", []),
                    "cc": record.get("cc", []),
                    "text": chunk_text,
                    "token_count": len(self._tokenize(chunk_text)),
                    "source_file": record.get("source_file"),
                }
            )

        return chunks

    def ingest(self):
        try:
            structured_records = self.email_parser.build_structured_records()
            cleaned_records = self.email_cleaner.clean_records(structured_records)
            _, threaded_records = self.email_threader.build_thread_mapping(cleaned_records)

            chunks = []
            for index, record in enumerate(threaded_records, start=1):
                chunks.extend(self._build_email_chunks(record, index))

            logger.info("built %s retrievable chunks", len(chunks))
            return {
                "records": threaded_records,
                "chunks": chunks,
            }

        except Exception as e:
            raise SecurityException(e, sys)


class ThreadAwareRetriever:
    TOKEN_RE = re.compile(r"\b\w+\b")

    def __init__(self, chunks):
        self.chunks = chunks
        self.doc_freq = Counter()
        self.term_freqs = {}
        self.doc_lengths = {}
        self.thread_index = defaultdict(list)
        self.avg_doc_length = 0
        self.total_docs = 0
        self._build_index()

    def _tokenize(self, text):
        return self.TOKEN_RE.findall((text or "").lower())

    def _build_index(self):
        self.total_docs = len(self.chunks)
        total_length = 0

        for chunk in self.chunks:
            doc_id = chunk["doc_id"]
            tokens = self._tokenize(chunk.get("text", ""))
            term_counts = Counter(tokens)

            self.term_freqs[doc_id] = term_counts
            self.doc_lengths[doc_id] = len(tokens)
            total_length += len(tokens)

            for token in term_counts:
                self.doc_freq[token] += 1

            self.thread_index[chunk.get("thread_id")].append(chunk)

        self.avg_doc_length = total_length / self.total_docs if self.total_docs else 0
        logger.info("indexed %s chunks across %s threads", self.total_docs, len(self.thread_index))

    def _idf(self, term):
        doc_frequency = self.doc_freq.get(term, 0)
        if doc_frequency == 0 or self.total_docs == 0:
            return 0.0
        return math.log(1 + (self.total_docs - doc_frequency + 0.5) / (doc_frequency + 0.5))

    def _bm25_score(self, query_terms, chunk, k1=1.5, b=0.75):
        doc_id = chunk["doc_id"]
        term_counts = self.term_freqs.get(doc_id, Counter())
        doc_length = self.doc_lengths.get(doc_id, 0)
        score = 0.0

        for term in query_terms:
            tf = term_counts.get(term, 0)
            if tf == 0:
                continue

            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (
                1 - b + b * (doc_length / self.avg_doc_length if self.avg_doc_length else 0)
            )
            score += self._idf(term) * (numerator / denominator)

        return score

    def search(self, query, thread_id=None, top_k=5):
        query_terms = self._tokenize(query)
        if not query_terms:
            return self.get_thread_chunks(thread_id, top_k=top_k) if thread_id else []

        candidate_chunks = self.thread_index.get(thread_id, []) if thread_id else self.chunks
        scored_results = []
        seen_signatures = set()

        for chunk in candidate_chunks:
            score = self._bm25_score(query_terms, chunk)
            if score <= 0:
                continue

            signature = (
                chunk.get("message_id"),
                (chunk.get("text", "")[:180] or "").strip().lower(),
            )
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            scored_results.append(
                {
                    "doc_id": chunk["doc_id"],
                    "thread_id": chunk["thread_id"],
                    "message_id": chunk["message_id"],
                    "page_no": chunk["page_no"],
                    "filename": chunk.get("filename"),
                    "chunk_type": chunk.get("chunk_type"),
                    "score": round(score, 4),
                    "subject": chunk.get("subject"),
                    "date": chunk.get("date"),
                    "from": chunk.get("from"),
                    "to": chunk.get("to", []),
                    "cc": chunk.get("cc", []),
                    "text": chunk.get("text", ""),
                    "text_preview": chunk.get("text", "")[:280],
                }
            )

        scored_results.sort(key=lambda item: item["score"], reverse=True)
        return scored_results[:top_k]

    def get_thread_chunks(self, thread_id, top_k=5):
        candidate_chunks = self.thread_index.get(thread_id, [])
        if not candidate_chunks:
            return []

        ordered_chunks = sorted(
            candidate_chunks,
            key=lambda chunk: (chunk.get("date") or "", chunk.get("message_id") or "", chunk.get("doc_id")),
        )
        results = []
        seen_messages = set()

        for chunk in ordered_chunks:
            message_id = chunk.get("message_id")
            if message_id in seen_messages:
                continue
            seen_messages.add(message_id)
            results.append(
                {
                    "doc_id": chunk["doc_id"],
                    "thread_id": chunk["thread_id"],
                    "message_id": chunk["message_id"],
                    "page_no": chunk["page_no"],
                    "filename": chunk.get("filename"),
                    "chunk_type": chunk.get("chunk_type"),
                    "score": 0.0,
                    "subject": chunk.get("subject"),
                    "date": chunk.get("date"),
                    "from": chunk.get("from"),
                    "to": chunk.get("to", []),
                    "cc": chunk.get("cc", []),
                    "text": chunk.get("text", ""),
                    "text_preview": chunk.get("text", "")[:280],
                }
            )
            if len(results) >= top_k:
                break

        return results
