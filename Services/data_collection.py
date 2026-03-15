import csv
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import kagglehub
from Services.Exceptions.exception import SecurityException
from Services.Logger import logger

DATASET_NAME = "wcukierski/enron-email-dataset"
SOURCE_CSV = os.path.join("data", "emails.csv")
SLICE_DIR = os.path.join("data", "laptop_slice")
SLICE_CSV = os.path.join(SLICE_DIR, "emails.csv")
SLICE_SUMMARY = os.path.join(SLICE_DIR, "summary.json")

SUBJECT_PREFIX_RE = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
ATTACHMENT_MARKERS = (
    "content-disposition: attachment",
    "filename=",
    "name=",
)


csv.field_size_limit(min(sys.maxsize, 2147483647))


@dataclass(frozen=True)
class SliceTargets:
    month_span_min: int = 3
    month_span_max: int = 6
    thread_min: int = 10
    thread_max: int = 20
    message_min: int = 100
    message_max: int = 300
    attachment_min: int = 20
    attachment_max: int = 50
    text_bytes_max: int = 100 * 1024 * 1024


@dataclass(frozen=True)
class MessageMetadata:
    date: object
    subject: str
    has_attachment: bool
    message_size: int


@dataclass(frozen=True)
class WindowSelection:
    start: tuple[int, int]
    end: tuple[int, int]
    span: int
    total_messages: int
    total_attachments: int
    viable_threads: int


TARGETS = SliceTargets()


def extract_headers(message):
    headers = {}
    current_key = None

    for raw_line in message.splitlines():
        if not raw_line.strip():
            break

        if raw_line[0] in " \t" and current_key:
            headers[current_key] = f"{headers[current_key]} {raw_line.strip()}"
            continue

        if ":" not in raw_line:
            continue

        key, value = raw_line.split(":", 1)
        current_key = key.lower()
        headers[current_key] = value.strip()

    return headers


def normalize_subject(subject):
    cleaned = SUBJECT_PREFIX_RE.sub("", (subject or "").strip())
    return " ".join(cleaned.lower().split())


def parse_message_metadata(row):
    message = row["message"]
    headers = extract_headers(message)
    subject = normalize_subject(headers.get("subject", ""))
    date_value = headers.get("date")

    if not subject or not date_value:
        return None

    try:
        parsed_date = parsedate_to_datetime(date_value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None

    if parsed_date is None:
        return None

    if parsed_date.tzinfo is not None:
        parsed_date = parsed_date.replace(tzinfo=None)

    lowered_message = message.lower()
    return MessageMetadata(
        date=parsed_date,
        subject=subject,
        has_attachment=any(marker in lowered_message for marker in ATTACHMENT_MARKERS),
        message_size=len(message.encode("utf-8", errors="ignore")),
    )


def month_key(dt):
    return dt.year, dt.month


def iter_month_range(start_key, span):
    year, month = start_key
    for _ in range(span):
        yield year, month
        month += 1
        if month > 12:
            month = 1
            year += 1


def add_months(start_key, span):
    months = list(iter_month_range(start_key, span))
    return months[-1]


def date_in_window(dt, start_key, end_key):
    current = (dt.year, dt.month)
    return start_key <= current <= end_key


def iter_valid_rows(source_csv):
    with open(source_csv, newline="", encoding="utf-8") as source_file:
        reader = csv.DictReader(source_file)
        for row in reader:
            metadata = parse_message_metadata(row)
            if metadata is not None:
                yield row, metadata


def locate_source_csv():
    if os.path.exists(SOURCE_CSV):
        return SOURCE_CSV

    os.makedirs("data", exist_ok=True)
    dataset_path = kagglehub.dataset_download(DATASET_NAME)

    for root, _, files in os.walk(dataset_path):
        if "emails.csv" in files:
            source_path = os.path.join(root, "emails.csv")
            shutil.copy2(source_path, SOURCE_CSV)
            logger.info("copied source emails.csv into %s", SOURCE_CSV)
            return SOURCE_CSV

    raise FileNotFoundError("emails.csv was not found in the downloaded dataset")


def score_window(total_messages, total_attachments, viable_threads, span):
    return (
        viable_threads * 1000
        - abs(total_messages - 200)
        - abs(total_attachments - 35) * 2
        - abs(span - 4) * 25
    )


def choose_window(month_totals, month_thread_counts, month_attachment_totals, targets):
    available_months = sorted(month_totals)
    best_window = None
    best_score = None

    for start_key in available_months:
        for span in range(targets.month_span_min, targets.month_span_max + 1):
            window_months = list(iter_month_range(start_key, span))
            if any(month not in month_totals for month in window_months):
                continue

            total_messages = sum(month_totals[month] for month in window_months)
            total_attachments = sum(month_attachment_totals[month] for month in window_months)

            thread_counts = Counter()
            for month in window_months:
                thread_counts.update(month_thread_counts[month])

            viable_threads = sum(1 for count in thread_counts.values() if count >= 3)
            score = score_window(total_messages, total_attachments, viable_threads, span)

            if best_score is None or score > best_score:
                best_score = score
                best_window = WindowSelection(
                    start=start_key,
                    end=add_months(start_key, span - 1),
                    span=span,
                    total_messages=total_messages,
                    total_attachments=total_attachments,
                    viable_threads=viable_threads,
                )

    if best_window is None:
        raise ValueError("unable to find a coherent date window in emails.csv")

    return best_window


def targets_satisfied(selected_threads, total_messages, total_attachments, targets):
    return (
        len(selected_threads) >= targets.thread_min
        and targets.message_min <= total_messages <= targets.message_max
        and targets.attachment_min <= total_attachments <= targets.attachment_max
    )


def select_threads(thread_stats, targets):
    ranked_threads = sorted(
        thread_stats.items(),
        key=lambda item: (
            item[1]["attachments"] > 0,
            item[1]["attachments"],
            item[1]["messages"],
        ),
        reverse=True,
    )

    selected_threads = []
    total_messages = 0
    total_attachments = 0

    for subject, stats in ranked_threads:
        if len(selected_threads) >= targets.thread_max:
            break

        prospective_messages = total_messages + stats["messages"]
        if prospective_messages > targets.message_max and len(selected_threads) >= targets.thread_min:
            continue

        selected_threads.append(subject)
        total_messages = prospective_messages
        total_attachments += stats["attachments"]

        if targets_satisfied(selected_threads, total_messages, total_attachments, targets):
            break

    return selected_threads


def build_slice_summary(source_csv, window, thread_counts, selected_rows, attachment_count, total_bytes):
    return {
        "source_csv": os.path.abspath(source_csv),
        "slice_csv": os.path.abspath(SLICE_CSV),
        "window_start": f"{window.start[0]:04d}-{window.start[1]:02d}",
        "window_end": f"{window.end[0]:04d}-{window.end[1]:02d}",
        "month_span": window.span,
        "threads_selected": len(thread_counts),
        "messages_selected": len(selected_rows),
        "attachment_messages": attachment_count,
        "indexed_text_bytes": total_bytes,
        "indexed_text_mb": round(total_bytes / (1024 * 1024), 2),
        "thread_message_counts": dict(thread_counts.most_common()),
    }


def write_slice(source_csv, window, selected_threads, targets):
    os.makedirs(SLICE_DIR, exist_ok=True)
    selected_set = set(selected_threads)

    selected_rows = []
    thread_counts = Counter()
    attachment_count = 0
    total_bytes = 0

    for row, metadata in iter_valid_rows(source_csv):
        if not date_in_window(metadata.date, window.start, window.end):
            continue

        if metadata.subject not in selected_set:
            continue

        if len(selected_rows) >= targets.message_max:
            break

        if total_bytes + metadata.message_size > targets.text_bytes_max:
            break

        selected_rows.append(row)
        thread_counts[metadata.subject] += 1
        total_bytes += metadata.message_size
        if metadata.has_attachment:
            attachment_count += 1

    with open(SLICE_CSV, "w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=["file", "message"])
        writer.writeheader()
        writer.writerows(selected_rows)

    summary = build_slice_summary(
        source_csv,
        window,
        thread_counts,
        selected_rows,
        attachment_count,
        total_bytes,
    )

    with open(SLICE_SUMMARY, "w", encoding="utf-8") as summary_file:
        json.dump(summary, summary_file, indent=2)

    return summary


def collect_month_statistics(source_csv):
    month_totals = Counter()
    month_attachment_totals = Counter()
    month_thread_counts = defaultdict(Counter)

    for _, metadata in iter_valid_rows(source_csv):
        current_month = month_key(metadata.date)
        month_totals[current_month] += 1
        month_thread_counts[current_month][metadata.subject] += 1
        if metadata.has_attachment:
            month_attachment_totals[current_month] += 1

    return month_totals, month_thread_counts, month_attachment_totals


def collect_thread_statistics(source_csv, window):
    thread_stats = defaultdict(lambda: {"messages": 0, "attachments": 0})

    for _, metadata in iter_valid_rows(source_csv):
        if not date_in_window(metadata.date, window.start, window.end):
            continue

        thread_stats[metadata.subject]["messages"] += 1
        if metadata.has_attachment:
            thread_stats[metadata.subject]["attachments"] += 1

    return thread_stats


def data_collection():
    try:
        source_csv = locate_source_csv()
        month_totals, month_thread_counts, month_attachment_totals = collect_month_statistics(source_csv)
        window = choose_window(month_totals, month_thread_counts, month_attachment_totals, TARGETS)
        thread_stats = collect_thread_statistics(source_csv, window)
        selected_threads = select_threads(thread_stats, TARGETS)
        summary = write_slice(source_csv, window, selected_threads, TARGETS)

        logger.info("laptop slice created at %s", SLICE_CSV)
        logger.info("slice summary: %s", summary)

    except Exception as e:
        raise SecurityException(e, sys)

