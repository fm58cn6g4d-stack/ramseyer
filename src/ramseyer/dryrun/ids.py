"""Stable element ids for a section the engine works on (M8): the comparative print lines the original section up
with the edited one by these ids (ramseyer.comparative.redline)."""
from __future__ import annotations

import itertools

ID = "{urn:ramseyer}id"


def tag(el) -> None:
    """Give every element of `el` an id, once."""
    counter = itertools.count(1)
    for e in el.iter():
        if isinstance(e.tag, str) and e.get(ID) is None:
            e.set(ID, str(next(counter)))
