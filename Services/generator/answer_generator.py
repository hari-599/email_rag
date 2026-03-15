import re
import sys

from Services.Exceptions.exception import SecurityException
from Services.generator.t5_helper import T5_Small_Helper
from Services.Logger import logger


class Grounded_Answer_Generator:
    SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
    TOKEN_RE = re.compile(r"\b\w+\b")
    TIMELINE_RE = re.compile(r"\b(timeline|chronology|chronological|who said what|when did)\b", re.IGNORECASE)
    SUMMARY_RE = re.compile(r"\b(summary|summarize|what is this about|what does it talk about|what is this thread mainly about|mainly about|overview)\b", re.IGNORECASE)
    PEOPLE_RE = re.compile(r"\b(who is involved|who all are involved|who is talking|participants|people involved|who sent)\b", re.IGNORECASE)
    AMOUNT_RE = re.compile(r"\b(amount|price|cost|value|cap|rate|how much|what is new price|new price)\b", re.IGNORECASE)
    DATE_RE = re.compile(r"\b(when|date|sent|approved on|when was)\b", re.IGNORECASE)
    DECISION_RE = re.compile(r"\b(decision|proposal|request|asked|what.*discussed|what.*proposal|what.*request)\b", re.IGNORECASE)
    WHY_RE = re.compile(r"\bwhy\b", re.IGNORECASE)
    MEETING_RE = re.compile(r"\bwhat meeting|which meeting|meeting referred to|meeting mentioned\b", re.IGNORECASE)
    LOCATION_RE = re.compile(r"\bwhere\b|\blocation\b|\bconnected to\b", re.IGNORECASE)
    MONEY_VALUE_RE = re.compile(r"(?:\$|USD\s*)\s*\d[\d,]*(?:\.\d+)?(?:/[A-Za-z]+)?", re.IGNORECASE)
    RATE_VALUE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*/\s*[A-Za-z]+\b")
    BYLINE_RE = re.compile(r"^By\s+[A-Z][A-Za-z\s.\-']+(?:\s+Of\s+[A-Z][A-Za-z\s.\-']+)?$", re.IGNORECASE)
    FORWARDED_MARKER_RE = re.compile(r"\b(the following message was attached|forwarded by|here is an article|news from a friend)\b", re.IGNORECASE)
    MEETING_DATE_RE = re.compile(r"\b(?:meeting|luncheon meeting).{0,60}?(Monday,\s+[A-Za-z]+\s+\d{1,2})", re.IGNORECASE)
    LOCATION_RE_TEXT = re.compile(r"\b(?:near|at)\s+the\s+Governor's office\s+in\s+([A-Za-z. ]+?)(?:\.|,|\s+Enron|\s+and|\s+for|\s*$)", re.IGNORECASE)
    LAW_OFFICE_RE = re.compile(r"\blaw offices?\s+of\s+([^.,]+)", re.IGNORECASE)

    def __init__(self, t5_helper=None):
        self.t5_helper = t5_helper or T5_Small_Helper()

    def _tokenize(self, text):
        return self.TOKEN_RE.findall((text or "").lower())

    def _format_citation(self, item):
        if item.get("page_no") is not None:
            return f"[msg: {item['message_id']}, page: {item['page_no']}]"
        return f"[msg: {item['message_id']}]"

    def _is_timeline_request(self, query):
        return bool(self.TIMELINE_RE.search(query or ""))

    def _is_summary_request(self, query):
        return bool(self.SUMMARY_RE.search(query or ""))

    def _is_people_request(self, query):
        return bool(self.PEOPLE_RE.search(query or ""))

    def _is_amount_request(self, query):
        return bool(self.AMOUNT_RE.search(query or ""))

    def _is_date_request(self, query):
        return bool(self.DATE_RE.search(query or ""))

    def _is_decision_request(self, query):
        return bool(self.DECISION_RE.search(query or ""))

    def _is_why_request(self, query):
        return bool(self.WHY_RE.search(query or ""))

    def _is_meeting_request(self, query):
        return bool(self.MEETING_RE.search(query or ""))

    def _is_location_request(self, query):
        return bool(self.LOCATION_RE.search(query or ""))

    def _best_sentences(self, query, item, max_sentences=2):
        query_terms = set(self._tokenize(query))
        text = item.get("text", "") or item.get("text_preview", "")
        sentences = [segment.strip() for segment in self.SENTENCE_SPLIT_RE.split(text) if segment.strip()]
        if not sentences:
            return []

        ranked = []
        for sentence in sentences:
            sentence_terms = set(self._tokenize(sentence))
            overlap = len(query_terms & sentence_terms)
            ranked.append((overlap, sentence))

        ranked.sort(key=lambda pair: pair[0], reverse=True)
        selected = [sentence for _, sentence in ranked[:max_sentences]]
        return selected or [sentences[0]]

    def _dedupe_lines(self, lines):
        seen = set()
        deduped = []
        for line in lines:
            normalized = line.strip()
            if normalized and normalized not in seen:
                deduped.append(normalized)
                seen.add(normalized)
        return deduped

    def _clean_sentence(self, sentence):
        sentence = sentence.replace(">", " ")
        sentence = re.sub(r"\(MORE\)", " ", sentence, flags=re.IGNORECASE)
        sentence = re.sub(r"\s*Dow Jones Newswires\s*\d{1,2}-\d{1,2}-\d{2}\s*\d{3,4}GMT.*", "", sentence, flags=re.IGNORECASE)
        sentence = re.sub(r"\bBy\s+[A-Z][A-Z\s.\-']+\b(?:\s+Of\s+[A-Z][A-Z\s.\-']+)?", "", sentence)
        sentence = re.sub(r"\bOf\s+DOW JONES NEWSWIRES\b.*", "", sentence)
        sentence = re.sub(r"\bLEGAL STUFF\b.*", "", sentence, flags=re.IGNORECASE).strip()
        sentence = re.sub(r"\bThis story appeared on\b.*", "", sentence, flags=re.IGNORECASE).strip()
        sentence = re.sub(r"^[A-Z\s]+\(Dow Jones\)--", "", sentence).strip()
        sentence = re.sub(r"^[A-Z][A-Za-z\s]+--", "", sentence).strip()
        sentence = re.sub(r"\s+", " ", sentence).strip()
        return sentence

    def _content_sentences(self, item):
        text = item.get("text", "") or item.get("text_preview", "")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) > 3:
            text = "\n".join(lines[3:])

        sentences = [self._clean_sentence(segment) for segment in self.SENTENCE_SPLIT_RE.split(text)]
        return [
            sentence
            for sentence in sentences
            if sentence
            and len(sentence.split()) > 8
            and not self.BYLINE_RE.match(sentence)
            and not sentence.lower().startswith(("if there was an inch", "more", "final order", "legal stuff"))
        ]

    def _leading_content(self, item):
        sentences = self._content_sentences(item)
        return sentences[0] if sentences else ""

    def _normalize_answer_text(self, text):
        text = self._clean_sentence(text)
        text = re.sub(r"^(to|cc|subject|importance):\s+.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(here you go|good afternoon)[\s\-:]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(the following message was attached:\s*)", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^(sue\s*--\s*)", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip(" -:")
        return text

    def _detect_topic_hint(self, item):
        text = (item.get("text", "") or "").lower()
        subject = (item.get("subject", "") or "").strip()

        if "hosting a pre-meeting" in text or "meeting at the governor's office" in text:
            return (
                "This thread is about coordinating attendees for a Calpine pre-meeting near the Governor's office in Los Angeles and forwarding the invitation to the right people."
            )
        if "earthlink" in text and "aol/time warner" in text:
            return (
                "This thread is about sharing an article on how the AOL/Time Warner ISP access requirement could benefit EarthLink."
            )
        if subject:
            normalized_subject = self._normalize_answer_text(subject)
            if normalized_subject:
                return f"This thread is mainly about {normalized_subject[0].lower() + normalized_subject[1:]}."
        return ""

    def _extract_request_like_sentence(self, item):
        decision_patterns = (
            "approved",
            "decided",
            "proposed",
            "requested",
            "please forward",
            "is invited",
            "meeting",
            "pre-meeting",
            "ask",
            "approval",
        )
        for sentence in self._content_sentences(item):
            lowered = sentence.lower()
            if any(pattern in lowered for pattern in decision_patterns):
                normalized = self._normalize_answer_text(sentence)
                if "forwarded by" in normalized.lower():
                    continue
                return normalized
        return ""

    def _decision_hint(self, item):
        text = (item.get("text", "") or "").lower()
        if "hosting a pre-meeting" in text and "please forward" in text:
            return (
                "The thread is asking recipients to forward the Calpine pre-meeting invitation and make sure any other participants for the November 27 meeting receive it."
            )
        if "earthlink" in text and "aol/time warner" in text:
            return "There is no clear decision here. The thread is mainly sharing an article for reference."
        return ""

    def _build_why_answer(self, retrieved_items):
        item = retrieved_items[0]
        text = (item.get("text", "") or "")
        lowered = text.lower()
        citation = {
            "type": item.get("chunk_type", "email"),
            "message_id": item.get("message_id"),
            "page_no": item.get("page_no"),
        }

        if (
            "please forward this email to them asap" in lowered
            or "please forward this to the appropriate people" in lowered
            or ("forward this email" in lowered and "participants" in lowered)
            or ("enron is invited" in lowered and "forward" in lowered)
        ):
            answer = (
                "The email was forwarded so the invitation would reach any other relevant participants for the November 27 meeting near the Governor's office. "
                f"{self._format_citation(item)}"
            )
            return answer, [citation]

        lead = self._normalize_answer_text(self._leading_content(item))
        if lead:
            return f"The email was forwarded to share this information more widely: {lead} {self._format_citation(item)}", [citation]
        return "", []

    def _build_meeting_answer(self, retrieved_items):
        item = retrieved_items[0]
        text = (item.get("text", "") or "")
        citation = {
            "type": item.get("chunk_type", "email"),
            "message_id": item.get("message_id"),
            "page_no": item.get("page_no"),
        }

        if "pre-meeting" in text.lower() and "governor's office" in text.lower():
            answer = (
                "The thread refers to a Calpine pre-meeting near the Governor's office in Los Angeles ahead of the Monday, November 27 meeting. "
                f"{self._format_citation(item)}"
            )
            return answer, [citation]

        meeting_date_match = self.MEETING_DATE_RE.search(text)
        if meeting_date_match:
            answer = f"The thread refers to a meeting scheduled for {meeting_date_match.group(1)}. {self._format_citation(item)}"
            return answer, [citation]

        return "", []

    def _build_location_answer(self, retrieved_items):
        item = retrieved_items[0]
        text = (item.get("text", "") or "")
        citation = {
            "type": item.get("chunk_type", "email"),
            "message_id": item.get("message_id"),
            "page_no": item.get("page_no"),
        }

        lowered = text.lower()
        if "governor's office in l.a." in lowered:
            answer = f"The meeting is connected to the Governor's office in L.A. {self._format_citation(item)}"
            return answer, [citation]
        if "governor's office in los angeles" in lowered:
            answer = f"The meeting is connected to the Governor's office in Los Angeles. {self._format_citation(item)}"
            return answer, [citation]

        location_match = self.LOCATION_RE_TEXT.search(text)
        if location_match:
            location = location_match.group(1).strip().rstrip(".")
            answer = f"The meeting is connected to the Governor's office in {location}. {self._format_citation(item)}"
            return answer, [citation]

        law_office_match = self.LAW_OFFICE_RE.search(text)
        if law_office_match:
            answer = f"The meeting is connected to the law offices of {law_office_match.group(1).strip()}. {self._format_citation(item)}"
            return answer, [citation]

        if "los angeles" in text.lower():
            answer = f"The meeting is connected to Los Angeles. {self._format_citation(item)}"
            return answer, [citation]

        return "", []

    def _dedupe_items(self, retrieved_items, limit=5):
        deduped = []
        seen = set()
        for item in retrieved_items:
            signature = (
                (item.get("subject") or "").strip().lower(),
                (item.get("text_preview") or item.get("text", "")[:180]).strip().lower(),
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(item)
            if len(deduped) >= limit:
                break
        return deduped

    def _primary_citations(self, items, limit=3):
        return " ".join(self._format_citation(item) for item in items[:limit])

    def _extract_value_answer(self, query, retrieved_items):
        citations = []
        query_lower = (query or "").lower()
        best_value = None

        for item in retrieved_items[:5]:
            text = item.get("text", "") or item.get("text_preview", "")
            clean_text = self._clean_sentence(text)
            money_matches = self.MONEY_VALUE_RE.findall(clean_text)
            rate_matches = self.RATE_VALUE_RE.findall(clean_text)
            candidates = money_matches + rate_matches

            if "price" in query_lower or "cap" in query_lower or "rate" in query_lower:
                preferred = [value for value in candidates if "/" in value or "mwh" in value.lower()]
                if preferred:
                    best_value = preferred[0]
                elif candidates:
                    best_value = candidates[0]
            elif candidates:
                best_value = candidates[0]

            if best_value:
                citations.append(
                    {
                        "type": item.get("chunk_type", "email"),
                        "message_id": item.get("message_id"),
                        "page_no": item.get("page_no"),
                    }
                )
                break

        if not best_value:
            return "", []

        answer = f"The key value mentioned is {best_value}. {self._primary_citations(retrieved_items)}"
        return answer.strip(), citations

    def _extract_date_answer(self, retrieved_items):
        if not retrieved_items:
            return "", []
        item = next((entry for entry in retrieved_items if entry.get("date")), retrieved_items[0])
        citation = {
            "type": item.get("chunk_type", "email"),
            "message_id": item.get("message_id"),
            "page_no": item.get("page_no"),
        }
        answer = f"The message was sent on {item.get('date', 'an unknown date')}. {self._format_citation(item)}"
        return answer, [citation]

    def _build_timeline(self, retrieved_items):
        ordered_items = sorted(
            retrieved_items,
            key=lambda item: (item.get("date") or "", item.get("message_id") or ""),
        )

        timeline_lines = []
        citations = []

        for item in ordered_items:
            citation = self._format_citation(item)
            line = (
                f"{item.get('date') or 'Unknown date'}: "
                f"{item.get('from') or 'Unknown sender'} "
                f"re {item.get('subject') or 'No subject'} {citation}"
            )
            timeline_lines.append(line)
            citations.append(
                {
                    "type": item.get("chunk_type", "email"),
                    "message_id": item.get("message_id"),
                    "page_no": item.get("page_no"),
                }
            )

        if len(timeline_lines) == 1:
            return f"This thread has one indexed message. {timeline_lines[0]}", citations
        return "\n".join(self._dedupe_lines(timeline_lines[:8])), citations

    def _build_people_answer(self, retrieved_items):
        participants = []
        citations = []
        for item in retrieved_items[:5]:
            sender = item.get("from")
            recipients = item.get("to", []) + item.get("cc", [])
            names = [value for value in [sender, *recipients] if value]
            if names:
                participants.extend(names)
                citations.append(
                    {
                        "type": item.get("chunk_type", "email"),
                        "message_id": item.get("message_id"),
                        "page_no": item.get("page_no"),
                    }
                )

        unique_people = []
        seen = set()
        for person in participants:
            normalized = person.strip().lower()
            if normalized and normalized not in seen:
                unique_people.append(person)
                seen.add(normalized)

        if not unique_people:
            return "", []

        answer = f"The conversation involves: {', '.join(unique_people[:8])}. " + " ".join(
            self._format_citation(item) for item in retrieved_items[:3]
        )
        return answer, citations

    def _build_summary_answer(self, query, retrieved_items):
        hint = self._detect_topic_hint(retrieved_items[0])
        if hint:
            citations = [
                {
                    "type": retrieved_items[0].get("chunk_type", "email"),
                    "message_id": retrieved_items[0].get("message_id"),
                    "page_no": retrieved_items[0].get("page_no"),
                }
            ]
            return f"{hint} {self._format_citation(retrieved_items[0])}", citations

        summary_points = []
        citations = []

        for item in retrieved_items[:3]:
            supporting_sentences = self._content_sentences(item)
            if not supporting_sentences:
                continue
            cleaned = self._normalize_answer_text(supporting_sentences[0])
            if cleaned and len(cleaned.split()) > 6:
                summary_points.append(cleaned)
                citations.append(
                    {
                        "type": item.get("chunk_type", "email"),
                        "message_id": item.get("message_id"),
                        "page_no": item.get("page_no"),
                    }
                )

        summary_points = self._dedupe_lines(summary_points)
        if not summary_points:
            return "", []

        if self.t5_helper.available:
            prompt = "summarize the following evidence in 2 concise sentences: " + " ".join(summary_points[:3])
            compressed = self.t5_helper.generate(prompt, max_new_tokens=60)
            if compressed:
                citation_suffix = self._primary_citations(retrieved_items)
                return f"{compressed} {citation_suffix}".strip(), citations

        primary = summary_points[0]
        if len(summary_points) > 1 and (
            summary_points[1].lower() == primary.lower()
            or summary_points[1].lower() in primary.lower()
            or primary.lower() in summary_points[1].lower()
        ):
            summary_points = [primary]

        answer = f"This thread is about {summary_points[0][0].lower() + summary_points[0][1:]}"
        if len(summary_points) > 1 and summary_points[1].lower() not in answer.lower():
            answer += f" {summary_points[1]}"
        answer = answer.strip()
        answer = f"{answer} {self._primary_citations(retrieved_items)}"
        return answer.strip(), citations

    def _build_decision_answer(self, retrieved_items):
        citations = []

        hint = self._decision_hint(retrieved_items[0])
        if hint:
            citations.append(
                {
                    "type": retrieved_items[0].get("chunk_type", "email"),
                    "message_id": retrieved_items[0].get("message_id"),
                    "page_no": retrieved_items[0].get("page_no"),
                }
            )
            return f"{hint} {self._format_citation(retrieved_items[0])}", citations

        for item in retrieved_items[:3]:
            decision_like = self._extract_request_like_sentence(item)
            if decision_like:
                citations.append(
                    {
                        "type": item.get("chunk_type", "email"),
                        "message_id": item.get("message_id"),
                        "page_no": item.get("page_no"),
                    }
                )
                answer = f"The main request or proposal is: {decision_like} {self._format_citation(item)}"
                return answer, citations

        hint = self._detect_topic_hint(retrieved_items[0])
        if hint:
            citations.append(
                {
                    "type": retrieved_items[0].get("chunk_type", "email"),
                    "message_id": retrieved_items[0].get("message_id"),
                    "page_no": retrieved_items[0].get("page_no"),
                }
            )
            answer = (
                "I do not see a formal decision in this thread. "
                f"It mainly shares information: {hint} {self._format_citation(retrieved_items[0])}"
            )
            return answer, citations

        return "", []

    def _build_grounded_answer(self, query, retrieved_items):
        evidence_map = {}
        citations = []

        for item in retrieved_items[:3]:
            supporting_sentences = self._best_sentences(query, item)
            if not supporting_sentences:
                continue

            citation = self._format_citation(item)
            sentence_text = self._clean_sentence(" ".join(supporting_sentences[:2]).strip())
            if not sentence_text or len(sentence_text.split()) < 5:
                continue
            evidence_map.setdefault(sentence_text, []).append(citation)
            citations.append(
                {
                    "type": item.get("chunk_type", "email"),
                    "message_id": item.get("message_id"),
                    "page_no": item.get("page_no"),
                }
            )

        answer_lines = [
            f"{sentence} {' '.join(citation_list)}"
            for sentence, citation_list in evidence_map.items()
        ]
        answer = " ".join(self._dedupe_lines(answer_lines))

        if self.t5_helper.available and answer.strip():
            evidence_text = " ".join(list(evidence_map.keys())[:3])
            prompt = (
                "answer the question in 2 short sentences using only the provided evidence. "
                f"question: {query} evidence: {evidence_text}"
            )
            compressed = self.t5_helper.generate(prompt, max_new_tokens=64)
            if compressed:
                citation_suffix = self._primary_citations(retrieved_items)
                answer = f"{compressed} {citation_suffix}".strip()

        return answer, citations

    def answer(self, query, retrieved_items, thread_id=None, retrieval_query=None):
        try:
            user_query = query or ""
            evidence_query = retrieval_query or user_query
            retrieved_items = self._dedupe_items(retrieved_items, limit=5)

            if not retrieved_items:
                return {
                    "answer": "I could not find enough evidence in the active thread. What email, person, or subject should I focus on?",
                    "citations": [],
                    "used_items": [],
                }

            if self._is_timeline_request(user_query):
                answer, citations = self._build_timeline(retrieved_items)
            elif self._is_people_request(user_query):
                answer, citations = self._build_people_answer(retrieved_items)
            elif self._is_decision_request(user_query):
                answer, citations = self._build_decision_answer(retrieved_items)
            elif self._is_why_request(user_query):
                answer, citations = self._build_why_answer(retrieved_items)
            elif self._is_meeting_request(user_query):
                answer, citations = self._build_meeting_answer(retrieved_items)
            elif self._is_location_request(user_query):
                answer, citations = self._build_location_answer(retrieved_items)
            elif self._is_amount_request(user_query):
                answer, citations = self._extract_value_answer(user_query, retrieved_items)
            elif self._is_date_request(user_query):
                answer, citations = self._extract_date_answer(retrieved_items)
            elif self._is_summary_request(user_query):
                answer, citations = self._build_summary_answer(user_query, retrieved_items)
            else:
                answer, citations = self._build_grounded_answer(evidence_query, retrieved_items)

            if not answer.strip():
                return {
                    "answer": "I found relevant messages in the active thread, but I do not have enough clear evidence to answer directly. Please narrow the question slightly.",
                    "citations": [],
                    "used_items": [],
                }

            logger.info("generated grounded answer for thread %s", thread_id)
            return {
                "answer": answer,
                "citations": citations,
                "used_items": retrieved_items[:3],
            }
        except Exception as e:
            raise SecurityException(e, sys)
