from trove_sources.links import dedupe, html_to_text, links_in_text

KEY = "k" * 22


def urls(text):
    return [l.url for l in links_in_text(text, "post 1")]


def test_gofile_forms():
    assert urls("grab gofile.io/d/Ab12Cd now") == ["https://gofile.io/d/Ab12Cd"]
    assert urls("g0f1le /d/3xYzQ9") == ["https://gofile.io/d/3xYzQ9"]
    assert urls("d/Gh34Jk") == ["https://gofile.io/d/Gh34Jk"]
    assert urls("gf-d-5mNpQr78") == ["https://gofile.io/d/5mNpQr78"]
    assert urls("This one?\n/3Lm9Np\nthanks") == ["https://gofile.io/d/3Lm9Np"]


def test_gofile_false_positives_stay_out():
    assert urls("read/foobar") == []
    assert urls("https://drive.example.com/file/d/" + "x" * 33 + "/view") == []
    assert urls("https://shop.example/product/564646/some-book") == []
    assert urls("xgf-d-5mNpQr78") == []
    assert urls("odd /abcdefg length") == []  # 7 characters


def test_bare_ids_carry_a_note():
    (link,) = links_in_text("/3Lm9Np", "post 9")
    assert link.note and link.where == "post 9"


def test_other_supported_links_with_and_without_scheme():
    text = f"mega.nz/folder/AbCdEf12#{KEY} and https://app.koofr.net/links/{'0' * 8}-{'1' * 4}-{'2' * 4}-{'3' * 4}-{'4' * 12}."
    assert urls(text) == [f"https://mega.nz/folder/AbCdEf12#{KEY}", f"https://app.koofr.net/links/{'0' * 8}-{'1' * 4}-{'2' * 4}-{'3' * 4}-{'4' * 12}"]


def test_unsupported_links_are_ignored():
    assert urls("https://blog.example/post/1 https://short.example/abc") == []


def test_html_with_word_breaks():
    assert html_to_text("mega.nz/folder/AbCd<wbr>Ef12#k<br>next &amp; more") == "mega.nz/folder/AbCdEf12#k\nnext & more"


def test_dedupe_keeps_the_first_and_matches_gofile_loosely():
    links = links_in_text("gofile.io/d/Ab12Cd", "a") + links_in_text("d/Ab12Cd", "b")
    assert [(l.url, l.where) for l in dedupe(links)] == [("https://gofile.io/d/Ab12Cd", "a")]


def test_gofile_ids_differ_by_case():
    assert len(dedupe(links_in_text("d/AbC123 d/abc123", "a"))) == 2
