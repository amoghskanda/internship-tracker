"""Command-line entry point for the JSON collector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .collector import CollectorConfig, collect_default


def _board_map(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        slug, separator, company = value.partition(":")
        slug = slug.strip()
        if slug:
            result[slug] = company.strip() if separator and company.strip() else slug
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect explicit Summer 2027 internship postings as JSON")
    parser.add_argument("--output", type=Path, help="write the JSON response to this path")
    parser.add_argument("--all-countries", action="store_true", help="include locations outside the United States")
    parser.add_argument("--include-remote", action="store_true", help="include generic Remote locations without a country")
    parser.add_argument("--role-keyword", action="append", default=[], help="optional title keyword; repeat to allow several")
    parser.add_argument("--greenhouse-board", action="append", default=[], metavar="SLUG[:COMPANY]", help="add a Greenhouse board")
    parser.add_argument("--ashby-board", action="append", default=[], metavar="SLUG[:COMPANY]", help="add an Ashby board")
    parser.add_argument("--no-simplify-enrichment", action="store_true", help="do not fetch employer descriptions linked from Simplify")
    parser.add_argument("--max-enrichment-requests", type=int, default=400)
    parser.add_argument("--enrichment-workers", type=int, default=8)
    parser.add_argument("--browser-jobs", type=Path, help="JSON jobs verified through the signed-in T3 browser")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    greenhouse = _board_map(args.greenhouse_board) if args.greenhouse_board else None
    ashby = _board_map(args.ashby_board) if args.ashby_board else None
    config = CollectorConfig(
        country_filter=None if args.all_countries else "US",
        include_remote_unknown=args.include_remote,
        role_keywords=tuple(args.role_keyword),
        greenhouse_boards=greenhouse if greenhouse is not None else CollectorConfig().greenhouse_boards,
        ashby_boards=ashby if ashby is not None else CollectorConfig().ashby_boards,
        enrich_simplify=not args.no_simplify_enrichment,
        max_enrichment_requests=max(0, args.max_enrichment_requests),
        enrichment_workers=max(1, args.enrichment_workers),
        browser_jobs_path=str(args.browser_jobs) if args.browser_jobs else None,
    )
    result = collect_default(config)
    payload = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if any(item.status == "ok" for item in result.source_health) else 1


if __name__ == "__main__":
    raise SystemExit(main())
