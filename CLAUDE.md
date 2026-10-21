# Regelstruktur

Se `README.md` for formål, kørsel, syntaks og filoversigt.

Retningslinjer for ændringer:

- Kode skal helst kun bruge Pythons standardbibliotek. Undtagelser: Flask (webappen) og python-docx
  (indlæsning af Word-filer). `rule_parser.py`, `overview.py`, `catalog.py` og `print_rules.py` på
  tekstfiler må ikke kræve andet end standardbiblioteket.
- Koden skal kunne køre på Python 3.9 (fx ingen backslash i f-string-udtryk).
- Siden skal virke uden internetadgang: ingen CDN'er, alt ligger lokalt i `static/`.
- Læg aldrig rigtige skabeloner, kataloger eller andre data i repoet.
- Farverne ligger i `static/custom.css` ("Sage and Sand") som Bootstrap 5.3-variabler oven på Bootstrap;
  skabelonens egen `<style>` står før den. Hvad der tæller som et datapunkt, styres af `DATA_CODE` i
  `rule_parser.py`.
- Der er ingen automatiske tests; kontrollér ændringer ved at køre begge visninger på `test_document.docx`.
