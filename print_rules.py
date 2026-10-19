#!/usr/bin/env python3
"""Printer en regel-streng som et indrykket træ i terminalen.

Brug:
  python3 print_rules.py                 # test_document.docx (opdigtet eksempel)
  python3 print_rules.py min_fil.txt
  python3 print_rules.py skabelon.docx   # kræver python-docx; --hide-strike udelader overstreget tekst
  python3 print_rules.py -s '<<K1 <<Hvis x (R1=TRUE)\ntekst\n>>K1>>'
  pbpaste | python3 print_rules.py -     # læs fra stdin
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import textwrap
from pathlib import Path

from rule_parser import HILITE, STRIKE_OFF, STRIKE_ON, STRUCK, parse, to_tree

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
UNDERLINE, STRIKE, NOSTRIKE = "\033[4m", "\033[9m", "\033[29m"
RED, YELLOW, MAGENTA, CYAN = "\033[31m", "\033[33m", "\033[35m", "\033[36m"
PALETTE = ["\033[34m", "\033[32m", "\033[35m", "\033[33m", "\033[36m"]  # én farve pr. niveau
ANSI = re.compile(r"\033\[\d+m")
STRIKE_PARTS = re.compile(f"([{STRIKE_ON}{STRIKE_OFF}]|\033\\[0m)")
STRUCK_TOKEN = re.compile(STRUCK + "(<<|>>|<)")


def wrap(line: str, width: int) -> list[str]:
    return textwrap.wrap(
        line, max(width, 30), subsequent_indent="    ",
        break_long_words=False, break_on_hyphens=False,
    ) or [""]


class Strike:
    """Viser overstreget tekst (ANSI, eller ~~...~~ uden farver); husker tilstanden hen over linjer."""

    def __init__(self, color: bool = True):
        self.color, self.on = color, False

    def __call__(self, line: str) -> str:
        line = STRUCK_TOKEN.sub(STRIKE_ON + r"\1" + STRIKE_OFF, line)
        if not self.color:  # sammenhængende overstregning vises som ét ~~...~~
            return re.sub(f"{STRIKE_OFF}((?:\033\\[\\d+m| )*){STRIKE_ON}", r"\1", line).replace(STRIKE_ON, "~~").replace(STRIKE_OFF, "~~")
        out = [STRIKE] if self.on else []
        for part in STRIKE_PARTS.split(line):
            if part == STRIKE_ON:
                self.on = True
                out.append(STRIKE)
            elif part == STRIKE_OFF:
                self.on = False
                out.append(NOSTRIKE)
            elif part == RESET:
                out.append(RESET + (STRIKE if self.on else ""))
            else:
                out.append(part)
        return "".join(out) + (NOSTRIKE if self.on else "")


class Painter:
    """Farvelægger linjer; husker om vi er inde i et <<...>> hen over linjeskift."""

    def __init__(self, strike: Strike, base: str = ""):
        self.strike, self.base, self.depth = strike, base, 0

    def current(self) -> str:
        return CYAN if self.depth else self.base

    def __call__(self, line: str) -> str:
        def sub(m: re.Match) -> str:
            tok = m.group()
            if tok.endswith("<<"):
                self.depth += 1
                return CYAN + tok
            if tok.endswith(">>"):
                self.depth = max(0, self.depth - 1)
                return CYAN + tok + RESET + self.current()
            color = DIM if tok[0] == "[" else YELLOW if tok[0] == "(" else BOLD + MAGENTA
            return RESET + color + tok + RESET + self.current()

        return self.strike(self.current() + HILITE.sub(sub, line) + RESET)


def render(tree: list[dict], out: list[str], prefix: str, depth: int, width: int, strike: Strike) -> None:
    room = width - len(ANSI.sub("", prefix))
    for item in tree:
        if item["type"] == "heading":
            # Terminalen har kun én skriftstørrelse: niveau 1 får en streg under, resten #'er
            title = "#" * item["level"] + " " + item["text"]
            style = BOLD + UNDERLINE if item["level"] > 1 else BOLD
            out.extend([prefix.rstrip(), prefix + strike(style + title + RESET)])
            if item["level"] == 1:
                out.append(prefix + BOLD + "═" * min(room, len(title)) + RESET)
            continue
        if item["type"] == "table":
            item = {"type": "text", "lines": [" | ".join(row) for row in item["rows"]]}
        if item["type"] == "text":
            painter = Painter(strike)
            for line in item["lines"]:
                out.extend(prefix + painter(part) for part in wrap(line, room))
            continue

        color = PALETTE[depth % len(PALETTE)]
        bar = color + "│  " + RESET
        painter = Painter(strike, color)
        head = item["opener"] + item["label"]
        first, *more = item["clauses"]
        lines = wrap(first, room - 4 - len(head)) + [p for c in more for p in wrap(c, room - 6)]
        rest = " " + painter(lines[0]) if lines[0] else ""
        missing = f"  {RED}{BOLD}MANGLER LUKNING{RESET}" if item["closer"] is None else ""
        out.append(f"{prefix}{color}┌─ {strike(BOLD + head + RESET)}{rest}{missing}")
        out.extend(f"{prefix}{bar}   {painter(line)}" for line in lines[1:])

        render(item["children"], out, prefix + bar, depth + 1, width, strike)

        if item["closer"] is None:
            out.append(f"{prefix}{RED}└─ ({item['name']} mangler lukning){RESET}")
        else:
            out.append(prefix + strike(f"{color}└─ {item['closer']}{RESET}"))


def format_rules(text: str, width: int = 100, color: bool = True) -> str:
    out: list[str] = []
    render(to_tree(parse(text).children), out, "", 0, width, Strike(color))
    result = "\n".join(out)
    return result if color else ANSI.sub("", result)


def main() -> None:
    ap = argparse.ArgumentParser(description="Print en regel-streng som et overskueligt træ.")
    ap.add_argument("file", nargs="?",
                    help="tekstfil eller Word-fil (.docx); '-' læser fra stdin (standard: test_document.docx)")
    ap.add_argument("-s", "--string", help="strengen angivet direkte (\\n tolkes som linjeskift)")
    ap.add_argument("--no-color", action="store_true", help="slå farver fra")
    ap.add_argument("--hide-strike", action="store_true", help="udelad overstreget tekst (kun Word-filer)")
    ap.add_argument("--width", type=int, default=shutil.get_terminal_size((100, 24)).columns)
    args = ap.parse_args()

    if args.string is not None:
        text = args.string.replace("\\n", "\n")
    elif args.file == "-":
        text = sys.stdin.read()
    else:
        path = Path(args.file) if args.file else Path(__file__).with_name("test_document.docx")
        if path.suffix.lower() == ".docx":
            from docx_reader import read_docx  # kræver python-docx; resten klarer sig uden

            text = read_docx(path, keep_struck=not args.hide_strike)
        else:
            text = path.read_text(encoding="utf-8")

    print(format_rules(text, args.width, color=not args.no_color and sys.stdout.isatty()))


if __name__ == "__main__":
    main()
