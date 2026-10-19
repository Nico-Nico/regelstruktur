# Regelstruktur

Se `README.md` for formål, kørsel, syntaks og filoversigt.

Retningslinjer for ændringer:

- Kode skal helst kun bruge Pythons standardbibliotek. Undtagelser: Flask (webappen) og python-docx
  (indlæsning af Word-filer). `rule_parser.py`, `overview.py`, `catalog.py` og `print_rules.py` på
  tekstfiler må ikke kræve andet end standardbiblioteket.
- Koden skal kunne køre på Python 3.9 (fx ingen backslash i f-string-udtryk).
- Siden skal virke uden internetadgang: ingen CDN'er, alt ligger lokalt i `static/`.
- Læg aldrig rigtige skabeloner, kataloger eller andre data i repoet.
- Der er ingen automatiske tests; kontrollér ændringer ved at køre begge visninger på `test_document.docx`.
