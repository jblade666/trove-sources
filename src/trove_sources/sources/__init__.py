"""One module per kind of place that posts links.

A source module has NAME, HELP, SourceError, add_arguments(parser) and
find_links(args) -> list[FoundLink]. It only finds links; trove does the rest.

A source that reports rather than syncs (sharethread) has run(args) -> int instead
of find_links, and gets only its own options and --config.
"""

from trove_sources.sources import fourchan, sharethread

SOURCES = {fourchan.NAME: fourchan, sharethread.NAME: sharethread}
