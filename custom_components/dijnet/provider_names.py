"""
Recognizes a provider that Dijnet renamed.

The sensor unique_id contains the provider name as Dijnet reports it, and Dijnet
does rename providers: in 2026-09 "FV Zrt.", "FCSM Zrt." and "DFaktorház Zrt."
became "Fővárosi Vízművek Zártkörűen Működő Rész", "Fővárosi Csatornázási Művek
Zrt." and "Díjbeszedő Faktorház Zrt.", retroactively, on every invoice. Dijnet
offers no other stable id per provider, so a rename has to be recognized from
the two names themselves.

The rule is deliberately narrow: after dropping company-form words, one name
must spell the other as prefixes of its consecutive words ("FV" = "F"ővárosi
"V"ízművek, "FCSM" = "F"ővárosi "Cs"atornázási "M"űvek). This module has no
Home Assistant imports so it can be tested on its own.
"""

from __future__ import annotations

import re
import unicodedata

# Company-form words, and the fragments Dijnet leaves when it cuts a long name
# at 40 characters. They carry no identity, and either name may lack them.
_FORM_WORDS = frozenset(
    {
        "bt",
        "felelossegu",
        "kft",
        "kkt",
        "korlatolt",
        "mukodo",
        "nyilvanosan",
        "nyrt",
        "resz",
        "reszvenytarsasag",
        "rt",
        "tarsasag",
        "zartkoruen",
        "zrt",
    }
)


def _words(name: str) -> list[str]:
    """Lowercase, accent-free words of a name, without company-form words."""
    decomposed = unicodedata.normalize("NFKD", name)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char)).lower()
    return [word for word in re.split(r"[^a-z0-9]+", plain) if word and word not in _FORM_WORDS]


def _spells(target: str, words: list[str]) -> bool:
    """True if target is non-empty prefixes of consecutive words, from the first."""
    if not target:
        return True
    if not words:
        return False
    word = words[0]
    for length in range(min(len(word), len(target)), 0, -1):
        if target[:length] == word[:length] and _spells(target[length:], words[1:]):
            return True
    return False


def is_same_provider(old_name: str, new_name: str) -> bool:
    """
    Tells whether two provider names denote the same provider.

    Args:
      old_name:
        The provider name an existing sensor was created from.
      new_name:
        The provider name Dijnet reports now.

    Returns:
      True if either name abbreviates the other by the rule described above.
    """
    old_words = _words(old_name)
    new_words = _words(new_name)
    if not old_words or not new_words:
        return False
    return _spells("".join(old_words), new_words) or _spells("".join(new_words), old_words)


def pair_renamed(old_names: list[str], new_names: list[str]) -> dict[str, str]:
    """
    Pairs vanished provider names with newly reported ones.

    A pair is kept only if it is unambiguous both ways: the old name matches
    exactly one new name, and that new name matches no other old name. Anything
    else is left unpaired, because moving a sensor to the wrong provider would
    be worse than leaving an orphan.

    Args:
      old_names:
        Provider names that have a sensor but are no longer reported.
      new_names:
        Provider names that are reported now.

    Returns:
      The unambiguous old name -> new name pairs.
    """
    matches = {old: [new for new in new_names if is_same_provider(old, new)] for old in old_names}
    pairs: dict[str, str] = {}
    for old, candidates in matches.items():
        if len(candidates) != 1:
            continue
        new = candidates[0]
        if sum(new in other for other in matches.values()) == 1:
            pairs[old] = new
    return pairs
