# CLAUDE.md

Sources of share links for trove (`../trove-downloader`). A source finds links on one
kind of site; everything else goes through `trove.api` (`get`, `recognizes`), which is
trove's stable interface. Don't import trove internals: if a source needs more, add it
to `trove.api` and `docs/helpers.md` in trove first.

- `links.py` is shared: post HTML to text (`<wbr>` removed first), supported links via
  `api.recognizes`, and the strict gofile id matchers. Keep the matchers' anchors; each
  one is there because of a real false positive (see the comments).
- Gofile ids are case-sensitive; dedupe exactly. Shortener slugs aren't
  (`sharethread.link_key`).
- `sharethread` reports and never edits trove's sites list. Its parser was checked
  against a hand-made list of the same edition (all 142 links); keep that check when
  changing it, on a real PDF kept outside the repo.
- Be gentle with the sites read: one request at a time, a pause between calls.
- Tests are offline with made-up posts: `.venv/Scripts/python -m pytest`.
- Links can carry a decryption key in the `#fragment`; never print it (`url.split("#")[0]`).
- This repo may become public: synthetic test data only, no real share links, hosts or paths.
  CI runs a gitleaks secret scan; locally, trove's `scripts/check_private.py` runs as a
  pre-commit hook against the private list kept outside the repo.
