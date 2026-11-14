"""Rights-aware PMC passages and current Crossref research-integrity metadata."""

import re
from urllib.parse import quote
from xml.etree import ElementTree as ET

from utils.literature_sources import (
    SourceError,
    normalise_doi,
    normalise_title,
    utc_now,
)


def fetch_pmc(record, transport):
    pmcid = record.pmcid.upper()
    if not re.fullmatch(r"PMC\d+", pmcid):
        return {"status": "unavailable", "reason": "no_pmcid"}
    url = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"
    payload = transport.get(
        "pmc",
        url,
        params={
            "verb": "GetRecord",
            "identifier": "oai:pubmedcentral.nih.gov:" + pmcid[3:],
            "metadataPrefix": "pmc",
        },
        as_json=False,
    )
    root = ET.fromstring(payload)
    # Ignore namespace prefixes, retaining all sections and paragraphs in order.
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    if root.find(".//error") is not None:
        return {"status": "unavailable", "reason": "oai_fulltext_not_available"}
    article = root.find(".//article")
    if article is None or article.find("body") is None:
        return {"status": "unavailable", "reason": "no_article_body"}
    identifiers = {
        n.get("pub-id-type"): "".join(n.itertext()).strip()
        for n in article.findall(".//article-id")
    }
    returned_id = identifiers.get("pmc") or identifiers.get("pmcid")
    if returned_id and returned_id.removeprefix("PMC") != pmcid[3:]:
        raise SourceError("pmc_identity_mismatch")
    returned_doi = normalise_doi(identifiers.get("doi", ""))
    if record.doi and returned_doi and record.doi != returned_doi:
        raise SourceError("pmc_identity_mismatch")
    permissions = article.find(".//permissions")
    licence = "" if permissions is None else " ".join(permissions.itertext()).strip()
    if not licence:
        return {"status": "unavailable", "reason": "rights_metadata_missing"}
    passages = []

    def visit(node, section="Body"):
        if node.tag == "sec":
            title = node.find("title")
            section = (
                section
                + " / "
                + (
                    "".join(title.itertext())
                    if title is not None
                    else node.get("id", "Section")
                )
            )
        if node.tag in {"p", "table-wrap", "fig"}:
            text = " ".join("".join(node.itertext()).split())
            if text:
                passages.append(
                    {
                        "section": section,
                        "paragraph": len(passages) + 1,
                        "page": None,
                        "text": text,
                    }
                )
            return
        for child in node:
            visit(child, section)

    visit(article.find("body"))
    record.passages = passages
    record.full_text = "\n\n".join(
        f"[{p['section']}, paragraph {p['paragraph']}] {p['text']}" for p in passages
    )
    record.full_text_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    record.rights = licence
    record.provenance.append(
        {
            "adapter": "pmc_oai",
            "retrieved_at": utc_now(),
            "rights": licence,
            "url": record.full_text_url,
            "location_note": "XML section/paragraph anchors; page numbers unavailable.",
        }
    )
    return {"status": "retrieved", "passages": len(passages), "rights": licence}


def check_integrity(record, transport):
    report = {
        "status": "unknown",
        "checked_at": utc_now(),
        "source": "Crossref production REST API",
        "updates": [],
        "version_relations": [],
        "notice": "No update metadata is not proof of no retraction.",
    }
    if not record.doi:
        report["reason"] = "no_doi"
        record.integrity = report
        return report
    url = "https://api.crossref.org/works/" + quote(record.doi, safe="")
    report["url"] = url
    try:
        work = transport.get("crossref", url)["message"]
        if normalise_doi(work.get("DOI")) != record.doi:
            raise SourceError("doi_identity_mismatch")
        title = (work.get("title") or [""])[0]
        if title and normalise_title(title) != normalise_title(record.title):
            report["title_conflict"] = {"requested": record.title, "registered": title}
            report["status"] = "metadata_conflict"
        updates = work.get("updated-by") or []
        report["updates"] = updates
        report["is_update_notice_for"] = work.get("update-to") or []
        types = {u.get("type", "").lower() for u in updates}
        if types & {"retraction", "withdrawal"}:
            report["status"] = "retracted" if "retraction" in types else "withdrawn"
        elif updates:
            report["status"] = "update_requires_review"
        for kind, relations in (work.get("relation") or {}).items():
            if kind in {
                "is-preprint-of",
                "has-preprint",
                "is-version-of",
                "has-version",
            }:
                report["version_relations"].extend(
                    {"relationship": kind, **r} for r in relations
                )
        if report["status"] == "unknown":
            report["reason"] = "no_update_metadata"
    except Exception:
        report["reason"] = "lookup_failed"
    record.integrity = report
    return report
