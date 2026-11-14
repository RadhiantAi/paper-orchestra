"""Bounded alternate queries, citation chasing and explicit screening reasons."""

import os
import re
from copy import deepcopy
from urllib.parse import quote

from utils.literature_sources import LiteratureRecord, merge_records, utc_now


def run_search_plan(
    engine,
    queries,
    cutoff=None,
    *,
    required_terms=(),
    excluded_terms=(),
    chase_dois=(),
    max_chase=10,
    enrich=False,
):
    if not 1 <= len(queries) <= 20 or len(set(queries)) != len(queries):
        raise ValueError("Supply 1-20 distinct alternate queries.")
    if not 0 <= max_chase <= 100 or len(chase_dois) > 20:
        raise ValueError(
            "Citation expansion is limited to 20 seeds and 100 records per direction."
        )
    records = []
    for query in queries:
        records.extend(engine.search(query, cutoff))
    for doi in chase_dois:
        records.extend(chase_citations(doi, engine, max_chase, cutoff))
    merged = merge_records(records)
    selected = []
    for record in merged:
        text = (record.title + " " + record.abstract).casefold()
        missing = [t for t in required_terms if t.casefold() not in text]
        excluded = [t for t in excluded_terms if t.casefold() in text]
        reason = (
            "missing_required_terms: " + ", ".join(missing)
            if missing
            else (
                "excluded_terms: " + ", ".join(excluded)
                if excluded
                else "matches_declared_screen"
            )
        )
        decision = "exclude" if missing or excluded else "include_for_review"
        engine.report.setdefault("screening", []).append(
            dict(
                source_id=record.source_id,
                doi=record.doi,
                title=record.title,
                decision=decision,
                reason=reason,
                at=utc_now(),
            )
        )
        if decision == "include_for_review":
            selected.append(record)
    if enrich:
        from utils.literature_enrichment import check_integrity, fetch_pmc

        for record in selected:
            result = {"doi": record.doi, "pmcid": record.pmcid}
            result["integrity"] = check_integrity(record, engine.transport)
            try:
                result["full_text"] = fetch_pmc(record, engine.transport)
            except Exception:
                result["full_text"] = {"status": "failed_or_budget_exhausted"}
            engine.report.setdefault("enrichment", []).append(result)
    return selected


def chase_citations(doi, engine, limit, cutoff=None):
    """One generation of reference/citing-paper expansion through OpenAlex."""
    if not limit:
        return []
    from utils.literature_sources import cutoff_end

    end = cutoff_end(cutoff)
    transport, records = engine.transport, []
    params = (
        {"api_key": os.environ["OPENALEX_API_KEY"]}
        if os.getenv("OPENALEX_API_KEY")
        else {}
    )
    entry = {
        "seed_doi": doi,
        "status": "ok",
        "limit_per_direction": limit,
        "truncated": False,
    }
    before = transport.requests_used
    work_batches = []
    try:
        seed = transport.get(
            "openalex",
            "https://api.openalex.org/works/https://doi.org/" + quote(doi, safe=""),
            params=params,
        )
        identifier = seed["id"].rsplit("/", 1)[-1]
        if not re.fullmatch(r"W\d+", identifier):
            raise ValueError("Invalid OpenAlex ID")
        refs = seed.get("referenced_works") or []
        entry["truncated"] = len(refs) > limit
        for reference in refs[:limit]:
            rid = reference.rsplit("/", 1)[-1]
            if not re.fullmatch(r"W\d+", rid):
                continue
            work_batches.append(
                (
                    "reference",
                    transport.get(
                        "openalex",
                        "https://api.openalex.org/works/" + rid,
                        params=params,
                    ),
                )
            )
        citing = transport.get(
            "openalex",
            "https://api.openalex.org/works",
            params={**params, "filter": "cites:" + identifier, "per_page": limit},
        )
        entry["truncated"] |= citing.get("meta", {}).get("count", 0) > limit
        work_batches.extend(("citing", w) for w in citing["results"])
    except Exception:
        entry["status"] = "failed_or_budget_exhausted"
    try:
        for direction, work in work_batches:
            inverted = work.get("abstract_inverted_index") or {}
            abstract = " ".join(
                w
                for _, w in sorted(
                    (i, w) for w, indexes in inverted.items() for i in indexes
                )
            )
            record = LiteratureRecord(
                title=work["title"],
                source="openalex",
                source_id=work["id"],
                year=work.get("publication_year"),
                publication_date=work.get("publication_date") or "",
                doi=work.get("doi") or "",
                abstract=abstract,
                url=work["id"],
                provenance=[
                    {"seed_doi": doi, "direction": direction, "retrieved_at": utc_now()}
                ],
            )
            engine.records.append(deepcopy(record))
            if end and (
                (record.publication_date and record.publication_date > end)
                or (record.year and record.year > int(end[:4]))
            ):
                engine.report.setdefault("screening", []).append(
                    {"doi": record.doi, "decision": "exclude", "reason": "after_cutoff"}
                )
            else:
                records.append(record)
    except Exception:
        entry["status"] = "failed_or_budget_exhausted"
    entry.update(returned=len(records), http_requests=transport.requests_used - before)
    engine.report.setdefault("citation_chasing", []).append(entry)
    return records
