"""The Share Thread's Curated Archive, checked against your trove sites.

The Share Thread keeps its documents (the Curated Archive, an Archive, an Annex and a
FAQ) as dated PDFs in one folder, which a trove site syncs. This source syncs that
site, finds the newest Curated Archive, reads its links, and writes a report of what
your sites list is missing. It never edits the sites list and downloads no troves:
you pick from the report and add sites by hand.

The PDF has no clickable links. They're written out with the hosts disguised
("r3br@nd<dot>ly /Slug", "m3g4 /folder/ID#KEY", a title ending "- M3g@" over a bare
"folder/ID#KEY"), so they're read from the text. A line that names a host but can't
be read is listed in the report rather than dropped.

An edition counts as reviewed once a report for it is in the reports folder, either
this source's (sharethread_DATE.md) or a hand-written one (curated_review_DATE.md).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field

from trove import api

NAME = "sharethread"
HELP = "the Share Thread's Curated Archive: report links missing from your trove sites"
EXAMPLES = """examples:
  trove-sources sharethread                  # sync the documents; report if there's a new edition
  trove-sources sharethread --force          # report on the newest edition even if it was reviewed
  trove-sources sharethread --no-fetch       # use the documents already synced
  trove-sources sharethread --site "Other"   # a different site holding the documents
"""

DEFAULT_SITE = "Share Thread"
PAUSE = 1.0  # seconds between shortener walks
EDITION = re.compile(r"^Da Curated Archive (\d{4}-\d{2}-\d{2})\.pdf$", re.I)
REVIEWED = ("sharethread_{date}.md", "curated_review_{date}.md")
PREVIOUS_LINKS = re.compile(r"^(?:sharethread|curated_links)_(\d{4}-\d{2}-\d{2})\.json$")

# Hosts are disguised the way the archive explains: digits and symbols for letters,
# "<dot>" for the period. Decoding follows that rule rather than a list of hosts, so
# any host written this way is read.
_DOT = r"\s*<\s*d[o0]t\s*>\s*"
_LEET = str.maketrans("3@401$", "eaaois")
_DOTTED = re.compile(r"([A-Za-z0-9@$]+)" + _DOT + r"([A-Za-z]{2,4})(?![A-Za-z])", re.I)
# Two hosts are written by name alone, with no domain.
_BARE_NAMES = {"mega": "mega.nz", "mf": "www.mediafire.com"}
_BARE = re.compile(r"(?<![A-Za-z0-9@$])((?i:m3g[a4@])|MF)(?=\s*/)")
_ANY_HOST = re.compile(_DOTTED.pattern + r"|(?<![A-Za-z])((?i:m3g[a4@])|MF)(?![A-Za-z])", re.I)
# The path follows the host, sometimes with one word of the title between them where
# the layout wrapped ("Heart & r3br@nd<dot>ly Spire /laResistance").
_PATH = r"\s*(?:([A-Za-z]+)\s+)?(/[^\s←]+)"
# A title line ending in a disguised MEGA name, with the link's path on the next line.
_MEGA_TITLE = re.compile(r"[-–]\s*m3g[a4@]\s*$", re.I)
_BARE_MEGA_PATH = re.compile(r"^\s*((?:folder|file)/\S+|#F?!\S+)")
_URL = re.compile(r"https?://[^\s<>\"']+")
_DROP = re.compile(r"drop|donat|submi", re.I)


class SourceError(Exception):
    """A failure worth a plain message."""


@dataclass
class ArchiveLink:
    title: str
    url: str  # with any #key; never print it whole
    drop: bool = False  # an upload or donation link, not a trove
    line: int = 0

    @property
    def key(self) -> str:
        return link_key(self.url)


@dataclass
class Archive:
    links: list[ArchiveLink] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)  # lines naming a host that couldn't be read


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--site", default=DEFAULT_SITE,
                        help=f"The trove site holding the documents (default: {DEFAULT_SITE!r})")
    parser.add_argument("--reports", metavar="DIR", help="Where reports go (default: beside the trove config)")
    parser.add_argument("--force", action="store_true", help="Report on the newest edition even if it was reviewed")
    parser.add_argument("--no-fetch", action="store_true", help="Don't sync the site first; use what's there")
    parser.add_argument("--no-follow", action="store_true",
                        help="Don't walk shorteners; match links to sites by the link alone")
    parser.add_argument("--pause", type=float, default=PAUSE, help=f"Seconds between shortener walks (default: {PAUSE:g})")


def safe(url: str | None) -> str:
    """A link fit to print: without its #key. An old MEGA link keeps its folder id
    there (#F!ID!KEY), so that much stays."""
    url = url or ""
    old_mega = re.match(r"([^#]*#F?!)([^!]*)", url)
    return old_mega.group(1) + old_mega.group(2) if old_mega else url.split("#", 1)[0]


def link_key(url: str) -> str:
    """What makes two written links the same: a share link trove recognizes is
    compared as written, key included; anything else (a shortener) ignores the case
    of its slug and a trailing slash."""
    m = re.match(r"(?:https?://)?(?:www\.)?([^/#?]+)(.*)", url.strip())
    host, rest = (m.group(1).lower(), m.group(2)) if m else ("", url)
    if not api.recognizes(url if "://" in url else "https://" + url):
        return host + rest.split("#", 1)[0].rstrip("/").lower()
    return host + rest


def _hosts_in(line: str) -> list[tuple[int, int, str]]:
    """``(start, end, host)`` for each disguised host in a line."""
    out = []
    for m in _DOTTED.finditer(line):
        name, start = m.group(1), m.start(1)
        cut = name.find("$", 1)  # "products$plit<dot>to": "$" starts the host's name
        if cut > 0:
            name, start = name[cut:], start + cut
        out.append((start, m.end(), f"{name.translate(_LEET).lower()}.{m.group(2).lower()}"))
    for m in _BARE.finditer(line):
        out.append((m.start(), m.end(), _BARE_NAMES[m.group(1).translate(_LEET).lower()]))
    return out


# Reading the archive


def pdf_text(data: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)


def _is_heading(line: str) -> bool:
    text = line.strip()
    return bool(text) and not text.startswith(("←", "- ")) and not re.fullmatch(r"[-\s]+", text)


def _drop(line: str, after: int, url: str) -> bool:
    return "←" in line[after:] or bool(_DROP.search(url.rsplit("/", 1)[-1]))


def read_archive(text: str) -> Archive:
    """The links in the archive's text, in order, without repeats, each with the
    heading it's under."""
    archive, seen = Archive(), set()
    title = ""
    lines = text.splitlines()

    def add(link: ArchiveLink) -> None:
        if link.key not in seen:
            seen.add(link.key)
            archive.links.append(link)

    for number, line in enumerate(lines, 1):
        found = []
        title_tail = ""
        for host_start, host_end, host in _hosts_in(line):
            path = re.match(_PATH, line[host_end:])
            if path:
                found.append((host_start, host_end + path.end(), f"https://{host}{path.group(2)}"))
                if path.group(1):  # the title's last word, wrapped past the host
                    title_tail = path.group(1)
        for match in _URL.finditer(line):
            url = match.group(0).rstrip(".,;:!?)")
            if api.recognizes(url) and not any(start <= match.start() < end for start, end, _ in found):
                found.append((match.start(), match.end(), url))
        bare = _BARE_MEGA_PATH.match(line)
        if not found and bare and number > 1 and _MEGA_TITLE.search(lines[number - 2]):
            found.append((bare.start(1), bare.end(1), "https://mega.nz/" + bare.group(1)))
        if found:
            found.sort()
            start = found[0][0]
            before = line[:start].strip()
            # Text before a link titles it only when it reads like a heading: separated
            # from the link, capitalized, more than a stray letter. Layout leftovers
            # ("products$plit...", "tables) m3g4 ...", a stray "r") don't.
            if (len(before) > 2 and line[start - 1].isspace() and before[0].isupper() and _is_heading(before)):
                title = f"{before} {title_tail}".strip()
            for _start, end, url in found:
                add(ArchiveLink(title, url, _drop(line, end, url), number))
            continue
        if _MEGA_TITLE.search(line):
            title = line.strip()
            continue
        host = _ANY_HOST.search(line)
        if host and "/" in line[host.end():]:  # prose naming a host has no path after it
            archive.unread.append(line.strip())
            continue
        if _is_heading(line):
            title = line.strip()
    return archive


# Comparing with the sites


@dataclass
class Finding:
    link: ArchiveLink
    status: str  # have, moved, new, dead
    site: str | None = None
    provider: str | None = None
    final: str | None = None
    error: str | None = None
    note: str = ""


def _site_index(sites: list[api.SiteInfo]):
    by_link, by_identity = {}, {}
    for site in sites:
        for url in (site.url, *site.fallback):
            by_link.setdefault(link_key(url), site)
            info = api.identify(url, follow=False)
            if info.identity:
                by_identity.setdefault(info.identity, site)
        if site.identity:
            by_identity.setdefault(site.identity, site)
    return by_link, by_identity


def compare(archive: Archive, sites: list[api.SiteInfo], follow: bool = True, pause: float = PAUSE,
            progress=print) -> list[Finding]:
    by_link, by_identity = _site_index(sites)
    findings = []
    walks = 0
    for link in (l for l in archive.links if not l.drop):
        site = by_link.get(link.key)
        walk = follow and not api.recognizes(link.url)
        if walk:
            if walks and pause:
                time.sleep(pause)
            walks += 1
            progress(f"  {safe(link.url)}")
        info = api.identify(link.url, follow=walk)
        finding = Finding(link, "new", provider=info.provider, final=info.final, error=info.error)
        if not walk and not api.recognizes(link.url):
            finding.error = None  # not followed, so nothing is known about it
        if info.error and "upload link" in info.error:
            # A MEGA upload link takes files and lists none: a drop without its arrow.
            link.drop = True
            continue
        if site is None and info.identity:
            site = by_identity.get(info.identity)
            if site:
                finding.note = "under another link"
        if site:
            finding.status, finding.site = "have", site.name
            if not site.enabled:
                finding.note = ", ".join(filter(None, [finding.note, "disabled"]))
            # A site reading its link from a document leads to the document, never to
            # the share it last synced, so only the others can have moved.
            if info.identity and site.identity and info.identity != site.identity and not site.link_in_document:
                finding.status = "moved"
        elif finding.error:
            finding.status = "dead"
        findings.append(finding)
    return findings


# Editions and reports


def editions(names: list[str]) -> dict[str, str]:
    """Curated Archive file names by date."""
    return {m.group(1): name for name in names if (m := EDITION.match(name))}


def is_reviewed(folder: str, date: str) -> str | None:
    for pattern in REVIEWED:
        path = os.path.join(folder, pattern.format(date=date))
        if os.path.exists(path):
            return path
    return None


def previous_links(folder: str, before: str) -> tuple[str | None, set[str]]:
    """The links of the newest earlier edition with a saved link list."""
    dated = sorted((m.group(1), name) for name in os.listdir(folder) if (m := PREVIOUS_LINKS.match(name))
                   and m.group(1) < before)
    if not dated:
        return None, set()
    date, name = dated[-1]
    with open(os.path.join(folder, name), encoding="utf-8") as fp:
        data = json.load(fp)
    entries = data.get("links", []) if isinstance(data, dict) else data
    return date, {link_key(e["url"]) for e in entries if isinstance(e, dict) and e.get("url")}


def _row(*cells: str) -> str:
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"


def write_report(path: str, date: str, findings: list[Finding], archive: Archive, prev_date: str | None,
                 prev_keys: set[str], gone_sites: list[str], sites_count: int) -> None:
    today = datetime.date.today().isoformat()
    groups = {s: [f for f in findings if f.status == s] for s in ("new", "moved", "dead", "have")}
    out = [f"# Share Thread: Curated Archive {date}", "",
           f"Checked {today} against {sites_count} sites. "
           + (f"Compared with the {prev_date} edition." if prev_date else "No earlier edition's links to compare with."),
           "", f"{len(findings)} trove links: {len(groups['new'])} new, {len(groups['moved'])} moved, "
           f"{len(groups['dead'])} dead, {len(groups['have'])} already in your sites. "
           f"{sum(l.drop for l in archive.links)} drop links left out.", ""]

    def leads(f: Finding) -> str:
        if f.final and safe(f.final) != safe(f.link.url):
            return f"{f.provider}: {safe(f.final)}"
        return f.provider or ""

    new = groups["new"]
    fresh = [f for f in new if prev_date and f.link.key not in prev_keys]
    for heading, rows in ((f"## New in this edition ({len(fresh)})", fresh),
                          (f"## Not in your sites ({len(new) - len(fresh)})" + (f", also in {prev_date}" if prev_date else ""),
                           [f for f in new if f not in fresh])):
        if not rows and heading.startswith("## New in") and not prev_date:
            continue
        out += [heading, ""]
        if rows:
            out += [_row("Title", "Link", "Leads to"), _row("---", "---", "---")]
            out += [_row(f.link.title, safe(f.link.url), leads(f)) for f in rows]
        else:
            out.append("None.")
        out.append("")
    if groups["moved"]:
        out += [f"## Moved ({len(groups['moved'])})", "",
                "The link is one of your sites', but now leads to a different share than the site last synced.", "",
                _row("Site", "Link", "Now leads to"), _row("---", "---", "---")]
        out += [_row(f.site or "", safe(f.link.url), leads(f)) for f in groups["moved"]] + [""]
    if groups["dead"]:
        out += [f"## Dead ({len(groups['dead'])})", "", _row("Title", "Link", "Why"), _row("---", "---", "---")]
        out += [_row(f.link.title, safe(f.link.url), f.error or "") for f in groups["dead"]] + [""]
    if gone_sites:
        out += [f"## Your sites no longer in the archive ({len(gone_sites)})", ""]
        out += [f"- {name}" for name in gone_sites] + [""]
    if archive.unread:
        out += [f"## Lines that couldn't be read ({len(archive.unread)})", "",
                "They name a host, but no link could be made from them. Check them in the PDF.", ""]
        out += [f"- `{safe(line)}`" for line in archive.unread] + [""]
    out += [f"## Already in your sites ({len(groups['have'])})", ""]
    out += [f"- {f.link.title} ({safe(f.link.url)}): {f.site}" + (f", {f.note}" if f.note else "")
            for f in groups["have"]] + [""]
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(out))


def run(args) -> int:
    sites = api.sites(config=args.config)
    site = next((s for s in sites if s.name.lower() == args.site.lower()), None)
    if site is None:
        raise SourceError(f"No trove site is named {args.site!r}. Add the Share Thread folder to sites.yaml first.")
    reports = args.reports or os.path.dirname(api.config_path(args.config))
    os.makedirs(reports, exist_ok=True)

    if not args.no_fetch:
        print(f"Syncing {site.name}...")
        report = api.sync([site.name], config=args.config, quiet=True)
        if report.exit_code == 4:
            print("  Another trove sync is running; using the documents already there.")
        else:
            for share in report.shares:
                print(f"  {share.status}: {share.downloaded} downloaded, {share.skipped} already there"
                      + (f" ({share.error})" if share.error else ""))
            sites = api.sites(config=args.config)
            site = next(s for s in sites if s.name == site.name)

    folder = site.output or site.dest
    if not folder:
        raise SourceError(f"{site.name} hasn't synced yet, so its folder isn't known. Run: trove sync \"{site.name}\"")
    with api.open_folder(folder, config=args.config) as docs:
        found = editions([f.name for f in docs.files()])
        if not found:
            raise SourceError(f"No 'Da Curated Archive DATE.pdf' in {safe(folder)}.")
        date = max(found)
        reviewed = is_reviewed(reports, date)
        print(f"Newest Curated Archive: {date}")
        if reviewed and not args.force:
            print(f"  Already reviewed ({os.path.basename(reviewed)}). Nothing to do; --force reviews it again.")
            return 0
        data = docs.read(found[date])

    archive = read_archive(pdf_text(data))
    troves = [l for l in archive.links if not l.drop]
    print(f"  {len(troves)} trove links, {len(archive.links) - len(troves)} drop links, "
          f"{len(archive.unread)} line(s) unreadable")
    print("Following shorteners..." if not args.no_follow else "Matching links (shorteners not followed)...")
    findings = compare(archive, sites, follow=not args.no_follow, pause=args.pause)

    prev_date, prev_keys = previous_links(reports, date)
    current = {l.key for l in archive.links}
    by_link = {link_key(u): s.name for s in sites for u in (s.url, *s.fallback)}
    gone_sites = sorted({by_link[k] for k in prev_keys - current if k in by_link})

    base = os.path.join(reports, f"sharethread_{date}")
    write_report(base + ".md", date, findings, archive, prev_date, prev_keys, gone_sites, len(sites))
    with open(base + ".json", "w", encoding="utf-8") as fp:
        json.dump({"edition": date, "checked": datetime.date.today().isoformat(),
                   "links": [{**asdict(f.link), "status": f.status, "site": f.site, "provider": f.provider,
                              "final": f.final, "error": f.error} for f in findings]
                            + [{**asdict(l), "status": "drop"} for l in archive.links if l.drop],
                   "unread": archive.unread}, fp, indent=1, ensure_ascii=False)

    counts = {s: sum(f.status == s for f in findings) for s in ("new", "moved", "dead", "have")}
    print(f"\n{counts['new']} new, {counts['moved']} moved, {counts['dead']} dead, {counts['have']} already in your sites.")
    print(f"Report: {base}.md")
    return 0
