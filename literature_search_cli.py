"""Search and save evidence without model calls or manuscript generation."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from utils.literature_discovery import DiscoveryConfig, DiscoveryEngine


def main():
    load_dotenv(Path(__file__).resolve().parent / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument(
        "--sources", help="Comma-separated source names; default is all four databases."
    )
    parser.add_argument("--limit", type=int, help="Results per source, 1-100.")
    parser.add_argument("--cutoff", help="Inclusive YYYY, YYYY-MM or YYYY-MM-DD.")
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--alternate", action="append", default=[])
    parser.add_argument("--require-term", action="append", default=[])
    parser.add_argument("--exclude-term", action="append", default=[])
    parser.add_argument("--chase-doi", action="append", default=[])
    parser.add_argument("--chase-limit", type=int, default=10)
    parser.add_argument("--enrich", action="store_true", help="Check Crossref integrity and permitted PMC full text.")
    parser.add_argument("--connectors", help="Explicit JSON connector configuration.")
    args = parser.parse_args()
    config = DiscoveryConfig.from_env()
    if args.sources is not None:
        config.sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    if args.limit is not None:
        config.per_source_limit = args.limit
    if args.pages is not None:
        config.max_pages = args.pages
    if args.connectors:
        config.connector_config = args.connectors
    config.__post_init__()
    engine = DiscoveryEngine(config)
    try:
        from utils.search_plan import run_search_plan
        records = run_search_plan(engine, [args.query] + args.alternate, args.cutoff,
                                  required_terms=args.require_term, excluded_terms=args.exclude_term,
                                  chase_dois=args.chase_doi, max_chase=args.chase_limit, enrich=args.enrich)
    finally:
        report = engine.save_report(args.output_dir)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "sources": [
                        {
                            k: entry[k]
                            for k in ("source", "status", "returned", "truncated")
                        }
                        for entry in report["coverage"]
                    ],
                    "http_requests_used": report["http_requests_used"],
                }
            )
        )
    (Path(args.output_dir) / "merged_records.json").write_text(
        json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not records:
        raise SystemExit(1)
    if report["status"] == "partial":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
