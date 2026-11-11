"""``trove-sources SOURCE [options]``: find share links with a source, then sync
them with trove.

Each source knows one kind of place (a forum, a blog) and only finds links;
downloading, skipping, dates, destinations and credentials are trove's, through
``trove.api``, with the user's trove config.
"""

from __future__ import annotations

import argparse
import sys

from trove import api

from trove_sources.sources import SOURCES

PAUSE = 3.0  # seconds between links; gofile in particular bans clients that are quicker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trove-sources", description="Find share links and sync them with trove.",
        epilog="Each source has its own options: run 'trove-sources SOURCE --help', e.g. 'trove-sources fourchan --help'.")
    sub = parser.add_subparsers(dest="source", required=True)
    for name, module in SOURCES.items():
        source = sub.add_parser(name, help=module.HELP, description=module.HELP,
                                epilog=getattr(module, "EXAMPLES", None),
                                formatter_class=argparse.RawDescriptionHelpFormatter)
        module.add_arguments(source)
        source.set_defaults(module=module)
        if hasattr(module, "run"):  # reports instead of syncing: no download options
            source.add_argument("--config", help="trove config file (default: trove's usual one)")
            continue
        source.add_argument("-o", "--output", help="trove destination (default: the config's default_output)")
        source.add_argument("--list-only", action="store_true", help="Only list the links found; don't contact any host")
        source.add_argument("--dry-run", action="store_true", help="List each share but download nothing")
        source.add_argument("--pause", type=float, default=PAUSE, help=f"Seconds between links (default: {PAUSE:g})")
        source.add_argument("--config", help="trove config file (default: trove's usual one)")
        source.set_defaults(module=module)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(args.module, "run"):
        try:
            return args.module.run(args)
        except args.module.SourceError as e:
            print(e)
            return 1
        except api.ConfigError as e:
            print(f"trove: {e}")
            return 2
        except KeyboardInterrupt:
            return 130
    try:
        links = args.module.find_links(args)
    except args.module.SourceError as e:
        print(e)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # the source's site failed: nothing to hand on
        print(f"{args.source}: {e.__class__.__name__}: {e}")
        return 1
    if not links:
        print("No links found.")
        return 1

    print(f"\n{len(links)} link(s):")
    for link in links:
        print(f"  {link.url.split('#', 1)[0]}  ({link.where}{'; ' + link.note if link.note else ''})")
    if args.list_only:
        return 0

    print()
    try:
        report = api.get([l.url for l in links], output=args.output, dry_run=args.dry_run,
                         pause=args.pause, config=args.config)
    except api.ConfigError as e:
        print(f"trove: {e}")
        return 2
    except KeyboardInterrupt:
        return 130

    counts: dict[str, int] = {}
    for share in report.shares:
        counts[share.status] = counts.get(share.status, 0) + 1
    print(f"\n{len(report.shares)} link(s): " + ", ".join(f"{n} {status}" for status, n in sorted(counts.items())))
    for share in report.shares:
        if share.status != "ok":
            print(f"  {share.status:<8} {share.link}{': ' + share.error if share.error else ''}")
    if report.aborted:
        print("The run stopped early; run it again later and finished files are skipped.")
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
