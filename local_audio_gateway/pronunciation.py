"""Model-aware pronunciation conversion. Displayed Traditional Chinese stays untouched."""
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from opencc import OpenCC

_converter = OpenCC('t2s')


@lru_cache(maxsize=4)
def voiced_entries(path: Path) -> frozenset[str]:
    return frozenset(
        fields[0] for line in path.read_text(encoding='utf-8').splitlines()
        if len(fields := line.split()) > 1
    )


def prepare_speech(text: str, lexicon: Path) -> tuple[str, tuple[str, ...]]:
    entries = voiced_entries(lexicon)
    # Latin words are spelled with supported single-letter entries, not silently discarded.
    text = re.sub(r'[A-Za-z]+', lambda m: ' '.join(m[0].lower()), text)
    result: list[str] = []
    missing: set[str] = set()
    for char in text:
        candidate = char if char in entries else _converter.convert(char)
        if candidate in entries or all(c.isspace() or unicodedata.category(c)[0] in 'PNZS' for c in candidate):
            result.append(candidate)
        else:
            missing.add(char)
            result.append(char)
    return ''.join(result), tuple(sorted(missing))
