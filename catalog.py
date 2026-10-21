"""Katalog over regler og datapunkter i EDN-format (Clojures dataformat), og stien til det fra config.ini.

Læseren forstår EDN og de stykker Clojure-syntaks, der ofte står i .edn-filer (#"regex", #(...),
#?(...), ##Inf, ^metadata, 'quote osv.). Kan filen alligevel ikke læses, findes nøglerne med en
nødløsning, der leder efter :nøgle {... :titel "..."}.

Kataloget forventes at være et map, hvor hver nøgle er en regel eller et datapunkt, og værdien er et
map med bl.a. :titel, fx {:R895b {:titel "..." ...} :10F {:titel "..." ...}}. En kode regnes for at
findes i kataloget, hvis den står som nøgle (uden kolon og evt. navnerum) eller forrest i :titel før
et kolon. Store og små bogstaver er ligegyldige. Kun standardbibliotek.
"""
from __future__ import annotations

import configparser
import re
from pathlib import Path

CONFIG = Path(__file__).with_name("config.ini")
CATALOG_HEADER = "I katalog"
DESCRIPTION_HEADER = "Beskrivelse - katalog"


class Keyword(str):
    """Et EDN-keyword som :titel eller :regel/R1, gemt uden kolon."""


class Symbol(str):
    """Et EDN-symbol som fn eller clojure.string/join (vises uden anførselstegn)."""


class EdnList(tuple):
    """En liste i parenteser, fx (fn [x] ...), til forskel fra en vektor i firkantede parenteser."""


class Tagged:
    """En mærket værdi som #inst "2024-01-01"; mærket bevares, men bruges ikke."""

    def __init__(self, tag: str, value):
        self.tag, self.value = tag, value


# --- EDN-læser ---

SKIP = re.compile(r"(?:[\s,]|;[^\n]*)*")
STRING = re.compile(r'"((?:[^"\\]|\\.)*)"', re.S)
TOKEN = re.compile(r'[^\s,()\[\]{}";]+')
ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "/": "/"}
CHARS = {"newline": "\n", "space": " ", "tab": "\t", "return": "\r", "backspace": "\b", "formfeed": "\f"}
CLOSING = {"{": "}", "[": "]", "(": ")"}


class EdnError(ValueError):
    pass


def hashable(value):
    """Map-nøgler skal kunne hashes; vektorer er tupler og sæt frozensets, alt andet laves om til tekst."""
    try:
        hash(value)
        return value
    except TypeError:
        return repr(value)


def unescape(text: str) -> str:
    def sub(m: re.Match) -> str:
        code = m.group(1)
        if code.startswith("u"):
            return chr(int(code[1:], 16))
        return ESCAPES.get(code, code)

    return re.sub(r"\\(u[0-9a-fA-F]{4}|.)", sub, text)


def atom(token: str):
    if token == "nil":
        return None
    if token in ("true", "false"):
        return token == "true"
    if token.startswith(":"):
        return Keyword(token[1:])
    number = token[:-1] if token[-1:] in ("N", "M") else token
    for kind in (int, float):
        try:
            return kind(number)
        except ValueError:
            pass
    return Symbol(token)


class Reader:
    def __init__(self, text: str):
        self.text, self.pos = text, 0

    def skip(self) -> None:
        """Spring mellemrum, kommaer, kommentarer og #_-værdier (som skal ignoreres) over."""
        while True:
            self.pos = SKIP.match(self.text, self.pos).end()
            if not self.text.startswith("#_", self.pos):
                return
            self.pos += 2
            self.read()

    def error(self, message: str) -> EdnError:
        line = self.text.count("\n", 0, self.pos) + 1
        start = self.text.rfind("\n", 0, self.pos) + 1
        column = self.pos - start + 1
        context = self.text[max(start, self.pos - 40):self.pos + 20].split("\n", 1)[0].strip()
        return EdnError(f"{message} (linje {line}, tegn {column}: »{context}«)")

    def forms(self) -> list:
        out = []
        self.skip()
        while self.pos < len(self.text):
            out.append(self.read())
            self.skip()
        return out

    def items(self, opener: str) -> list:
        closer, out = CLOSING[opener], []
        self.pos += 1
        while True:
            self.skip()
            if self.pos >= len(self.text):
                raise self.error(f"{opener} lukkes aldrig")
            if self.text[self.pos] == closer:
                self.pos += 1
                return out
            out.append(self.read())

    def read(self):
        self.skip()
        if self.pos >= len(self.text):
            raise self.error("Filen slutter midt i en værdi")
        ch = self.text[self.pos]
        if ch == "{":
            items = self.items("{")
            if len(items) % 2:
                raise self.error("Et map har et ulige antal elementer")
            return {hashable(items[i]): items[i + 1] for i in range(0, len(items), 2)}
        if ch == "[":
            return tuple(self.items(ch))
        if ch == "(":
            return EdnList(self.items(ch))
        if ch == "#":
            nxt = self.text[self.pos + 1:self.pos + 2]
            if nxt == "{":
                self.pos += 1
                return frozenset(hashable(item) for item in self.items("{"))
            if nxt == '"':  # #"regex" gemmes, som den står (\d skal ikke læses som en escape)
                m = STRING.match(self.text, self.pos + 1)
                if not m:
                    raise self.error("En tekst lukkes aldrig")
                self.pos = m.end()
                return Tagged("regex", m.group(1))
            if nxt in ("(", "'"):  # #(funktion) og #'var
                self.pos += 1 + (nxt == "'")
                return Tagged("" if nxt == "(" else "'", self.read())
            if nxt == "#":  # ##Inf, ##-Inf, ##NaN
                m = TOKEN.match(self.text, self.pos + 2)
                self.pos = m.end() if m else self.pos + 2
                return {"Inf": float("inf"), "-Inf": float("-inf")}.get(m.group() if m else "", float("nan"))
            if nxt == "?":  # #?(:clj ... :cljs ...) og #?@(...)
                self.pos += 2 + self.text.startswith("@", self.pos + 2)
                return self.read()
            if nxt == ":":  # #:navnerum{...}
                self.pos = TOKEN.match(self.text, self.pos + 1).end()
                return self.read()
            self.pos += 1
            tag = self.read()
            self.skip()
            if self.pos >= len(self.text) or self.text[self.pos] in ")]}":
                return tag
            return Tagged(str(tag), self.read())
        if ch == "^":  # metadata: ^{...} eller ^:navn foran en værdi; metadata springes over
            self.pos += 1
            self.read()
            return self.read()
        if ch in "'`~@":  # quote, syntax-quote, unquote og deref
            self.pos += 1 + self.text.startswith("~@", self.pos)
            return self.read()
        if ch == '"':
            m = STRING.match(self.text, self.pos)
            if not m:
                raise self.error("En tekst lukkes aldrig")
            self.pos = m.end()
            return unescape(m.group(1))
        if ch == "\\":
            m = TOKEN.match(self.text, self.pos + 1) or None
            name = m.group() if m else self.text[self.pos + 1:self.pos + 2]
            self.pos += 1 + max(len(name), 1)
            if name in CHARS:
                return CHARS[name]
            if len(name) == 5 and name.startswith("u"):
                return chr(int(name[1:], 16))
            return name[:1]
        if ch in ")]}":
            raise self.error(f"Uventet {ch}")
        m = TOKEN.match(self.text, self.pos)
        self.pos = m.end()
        return atom(m.group())


def read_edn(text: str) -> list:
    """Alle værdier på yderste niveau i en EDN-tekst."""
    return Reader(text).forms()


# --- Kataloget ---

def normalize(code: str) -> str:
    return code.strip().lower()


FALLBACK_KEY = re.compile(r':([^\s,()\[\]{}";]+)\s*\{')
FALLBACK_FIELD = r':{}\s+"((?:[^"\\]|\\.)*)"'


class Catalog:
    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, dict] = {}  # normaliseret kode → {"titel", "beskr"}
        self.warning = ""
        text = path.read_text(encoding="utf-8")
        try:
            forms = read_edn(text)
        except EdnError as exc:
            forms = [self.fallback(text)]
            self.warning = (f"Kataloget {path.name} kunne ikke læses helt ({exc}), så nøglerne er fundet med "
                            "en nødløsning. Resultatet er sandsynligvis rigtigt, men sig gerne til, hvad der står dér.")
        for form in forms:
            self.add(form)

    @staticmethod
    def fallback(text: str) -> dict:
        """Find alle :nøgle {...} og den første :titel "..." og :beskr "..." efter hver af dem."""
        keys = list(FALLBACK_KEY.finditer(text))
        found = {}
        for key, nxt in zip(keys, keys[1:] + [None]):
            end = nxt.start() if nxt else len(text)
            entry = {}
            for field in ("titel", "beskr"):
                m = re.compile(FALLBACK_FIELD.format(field)).search(text, key.end(), end)
                entry[Keyword(field)] = unescape(m.group(1)) if m else ""
            found[Keyword(key.group(1))] = entry
        return found

    def add(self, form) -> None:
        if isinstance(form, (tuple, list, frozenset)):  # flere kataloger i en vektor eller liste
            for item in form:
                self.add(item)
            return
        if not isinstance(form, dict):
            return
        for key, value in form.items():
            fields = value if isinstance(value, dict) else {}
            entry = {"titel": text_of(fields.get(Keyword("titel"))), "beskr": text_of(fields.get(Keyword("beskr"))),
                     "fields": [[show(field), show(item)] for field, item in fields.items()]}
            name = str(key).rsplit("/", 1)[-1]  # :regel/R1 → R1
            self.entries.setdefault(normalize(name), entry)
            prefix = entry["titel"].split(":", 1)[0]
            if ":" in entry["titel"] and prefix.strip() and " " not in prefix.strip():
                self.entries.setdefault(normalize(prefix), entry)

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, code: str) -> bool:
        return normalize(code) in self.entries

    def fields(self, code: str) -> list[list[str]]:
        """Alle kodens oplysninger i kataloget som [felt, værdi]-par, skrevet som EDN."""
        return self.entries.get(normalize(code), {}).get("fields", [])

    def description(self, code: str) -> str:
        """Kodens :beskr fra kataloget; tom, hvis den ikke findes eller ikke har nogen."""
        return self.entries.get(normalize(code), {}).get("beskr", "")


_cache: dict[tuple, Catalog] = {}


def configured_catalog() -> tuple[Catalog | None, str]:
    """Kataloget fra config.ini; (None, besked) hvis det ikke er angivet eller ikke kan læses.

    Filen læses igen, når den er ændret (fx efter git pull i katalogets repo).
    """
    if not CONFIG.exists():
        return None, ""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(CONFIG, encoding="utf-8")
        raw = parser.get("katalog", "sti", fallback="").strip().strip('"')
    except configparser.Error as exc:
        return None, f"config.ini kan ikke læses: {exc}"
    if not raw:
        return None, ""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = CONFIG.parent / path
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return None, f"Kataloget findes ikke: {path}"
    if key not in _cache:
        try:
            catalog = Catalog(path)
        except (OSError, UnicodeDecodeError, EdnError) as exc:
            return None, f"Kataloget {path.name} kan ikke læses: {exc}"
        _cache.clear()
        _cache[key] = catalog
    return _cache[key], _cache[key].warning


def show(value, indent: int = 0) -> str:
    """Skriv en katalogværdi tilbage som læsbar EDN; store maps og vektorer brydes over flere linjer."""
    pad = " " * (indent + 1)
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Keyword):
        return ":" + value
    if isinstance(value, Symbol):
        return str(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, Tagged):
        if value.tag == "regex":
            return '#"' + value.value + '"'
        if value.tag in ("", "'"):
            return "#" + value.tag + show(value.value, indent + 1 + len(value.tag))
        return f"#{value.tag} {show(value.value, indent)}"
    if isinstance(value, dict):
        parts = [f"{show(k)} {show(v, indent + len(show(k)) + 2)}" for k, v in value.items()]
        opener, closer = "{", "}"
    elif isinstance(value, (tuple, list, frozenset)):
        parts = [show(item, indent + 1) for item in value]
        opener, closer = ("#{", "}") if isinstance(value, frozenset) else ("(", ")") if isinstance(value, EdnList) else ("[", "]")
    else:
        return str(value)
    flat = opener + " ".join(parts) + closer
    if len(flat) <= 70 and "\n" not in flat:
        return flat
    return opener + ("\n" + pad).join(parts) + closer


def text_of(value) -> str:
    """En katalogværdi som tekst: tekster som de er, lister samlet med mellemrum, nil som tomt."""
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, (tuple, list)):
        return " ".join(text_of(item) for item in value if item is not None)
    return str(value)


def add_catalog_column(table: dict, catalog: Catalog) -> None:
    """Indsæt "I katalog" (Ja/Nej) lige efter koden og "Beskrivelse - katalog" (:beskr) sidst
    i en tabel fra overview.collect."""
    table["headers"].insert(1, CATALOG_HEADER)
    table["headers"].append(DESCRIPTION_HEADER)
    for row in table["rows"]:
        row.insert(1, "Ja" if row[0] in catalog else "Nej")
        row.append(catalog.description(row[0]))
