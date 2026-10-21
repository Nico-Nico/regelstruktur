#!/usr/bin/env python3
"""Lille Flask-app der viser en regel-streng som et sammenfoldeligt træ.

Start:  python app.py [fil.docx | fil.txt]   →  http://127.0.0.1:5001
Word-filer kan også vælges på siden.
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

from flask import Flask, abort, render_template, request, send_file
from markupsafe import Markup, escape

from catalog import CATALOG_HEADER, DESCRIPTION_HEADER, add_catalog_column, configured_catalog
from docx_reader import read_docx
from overview import collect, to_csv, to_xlsx
from rule_parser import DATA_CODE, HILITE, MARKS, STRIKE_OFF, STRIKE_ON, STRUCK, parse, to_tree

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200_000_000  # Word-skabeloner med billeder kan være store
app.config["MAX_FORM_MEMORY_SIZE"] = 50_000_000  # indsat tekst og eksportdata sendes som formularfelter

EXAMPLE = Path(__file__).with_name("test_document.docx")  # opdigtet eksempel
DATA_START = re.compile(rf"\s*{DATA_CODE}(?![^\s<>])")  # det, der står efter << i et datapunkt
PARTS = re.compile(f"{HILITE.pattern}|{MARKS.pattern}")
STRIKE_OPEN, STRIKE_CLOSE = Markup('<s class="strike">'), Markup("</s>")


class Highlighter:
    """Pakker flettefelter, regelhenvisninger, kommentarmærker, ELLER/OG og overstregning ind i HTML.

    Overstregning kan fortsætte fra én streng til den næste, så tilstanden huskes mellem kald.
    Hvert kald giver (html, struck): struck er True hvis al teksten er overstreget, False hvis
    noget af den ikke er, og None hvis der ingen tekst er.
    """

    def __init__(self) -> None:
        self.struck = False

    def __call__(self, text: str) -> tuple[Markup, bool | None]:
        out, pos, depth = [], 0, 0
        seen = {True: False, False: False}

        def plain(chunk: str) -> None:
            if chunk.strip(" |"):  # kolonneskillere alene holder ikke en linje i live
                seen[self.struck] = True
            out.append(escape(chunk))

        def delimiter(tok: str) -> Markup:
            """<< eller >>, overstreget hvis det har STRUCK foran."""
            struck = tok.startswith(STRUCK)
            seen[struck] = True
            return STRIKE_OPEN + tok[1:] + STRIKE_CLOSE if struck else escape(tok)

        if self.struck:
            out.append(STRIKE_OPEN)
        for m in PARTS.finditer(text):
            plain(text[pos:m.start()])
            pos, tok = m.end(), m.group()
            if tok.endswith("<<"):
                depth += 1
                cls = "field"
                if DATA_START.match(MARKS.sub("", text[pos:pos + 60])):  # datapunkt, fx <<10F …>> eller <<VM127 …>>
                    cls += " data"
                if tok.startswith(STRUCK):
                    cls += " cut"
                out.append(Markup('<span class="{}">').format(cls))
                out.append(delimiter(tok))
            elif tok.endswith(">>"):
                out.append(delimiter(tok))
                if depth:
                    depth -= 1
                    out.append(Markup("</span>"))
            elif tok in (STRIKE_ON, STRIKE_OFF):
                if self.struck != (tok == STRIKE_ON):
                    self.struck = not self.struck
                    out.append(STRIKE_OPEN if self.struck else STRIKE_CLOSE)
            elif tok == STRUCK:  # står kun alene foran et enkelt < (Layout), som ikke fremhæves
                pass
            else:
                seen[self.struck] = True
                cls = "ref" if tok[0] == "[" else "rule" if tok[0] == "(" else "op"
                out.append(Markup('<span class="{}">{}</span>').format(cls, tok))
        plain(text[pos:])
        if self.struck:
            out.append(STRIKE_CLOSE)
        out.append(Markup("</span>") * depth)
        return Markup("").join(out), False if seen[False] else True if seen[True] else None


def combine(states: list) -> bool | None:
    return False if False in states else True if True in states else None


def prepare(tree: list[dict]) -> list[dict]:
    """Gør træet klar til skabelonen og returnér et indeks over afsnittene.

    Tekster får fremhævet HTML, og linjer og blokke, der er helt overstregede, får struck=True.
    Indekset har en post for hver overskrift og hver blok. Indrykningen følger træet: alt inde i en
    blok står længere inde end blokken selv, og under en overskrift rykkes der ind efter dens niveau.
    """
    mark, index = Highlighter(), []

    def entry(item: dict, kind: str, indent: int, title: str) -> dict:
        item["id"] = f"s{len(index) + 1}"
        index.append({"id": item["id"], "kind": kind, "indent": indent, "struck": None,
                      "title": MARKS.sub("", title).strip()})
        return index[-1]

    def walk(items: list[dict], base: int) -> bool | None:
        # Overskrifter rykkes ind i forhold til den højeste overskrift i samme blok, så en overskrift
        # inde i en blok aldrig står længere ude end blokken
        top = min((item["level"] for item in items if item["type"] == "heading"), default=1)
        inside = base  # indrykning for blokke: ét trin inde under den seneste overskrift
        states = []
        for item in items:
            if item["type"] == "text":
                item["lines"] = [{"html": html, "struck": struck} for html, struck in map(mark, item["lines"])]
                states += [line["struck"] for line in item["lines"]]
                continue
            if item["type"] == "table":
                rows = [[mark(cell) for cell in row] for row in item["rows"]]
                item["rows"] = [{"cells": [html for html, _ in row], "struck": combine([struck for _, struck in row])}
                                for row in rows]
                item["struck"] = combine([row["struck"] for row in item["rows"]])
                states.append(item["struck"])
                continue
            if item["type"] == "heading":
                post = entry(item, "heading", base + item["level"] - top, item["text"])
                inside = post["indent"] + 1
                item["html"], item["struck"] = mark(item["text"])
                post["html"] = item["html"]
            else:
                post = entry(item, "block", inside, f'{item["opener"]}{item["label"]} {item["clauses"][0]}')
                opener_struck = item["opener"].startswith(STRUCK)
                item["opener"] = MARKS.sub("", item["opener"])
                item["label"], label_struck = mark(item["label"])
                clauses = [mark(clause) for clause in item["clauses"]]
                item["clauses"] = [html for html, _ in clauses]
                inner = walk(item["children"], inside + 1)
                closer_struck = None
                if item["closer"] is not None:
                    item["closer"], closer_struck = mark(item["closer"])
                # Åbningen og lukningen vises overstreget hver for sig; blokken er kun helt
                # overstreget (og skjules), når begge dele og alt indholdet er det
                item["opener_struck"] = opener_struck
                item["closer_struck"] = closer_struck
                # Indekset viser blokkens første linje med samme overstregning som i træet
                opener = STRIKE_OPEN + item["opener"] + STRIKE_CLOSE if opener_struck else escape(item["opener"])
                post["html"] = opener + item["label"] + " " + item["clauses"][0]
                post["head_struck"] = opener_struck
                item["struck"] = combine([opener_struck, label_struck, inner, closer_struck]
                                         + [struck for _, struck in clauses])
            post["struck"] = item["struck"]
            states.append(item["struck"])
        return combine(states)

    walk(tree, 0)
    return index


def stats(tree: list[dict], depth: int = 1) -> dict:
    """Tæl blokke, ulukkede blokke og største dybde."""
    total = {"blocks": 0, "unclosed": 0, "depth": 0}
    for item in tree:
        if item["type"] != "block":
            continue
        sub = stats(item["children"], depth + 1)
        total["blocks"] += 1 + sub["blocks"]
        total["unclosed"] += (item["closer"] is None) + sub["unclosed"]
        total["depth"] = max(total["depth"], depth, sub["depth"])
    return total


def load(path: Path) -> str:
    return read_docx(path) if path.suffix.lower() == ".docx" else path.read_text(encoding="utf-8")


@app.route("/", methods=["GET", "POST"])
def index():
    text = pasted = name = error = ""
    upload = request.files.get("file")
    try:
        if upload and upload.filename:
            name = upload.filename
            if name.lower().endswith(".docx"):
                text = read_docx(upload.stream)
            else:
                text = pasted = upload.stream.read().decode("utf-8")
        elif request.method == "POST":
            text = pasted = request.form.get("text", "")
        elif START.exists():
            text = load(START)
            name, pasted = (START.name, "") if START.suffix.lower() == ".docx" else ("", text)
    except Exception as exc:  # python-docx melder forskellige fejl alt efter, hvad der er galt med filen
        error = f"Kunne ikke læse {name}: {exc}"
    tree = to_tree(parse(text).children)
    counts = stats(tree) | {"struck": text.count(STRIKE_ON)}
    overview = collect(tree)  # før prepare, som laver teksterne om til HTML
    blocks = overview.pop("blocks")  # blokkene i kolonnen "Blokke"; skal ikke med i eksporten
    catalog, catalog_error = configured_catalog()
    details = {}  # kode → alle oplysninger fra kataloget, til vinduet over "Beskrivelse - katalog"
    if catalog:
        for table in (overview["rules"], overview["data"]):
            add_catalog_column(table, catalog)
            details.update({row[0]: catalog.fields(row[0]) for row in table["rows"] if row[0] in catalog})
    index = prepare(tree)  # giver hver blok et id i træet, som vinduet over "Blokke" kopierer fra
    blocks = {bid: {"name": block["name"], "line": block["line"], "target": block["item"]["id"],
                    "struck": bool(block["item"]["struck"])}  # helt overstreget blok
              for bid, block in blocks.items()}
    return render_template("index.html", text=pasted, name=name, error=error,
                           tree=tree, index=index, stats=counts, overview=overview,
                           catalog=catalog, catalog_error=catalog_error, catalog_details=details, blocks=blocks,
                           catalog_header=CATALOG_HEADER, description_header=DESCRIPTION_HEADER)


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.post("/export")
def export():
    """Send oversigten som fil. Siden sender selv tabellerne med, så serveren ikke skal huske dokumentet."""
    try:
        overview = json.loads(request.form["overview"])
        rules, data = ([table["headers"], table["rows"]] for table in (overview["rules"], overview["data"]))
    except (KeyError, TypeError, ValueError):
        abort(400)
    stem = Path(request.form.get("name") or "skabelon").stem
    kind = request.form.get("format")
    if kind == "xlsx":
        content, filename, mimetype = to_xlsx([("Regler", *rules), ("Datapunkter", *data)]), f"{stem} - regler og datapunkter.xlsx", XLSX_TYPE
    elif kind == "csv-rules":
        content, filename, mimetype = to_csv(*rules), f"{stem} - regler.csv", "text/csv"
    elif kind == "csv-data":
        content, filename, mimetype = to_csv(*data), f"{stem} - datapunkter.csv", "text/csv"
    else:
        abort(400)
    return send_file(io.BytesIO(content), mimetype=mimetype, as_attachment=True, download_name=filename)


# Filen, der vises ved start: python app.py [fil.docx | fil.txt]
START = Path(sys.argv[1]) if len(sys.argv) > 1 else EXAMPLE

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
