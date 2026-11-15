"""Common literature records and bounded HTTP access, independent of model SDKs."""

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
import calendar
import html
import re
import threading
import time
import unicodedata
from typing import Protocol

import requests


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clean_text(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).split())


def normalise_doi(value):
    value = str(value or "").strip().lower()
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)


def normalise_title(value):
    return "".join(
        c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum()
    )


def cutoff_end(value):
    """A month cutoff includes that entire month; a year includes that year."""
    if not value:
        return None
    parts = [int(p) for p in value.split("-")]
    if len(parts) == 1:
        return date(parts[0], 12, 31).isoformat()
    if len(parts) == 2:
        return date(parts[0], parts[1], calendar.monthrange(*parts)[1]).isoformat()
    if len(parts) == 3:
        return date(*parts).isoformat()
    raise ValueError("Use a YYYY, YYYY-MM or YYYY-MM-DD literature cutoff.")


@dataclass
class LiteratureRecord:
    title: str
    source: str
    source_id: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    doi: str = ""
    pmid: str = ""
    pmcid: str = ""
    url: str = ""
    venue: str = ""
    publication_type: str = ""
    publication_date: str = ""
    volume: str = ""
    pages: str = ""
    full_text: str = ""
    full_text_url: str = ""
    rights: str = ""
    provenance: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    integrity: dict = field(default_factory=lambda: {"status": "unknown"})
    passages: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.title = clean_text(self.title)
        self.doi = normalise_doi(self.doi)
        self.pmid = str(self.pmid or "").rstrip("/").rsplit("/", 1)[-1]
        if not self.title or not self.source or not self.source_id:
            raise ValueError("Literature records require title, source and source_id.")

    @property
    def evidence_level(self):
        return (
            "full_text"
            if self.full_text
            else "abstract"
            if self.abstract
            else "metadata"
        )

    def to_dict(self):
        return {**asdict(self), "evidence_level": self.evidence_level}


@dataclass
class SearchPage:
    records: list[LiteratureRecord]
    total: int | None = None
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)
    next_cursor: str | None = None


class LiteratureSource(Protocol):
    """Adapters must use the supplied transport for network I/O and return one bounded page."""

    name: str

    def search(
        self, query: str, limit: int, cutoff: str | None, transport
    ) -> SearchPage: ...


class SourceError(RuntimeError):
    """Only a fixed code, never a raw HTTP exception or credentials."""


class BudgetExceeded(SourceError):
    pass


class SearchTransport:
    def __init__(
        self, max_requests=80, max_seconds=180, timeout=20, max_bytes=8_000_000
    ):
        if max_requests < 1 or max_seconds <= 0 or timeout <= 0:
            raise ValueError("Literature request and time budgets must be positive.")
        self.max_requests = max_requests
        self.max_seconds = max_seconds
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.requests_used = 0
        self.started = None
        self.lock = threading.Lock()
        self.last_requests = {}

    def remaining(self):
        if self.started is None:
            self.started = time.monotonic()
        return self.max_seconds - (time.monotonic() - self.started)

    def get(
        self, source, url, *, params=None, headers=None, interval=1.0, as_json=True
    ):
        return self.request(
            source,
            url,
            params=params,
            headers=headers,
            interval=interval,
            as_json=as_json,
        )

    def request(
        self,
        source,
        url,
        *,
        params=None,
        headers=None,
        interval=1.0,
        as_json=True,
        method="GET",
        body=None,
        with_headers=False,
    ):
        from utils.network_policy import require_online

        require_online("external literature retrieval")
        # Serialize reservation and pacing across all tasks in this discovery run.
        with self.lock:
            if self.requests_used >= self.max_requests or self.remaining() <= 0:
                raise BudgetExceeded("budget_exhausted")
            wait = max(
                0, interval - (time.monotonic() - self.last_requests.get(source, 0))
            )
            if wait >= self.remaining():
                raise BudgetExceeded("time_budget_exhausted")
            time.sleep(wait)
            self.requests_used += 1
            self.last_requests[source] = time.monotonic()
            timeout = min(self.timeout, self.remaining())
        try:
            request = requests.get if method == "GET" else requests.post
            extra = {"json": body} if method == "POST" else {}
            with request(
                url,
                params=params,
                headers={
                    "User-Agent": "PaperOrchestra-research/1.0",
                    **(headers or {}),
                },
                timeout=timeout,
                stream=True,
                allow_redirects=False,
                **extra,
            ) as response:
                if response.status_code not in (200, 202):
                    raise SourceError(f"http_{response.status_code}")
                chunks, length = [], 0
                for chunk in response.iter_content(65536):
                    length += len(chunk)
                    if length > self.max_bytes:
                        raise SourceError("response_too_large")
                    if self.remaining() <= 0:
                        raise BudgetExceeded("time_budget_exhausted")
                    chunks.append(chunk)
                    # Streamable HTTP may keep an SSE connection open after its reply.
                    # Stop only once a complete event for our request ID has arrived.
                    if (
                        method == "POST"
                        and body
                        and "id" in body
                        and "text/event-stream"
                        in response.headers.get("Content-Type", "")
                    ):
                        import json

                        raw_events = (
                            b"".join(chunks).replace(b"\r\n", b"\n").split(b"\n\n")[:-1]
                        )
                        complete = False
                        for event in raw_events:
                            data = b"\n".join(
                                line[5:].lstrip()
                                for line in event.splitlines()
                                if line.startswith(b"data:")
                            )
                            if not data:
                                continue
                            try:
                                item = json.loads(data)
                                complete |= item.get("id") == body["id"] and (
                                    "result" in item or "error" in item
                                )
                            except (ValueError, AttributeError):
                                continue
                        if complete:
                            break
                payload = b"".join(chunks)
                response_headers = dict(response.headers)
            if as_json:
                import json

                payload = json.loads(payload) if payload else None
            return (payload, response_headers) if with_headers else payload
        except SourceError:
            raise
        except requests.Timeout:
            raise SourceError("timeout") from None
        except Exception:
            raise SourceError("request_or_response_failed") from None


def merge_records(records):
    """Merge matching IDs, then exact normalised title/year with no conflicting IDs."""
    merged = []
    for record in records:
        match = None
        for existing in merged:
            same_doi = bool(record.doi and record.doi == existing.doi)
            same_pmid = bool(record.pmid and record.pmid == existing.pmid)
            conflicting_id = any(
                getattr(record, key)
                and getattr(existing, key)
                and getattr(record, key) != getattr(existing, key)
                for key in ("doi", "pmid")
            )
            same_title = (
                normalise_title(record.title) == normalise_title(existing.title)
                and record.year is not None
                and record.year == existing.year
            )
            if (same_doi or same_pmid or same_title) and not conflicting_id:
                match = existing
                break
        if match is None:
            merged.append(record)
            continue
        match.provenance.extend(
            p for p in record.provenance if p not in match.provenance
        )
        for key in (
            "title",
            "authors",
            "year",
            "doi",
            "pmid",
            "pmcid",
            "venue",
            "publication_type",
            "publication_date",
            "volume",
            "pages",
        ):
            old, new = getattr(match, key), getattr(record, key)
            if old and new and old != new:
                conflict = {
                    "field": key,
                    "retained": old,
                    "alternative": new,
                    "source": record.source,
                }
                if conflict not in match.conflicts:
                    match.conflicts.append(conflict)
            elif not old and new:
                setattr(match, key, new)
        # Prefer a complete abstract over a shorter copy, without truncating it.
        if len(record.abstract) > len(match.abstract):
            match.abstract = record.abstract
        if record.full_text and not match.full_text:
            match.full_text, match.rights = record.full_text, record.rights
            match.full_text_url = record.full_text_url
            match.passages = record.passages
        if record.integrity.get("status") in {
            "retracted",
            "withdrawn",
            "update_requires_review",
        }:
            match.integrity = record.integrity
        for key in ("url", "full_text_url", "rights"):
            if not getattr(match, key):
                setattr(match, key, getattr(record, key))
    return merged
