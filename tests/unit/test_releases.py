"""Incorporated-set release-point windows (oracle/releases.py). Label shapes from OLRC's release history."""
import pytest

from ramseyer.oracle import releases


def test_parse_shapes():
    p = releases.parse("116-344not283u1")
    assert (p.congress, p.law, p.excluded, p.reissue) == (116, 344, frozenset({283}), 1)
    p = releases.parse("118-277not255not268")
    assert p.excluded == frozenset({255, 268}) and p.reissue == 0
    assert releases.parse("119-134").excluded == frozenset()
    with pytest.raises(ValueError):
        releases.parse("119-134 (current)")


def test_incorporates():
    rp = releases.parse("116-344not283u1")
    assert rp.incorporates(116, 344) and rp.incorporates(116, 282) and rp.incorporates(115, 999)
    assert not rp.incorporates(116, 283)          # held back, though below the label
    assert not rp.incorporates(116, 345) and not rp.incorporates(117, 1)


def test_a_held_back_law_enters_at_the_full_release():
    labels = ["116-260", "116-344not283", "116-344not283u1", "116-344", "117-2"]
    assert releases.window(labels, "116-283") == ("116-344not283u1", "116-344")
    assert releases.window(labels, "116-344") == ("116-260", "116-344not283")
    assert releases.window(labels, "116-301") == ("116-260", "116-344not283")


def test_a_law_in_a_not_release_enters_there():
    # 119-102not101 holds back 119-101 only; 119-102 is already in it.
    labels = ["119-100", "119-102not101", "119-102", "119-103"]
    assert releases.window(labels, "119-102") == ("119-100", "119-102not101")
    assert releases.window(labels, "119-101") == ("119-102not101", "119-102")


def test_several_held_back_laws():
    labels = ["118-250", "118-277not255not268", "118-277not268", "118-277"]
    assert releases.window(labels, "118-255") == ("118-277not255not268", "118-277not268")
    assert releases.window(labels, "118-268") == ("118-277not268", "118-277")


def test_no_window_before_the_earliest_or_after_the_latest():
    labels = ["119-55", "119-73not60", "119-73"]
    assert releases.window(labels, "119-50") is None          # already in the earliest listed
    assert releases.window(labels, "119-90") is None          # not yet published
    assert releases.window(labels, "119-60") == ("119-73not60", "119-73")


def test_order_follows_publication():
    labels = ["116-344", "116-344not283u1", "116-344not283", "116-300"]
    assert [p.raw for p in sorted(map(releases.parse, labels), key=lambda p: p.order)] == \
        ["116-300", "116-344not283", "116-344not283u1", "116-344"]


def test_entering():
    assert releases.entering("116-344not283u1", "116-344", ["116-283", "116-344", "116-1"]) == ["116-283"]
    assert releases.entering("119-100", "119-102", ["119-101", "119-102", "119-99"]) == ["119-101", "119-102"]
