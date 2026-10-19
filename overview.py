"""Oversigt over regler (R123=TRUE) og datapunkter (<<10F vurderingsår>>) i en skabelon.

collect(tree) tager træet fra rule_parser.to_tree og giver to tabeller (overskrifter + rækker),
som to_csv og to_xlsx kan skrive til en fil. Kun standardbibliotek.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from xml.sax.saxutils import escape, quoteattr

from rule_parser import MARKS, STRIKE_OFF, STRIKE_ON

RULE = re.compile(r"\(\s*(R\w+)\s*=\s*(\w+)\s*\)")
DATA = re.compile(r"<<\s*(\d\w*)([^<>]*)>>")
# Her starter teksten, der beskriver en regel: efter forrige regel, ELLER/OG, <<, >>, "(dvs." eller et kommentarmærke
BREAK = re.compile(r"\(\s*R\w+\s*=\s*\w+\s*\)|\b(?:ELLER|OG)\b|<<|>>|\(dvs\.|\[[A-Z]*\d+\.\d+\]")
NATURAL = re.compile(r"(\d+)")

RULE_HEADERS = ["Regel", "Værdi", "Forekomster", "Heraf overstreget", "Blokke", "Beskrivelse (teksten foran reglen)"]
DATA_HEADERS = ["Datapunkt", "Tekst", "Forekomster", "Heraf overstreget", "Blokke"]
MAX_VARIANTS = 5  # så mange forskellige beskrivelser/tekster vises pr. regel eller datapunkt


def natural(key: str) -> list:
    """Sorteringsnøgle, så R2 kommer før R10 og 10F før 140a."""
    return [int(part) if part.isdigit() else part.lower() for part in NATURAL.split(key)]


def block_name(item: dict) -> tuple[str, str]:
    """(K-navn, andet navn) for en blok; højst ét af dem er udfyldt, og <<Hvis-blokke har ingen."""
    label = MARKS.sub("", item["label"]).rstrip(":")
    if not label or label.lower() == "hvis":
        return "", ""
    if re.fullmatch(r"K\w+", label):
        return label, ""
    return "", " ".join(f"{label} {MARKS.sub('', item['clauses'][0])}".split())[:40].strip()


def collect(tree: list[dict]) -> dict:
    """Find alle regler og datapunkter. Giver {"rules": {"headers", "rows"}, "data": {"headers", "rows"}}."""
    rules: dict[str, dict] = {}
    data: dict[str, dict] = {}
    struck = False  # overstregning kan fortsætte fra én streng til den næste, ligesom i visningen

    def clean(text: str) -> tuple[str, list[bool]]:
        """Teksten uden mærker, og for hvert tegn om det er overstreget."""
        nonlocal struck
        chars, flags = [], []
        for ch in text:
            if ch in (STRIKE_ON, STRIKE_OFF):
                struck = ch == STRIKE_ON
            elif not MARKS.match(ch):
                chars.append(ch)
                flags.append(struck)
        return "".join(chars), flags

    def note(table: dict, key: str, is_struck: bool, block: str, variant: str) -> dict:
        rec = table.setdefault(key, {"count": 0, "struck": 0, "blocks": {}, "variants": {}, "values": {}})
        rec["count"] += 1
        rec["struck"] += is_struck
        if block:
            rec["blocks"][block] = True
        if variant:
            rec["variants"][variant] = True
        return rec

    def scan(text: str, block: str) -> None:
        plain, flags = clean(text)
        for m in RULE.finditer(plain):
            before = plain[: m.start()]
            cut = max((b.end() for b in BREAK.finditer(before)), default=0)
            description = " ".join(before[cut:].split()).strip(" .,;:")
            note(rules, m.group(1), flags[m.start()], block, description)["values"][m.group(2)] = True
        for m in DATA.finditer(plain):
            note(data, m.group(1), flags[m.start(1)], block, " ".join(m.group(2).split()))

    def walk(items: list[dict], k_block: str, other: str) -> None:
        # "Blokke" er den nærmeste K-blok udenom; kun uden for alle K-blokke bruges et andet bloknavn
        block = k_block or other
        for item in items:
            if item["type"] == "text":
                for line in item["lines"]:
                    scan(line, block)
            elif item["type"] == "table":
                for row in item["rows"]:
                    for cell in row:
                        scan(cell, block)
            elif item["type"] == "heading":
                scan(item["text"], block)
            else:
                own_k, own_other = block_name(item)
                inner_k, inner_other = own_k or k_block, own_other or other
                for text in [item["label"], *item["clauses"]]:
                    scan(text, inner_k or inner_other)
                walk(item["children"], inner_k, inner_other)
                clean(item["closer"] or "")

    def variants(rec: dict) -> str:
        shown = list(rec["variants"])
        return " / ".join(shown[:MAX_VARIANTS]) + (" / …" if len(shown) > MAX_VARIANTS else "")

    walk(tree, "", "")
    return {
        "rules": {"headers": RULE_HEADERS, "rows": [
            [key, ", ".join(rec["values"]), rec["count"], rec["struck"], ", ".join(rec["blocks"]), variants(rec)]
            for key, rec in sorted(rules.items(), key=lambda kv: natural(kv[0]))]},
        "data": {"headers": DATA_HEADERS, "rows": [
            [key, variants(rec), rec["count"], rec["struck"], ", ".join(rec["blocks"])]
            for key, rec in sorted(data.items(), key=lambda kv: natural(kv[0]))]},
    }


def to_csv(headers: list, rows: list[list]) -> bytes:
    """CSV som dansk Excel åbner rigtigt ved dobbeltklik: semikolon som skilletegn og UTF-8 med BOM."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


# --- XLSX: en .xlsx er en zip-fil med XML, så den kan skrives uden andre pakker ---

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT = "application/vnd.openxmlformats-officedocument.spreadsheetml"
XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")  # tegn, XML ikke tillader

STYLES = (
    f'{XML}<styleSheet xmlns="{MAIN_NS}">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)


def column(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def sheet_xml(headers: list, rows: list[list]) -> str:
    def cell(ref: str, value, style: int) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{ref}"><v>{value}</v></c>'
        text = escape(ILLEGAL.sub("", str(value)))
        bold = ' s="1"' if style else ""
        return f'<c r="{ref}" t="inlineStr"{bold}><is><t xml:space="preserve">{text}</t></is></c>'

    table = [headers] + rows
    widths = [min(80, max(10, *(len(str(row[i])) + 2 for row in table if i < len(row)))) for i in range(len(headers))]
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    body = "".join(
        f'<row r="{r}">' + "".join(cell(f"{column(c)}{r}", value, r == 1) for c, value in enumerate(row)) + "</row>"
        for r, row in enumerate(table, start=1)
    )
    last = f"{column(len(headers) - 1)}{len(table)}"
    return (
        f'{XML}<worksheet xmlns="{MAIN_NS}">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        f'<cols>{cols}</cols><sheetData>{body}</sheetData><autoFilter ref="A1:{last}"/></worksheet>'
    )


def to_xlsx(sheets: list[tuple[str, list, list[list]]]) -> bytes:
    """Skriv en projektmappe med ét ark pr. (navn, overskrifter, rækker). Øverste række er fed og låst."""
    numbers = range(1, len(sheets) + 1)
    files = {
        "[Content_Types].xml": (
            f'{XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{CONTENT}.sheet.main+xml"/>'
            f'<Override PartName="/xl/styles.xml" ContentType="{CONTENT}.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{n}.xml" ContentType="{CONTENT}.worksheet+xml"/>'
                      for n in numbers)
            + "</Types>"
        ),
        "_rels/.rels": (
            f'{XML}<Relationships xmlns="{PKG_REL_NS}">'
            f'<Relationship Id="rId1" Type="{REL_NS}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            f'{XML}<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><bookViews><workbookView/></bookViews><sheets>'
            + "".join(f'<sheet name={quoteattr(name[:31])} sheetId="{n}" r:id="rId{n}"/>'
                      for n, (name, _, _) in zip(numbers, sheets))
            + "</sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            f'{XML}<Relationships xmlns="{PKG_REL_NS}">'
            + "".join(f'<Relationship Id="rId{n}" Type="{REL_NS}/worksheet" Target="worksheets/sheet{n}.xml"/>'
                      for n in numbers)
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="{REL_NS}/styles" Target="styles.xml"/></Relationships>'
        ),
        "xl/styles.xml": STYLES,
    }
    for n, (_, headers, rows) in zip(numbers, sheets):
        files[f"xl/worksheets/sheet{n}.xml"] = sheet_xml(headers, rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return out.getvalue()
