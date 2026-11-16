"""How a controller says goodbye when handing the pilot to the next frequency: in the language of the country, the way
real controllers do ("tschüss" in Germany, "servus" in Austria, "au revoir" in France), else "good day".

The country is the first two letters of the ICAO ident (ED Germany, LO Austria, ...). Each controller always uses the
same of its country's phrases, picked from its name, like its voice. The text stays as written ("tschüss"); the
Piper voice speaks it with that language's sounds (see spoken_in_own_language), so an English voice doesn't say
"tee-shoos"."""
from __future__ import annotations

import re
import zlib

# ICAO prefix → (espeak language, phrases). Short, everyday radio goodbyes.
BY_COUNTRY: dict[str, tuple[str, tuple[str, ...]]] = {
    "ED": ("de", ("tschüss", "schönen Tag noch", "tschüss, gute Reise")),
    "ET": ("de", ("tschüss", "schönen Tag noch")),
    "LO": ("de", ("servus", "baba, schönen Tag")),
    "LS": ("de", ("merci, adieu", "uf widerluege")),
    "LF": ("fr", ("au revoir", "bonne journée")),
    "EB": ("fr", ("au revoir", "bonne journée")),
    "EL": ("fr", ("au revoir",)),
    "EH": ("nl", ("goedendag", "doei")),
    "LI": ("it", ("ciao", "buona giornata")),
    "LE": ("es", ("adiós", "buen vuelo")),
    "GC": ("es", ("adiós", "buen vuelo")),
    "LP": ("pt", ("adeus", "boa viagem")),
    "EP": ("pl", ("do widzenia",)),
    "LK": ("cs", ("na shledanou",)),
    "EK": ("da", ("farvel",)),
    "ES": ("sv", ("hej då",)),
    "EN": ("no", ("ha det",)),
    "EF": ("fi", ("moi moi",)),
    "EG": ("en", ("cheers", "good day")),
    "EI": ("en", ("cheers", "good day")),
}
DEFAULT = ("en", ("good day", "goodbye"))


def farewell(ident: str, station_name: str) -> str:
    """The goodbye of this controller. ident: the airport's or FIR's ICAO code ("EDDH", "EDWW/Bremen Radar/...")."""
    _, phrases = BY_COUNTRY.get(ident[:2].upper(), DEFAULT)
    return phrases[zlib.crc32(station_name.encode()) % len(phrases)]


def spoken_in_own_language(text: str, phonemize) -> str:
    """Each foreign goodbye in `text` as Piper raw phonemes, [[ ... ]], in its own language's sounds.
    phonemize(language, text) → IPA string."""
    if _FOREIGN.search(text) is None:
        return text
    def as_phonemes(m: re.Match) -> str:
        phrase = next(p for p in _LANGUAGE if p.lower() == m[0].lower())
        return f"[[ {phonemize(_LANGUAGE[phrase], phrase)} ]]"
    return _FOREIGN.sub(as_phonemes, text)


# One pass over all foreign phrases, longest first ("tschüss, gute Reise" before "tschüss")
_LANGUAGE = {phrase: lang for lang, phrases in BY_COUNTRY.values() if lang != "en" for phrase in phrases}
_FOREIGN = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(p) for p in sorted(_LANGUAGE, key=len, reverse=True))
                      + r")(?!\w)", re.IGNORECASE)
