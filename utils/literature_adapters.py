"""Public database adapters plus an explicitly selected collection export."""

import json
import os
from pathlib import Path
import re
from xml.etree import ElementTree as ET

from utils.literature_sources import (
    LiteratureRecord,
    SearchPage,
    SourceError,
    clean_text,
)


class PubMedSource:
    name = "pubmed"

    def search(self, query, limit, cutoff, transport):
        base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        common = {"db": "pubmed", "tool": "paper_orchestra"}
        if os.getenv("NCBI_API_KEY"):
            common["api_key"] = os.environ["NCBI_API_KEY"]
        if os.getenv("LITERATURE_CONTACT_EMAIL"):
            common["email"] = os.environ["LITERATURE_CONTACT_EMAIL"]
        params = {
            **common,
            "term": query,
            "retmax": limit,
            "retmode": "json",
            "sort": "relevance",
        }
        if cutoff:
            params.update(
                datetype="pdat", mindate="1000/01/01", maxdate=cutoff.replace("-", "/")
            )
        data = transport.get(self.name, base + "esearch.fcgi", params=params)[
            "esearchresult"
        ]
        if data.get("errorlist") or data.get("ERROR"):
            raise SourceError("query_rejected")
        ids = data["idlist"]
        total = int(data["count"])
        warnings = ["pubmed_query_warning"] if data.get("warninglist") else []
        if not ids:
            return SearchPage([], total, total > 0, warnings)
        payload = transport.get(
            self.name,
            base + "efetch.fcgi",
            params={**common, "id": ",".join(ids), "retmode": "xml"},
            as_json=False,
        )
        root = ET.fromstring(payload)
        if root.tag != "PubmedArticleSet":
            raise SourceError("invalid_response")
        records = []
        for article in root.findall("PubmedArticle"):
            citation = article.find("MedlineCitation")
            info = citation.find("Article")
            text = lambda node: "" if node is None else "".join(node.itertext()).strip()
            pmid = citation.findtext("PMID", "")
            identifiers = {
                n.get("IdType"): n.text
                for n in article.findall("PubmedData/ArticleIdList/ArticleId")
            }
            pub_date = info.find("Journal/JournalIssue/PubDate")
            year_text = pub_date.findtext("Year", "") if pub_date is not None else ""
            if not year_text and pub_date is not None:
                year_text = (
                    re.findall(r"\b\d{4}\b", pub_date.findtext("MedlineDate", ""))
                    or [""]
                )[0]
            abstracts = [
                ((n.get("Label") + ": ") if n.get("Label") else "") + text(n)
                for n in info.findall("Abstract/AbstractText")
            ]
            authors = [
                a.findtext("CollectiveName")
                or " ".join(
                    filter(None, [a.findtext("ForeName"), a.findtext("LastName")])
                )
                for a in info.findall("AuthorList/Author")
            ]
            records.append(
                LiteratureRecord(
                    title=text(info.find("ArticleTitle")),
                    source=self.name,
                    publication_type="journal-article",
                    source_id=pmid,
                    pmid=pmid,
                    pmcid=identifiers.get("pmc") or "",
                    doi=identifiers.get("doi") or "",
                    year=int(year_text) if year_text else None,
                    authors=authors,
                    abstract="\n".join(abstracts),
                    venue=info.findtext("Journal/Title", ""),
                    volume=info.findtext("Journal/JournalIssue/Volume", ""),
                    pages=info.findtext("Pagination/StartPage")
                    or info.findtext("Pagination/MedlinePgn", ""),
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                )
            )
        if len(records) < len(ids):
            warnings.append("some_pubmed_records_not_hydrated")
        return SearchPage(records, total, total > len(records), warnings)


class OpenAlexSource:
    name = "openalex"

    def search(self, query, limit, cutoff, transport):
        params = {"search": query, "per_page": limit}
        if cutoff:
            params["filter"] = f"to_publication_date:{cutoff}"
        if os.getenv("OPENALEX_API_KEY"):
            params["api_key"] = os.environ["OPENALEX_API_KEY"]
        data = transport.get(self.name, "https://api.openalex.org/works", params=params)
        records = []
        for work in data["results"]:
            inverted = work.get("abstract_inverted_index") or {}
            positions = sorted(
                (i, word) for word, indexes in inverted.items() for i in indexes
            )
            location = work.get("primary_location") or {}
            venue = location.get("source") or {}
            ids, biblio = work.get("ids") or {}, work.get("biblio") or {}
            records.append(
                LiteratureRecord(
                    title=work["title"],
                    source=self.name,
                    source_id=work["id"],
                    publication_type=work.get("type") or "",
                    year=work.get("publication_year"),
                    doi=work.get("doi") or "",
                    pmid=ids.get("pmid") or "",
                    authors=[
                        a["author"]["display_name"] for a in work.get("authorships", [])
                    ],
                    abstract=" ".join(word for _, word in positions),
                    venue=venue.get("display_name") or "",
                    publication_date=work.get("publication_date") or "",
                    volume=biblio.get("volume") or "",
                    pages="-".join(
                        str(x)
                        for x in [biblio.get("first_page"), biblio.get("last_page")]
                        if x
                    ),
                    url=location.get("landing_page_url") or work["id"],
                    full_text_url=location.get("pdf_url") or "",
                    rights=location.get("license") or "",
                )
            )
        total = int(data["meta"]["count"])
        return SearchPage(records, total, total > len(records))


class SemanticScholarSource:
    name = "semantic_scholar"

    def search(self, query, limit, cutoff, transport):
        params = {
            "query": query,
            "limit": limit,
            "fields": "title,authors,year,abstract,venue,publicationDate,externalIds,url,openAccessPdf,journal",
        }
        if cutoff:
            params["year"] = f":{cutoff[:4]}"
        headers = (
            {"x-api-key": os.environ["SEMANTIC_SCHOLAR_API_KEY"]}
            if os.getenv("SEMANTIC_SCHOLAR_API_KEY")
            else {}
        )
        data = transport.get(
            self.name,
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params,
            headers=headers,
        )
        records = []
        for work in data["data"]:
            ids, journal, pdf = (
                work.get("externalIds") or {},
                work.get("journal") or {},
                work.get("openAccessPdf") or {},
            )
            records.append(
                LiteratureRecord(
                    title=work["title"],
                    source=self.name,
                    source_id=work["paperId"],
                    publication_type="journal-article" if journal.get("name") else "",
                    authors=[a["name"] for a in work.get("authors", [])],
                    year=work.get("year"),
                    abstract=work.get("abstract") or "",
                    doi=ids.get("DOI") or "",
                    pmid=ids.get("PubMed") or "",
                    pmcid=ids.get("PubMedCentral") or "",
                    venue=work.get("venue") or journal.get("name") or "",
                    publication_date=work.get("publicationDate") or "",
                    volume=journal.get("volume") or "",
                    pages=journal.get("pages") or "",
                    url=work.get("url") or "",
                    full_text_url=pdf.get("url") or "",
                )
            )
        total = int(data["total"])
        return SearchPage(
            records, total, total > len(records) or data.get("next") is not None
        )


class CrossrefSource:
    name = "crossref"

    def search(self, query, limit, cutoff, transport):
        params = {"query.bibliographic": query, "rows": limit}
        if cutoff:
            params["filter"] = f"until-pub-date:{cutoff}"
        if os.getenv("LITERATURE_CONTACT_EMAIL"):
            params["mailto"] = os.environ["LITERATURE_CONTACT_EMAIL"]
        data = transport.get(
            self.name, "https://api.crossref.org/works", params=params
        )["message"]
        records = []
        for work in data["items"]:
            parts = (work.get("published", {}).get("date-parts") or [[]])[0]
            records.append(
                LiteratureRecord(
                    title=(work.get("title") or [""])[0],
                    source=self.name,
                    source_id=work["DOI"],
                    publication_type=work.get("type") or "",
                    doi=work["DOI"],
                    year=parts[0] if parts else None,
                    publication_date="-".join(f"{p:02d}" for p in parts)
                    if len(parts) == 3
                    else "",
                    authors=[
                        a.get("name")
                        or " ".join(filter(None, [a.get("given"), a.get("family")]))
                        for a in work.get("author", [])
                    ],
                    abstract=clean_text(work.get("abstract")),
                    venue=(work.get("container-title") or [""])[0],
                    volume=work.get("volume") or "",
                    pages=work.get("page") or "",
                    url=work.get("URL") or "",
                )
            )
        total = int(data["total-results"])
        return SearchPage(records, total, total > len(records))


class CollectionSource:
    """Search an explicitly configured JSON export. Never crawl folders or follow URLs."""

    name = "collection"

    def __init__(self, path):
        self.path = Path(path) if path else None

    def search(self, query, limit, cutoff, transport):
        if self.path is None:
            raise SourceError("collection_not_configured")
        if self.path.stat().st_size > 8_000_000:
            raise SourceError("collection_too_large")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or len(data) > 2000:
            raise SourceError("invalid_collection")
        records = []
        terms = set(re.findall(r"\w+", query.casefold()))
        for item in data:
            item = dict(item)
            item.pop("evidence_level", None)
            pdf_name = item.pop("pdf_path", None)
            if pdf_name:
                if not item.get("rights"):
                    raise SourceError("collection_full_text_requires_rights_note")
                selected = (self.path.parent / pdf_name).resolve()
                if (
                    not selected.is_relative_to(self.path.parent.resolve())
                    or selected.suffix.lower() != ".pdf"
                ):
                    raise SourceError("collection_pdf_outside_selected_folder")
                if selected.stat().st_size > 25_000_000:
                    raise SourceError("collection_pdf_too_large")
                import pymupdf

                with pymupdf.open(selected) as document:
                    if len(document) > 100:
                        raise SourceError("collection_pdf_too_many_pages")
                    item["full_text"] = "\n\n".join(
                        f"[Page {i + 1}] " + page.get_text()
                        for i, page in enumerate(document)
                    )
                    if not any(page.get_text().strip() for page in document):
                        raise SourceError("collection_pdf_has_no_extractable_text")
                item["full_text_url"] = selected.name

            # Metadata from an export is attributable to its original source.
            if not item.get("url"):
                raise SourceError("collection_record_missing_source_url")
            if item.get("full_text") and not item.get("rights"):
                raise SourceError("collection_full_text_requires_rights_note")
            record = LiteratureRecord(**item)
            haystack = set(
                re.findall(
                    r"\w+",
                    (
                        record.title + " " + record.abstract + " " + record.full_text
                    ).casefold(),
                )
            )
            score = len(terms & haystack)
            if score:
                records.append((score, record))
        records.sort(key=lambda pair: pair[0], reverse=True)
        return SearchPage(
            [r for _, r in records[:limit]], len(records), len(records) > limit
        )


BUILTIN_SOURCES = {
    cls.name: cls
    for cls in (PubMedSource, OpenAlexSource, SemanticScholarSource, CrossrefSource)
}
