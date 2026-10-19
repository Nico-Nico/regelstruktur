"""Læser en Word-fil (.docx) og laver den om til tekst, som rule_parser kan læse.

Hvert afsnit bliver én linje, og hver tabelrække én linje (ROW først, CELL mellem cellerne).
Overskrifter og overstreget tekst mærkes med tegnene fra rule_parser (HEADING, STRIKE_ON/OFF, STRUCK).
Som overstreget regnes både skrifttypen "gennemstreget" og sletninger under "registrer ændringer".
Word-kommentarer, sidehoved/-fod, fodnoter og tekstbokse læses ikke.

Kræver python-docx.
"""
from __future__ import annotations

import re

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from rule_parser import CELL, HEADING, ROW, STRIKE_OFF, STRIKE_ON, STRUCK

W_P, W_TBL, W_TR, W_TC, W_R = (qn(f"w:{tag}") for tag in ("p", "tbl", "tr", "tc", "r"))
WRAPPERS = {qn(f"w:{tag}") for tag in ("sdt", "sdtContent", "customXml", "ins", "moveTo")}
DELETED = {qn("w:del"), qn("w:moveFrom")}
TEXT = {qn("w:t"), qn("w:delText")}
BREAKS = {qn("w:br"), qn("w:cr")}

HEADING_STYLE = re.compile(r"(?:heading|overskrift) ?(\d)$", re.IGNORECASE)
TITLE_STYLES = {"title", "titel"}
# Overstregning må ikke gå hen over de tegn, parseren deler teksten ved; << og >> får deres eget mærke
SPLIT = re.compile(r"(<<|>>|<(?=\w+:)|\n|\t)")
RESERVED = str.maketrans("", "", STRIKE_ON + STRIKE_OFF + HEADING + STRUCK + ROW + CELL)


def children(parent, tag):
    """Elementer af den givne type, også dem der ligger i indholdskontroller og lignende."""
    for el in parent:
        if el.tag == tag:
            yield el
        elif el.tag in WRAPPERS:
            yield from children(el, tag)


def blocks(parent):
    """Afsnit og tabeller i dokumentrækkefølge."""
    for el in parent:
        if el.tag in (W_P, W_TBL):
            yield el
        elif el.tag in WRAPPERS:
            yield from blocks(el)


def strike_flag(font) -> bool | None:
    values = (font.strike, font.double_strike)
    return True if True in values else False if False in values else None


class Reader:
    def __init__(self, source, keep_struck: bool = True):
        self.doc = Document(source)
        self.keep_struck = keep_struck
        self.style_cache: dict[str, tuple[bool | None, int]] = {}

    def style_info(self, style) -> tuple[bool | None, int]:
        """(overstregning, overskriftsniveau) for en typografi, arvet fra dem den bygger på."""
        key = style.style_id
        if key not in self.style_cache:
            struck, level = None, 0
            while style is not None:
                if struck is None:
                    struck = strike_flag(style.font)
                if not level:
                    name = style.name or ""
                    match = HEADING_STYLE.match(name)
                    level = int(match.group(1)) if match else 1 if name.lower() in TITLE_STYLES else 0
                    level = level or self.outline_level(style.element.pPr)
                style = style.base_style
            self.style_cache[key] = (struck, level)
        return self.style_cache[key]

    @staticmethod
    def outline_level(pPr) -> int:
        outline = pPr.find(qn("w:outlineLvl")) if pPr is not None else None
        value = int(outline.get(qn("w:val"), 9)) if outline is not None else 9
        return value + 1 if value < 9 else 0

    def run_text(self, r) -> str:
        out = []
        for el in r:
            if el.tag in TEXT:
                out.append(el.text or "")
            elif el.tag == qn("w:tab"):
                out.append("\t")
            elif el.tag in BREAKS and el.get(qn("w:type")) not in ("page", "column"):
                out.append("\n")
            elif el.tag == qn("w:noBreakHyphen"):
                out.append("-")
        return "".join(out).translate(RESERVED)

    def segments(self, para: Paragraph) -> list[list]:
        """Afsnittets tekst som [tekst, overstreget]-par."""
        para_struck = self.style_info(para.style)[0]
        segs: list[list] = []
        for r in para._p.iter(W_R):
            deleted = False
            for parent in r.iterancestors():
                if parent.tag in DELETED:
                    deleted = True
                elif parent.tag == W_P:
                    break
            if parent is not para._p:  # tekstboks eller lignende inde i afsnittet
                continue
            text = self.run_text(r)
            if not text:
                continue
            struck = deleted
            if not struck:
                run = Run(r, para)
                struck = strike_flag(run.font)
                if struck is None and r.rPr is not None and r.rPr.rStyle is not None:
                    struck = self.style_info(run.style)[0]
                if struck is None:
                    struck = bool(para_struck)
            if segs and segs[-1][1] == struck:
                segs[-1][0] += text
            else:
                segs.append([text, struck])
        return segs

    @staticmethod
    def mark(text: str) -> str:
        parts = SPLIT.split(text)
        for i, part in enumerate(parts):
            core = part.strip()
            if not core:
                continue
            parts[i] = STRUCK + part if i % 2 else part.replace(core, STRIKE_ON + core + STRIKE_OFF, 1)
        return "".join(parts)

    def paragraph(self, p) -> str | None:
        """Afsnittets tekst; None hvis hele afsnittet var overstreget og er udeladt."""
        para = Paragraph(p, self.doc)
        segs = self.segments(para)
        if self.keep_struck:
            return "".join(self.mark(text) if struck else text for text, struck in segs)
        text = "".join(text for text, struck in segs if not struck)
        return None if segs and not text.strip() else text

    def heading_level(self, p) -> int:
        return self.outline_level(p.pPr) or self.style_info(Paragraph(p, self.doc).style)[1]

    def cell(self, tc) -> str:
        parts = []
        for el in blocks(tc):
            if el.tag == W_P:
                parts.append((self.paragraph(el) or "").replace("\n", " ").replace("\t", " ").strip())
            else:
                parts.extend(row.replace(ROW, "").replace(CELL, " | ") for row in self.table(el))  # tabel i tabel
        return " ".join(part for part in parts if part)

    def table(self, tbl) -> list[str]:
        return [ROW + CELL.join(self.cell(tc) for tc in children(tr, W_TC)) for tr in children(tbl, W_TR)]

    def lines(self) -> list[str]:
        out: list[str] = []
        for el in blocks(self.doc.element.body):
            if el.tag == W_TBL:
                out.extend(self.table(el))
                continue
            text = self.paragraph(el)
            if text is None:
                continue
            level = self.heading_level(el) if text.strip() else 0
            out.append(f"{HEADING}{level}" + " ".join(text.split("\n")) if level else text)
        return out


def read_docx(source, keep_struck: bool = True) -> str:
    """Læs en .docx (sti eller åben fil). keep_struck=False udelader overstreget tekst helt."""
    return "\n".join(Reader(source, keep_struck).lines())
