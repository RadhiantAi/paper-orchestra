"""Opt-in read-only web, Zotero and MCP searches. Credentials stay in environment."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from utils.literature_sources import LiteratureRecord, SearchPage, SourceError


class BraveSearchSource:
    name = "web"

    def search(self, query, limit, cutoff, transport, cursor=None):
        key = os.getenv("BRAVE_SEARCH_API_KEY")
        if not key:
            raise SourceError("web_not_configured")
        offset = int(cursor or 0)
        data = transport.get(
            self.name,
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": min(limit, 20), "offset": offset},
            headers={"X-Subscription-Token": key},
        )
        records = [
            LiteratureRecord(
                title=x["title"],
                source=self.name,
                source_id=x["url"],
                url=x["url"],
                publication_type="web-page",
                provenance=[
                    {
                        "snippet": x.get("description", ""),
                        "evidence_warning": "Search snippet is not an abstract or full text.",
                    }
                ],
            )
            for x in data.get("web", {}).get("results", [])
        ]
        more = bool(data.get("query", {}).get("more_results_available"))
        return SearchPage(
            records,
            truncated=more,
            warnings=["web_dates_and_claims_require_verification"],
            next_cursor=str(offset + 1) if more and offset < 9 else None,
        )


class ZoteroSource:
    def __init__(self, name, library, collection=""):
        if not re.fullmatch(r"(users|groups)/\d+", library) or (
            collection and not re.fullmatch(r"[A-Z0-9]{8}", collection)
        ):
            raise ValueError(
                "Select an exact Zotero user/group library and optional collection key."
            )
        self.name, self.library, self.collection = name, library, collection

    def search(self, query, limit, cutoff, transport, cursor=None):
        path = (
            f"{self.library}/"
            + (f"collections/{self.collection}/" if self.collection else "")
            + "items/top"
        )
        headers = {"Zotero-API-Version": "3"}
        if os.getenv("ZOTERO_API_KEY"):
            headers["Zotero-API-Key"] = os.environ["ZOTERO_API_KEY"]
        data = transport.get(
            self.name,
            "https://api.zotero.org/" + path,
            params={
                "q": query,
                "qmode": "everything",
                "format": "json",
                "limit": limit,
                "start": int(cursor or 0),
            },
            headers=headers,
        )
        records = []
        for item in data:
            d = item["data"]
            if d.get("itemType") in {"attachment", "note", "annotation"}:
                continue
            year = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", d.get("date", ""))
            records.append(
                LiteratureRecord(
                    title=d["title"],
                    source=self.name,
                    source_id=item["key"],
                    doi=d.get("DOI", ""),
                    abstract=d.get("abstractNote", ""),
                    year=int(year[0]) if year else None,
                    venue=d.get("publicationTitle", ""),
                    authors=[
                        c.get("name")
                        or " ".join(
                            filter(None, [c.get("firstName"), c.get("lastName")])
                        )
                        for c in d.get("creators", [])
                        if c.get("creatorType") == "author"
                    ],
                    url=d.get("url")
                    or item.get("links", {}).get("alternate", {}).get("href", ""),
                    provenance=[
                        {
                            "library": self.library,
                            "collection": self.collection,
                            "version": item.get("version"),
                        }
                    ],
                )
            )
        more = len(data) == limit
        return SearchPage(
            records,
            truncated=more,
            next_cursor=str(int(cursor or 0) + limit) if more else None,
        )


class MCPSource:
    """Streamable HTTP JSON or SSE responses, selected read-only tool only.

    Server output must be structuredContent {records: [LiteratureRecord fields],
    next_cursor, total}. Argument names are configured by the operator, never the LLM.
    OAuth token acquisition/refresh belongs to the host; no implicit credential reuse.
    """

    def __init__(self, name, endpoint, tool, argument_names=None, token_env=""):
        u = urlsplit(endpoint)
        if (
            u.scheme != "https"
            or not u.hostname
            or u.username
            or u.password
            or u.query
            or u.fragment
        ):
            raise ValueError(
                "MCP endpoint must be a selected HTTPS URL without embedded credentials/query."
            )
        self.name, self.endpoint, self.tool = name, endpoint, tool
        self.arguments = argument_names or {
            "query": "query",
            "limit": "limit",
            "cursor": "cursor",
        }
        if set(self.arguments) - {"query", "limit", "cursor"}:
            raise ValueError("Only query, limit and cursor mappings are supported.")
        self.token_env, self.session, self.ready = token_env, "", False
        self.sequence = 0

    def rpc(self, method, params, transport, notification=False):
        self.sequence += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            body["id"] = self.sequence
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.token_env:
            token = os.getenv(self.token_env)
            if not token:
                raise SourceError("mcp_token_missing")
            headers["Authorization"] = "Bearer " + token
        payload, response_headers = transport.request(
            self.name,
            self.endpoint,
            method="POST",
            body=body,
            headers=headers,
            as_json=False,
            with_headers=True,
        )
        self.session = next(
            (v for k, v in response_headers.items() if k.lower() == "mcp-session-id"),
            self.session,
        )
        if notification:
            return {}
        try:
            if payload.lstrip().startswith(b"{"):
                response = json.loads(payload)
            else:
                events = [
                    json.loads(
                        "\n".join(
                            line[5:].lstrip()
                            for line in block.splitlines()
                            if line.startswith("data:")
                        )
                    )
                    for block in payload.decode().replace("\r\n", "\n").split("\n\n")
                    if any(line.startswith("data:") for line in block.splitlines())
                ]
                response = next(e for e in events if e.get("id") == self.sequence)
            if response.get("id") != self.sequence or "error" in response:
                raise ValueError()
            return response["result"]
        except Exception:
            raise SourceError("invalid_mcp_response") from None

    def search(self, query, limit, cutoff, transport, cursor=None):
        if not self.ready:
            result = self.rpc(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "paper-orchestra", "version": "1"},
                },
                transport,
            )
            if result.get("protocolVersion") != "2025-06-18":
                raise SourceError("mcp_protocol_unsupported")
            self.rpc("notifications/initialized", {}, transport, notification=True)
            listing = self.rpc("tools/list", {}, transport)
            selected = next(
                (t for t in listing.get("tools", []) if t["name"] == self.tool), None
            )
            if (
                not selected
                or selected.get("annotations", {}).get("readOnlyHint") is not True
            ):
                raise SourceError("mcp_selected_tool_not_declared_readonly")
            self.ready = True
        values = {"query": query, "limit": limit, "cursor": cursor}
        arguments = {
            remote: values[local]
            for local, remote in self.arguments.items()
            if values[local] is not None
        }
        result = self.rpc(
            "tools/call", {"name": self.tool, "arguments": arguments}, transport
        )
        if result.get("isError"):
            raise SourceError("mcp_search_failed")
        data = result.get("structuredContent", {})
        if not isinstance(data.get("records"), list) or len(data["records"]) > limit:
            raise SourceError("mcp_records_schema_required")
        records = []
        for row in data["records"]:
            row = dict(row)
            row.pop("evidence_level", None)
            if row.get("full_text") and not row.get("rights"):
                raise SourceError("mcp_fulltext_rights_required")
            record = LiteratureRecord(**row)
            if not record.url:
                raise SourceError("mcp_source_url_required")
            records.append(record)
        return SearchPage(
            records,
            data.get("total"),
            bool(data.get("next_cursor")),
            next_cursor=data.get("next_cursor"),
        )


def configured_sources(path):
    selected = Path(path)
    if selected.stat().st_size > 100_000:
        raise ValueError("Connector configuration too large.")
    config = json.loads(selected.read_text(encoding="utf-8"))
    sources = []
    for c in config:
        if c["type"] == "web":
            sources.append(BraveSearchSource())
        elif c["type"] == "zotero":
            sources.append(
                ZoteroSource(c["name"], c["library"], c.get("collection", ""))
            )
        elif c["type"] == "mcp":
            sources.append(
                MCPSource(
                    c["name"],
                    c["endpoint"],
                    c["tool"],
                    c.get("argument_names"),
                    c.get("token_env", ""),
                )
            )
        else:
            raise ValueError("Unknown connector type.")
    return sources
