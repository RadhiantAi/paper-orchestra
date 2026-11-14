"""Federated discovery, provenance, coverage reports and extension registration."""

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading

from utils.literature_adapters import BUILTIN_SOURCES, CollectionSource
from utils.literature_sources import (
    LiteratureRecord,
    SearchPage,
    SearchTransport,
    SourceError,
    BudgetExceeded,
    cutoff_end,
    merge_records,
    utc_now,
)


DEFAULT_SOURCES = ("pubmed", "openalex", "semantic_scholar", "crossref")


@dataclass
class DiscoveryConfig:
    sources: tuple[str, ...] = DEFAULT_SOURCES
    per_source_limit: int = 20
    max_requests: int = 80
    max_seconds: float = 180
    request_timeout: float = 20
    require_all_sources: bool = False
    collection_path: str = ""

    def __post_init__(self):
        if not self.sources or len(set(self.sources)) != len(self.sources):
            raise ValueError("Choose at least one unique literature source.")
        if not 1 <= self.per_source_limit <= 100:
            raise ValueError("Literature results per source must be between 1 and 100.")
        if self.max_requests < 1 or self.max_seconds <= 0 or self.request_timeout <= 0:
            raise ValueError("Literature request and time budgets must be positive.")

    @classmethod
    def from_env(cls):
        return cls(
            sources=tuple(
                s.strip()
                for s in os.getenv(
                    "LITERATURE_SOURCES", ",".join(DEFAULT_SOURCES)
                ).split(",")
                if s.strip()
            ),
            per_source_limit=int(os.getenv("LITERATURE_RESULTS_PER_SOURCE", "20")),
            max_requests=int(os.getenv("LITERATURE_MAX_REQUESTS", "80")),
            max_seconds=float(os.getenv("LITERATURE_MAX_SECONDS", "180")),
            request_timeout=float(os.getenv("LITERATURE_REQUEST_TIMEOUT", "20")),
            require_all_sources=os.getenv(
                "LITERATURE_REQUIRE_ALL_SOURCES", "false"
            ).lower()
            == "true",
            collection_path=os.getenv("LITERATURE_COLLECTION_PATH", ""),
        )


class DiscoveryEngine:
    def __init__(self, config=None, *, extra_sources=None, transport=None):
        self.config = config or DiscoveryConfig.from_env()
        registry = {name: cls() for name, cls in BUILTIN_SOURCES.items()}
        registry["collection"] = CollectionSource(self.config.collection_path)
        for source in extra_sources or []:
            if source.name in registry:
                raise ValueError(
                    "Custom source names must not replace built-in sources."
                )
            registry[source.name] = source
        unknown = set(self.config.sources) - registry.keys()
        if unknown:
            raise ValueError(
                "Unknown literature sources: " + ", ".join(sorted(unknown))
            )
        self.sources = [registry[name] for name in self.config.sources]
        self.transport = transport or SearchTransport(
            self.config.max_requests,
            self.config.max_seconds,
            self.config.request_timeout,
        )
        self.lock = threading.Lock()
        self.cache = {}
        self.failed_queries = set()
        self.records = []
        self.report = {
            "schema_version": 1,
            "started_at": utc_now(),
            "enabled_sources": list(self.config.sources),
            "limits": {
                "results_per_source_per_query": self.config.per_source_limit,
                "max_http_requests": self.config.max_requests,
                "max_elapsed_seconds": self.config.max_seconds,
                "request_timeout_seconds": self.config.request_timeout,
            },
            "coverage": [],
            "selections": [],
            "scope": "Bounded discovery. This is not an exhaustive or systematic-review search.",
        }

    def search(self, query, cutoff=None):
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError(
                "Supply a nonempty literature query of at most 4000 characters."
            )
        end = cutoff_end(cutoff)
        key = (query, end)
        with self.lock:
            if key in self.cache:
                if key in self.failed_queries and self.config.require_all_sources:
                    raise RuntimeError(
                        "Some literature sources failed. See discovery_report.json."
                    )
                return deepcopy(self.cache[key])
            records, failed = [], False
            for source in self.sources:
                before = self.transport.requests_used
                entry = {
                    "source": source.name,
                    "query": query,
                    "cutoff_inclusive": end,
                    "searched_at": utc_now(),
                    "status": "ok",
                    "returned": 0,
                    "eligible": 0,
                    "excluded_after_cutoff": 0,
                    "total_reported": None,
                    "truncated": False,
                    "warnings": [],
                }
                try:
                    if self.transport.remaining() <= 0:
                        raise BudgetExceeded("time_budget_exhausted")
                    page = source.search(
                        query, self.config.per_source_limit, end, self.transport
                    )
                    if (
                        not isinstance(page, SearchPage)
                        or len(page.records) > self.config.per_source_limit
                    ):
                        raise SourceError("invalid_adapter_response")
                    entry.update(
                        returned=len(page.records),
                        total_reported=page.total,
                        truncated=page.truncated,
                        warnings=list(page.warnings),
                    )
                    for record in page.records:
                        if not isinstance(record, LiteratureRecord):
                            raise SourceError("invalid_adapter_record")
                        after_cutoff = bool(
                            end
                            and (
                                (
                                    record.publication_date
                                    and record.publication_date > end
                                )
                                or (record.year and record.year > int(end[:4]))
                            )
                        )
                        record.provenance.append(
                            {
                                "adapter": source.name,
                                "source": record.source,
                                "source_id": record.source_id,
                                "url": record.url,
                                "query": query,
                                "retrieved_at": entry["searched_at"],
                                "evidence_level": record.evidence_level,
                                "abstract": record.abstract,
                                "full_text_url": record.full_text_url,
                                "rights": record.rights,
                                "excluded_after_cutoff": after_cutoff,
                            }
                        )
                        self.records.append(deepcopy(record))
                        if after_cutoff:
                            entry["excluded_after_cutoff"] += 1
                            continue
                        if not record.year and not record.publication_date:
                            if "publication_date_unknown" not in entry["warnings"]:
                                entry["warnings"].append("publication_date_unknown")
                        records.append(record)
                        entry["eligible"] += 1
                except BudgetExceeded:
                    entry.update(status="budget_exhausted", error="budget_exhausted")
                    failed = True
                except SourceError as error:
                    # Only known fixed diagnostics are allowed in saved reports.
                    code = str(error)
                    allowed = {
                        "timeout",
                        "request_or_response_failed",
                        "response_too_large",
                        "query_rejected",
                        "invalid_response",
                        "collection_not_configured",
                        "collection_too_large",
                        "invalid_collection",
                        "collection_record_missing_source_url",
                        "collection_full_text_requires_rights_note",
                    }
                    if code not in allowed and not (
                        code.startswith("http_") and code[5:].isdigit()
                    ):
                        code = "source_failed"
                    entry.update(status="failed", error=code)
                    failed = True
                except Exception:
                    entry.update(
                        status="failed", error="invalid_response_or_unavailable"
                    )
                    failed = True
                finally:
                    entry["http_requests"] = self.transport.requests_used - before
                    self.report["coverage"].append(entry)
            result = merge_records(records)
            # Cache even failed/empty retrievals: model retries must not repeat HTTP calls.
            self.cache[key] = result
            if failed:
                self.failed_queries.add(key)
            if failed and self.config.require_all_sources:
                raise RuntimeError(
                    "Some literature sources failed. See discovery_report.json."
                )
            return deepcopy(result)

    def record_selection(self, task, records):
        with self.lock:
            self.report["selections"].append(
                {
                    "task": task,
                    "selected": [
                        {
                            "title": r.title,
                            "doi": r.doi,
                            "pmid": r.pmid,
                            "source": r.source,
                            "source_id": r.source_id,
                        }
                        for r in records
                    ],
                }
            )

    def save_report(self, output_dir):
        """Save before writing, and on errors, so missing sources never disappear."""
        with self.lock:
            report = deepcopy(self.report)
            failures = any(e["status"] != "ok" for e in report["coverage"])
            bounded = any(e["truncated"] or e["warnings"] for e in report["coverage"])
            report["status"] = (
                "partial" if failures else "bounded" if bounded else "completed_queries"
            )
            if not report["coverage"]:
                report["status"] = "not_searched"
            report.update(
                updated_at=utc_now(),
                http_requests_used=self.transport.requests_used,
                retrieved_record_count=len(self.records),
            )
            path = Path(output_dir)
            path.mkdir(parents=True, exist_ok=True)
            for name, payload in (
                ("discovery_report.json", report),
                ("retrieved_records.json", [r.to_dict() for r in self.records]),
            ):
                target = path / name
                temporary = path / (name + ".tmp")
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                temporary.replace(target)
            return report
