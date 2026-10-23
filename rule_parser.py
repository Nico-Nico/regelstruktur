"""Parser for regel-strenge med indlejrede <<...>>-blokke.

Syntaks der genkendes:
  <<NAVN ... NAVN>>   navngiven blok (K970a, LOOP, Loop over ..., osv.)
  <<Hvis ... >>       blok der lukkes med et "bart" >>
  <Layout: ... Layout>>
  <<140dGV ...>>      flettefelt (står på én linje og vises inline)

Teksten kan desuden indeholde mærker, som docx_reader.py sætter ind (tegn fra Unicodes
private område): STRIKE_ON/STRIKE_OFF omkring overstreget tekst, STRUCK lige foran et overstreget
<< eller >>, HEADING + niveau (1-9) først på en linje, der er en overskrift, og ROW først på en
linje, der er en tabelrække, med CELL mellem cellerne.

Bruges af app.py (Flask).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

STRIKE_ON, STRIKE_OFF, HEADING, STRUCK = "\ue000", "\ue001", "\ue002", "\ue003"
ROW, CELL = "\ue004", "\ue005"
# Et enkelt < åbner kun, når et navn med kolon følger (<Layout:); navnet kan være overstreget
TOKEN = re.compile(f"({STRUCK}?(?:<<|>>|<(?={STRIKE_ON}?\\w+:)))")
HILITE = re.compile(STRUCK + r"?(?:<<|>>)|\[[A-Z]*\d+\.\d+\]|\(R\w+=\w+\)|\b(?:ELLER|OG)\b")
OPERATOR = re.compile(r"<<|>>|[()]|\b(?:ELLER|OG)\b")
MARKS = re.compile(f"[{STRIKE_ON}{STRIKE_OFF}{STRUCK}]")
# Koden i et datapunkt: et tal først (10F, 140dGV) eller op til fire bogstaver og et tal (VM127, VM91c_db).
# K123 er blokke og R123 regler, så de tæller ikke.
DATA_CODE = r"(?:\d\w*|(?![KkRr]\d)[A-Za-z]{1,4}\d\w*)"
MAX_LABEL_WORDS = 8  # så mange ord af første linje kan indgå i et lukke-navn
LABEL = re.compile(f"{STRIKE_ON}?[\\w=]+:?{STRIKE_OFF}?")


@dataclass
class Node:
    opener: str = ""  # "<<" eller "<", evt. med STRUCK foran
    children: list = field(default_factory=list)  # str | Node
    closer: str | None = None  # lukke-navn + ">>", evt. med mærker; None = blokken blev aldrig lukket
    _closers: list | None = field(default=None, repr=False, compare=False)

    def closers(self) -> list[re.Pattern]:
        """Mønstre for det, der kan stå foran >> for at lukke netop denne blok, længste først.

        Et lukke-navn er begyndelsen af blokkens første linje: hele linjen, de første ord eller
        bare det første ord. <<BLOK 187 [Bonusfritekstfelt] kan altså lukkes med "Blok 187>>".
        Store og små bogstaver og antallet af mellemrum er ligegyldigt.
        """
        if self._closers is None:
            first = self.children[0] if self.children and isinstance(self.children[0], str) else ""
            words = MARKS.sub("", first.split("\n", 1)[0]).split()[:MAX_LABEL_WORDS]
            names = [words[:n] for n in range(len(words), 0, -1)]
            core = re.match(r"\w+", words[0]) if words else None  # <Layout: lukkes med Layout>>
            if core and [core.group()] not in names:
                names.append([core.group()])
            self._closers = [
                re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, name)) + r"\Z", re.IGNORECASE) for name in names
            ]
        return self._closers

    def is_inline(self) -> bool:
        return self.closer is not None and all(
            c.is_inline() if isinstance(c, Node) else "\n" not in c for c in self.children
        )


def strip_label(text: str, name: re.Pattern) -> tuple[str, str] | None:
    """Fjern et lukke-navn fra slutningen af teksten; None hvis det ikke står der.

    Returnerer teksten uden navnet og navnet, som det skal vises (med mærker, hvis det er overstreget).
    """
    body = text.rstrip()
    struck = body.endswith(STRIKE_OFF)
    if struck:
        body = body[:-1]
    found = name.search(body)
    if not found:
        return None
    body, label = body[: found.start()], found.group()
    if struck:  # hold mærkerne i balance, når det overstregede navn er væk
        body = body[:-1] if body.endswith(STRIKE_ON) else body + STRIKE_OFF
        label = STRIKE_ON + label + STRIKE_OFF
    return body, label


def find_close(stack: list[Node]) -> tuple[Node, str, str]:
    """Find den blok et >> lukker: den navngivne hvis der står et navn foran, ellers den inderste.

    Returnerer blokken, navnet (som det skal vises) og teksten foran >> uden navnet.
    """
    top = stack[-1]
    last = top.children[-1] if top.children else ""
    before = last if isinstance(last, str) else ""
    for node in reversed(stack[1:]):
        for name in node.closers():
            found = strip_label(before, name)
            if found is None:
                continue
            rest, shown = found
            # Blokkens egen åbningstekst er ikke et lukke-navn (fx <<140dGV adresse>>)
            if node is top and len(top.children) == 1 and not rest.strip():
                continue
            return node, shown, rest
    return top, "", before


def parse(text: str) -> Node:
    """Returnér en rod-node, hvis children er strengens indhold på yderste niveau."""
    root = Node()
    stack = [root]
    for tok in TOKEN.split(text.replace("\r\n", "\n")):
        top = stack[-1]
        bare = tok.lstrip(STRUCK)
        if bare in ("<<", "<"):
            node = Node(opener=tok)
            top.children.append(node)
            stack.append(node)
        elif bare == ">>" and len(stack) > 1:
            target, label, rest = find_close(stack)
            if label:
                top.children[-1] = rest
            while stack[-1] is not target:  # blokke imellem forbliver ulukkede
                stack.pop()
            target.closer = label + tok
            stack.pop()
        elif tok:
            top.children.append(tok)
    return root


def flat(item) -> str:
    """Skriv en inline-node (eller tekst) tilbage som den stod i kilden."""
    if isinstance(item, str):
        return item
    return item.opener + "".join(flat(c) for c in item.children) + (item.closer or "")


CONDITION = re.compile(r"\W*hvis\b", re.IGNORECASE)


def split_header(node: Node) -> tuple[str, list]:
    """Del en blok i overskrift (første linje) og indhold.

    I en Hvis-blok er hele første linje betingelsen, også indlejrede <<...>> som <<K953=TRUE (...)K953>>.
    I andre blokke (BLOK, K-blokke, FORMATERINGSREGEL, Layout ...) er overskriften kun navnet: en hel
    <<...>> længere henne på linjen er blokkens første element og hører til indholdet.
    """
    first = node.children[0] if node.children and isinstance(node.children[0], str) else ""
    named = not CONDITION.match(MARKS.sub("", first))
    header = ""
    for i, child in enumerate(node.children):
        if isinstance(child, Node):
            if not child.is_inline() or (named and MARKS.sub("", header).strip()):
                return header, node.children[i:]
            header += flat(child)
        elif "\n" in child:
            head, rest = child.split("\n", 1)
            return header + head, [rest] + node.children[i + 1:]
        else:
            header += child
    return header, []


def split_clauses(text: str) -> list[str]:
    """Del en betingelse ved ELLER/OG på yderste niveau (ikke inde i parenteser eller <<...>>)."""
    clauses, depth, start = [], 0, 0
    for m in OPERATOR.finditer(text):
        tok = m.group()
        if tok in ("<<", "("):  # et STRUCK foran << eller >> ændrer ikke på, hvad der matches her
            depth += 1
        elif tok in (">>", ")"):
            depth = max(0, depth - 1)
        elif depth == 0:
            cut = m.start() - text.endswith(STRIKE_ON, 0, m.start())  # et overstreget ELLER/OG beholder sit mærke
            clauses.append(text[start:cut])
            start = cut
    clauses.append(text[start:])
    return [c.strip() for c in clauses if c.strip()]


def text_lines(buf: str) -> list[str]:
    """Ryd op i løs tekst: kolonner adskilles med |, og tomme linjer i kanten fjernes."""
    lines: list[str] = []
    for raw in buf.split("\n"):
        line = re.sub(r"\t| {3,}", " | ", raw.rstrip()).strip()
        if line or (lines and lines[-1]):
            lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def block_name(header: str) -> str:
    """Kort navn til meddelelser om blokken, fx "BLOK 345" for <<BLOK 345 [Indledning] ..."""
    name = " ".join(MARKS.sub("", header).split())
    name = re.split(r" [\[(]", name, maxsplit=1)[0]  # skær [kommentar] og (R123=TRUE) fra
    return name if len(name) <= 40 else name[:39].rstrip() + "…"


def to_tree(items: list) -> list[dict]:
    """Lav en nodes indhold om til simple dicts, klar til visning (fx i en skabelon).

    Hvert element er enten {"type": "text", "lines": [...]}, {"type": "heading", "level", "text"},
    {"type": "table", "rows": [[celle, ...], ...]} eller
    {"type": "block", "opener", "label", "clauses", "closer", "name", "children"}.

    En blok, der åbner eller lukker midt i en tabel, deler tabellen: rækkerne før, i og efter blokken
    bliver hver sin tabel, og en række, der brydes af blokken, bliver til to stumper.
    """
    tree: list[dict] = []
    buf = ""

    def flush() -> None:
        lines: list[str] = []
        rows: list[list[str]] = []

        def flush_lines() -> None:
            while lines and not lines[-1]:
                lines.pop()
            if lines:
                tree.append({"type": "text", "lines": lines[:]})
            lines.clear()
            if rows:
                tree.append({"type": "table", "rows": rows[:]})
            rows.clear()

        for line in text_lines(buf):
            if line.startswith(ROW) or CELL in line:
                if lines:
                    flush_lines()
                cells = [cell.strip() for cell in line.replace(ROW, "").split(CELL)]
                if len(cells) > 1 or cells[0]:  # et ROW alene er resten af en række, en blok har taget
                    rows.append(cells)
            elif line.startswith(HEADING):
                flush_lines()
                level, title = line[1:2], line[2:].strip()
                if title:
                    tree.append({"type": "heading", "level": int(level) if level.isdigit() else 1, "text": title})
            elif line or lines:
                if rows:
                    flush_lines()
                lines.append(line)
        flush_lines()

    for item in items:
        if isinstance(item, Node) and not item.is_inline():
            flush()
            buf = ""
            header, body = split_header(item)
            header = header.replace(ROW, "").replace(CELL, " | ")
            clauses = split_clauses(header) or [""]
            label = LABEL.match(clauses[0])
            cut = label.end() if label else 0
            tree.append({
                "type": "block",
                "opener": item.opener,
                "label": clauses[0][:cut],
                "clauses": [clauses[0][cut:].strip()] + clauses[1:],
                "closer": item.closer,
                "name": block_name(header) or "Blok uden navn",
                "children": to_tree(body),
            })
        else:
            buf += flat(item)
    flush()
    return tree
