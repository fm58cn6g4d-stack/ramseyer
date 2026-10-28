"""Each grammar pattern against its harvested examples (tests/parse/patterns/P*.json, from enacted laws)."""
import json
from pathlib import Path

import pytest

from billmap.parse import parse_text
from billmap.parse.grammar import Ctx, apply_head, lift_quotes
from billmap.parse.segment import walk

PATTERNS = sorted((Path(__file__).parents[1] / "parse" / "patterns").glob("P*.json"))


def last_unit(result):
    nodes = [n for n in walk(result.nodes) if n.text and n.cls != "TABLE_OF_CONTENTS"]
    return nodes[-1]


def check(example, expect):
    result = parse_text("\n".join(example["lines"]) + "\n")
    node = last_unit(result)
    here = [i for i in result.instructions if i.bill_loc == node.loc]
    facts = {
        "op": {i.op for i in here},
        "occurrence": {i.occurrence for i in here},
        "freestanding_type": {node.freestanding_type},
        "cls": node.cls,
    }
    if "target_kind" in expect:
        ctx = Ctx()
        apply_head(lift_quotes(node.text)[0], ctx)
        facts["target_kind"] = {ctx.target.kind} if node.cls == "AMENDATORY" else set()
    return {k: (v in facts[k]) for k, v in expect.items()}, facts


def cases():
    for path in PATTERNS:
        data = json.loads(path.read_text())
        for i, ex in enumerate(data["positive"]):
            yield pytest.param(ex, True, id=f"{data['pattern']}+{i}")
        for i, ex in enumerate(data["negative"]):
            yield pytest.param(ex, False, id=f"{data['pattern']}-{i}")


def test_every_pattern_has_examples():
    assert len(PATTERNS) == 15
    for path in PATTERNS:
        data = json.loads(path.read_text())
        assert len(data["positive"]) >= 5 and len(data["negative"]) >= 3, path.name


@pytest.mark.parametrize("example,positive", list(cases()))
def test_pattern_example(example, positive):
    expect = example["expect"] if positive else example["must_not"]
    hits, facts = check(example, expect)
    where = f"{example['law']} {example['loc']}: {example['lines'][-1][:160]} -> {facts}"
    if positive:
        assert all(hits.values()), where
    else:
        assert not all(hits.values()), where
