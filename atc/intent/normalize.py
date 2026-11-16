"""Turn a whisper transcript into clean tokens: lower case, numbers as digit strings, frequencies as '119.875'.

Whisper writes the same number as "120", "1-2-0" or "one, two, zero" and hears ICAO "niner" as "9 or";
everything after this module only has to deal with "120" and "119.875"."""
import re

NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "tree": "3", "four": "4", "five": "5", "fife": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "niner": "9",
}
PHONETIC = {
    "alpha": "a", "alfa": "a", "bravo": "b", "charlie": "c", "delta": "d", "echo": "e", "foxtrot": "f",
    "golf": "g", "hotel": "h", "india": "i", "juliet": "j", "juliett": "j", "kilo": "k", "lima": "l",
    "mike": "m", "november": "n", "oscar": "o", "papa": "p", "quebec": "q", "romeo": "r", "sierra": "s",
    "tango": "t", "uniform": "u", "victor": "v", "whiskey": "w", "whisky": "w", "xray": "x", "yankee": "y",
    "zulu": "z",
}
GLUED_PREFIX = re.compile(r"(qnh|fl|squawk|runway|heading)(\d+)")  # "QNH101" -> "qnh", "101"


def tokenize(text: str) -> list[str]:
    t = text.lower()
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)  # "3,500" -> "3500"
    t = t.replace("x-ray", "xray")
    t = re.sub(r"\btake[\s-]?off\b", "takeoff", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)  # keep only dots between digits
    t = re.sub(r"[^a-z0-9.\s]", " ", t)

    tokens: list[str] = []
    spelled: list[bool] = []  # True if the digit came from a word ("tree"), not from a digit in the text
    for tok in t.split():
        if m := GLUED_PREFIX.fullmatch(tok):
            tokens += [m[1], m[2]]
            spelled += [False, False]
        else:
            tokens.append(NUMBER_WORDS.get(tok, tok))
            spelled.append(tok in NUMBER_WORDS)

    keep = [i for i in range(len(tokens)) if not _is_split_niner(tokens, i)]
    tokens, spelled = [tokens[i] for i in keep], [spelled[i] for i in keep]
    return [_repair_frequency(tok) for tok in _merge_decimals(_merge_digits(tokens, spelled))]


def _repair_frequency(tok: str) -> str:
    """"1199.825" for "one one niner decimal eight two fife": whisper doubled a digit. If dropping one digit gives
    the only possible airband frequency (118-136 MHz), use it."""
    whole, dot, fraction = tok.partition(".")
    if not dot or len(whole) != 4 or not whole.isdigit():
        return tok
    fixes = {whole[:k] + whole[k + 1:] for k in range(4)} & {str(n) for n in range(118, 137)}
    return f"{fixes.pop()}.{fraction}" if len(fixes) == 1 else tok


def _is_split_niner(tokens: list[str], i: int) -> bool:
    # "one one niner decimal ..." is transcribed as "119 or decimal ..."
    return (tokens[i] == "or" and 0 < i < len(tokens) - 1 and tokens[i - 1].isdigit()
            and (tokens[i + 1] == "decimal" or tokens[i + 1].isdigit()))


def _merge_digits(tokens: list[str], spelled: list[bool]) -> list[str]:
    """Join digits that belong to one number, but keep separate numbers apart:
    '1, 2, 0' -> 120 and 'one one niner' -> 119, but 'runway 23, 5000 feet' stays 23 and 5000.
    Spoken digits extend any number before them ('101 tree' -> 1013); single written digits only join
    other single written digits; multi-digit numbers in the text never grow. Before "thousand"/"hundred" at
    most two digits are said ("one one thousand" = 11000), so a digit there after two or more digits starts a
    new number: 'heading zero eight zero, three thousand five hundred' is 080 and 3500."""
    merged: list[str] = []
    singles_run = False  # merged[-1] was built only from single written digits
    for i, (tok, was_word) in enumerate(zip(tokens, spelled)):
        new_magnitude = (i + 1 < len(tokens) and tokens[i + 1] in ("thousand", "hundred")
                         and merged and len(merged[-1]) >= 2)
        if tok.isdigit() and merged and merged[-1].isdigit() and not new_magnitude:
            if was_word or (len(tok) == 1 and singles_run):
                merged[-1] += tok
                continue
        merged.append(tok)
        singles_run = tok.isdigit() and len(tok) == 1 and not was_word
    return merged


def _merge_decimals(tokens: list[str]) -> list[str]:
    result: list[str] = []
    i = 0
    while i < len(tokens):
        if (tokens[i] == "decimal" and result and result[-1].isdigit()
                and i + 1 < len(tokens) and tokens[i + 1].isdigit()):
            result[-1] = f"{result[-1]}.{tokens[i + 1]}"
            i += 2
        else:
            result.append(tokens[i])
            i += 1
    return result
