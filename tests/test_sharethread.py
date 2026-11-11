"""The Share Thread source, on made-up archive text."""

from __future__ import annotations

import json

import pytest

from trove import api
from trove_sources.sources import sharethread as st

KEY = "Q" * 22
ARCHIVE = f"""Some links are cAsE sEnSeTiVe, m3g@ is Mega, <d0t> is a period
Using indirect links like sh0rtl1nk<dot>test, $plit<dot>to, has an advantage
-Alpha, Beta - M3g@
folder/AbCdEfGh#{KEY}
Gamma Games
sh0rtl1nk<dot>test /GammaTrove
sh0rtl1nk<dot>test /GammaDrop ←(for drops)
The Big Collection
- one thing
- another thing
r sh0rtl1nk<dot>test /BigOne
sh0rtl1nk<dot>test/BigTwo
Delta - older editions
m3g4 /folder/ZyXwVuTs#{KEY}
Old Style
m3g4 /#F!OldIdAb!{KEY}
Epsilon - with other
products$plit<dot>to /Epsilon
sh0rtl1nk<dot>test /Epsilon
Zeta & sh0rtl1nk<dot>test Eta /ZetaEta
Theta
MF /folder/abc123def/Theta_Trove
Iota
G0f1le<dot>io /d/Ab12Cd
Kappa
m3g@ <dOT> nz /folder/KkKkKkKk#{KEY}
Lambda (lists,
tables) m3g4 /folder/LlLlLlLl#{KEY}
Broken sh0rtl1nk<dot>test two words /Nope
Gamma Games again
sh0rtl1nk<dot>test /gammatrove
"""


def links(text=ARCHIVE):
    return st.read_archive(text)


def test_every_disguise_becomes_a_link():
    urls = [st.safe(l.url) for l in links().links]
    assert urls == [
        "https://mega.nz/folder/AbCdEfGh",
        "https://shortlink.test/GammaTrove",
        "https://shortlink.test/GammaDrop",
        "https://shortlink.test/BigOne",
        "https://shortlink.test/BigTwo",
        "https://mega.nz/folder/ZyXwVuTs",
        "https://mega.nz/#F!OldIdAb",
        "https://split.to/Epsilon",
        "https://shortlink.test/Epsilon",
        "https://shortlink.test/ZetaEta",
        "https://www.mediafire.com/folder/abc123def/Theta_Trove",
        "https://gofile.io/d/Ab12Cd",
        "https://mega.nz/folder/KkKkKkKk",
        "https://mega.nz/folder/LlLlLlLl",
    ]


def test_keys_are_kept_but_never_printed():
    first = links().links[0]
    assert first.url.endswith("#" + KEY) and KEY not in st.safe(first.url)
    assert KEY not in st.safe(f"https://mega.nz/#F!OldIdAb!{KEY}")


def test_titles_come_from_the_heading_above():
    titles = {st.safe(l.url).rsplit("/", 1)[-1]: l.title for l in links().links}
    assert titles["AbCdEfGh"] == "-Alpha, Beta - M3g@"
    assert titles["GammaTrove"] == "Gamma Games"
    assert titles["BigOne"] == "The Big Collection"  # not the bullets, nor the stray "r"
    assert titles["Epsilon"] == "Epsilon - with other"  # not "products"
    assert titles["ZetaEta"] == "Zeta & Eta"  # the title wrapped around the host
    assert titles["LlLlLlLl"] == "Lambda (lists,"  # not the wrapped "tables)"


def test_drops_are_marked():
    drops = [st.safe(l.url) for l in links().links if l.drop]
    assert drops == ["https://shortlink.test/GammaDrop"]


def test_a_shortener_repeated_in_another_case_is_one_link():
    assert sum("gammatrove" in l.url.lower() for l in links().links) == 1


def test_a_line_naming_a_host_that_cant_be_read_is_kept_but_prose_is_not():
    assert links().unread == ["Broken sh0rtl1nk<dot>test two words /Nope"]


def test_link_keys():
    assert st.link_key("https://shortlink.test/Foo/") == st.link_key("shortlink.test/foo")
    assert st.link_key("https://mega.nz/folder/AbC#k") != st.link_key("https://mega.nz/folder/abc#k")


def test_editions_and_review_markers(tmp_path):
    names = ["Da Annex 2024-11-01.pdf", "Da Curated Archive 2026-08-28.pdf", "Da Curated Archive 2027-01-02.pdf"]
    assert max(st.editions(names)) == "2027-01-02"
    assert st.is_reviewed(str(tmp_path), "2026-08-28") is None
    (tmp_path / "curated_review_2026-08-28.md").write_text("by hand", encoding="utf-8")
    assert st.is_reviewed(str(tmp_path), "2026-08-28")


def test_previous_links_reads_both_formats(tmp_path):
    (tmp_path / "curated_links_2026-08-28.json").write_text(json.dumps([{"url": "https://shortlink.test/Old"}]))
    (tmp_path / "sharethread_2027-01-02.json").write_text(json.dumps({"links": [{"url": "https://shortlink.test/New"}]}))
    assert st.previous_links(str(tmp_path), "2027-01-02") == ("2026-08-28", {"shortlink.test/old"})
    assert st.previous_links(str(tmp_path), "2027-06-01") == ("2027-01-02", {"shortlink.test/new"})


def site(name, url, fallback=(), identity=None, enabled=True):
    return api.SiteInfo(name, url, tuple(fallback), enabled, None, identity, None, None)


def test_compare_sorts_links_into_have_moved_new_and_dead(monkeypatch):
    mega = f"https://mega.nz/folder/AbCdEfGh#{KEY}"
    targets = {
        "https://shortlink.test/Have": api.LinkInfo("x", "https://x.example/s/have", "allsync", "allsync:have"),
        "https://shortlink.test/Moved": api.LinkInfo("x", "https://x.example/s/new", "allsync", "allsync:new"),
        "https://shortlink.test/Fresh": api.LinkInfo("x", "https://x.example/s/fresh", "allsync", "allsync:fresh"),
        "https://shortlink.test/Dead": api.LinkInfo("x", error="shortlink.test answered HTTP 404 instead of redirecting"),
        "https://shortlink.test/Other": api.LinkInfo("x", "https://x.example/s/direct", "allsync", "allsync:direct"),
        "https://shortlink.test/Landing": api.LinkInfo("x", "https://mega.nz/file/Doc", "mega", "mega:doc"),
        "https://shortlink.test/Upload": api.LinkInfo("x", "https://mega.nz/filerequest/U", error="This is a MEGA upload link"),
        mega: api.LinkInfo(mega, mega, "mega", "mega:AbCdEfGh"),
    }
    calls = []

    def identify(url, follow=True):
        calls.append((url, follow))
        return targets.get(url) or api.LinkInfo(url, url, "allsync", "allsync:" + url.rsplit("/", 1)[-1])

    monkeypatch.setattr(st.api, "identify", identify)
    archive = st.Archive([st.ArchiveLink("T", u) for u in targets] + [st.ArchiveLink("D", "https://shortlink.test/aDrop", drop=True)])
    sites = [
        site("Have", "https://shortlink.test/have", identity="allsync:have"),
        site("Moved", "https://shortlink.test/Moved", identity="allsync:old"),
        site("Direct", "https://x.example/s/direct", enabled=False),
        site("Mega", "https://shortlink.test/MegaSlug", identity="mega:AbCdEfGh"),
        api.SiteInfo("Landing", "https://shortlink.test/Landing", (), True, None, "koofr:inner", None, None,
                     link_in_document=("k.example",)),
    ]
    found = {f.link.url.split("#")[0].rsplit("/", 1)[-1]: f for f in st.compare(archive, sites, pause=0, progress=lambda *_: None)}
    assert {k: f.status for k, f in found.items()} == {
        "Have": "have", "Moved": "moved", "Fresh": "new", "Dead": "dead", "Other": "have", "AbCdEfGh": "have",
        "Landing": "have"}  # its shortener leads to its document, which isn't a move
    assert next(l for l in archive.links if l.url.endswith("Upload")).drop  # an upload link is a drop
    assert (found["Other"].site, found["Other"].note) == ("Direct", "under another link, disabled")
    assert found["AbCdEfGh"].site == "Mega"
    assert not any("aDrop" in url for url, _ in calls)  # drops aren't followed


def test_without_following_shorteners_only_links_match(monkeypatch):
    monkeypatch.setattr(st.api, "identify", lambda url, follow=True: api.LinkInfo(url, error=None if follow else "not followed"))
    archive = st.Archive([st.ArchiveLink("T", "https://shortlink.test/Have"), st.ArchiveLink("T", "https://shortlink.test/Fresh")])
    found = st.compare(archive, [site("Have", "https://shortlink.test/Have")], follow=False, pause=0, progress=lambda *_: None)
    assert [(f.status, f.error) for f in found] == [("have", None), ("new", None)]


def test_the_report_lists_new_links_without_keys(tmp_path):
    mega = f"https://mega.nz/folder/AbCdEfGh#{KEY}"
    archive = st.Archive([st.ArchiveLink("Fresh", mega), st.ArchiveLink("Kept", "https://shortlink.test/Kept")],
                         unread=["Broken sh0rtl1nk<dot>test two words /Nope"])
    findings = [st.Finding(archive.links[0], "new", provider="mega", final=mega),
                st.Finding(archive.links[1], "new", provider="allsync", final="https://x.example/s/k")]
    path = tmp_path / "report.md"
    st.write_report(str(path), "2027-01-02", findings, archive, "2026-08-28", {"shortlink.test/kept"}, ["Gone Site"], 3)
    text = path.read_text(encoding="utf-8")
    assert KEY not in text
    assert "## New in this edition (1)" in text and "| Fresh | https://mega.nz/folder/AbCdEfGh | mega |" in text
    assert "## Not in your sites (1), also in 2026-08-28" in text and "allsync: https://x.example/s/k" in text
    assert "- Gone Site" in text and "two words /Nope" in text


def test_run_stops_when_the_edition_was_reviewed(tmp_path, monkeypatch, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "Da Curated Archive 2026-08-28.pdf").write_bytes(b"%PDF")
    (tmp_path / "curated_review_2026-08-28.md").write_text("done", encoding="utf-8")
    monkeypatch.setattr(st.api, "sites", lambda config=None: [
        api.SiteInfo("Share Thread", "https://short.example/x", (), True, "mediafire", None, None, None, str(docs))])
    args = st.argparse.Namespace(site="share thread", reports=str(tmp_path), force=False, no_fetch=True,
                                 no_follow=False, pause=0, config=None)
    assert st.run(args) == 0
    assert "Already reviewed (curated_review_2026-08-28.md)" in capsys.readouterr().out


def test_run_needs_the_site(monkeypatch):
    monkeypatch.setattr(st.api, "sites", lambda config=None: [])
    args = st.argparse.Namespace(site="Share Thread", reports=None, config=None)
    with pytest.raises(st.SourceError, match="No trove site is named"):
        st.run(args)
