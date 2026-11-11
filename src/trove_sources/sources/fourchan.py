"""A recurring 4chan thread: find the current one by its subject, follow its
"previous thread" links back, and collect every share link posted.

Defaults to /tg/'s PDF Share Thread; ``--board`` and ``--title`` pick another
general. Uses 4chan's read-only JSON API (a.4cdn.org).

* Between threads (the old one archived, the next not posted yet) the catalog has no
  match, so the archive is scanned newest-first. On a busy board the gap can be 30+
  threads, hence a deep scan; it stops at the first match.
* An OP often links several threads (related generals, resources), so each linked
  thread is fetched and the first whose subject matches is taken as the previous one.
* 4chan answers a site-wide outage with HTTP 429, the same as real throttling. Only
  the body tells them apart, so it's quoted in the error.
* Threads are walked newest first but their links are returned oldest first, so
  downloads run in the order things were posted.
"""

from __future__ import annotations

import argparse
import html
import re
import time

import requests

from trove_sources.links import FoundLink, dedupe, html_to_text, links_in_text

NAME = "fourchan"
HELP = "a recurring 4chan thread, by board and subject (default: /tg/'s PDF Share Thread)"
EXAMPLES = """examples:
  trove-sources fourchan                     find the current thread, read it and the previous one, sync every link
  trove-sources fourchan --depth 1           the current thread only
  trove-sources fourchan --depth 4           follow previous-thread links 3 times
  trove-sources fourchan 98169921            start from a given thread (a number or URL)
  trove-sources fourchan --list-only         just list the links found; contacts no file host
  trove-sources fourchan --dry-run           list each share through trove, download nothing
  trove-sources fourchan --board xx --title "some general"
"""
API = "https://a.4cdn.org"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ARCHIVE_SCAN_LIMIT = 150
MAX_ERROR_BODY = 200
COURTESY = 1.0  # seconds between 4chan API calls


class SourceError(Exception):
    pass


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("thread", nargs="?", help="Thread URL or number (default: find the newest by subject)")
    parser.add_argument("--board", default="tg", help="Board (default: tg)")
    parser.add_argument("--title", default="pdf share thread",
                        help="Text the thread's subject contains (default: 'pdf share thread')")
    parser.add_argument("--depth", type=int, default=2,
                        help="How many threads to read, following previous-thread links (default: 2)")


def _error_body(response: requests.Response) -> str:
    try:
        text = response.text or ""
    except Exception:
        return ""
    if "html" in response.headers.get("Content-Type", "").lower():
        text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = " ".join(text.split())
    if len(text) > MAX_ERROR_BODY:
        text = text[:MAX_ERROR_BODY].rstrip() + "..."
    return text.encode("ascii", "replace").decode("ascii")


class FourChan:
    def __init__(self, board: str, title: str, session: requests.Session | None = None):
        self.board, self.title = board, title.lower()
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _json(self, path: str):
        response = self.session.get(f"{API}/{self.board}/{path}", timeout=30)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            detail = _error_body(response)
            if not detail:
                raise
            raise requests.HTTPError(f"{e}; the server said: {detail}", response=response) from None
        return response.json()

    def thread(self, number: int) -> list[dict]:
        """A thread's posts, or [] if it's gone."""
        try:
            return self._json(f"thread/{number}.json").get("posts", [])
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return []
            raise

    def _subject(self, posts: list[dict]) -> str:
        return html.unescape(posts[0].get("sub", "")) if posts else ""

    def find_current(self) -> int:
        matches = [
            t["no"]
            for page in self._json("catalog.json")
            for t in page.get("threads", [])
            if self.title in html.unescape(t.get("sub", "")).lower()
        ]
        if matches:
            return max(matches)  # the newest has the highest number
        candidates = list(reversed(self._json("archive.json")))[:ARCHIVE_SCAN_LIMIT]
        print(f"Not in the catalog; scanning up to {len(candidates)} archived threads, newest first...")
        for i, number in enumerate(candidates, 1):
            try:
                posts = self.thread(number)
            except requests.RequestException:
                continue
            if self.title in self._subject(posts).lower():
                print(f"  Found it in the archive, {i} back.")
                return number
            time.sleep(COURTESY)
        raise SourceError(f"No thread titled like {self.title!r} in /{self.board}/'s catalog or recent archive.")

    def linked_threads(self, posts: list[dict]) -> list[int]:
        """Threads the OP links to, in order."""
        out: list[int] = []
        for match in re.finditer(rf'href="/{re.escape(self.board)}/thread/(\d+)', posts[0].get("com", "") if posts else ""):
            number = int(match.group(1))
            if number not in out:
                out.append(number)
        return out

    def previous(self, posts: list[dict], visited: set[int]) -> tuple[int, list[dict]] | None:
        for candidate in self.linked_threads(posts):
            if candidate in visited:
                continue
            try:
                candidate_posts = self.thread(candidate)
            except requests.RequestException as e:
                print(f"4chan API error on linked thread {candidate}: {e}")
                return None
            if self.title in self._subject(candidate_posts).lower():
                return candidate, candidate_posts
            if candidate_posts:
                print(f"  Skipping linked thread {candidate} ({self._subject(candidate_posts) or 'no subject'!r}).")
            time.sleep(COURTESY)
        return None


def parse_thread(value: str) -> int:
    match = re.search(r"/thread/(\d+)", value)
    if match:
        return int(match.group(1))
    if value.isdigit():
        return int(value)
    raise SourceError(f"Not a thread URL or number: {value}")


def find_links(args, chan: FourChan | None = None) -> list[FoundLink]:
    chan = chan or FourChan(args.board, args.title)
    if args.thread:
        number = parse_thread(args.thread)
    else:
        print(f"Looking for the newest /{args.board}/ thread titled like {args.title!r}...")
        number = chan.find_current()
    print(f"Starting thread: https://boards.4chan.org/{args.board}/thread/{number}")

    collected: list[FoundLink] = []
    visited: set[int] = set()
    posts = None
    for step in range(max(1, args.depth)):
        visited.add(number)
        if posts is None:
            try:
                posts = chan.thread(number)
            except requests.RequestException as e:
                print(f"4chan API error on thread {number}: {e}; keeping what was found so far.")
                break
        if not posts:
            print(f"Thread {number} is gone.")
            break
        found = []
        for post in posts:
            if post.get("com"):
                found += links_in_text(html_to_text(post["com"]), f"post {post['no']} in thread {number}")
        before = len(dedupe(collected))
        collected = found + collected  # older threads first
        print(f"Thread {number}: {len(posts)} posts, {len(found)} links ({len(dedupe(collected)) - before} new)")
        if step == args.depth - 1:
            break
        time.sleep(COURTESY)
        previous = chan.previous(posts, visited)
        if previous is None:
            print("No previous thread linked from the OP.")
            break
        number, posts = previous
    return dedupe(collected)
