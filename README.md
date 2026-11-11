# trove-sources

Finds share links where people post them (forum threads, blogs) and hands them to
[trove](../trove-downloader) to sync. Each source only finds links; downloading,
skipping what's already there, dates, destinations and credentials are trove's,
through its stable `trove.api`, using your trove config.

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -e ../trove-downloader -e ".[dev]"   # .venv/bin/pip elsewhere
```

## Sources

| Source | What it reads |
|---|---|
| `fourchan` | A recurring 4chan thread, found by board and subject, following "previous thread" links back. Defaults to /tg/'s PDF Share Thread. |
| `sharethread` | The Share Thread's Curated Archive PDF. Reports which of its links your trove sites are missing, instead of syncing them. |

```bash
trove-sources fourchan                     # find the current thread, read it and the previous one, sync every link
trove-sources fourchan --list-only         # just list the links found; contacts no file host
trove-sources fourchan --dry-run           # list each share through trove, download nothing
trove-sources fourchan 98169921 --depth 1  # one given thread
trove-sources fourchan --board xx --title "some general" --depth 3
trove-sources fourchan -o "nas:/files/{provider}"   # instead of the config's default_output
```

Common options: `-o/--output` (a trove destination), `--list-only`, `--dry-run`,
`--pause SECONDS` between links (default 3, since gofile bans clients that are
quicker), `--config` (another trove config).

Links taken from posts: any link trove can sync as it stands (MEGA, Koofr,
MediaFire, gofile, Yandex and the rest), with or without `https://`, plus gofile ids
written without a full link (`/d/Ab12Cd`, `g0f1le /d/3xYzQ9`, `gf-d-5mNpQr78`, a lone
`/3Lm9Np` on its own line). Shorteners aren't taken, since only following one tells
where it leads.

The exit code is trove's: 0 all synced, 1 something failed, 2 a config problem,
3 the run stopped early (run it again later). A source that can't read its site
exits 1 before trove is involved.

### sharethread

The Share Thread keeps its documents as dated PDFs in one folder. Add that folder to
trove as a permanent site first (by default named `Share Thread`), so `trove sync`
keeps the PDFs. Then:

```bash
trove-sources sharethread               # sync the site; if the Curated Archive is a new edition, report on it
trove-sources sharethread --force       # report on the newest edition even if it was reviewed
trove-sources sharethread --no-fetch    # use the PDFs already synced
trove-sources sharethread --no-follow   # don't walk shorteners; match by link only
```

The PDF's links are written with the hosts disguised (`r3br@nd<dot>ly /Slug`,
`m3g4 /folder/ID#KEY`), so they're read from its text. Each one is matched with
your sites by link, by fallback, and by the share it leads to: shorteners are walked
one request at a time (`--pause`, default 1 second), and the share link itself is
never fetched. The report, `sharethread_DATE.md` beside the trove config (or
`--reports DIR`), lists:
- links not in your sites, split into new in this edition and also in the last one
- shorteners of yours that now lead elsewhere
- dead links
- your sites that left the archive
- lines naming a host that couldn't be read

Drop and upload links are left out. A JSON file with the same name keeps the
links, keys included, for comparing with the next edition. Nothing is added to
your sites; that's yours to do.

An edition counts as reviewed once `sharethread_DATE.md` or a hand-written
`curated_review_DATE.md` is in the reports folder, so a run with nothing new says so
and stops. The exit code is 0 when it reported or had nothing to do, 1 when it
couldn't read the documents, and 2 for a trove config problem.

## Adding a source

Add `src/trove_sources/sources/<name>.py` with:

- `NAME` and `HELP`
- `SourceError`, for a failure worth a plain message
- `add_arguments(parser)`, for the source's own options
- `find_links(args) -> list[FoundLink]`, using `trove_sources.links` to pull links
  out of text, or instead `run(args) -> int` for a source that reports rather than
  syncs (it then gets only its own options and `--config`)

and register it in `sources/__init__.py`. Keep tests offline, with made-up posts.
