# Regelstruktur

Gør Word-skabeloner med indlejrede `<<...>>`-regler overskuelige. Skabelonen vises som et indrykket,
sammenfoldeligt træ, så man kan se, hvilke blokke der hører sammen, hvor de lukkes, og hvor en lukning
mangler. Der er også en oversigt over alle regler og datapunkter, som kan eksporteres til Excel eller CSV.

Værktøjet findes i to udgaver:

- **En lille webapp** (Flask), der kører lokalt i browseren.
- **Et terminalprogram**, der printer træet med farver.

## Kom i gang

Kræver Python 3.9 eller nyere.

```
git clone <repo-url>
cd regelstruktur
python -m venv .venv
```

Aktivér miljøet og installér pakkerne (Flask og python-docx):

```
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Start appen og åbn <http://127.0.0.1:5001> i browseren:

```
python app.py                    # viser den opdigtede test_document.docx
python app.py skabelon.docx      # viser en bestemt fil ved start
```

Port 5000 er undgået, fordi den er optaget af AirPlay på macOS.

## Webappen

- **Indlæs en skabelon:** træk en `.docx` ind hvor som helst i vinduet, eller klik på feltet øverst.
  Tekst kan også indsættes direkte under "… eller indsæt tekst".
- **Træet:** hver `<<...>>`-blok er en farvet ramme, der kan foldes sammen. Overskrifter fra Word vises
  i størrelse efter niveau, og Word-tabeller vises som tabeller. Datapunkter som `<<10F vurderingsår>>`
  og `<<VM127 …>>` har gul baggrund. Et klik på en regel eller et datapunkt fører til dens række under
  "Regler og datapunkter".
- **Manglende lukninger:** en blok, der aldrig lukkes, er markeret med MANGLER LUKNING ved åbningen og
  "… mangler lukning" med blokkens navn, der hvor den slutter.
- **Overstreget tekst:** tekst, der er overstreget i Word (eller slettet med "Registrer ændringer"),
  vises med streg igennem og kan skjules med knappen øverst til højre. Blokke, hvis egen åbning er
  overstreget, men som indeholder noget, der ikke er, "pakkes ud", når overstreget tekst skjules.
- **Indekset** til venstre viser alle overskrifter og blokke. Fluebenene tænder og slukker afsnit,
  og et klik ruller hen til afsnittet. Bredden kan trækkes i kanten.
- **Højreklik** på et afsnit (i indekset eller i træet) giver "Vis kun dette afsnit", "Vis alle
  afsnit" og, i træet, "Vis i indeks". Hold Shift nede for browserens egen menu.
- **Fanerne** "Struktur" og "Regler og datapunkter" står fast øverst, og hver fane husker, hvor langt
  man var nede på siden.
- **Fanen "Regler og datapunkter"** viser alle regler (`(R123=TRUE)`) og datapunkter (`<<10F ...>>`,
  `<<VM127 ...>>`). Kolonnen "Blokke" har én linje pr. blok, reglen eller datapunktet står i, og
  beskrivelsen fra skabelonen står på samme linje. Rækker, hvor alt er overstreget, forsvinder, når
  overstreget tekst skjules. Tabellerne kan eksporteres til Excel (.xlsx) eller CSV (semikolon, så
  dansk Excel åbner dem rigtigt).
- **Detaljepanelet** i den nederste del af skærmen viser blokken, beskrivelsen fra skabelonen, beskrivelsen
  fra kataloget og alle katalogets oplysninger for den blok, musen er over i kolonnen "Blokke". Et klik
  fastholder blokken (klik igen eller tryk Esc for at slippe), og panelets højde kan trækkes i kanten.

### Katalog over regler og datapunkter

Har man et katalog over regler og datapunkter i EDN-format, viser fanen "Regler og datapunkter" en
kolonne "I katalog", der er grøn, hvis koden findes i kataloget, og sandfarvet, hvis den ikke gør, og en
kolonne "Beskrivelse - katalog" med kodens `:beskr`.

1. Kopiér `config.example.ini` til `config.ini`.
2. Skriv stien til katalogfilen:

   ```ini
   [katalog]
   sti = C:\Users\navn\repos\katalog\katalog.edn
   ```

`config.ini` committes ikke, fordi stien er forskellig fra maskine til maskine. Kataloget læses igen,
når filen ændres, så en `git pull` i katalogets repo slår igennem ved næste genindlæsning.

Kataloget forventes at være et map, hvor hver nøgle er en regel eller et datapunkt:

```clojure
{:R895b {:titel "R895b: kort beskrivelse" ...}
 :10F   {:titel "10F: kort beskrivelse" ...}}
```

En kode tæller som fundet, hvis den står som nøgle (evt. med navnerum, fx `:regel/R895b`) eller
forrest i `:titel` før et kolon. Store og små bogstaver er ligegyldige.

## Terminalprogrammet

```
python print_rules.py                       # test_document.docx
python print_rules.py skabelon.docx         # en Word-fil
python print_rules.py skabelon.docx --hide-strike
python print_rules.py regler.txt            # en tekstfil
python print_rules.py -s '<<K1 <<Hvis x (R1=TRUE)\ntekst\n>>K1>>'
python print_rules.py -                     # læs fra stdin
```

`--no-color` slår farver fra, og `--width N` sætter bredden. På tekstfiler kræver terminalprogrammet
kun Pythons standardbibliotek.

## Syntaksen, som parseren forstår

- `<<NAVN ... NAVN>>` – navngiven blok (`K970a`, `LOOP`, `BLOK 187 [...]`). En blok lukkes af
  begyndelsen af sin første linje: hele linjen, de første ord eller kun første ord, uanset store og
  små bogstaver. `<<BLOK 187 [Bonusfritekstfelt]` lukkes altså af `Blok 187>>`.
- `<<Hvis betingelse` + linjeskift + indhold + `>>` – betingelsen er første linje. Et bart `>>`
  lukker altid den inderste åbne blok.
- `<Layout: navn ... Layout>>` – kan også åbnes med kun ét `<`.
- `<<140dGV adresse referenceejendom>>` – flettefelt/datapunkt. Alt, der åbnes og lukkes uden
  linjeskift, vises på én linje.
- `(R895b=TRUE)` er en regelhenvisning, `[AV189.1]` et kommentarmærke, og `ELLER`/`OG` deler en
  betingelse i led.

Kendt særhed: mangler en lukning, kan "mangler lukning" lande på en ydre blok frem for den rigtige, og
lukkes en ydre blok ved navn, regnes alle åbne blokke inden i den som ulukkede.

## Filer

| Fil | Indhold |
|---|---|
| `rule_parser.py` | Parseren: `parse(text)` giver et træ, `to_tree(...)` simple dicts til visning. Kun standardbibliotek. |
| `docx_reader.py` | Laver en `.docx` om til tekst til parseren (overskrifter, overstregning, tabeller). Kræver python-docx. |
| `overview.py` | Finder regler og datapunkter og skriver CSV og XLSX. Kun standardbibliotek. |
| `catalog.py` | Læser kataloget (EDN) og stien til det fra `config.ini`. Kun standardbibliotek. |
| `app.py`, `templates/index.html`, `static/` | Webappen. Bootstrap ligger i `static/`, så siden virker uden internet. |
| `print_rules.py` | Terminalprogrammet. |
| `test_document.docx` | Opdigtet skabelon til afprøvning. |

Der er ingen automatiske tests; kontrollér ændringer ved at køre begge visninger på `test_document.docx`.

## Rigtige skabeloner og kataloger

Læg aldrig rigtige skabeloner, kataloger eller andre data i repoet. `.gitignore` holder alle `.docx`
(undtagen `test_document.docx`), alle `.edn` og `config.ini` ude.
