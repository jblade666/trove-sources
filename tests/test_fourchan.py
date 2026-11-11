"""The 4chan source, against a fake API. All posts are made up here."""

from __future__ import annotations

import argparse

import pytest
import requests

from trove_sources import cli
from trove_sources.sources import fourchan


class Response:
    def __init__(self, status=200, data=None, text="", content_type="application/json"):
        self.status_code, self.data, self.text = status, data, text
        self.headers = {"Content-Type": content_type}

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeSession(requests.Session):
    def __init__(self, routes):
        super().__init__()
        self.routes, self.calls = routes, []

    def get(self, url, timeout=None):
        path = url.split("/tg/", 1)[1]
        self.calls.append(path)
        answer = self.routes.get(path, Response(404))
        return answer if isinstance(answer, Response) else Response(200, answer)


def op(number, subject, links_to=(), text=""):
    quotes = "".join(f'<a href="/tg/thread/{n}#p{n}" class="quotelink">&gt;&gt;{n}</a><br>' for n in links_to)
    return {"no": number, "sub": subject, "com": quotes + text}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(fourchan.time, "sleep", lambda s: None)


def args(**kw):
    base = dict(thread=None, board="tg", title="pdf share thread", depth=2)
    return argparse.Namespace(**{**base, **kw})


ROUTES = {
    "catalog.json": [{"threads": [{"no": 300, "sub": "PDF Share Thread"}, {"no": 250, "sub": "other general"}]}],
    "thread/300.json": {"posts": [op(300, "PDF Share Thread #3", links_to=(299, 200)),
                                  {"no": 301, "com": "new one gofile.io/d/NEW123"}]},
    "thread/299.json": {"posts": [op(299, "Unrelated general")]},
    "thread/200.json": {"posts": [op(200, "pdf share thread #2"), {"no": 201, "com": "old /d/OLD456 and gofile.io/d/NEW123"}]},
}


def test_walks_back_to_the_previous_thread_and_returns_oldest_first(capsys):
    chan = fourchan.FourChan("tg", "pdf share thread", FakeSession(ROUTES))
    links = fourchan.find_links(args(), chan)
    assert [l.url for l in links] == ["https://gofile.io/d/OLD456", "https://gofile.io/d/NEW123"]
    assert "Skipping linked thread 299" in capsys.readouterr().out


def test_depth_one_reads_only_the_current_thread():
    chan = fourchan.FourChan("tg", "pdf share thread", FakeSession(ROUTES))
    assert [l.url for l in fourchan.find_links(args(depth=1), chan)] == ["https://gofile.io/d/NEW123"]


def test_the_archive_is_searched_when_the_catalog_has_none():
    routes = dict(ROUTES, **{"catalog.json": [{"threads": [{"no": 250, "sub": "other"}]}], "archive.json": [100, 200, 280]})
    routes["thread/280.json"] = {"posts": [op(280, "something else")]}
    chan = fourchan.FourChan("tg", "pdf share thread", FakeSession(routes))
    assert chan.find_current() == 200


def test_an_outage_answer_is_quoted():
    routes = {"catalog.json": Response(429, text="Performing maintenance. We'll be back soon.", content_type="text/plain")}
    chan = fourchan.FourChan("tg", "pdf share thread", FakeSession(routes))
    with pytest.raises(requests.HTTPError, match="maintenance"):
        chan.find_current()


def test_a_thread_number_or_url():
    assert fourchan.parse_thread("https://boards.4chan.org/tg/thread/98169921/pdf-share-thread") == 98169921
    assert fourchan.parse_thread("98169921") == 98169921
    with pytest.raises(fourchan.SourceError):
        fourchan.parse_thread("nope")


def test_the_runner_hands_the_links_to_trove(monkeypatch, capsys):
    from trove.api import RunReport, ShareReport

    handed = {}

    def fake_get(links, **kwargs):
        handed.update(links=links, **kwargs)
        return RunReport("get", 1, False, [ShareReport(links[0], "ok"), ShareReport(links[1], "gone")])

    monkeypatch.setattr(fourchan, "find_links", lambda a: fourchan.links_in_text("d/AAA111 d/BBB222", "post 1"))
    monkeypatch.setattr(cli.api, "get", fake_get)
    assert cli.main(["fourchan", "--dry-run", "-o", "nas:/x"]) == 1
    assert handed["links"] == ["https://gofile.io/d/AAA111", "https://gofile.io/d/BBB222"]
    assert handed["dry_run"] is True and handed["pause"] == cli.PAUSE and handed["output"] == "nas:/x"
    assert "1 gone, 1 ok" in capsys.readouterr().out


def test_list_only_never_calls_trove(monkeypatch):
    monkeypatch.setattr(fourchan, "find_links", lambda a: fourchan.links_in_text("d/AAA111", "post 1"))
    monkeypatch.setattr(cli.api, "get", lambda *a, **k: pytest.fail("called trove"))
    assert cli.main(["fourchan", "--list-only"]) == 0


def test_a_config_error_exits_2(monkeypatch, capsys):
    def bad_config(links, **kwargs):
        raise cli.api.ConfigError("no default_output")

    monkeypatch.setattr(fourchan, "find_links", lambda a: fourchan.links_in_text("d/AAA111", "post 1"))
    monkeypatch.setattr(cli.api, "get", bad_config)
    assert cli.main(["fourchan"]) == 2
    assert "no default_output" in capsys.readouterr().out


def test_help_points_to_each_sources_options(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "trove-sources fourchan --help" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["fourchan", "--help"])
    out = capsys.readouterr().out
    assert "--depth" in out and "examples:" in out
