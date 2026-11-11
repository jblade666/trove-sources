"""Pulling share links out of post text, for any source.

Two kinds are taken:

* Any URL, with or without its scheme, that trove can sync as it stands
  (``trove.api.recognizes``): MEGA, Koofr, MediaFire, gofile and so on. Links to
  anything else are ignored.
* gofile ids written without a full link, the way people dodge link filters:
  ``/d/Ab12Cd``, ``d/Gh34Jk``, ``g0f1le /d/3xYzQ9``, ``gf-d-5mNpQr78``, or a lone
  ``/3Lm9Np`` on its own line. These matchers are deliberately strict; see below.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from trove import api

# gofile ids are letters and digits: 6 long historically, 8 since about 2026. Only
# those two lengths, never a range: "6 or more" would swallow other services' long
# ids and bring back the false positives the anchors below exist to prevent.
ID_CHARS = r"(?:[A-Za-z0-9]{8}|[A-Za-z0-9]{6})"

# The d/ form: gofile.io/d/Ab12Cd, /d/Ab12Cd, "g0f1le /d/3xYzQ9", and "d/Gh34Jk"
# without its slash. "d/" must follow whitespace, a slash or the start, so a word
# ending in d ("read/foobar") can't match, and the id can't run on (which rejects
# Google Drive's 33-character /d/ ids and odd lengths alike).
GOFILE_DFORM = re.compile(r"(?:^|(?<=[\s/]))d/\s*(" + ID_CHARS + r")(?![A-Za-z0-9])")

# A lone "/XXXXXX" with no d/, trusted only when bounded by whitespace or line ends on
# both sides. Without that, every path segment in an ordinary URL would look like an
# id; with it, "This one?\n/3Lm9Np" still matches.
GOFILE_BARE = re.compile(r"(?:^|(?<=\s))/(" + ID_CHARS + r")(?=\s|$)", re.MULTILINE)

# "gf-d-5mNpQr78": hyphens standing in for the slashes, bounded on both sides.
GOFILE_HYPHEN = re.compile(r"(?<![A-Za-z0-9])(?i:gf)-(?i:d)-(" + ID_CHARS + r")(?![A-Za-z0-9])")

# Anything that looks like a link, with or without a scheme. What it really is gets
# decided by trove.api.recognizes, so this can be generous.
URLISH = re.compile(r"(?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::\d+)?/[^\s<>\"']+")
TRAILING = ".,;:!?)]}>'\""


@dataclass
class FoundLink:
    url: str
    where: str  # where it was found, for the report, e.g. "post 98671658"
    note: str = ""  # set when a looser matcher accepted it, worth a look


def html_to_text(fragment: str) -> str:
    """Post HTML to plain text. Some boards break long words with <wbr>, which
    would split a link or an id, so those go first."""
    text = fragment.replace("<wbr>", "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def links_in_text(text: str, where: str) -> list[FoundLink]:
    """Supported links and gofile ids in one piece of text, in the order they
    appear, without repeats."""
    hits: list[tuple[int, str, str]] = []  # (position, url, note)
    for match in URLISH.finditer(text):
        url = match.group(0).rstrip(TRAILING)
        candidate = url if "://" in url else "https://" + url
        if api.recognizes(candidate):
            hits.append((match.start(), candidate, ""))
    for match in [*GOFILE_DFORM.finditer(text), *GOFILE_HYPHEN.finditer(text)]:
        hits.append((match.start(), f"https://gofile.io/d/{match.group(1)}", ""))
    for match in GOFILE_BARE.finditer(text):
        hits.append((match.start(), f"https://gofile.io/d/{match.group(1)}", "a bare /id with no d/ prefix"))
    hits.sort(key=lambda hit: (hit[0], hit[2] != ""))
    return dedupe([FoundLink(url, where, note) for _pos, url, note in hits])


def dedupe(links: list[FoundLink]) -> list[FoundLink]:
    """The first of each link across many texts, in order."""
    seen: set[str] = set()
    out = []
    for link in links:
        key = link.url.split("#", 1)[0].rstrip("/") if "gofile.io" in link.url else link.url
        if key not in seen:
            seen.add(key)
            out.append(link)
    return out
