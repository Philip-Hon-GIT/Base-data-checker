# Base Data Checker (modulen `basedata`)

Kontrollerer grunnlagsdata som legges i en vanlig mappe – lokalt eller i en OneDrive-/SharePoint-mappe
som er synkronisert til PC-en – og fører et
**grunnlagsdataregister** med én rad per mottatt fil eller pakke – med de samme kolonnene som
regnearket dere bruker i dag: Rekkefølge, Dokumentnavn/Pakke, Innhold i fil/folder, Filtype, Dato
mottatt, Mottatt fra, Lenke, Ansvarlig fag for KS, Status kontroll (Ikke begynt / Pågår / Utført),
Dato kontrollert og Er dokument/fil klar til bruk? (Ja / Med forbehold / Nei).

Alt kjører på din egen PC. Det trengs ingen databaseserver: registeret, kommentarer, korreksjoner,
overstyringer, spørsmål og regelsett lagres i én SQLite-fil (SQLite følger med Python).

## Kom i gang på din egen mappe (Windows/PowerShell)

Gjør ett steg om gangen.

1. Åpne PowerShell i mappa der koden ligger (mappa med `requirements.txt`):

   ```powershell
   cd "$env:USERPROFILE\Downloads\basedata-checker"
   ```

2. Lag et eget Python-miljø og installer pakkene (bare første gang):

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

   Får du en feilmelding om at skript er blokkert, kjør
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` og prøv `Activate.ps1` igjen.

3. Start appen på mappa med grunnlagsdata (bytt ut stien med din egen):

   ```powershell
   python -m basedata start "$env:USERPROFILE\OneDrive - Multiconsult\Prosjekt\Grunnlagsdata"
   ```

   Første gang opprettes et prosjekt for mappa med standardinnstillinger (EUREF89 UTM32, NN2000) og
   standardregelsettet. Mappa leses, nettleseren åpnes på http://127.0.0.1:8000/basedata/, og mappa leses
   på nytt hvert 5. minutt så lenge vinduet er åpent. Stopp med `Ctrl+C`.

4. Gå til **Prosjektinnstillinger** og sett koordinatsystem, prosjektområde, formater og fag. Endringer
   kontrolleres på nytt med en gang.

Neste gang er det bare steg 1, `.\.venv\Scripts\Activate.ps1` og steg 3.

## Slik skal kildemappa se ut

```
Grunnlagsdata\                         ← kildemappa
  2026-10-27 Kartverket FKB\           ← én undermappe = én leveranse
    levering.yaml                      ← valgfri: hvem som leverte og når
    FKB_Bygning_2026.sos
    FKB_Veg_2026.sos
  2026-10-29 Laserdata\
    Laserdata_Nordby_2026\             ← mappe i leveransen; fra 5 filer blir den én pakke i registeret
      blokk1.las …
    Leveransenotat.txt                 ← .txt/.md leses som leveransenotat
  Notat.pdf                            ← filer rett i kildemappa: én leveranse per dag
  _basedata\register.db                ← registeret (lages av appen, leses ikke som grunnlagsdata)
```

- **Dato mottatt**: `mottatt` i `levering.yaml`, ellers datoen først i mappenavnet (ÅÅÅÅ-MM-DD), ellers
  filens endringstid.
- **Mottatt fra**: `mottatt_fra` og `epost` i `levering.yaml`, ellers «Ukjent» (kan rettes i appen).

  ```yaml
  mottatt_fra: Kari Nordmann
  epost: kari.nordmann@example.com
  mottatt: 2026-10-27
  ```

- **Ny versjon**: legg en fil med samme navn på samme sted (overskriv den gamle). Den kontrolleres på nytt,
  og registreringen går tilbake til KS. Uendrede filer kontrolleres ikke på nytt.
- Hoppes over: `_basedata`, skjulte filer og mapper (starter med `.`), Office-låsefiler (`~$…`),
  `desktop.ini`, `Thumbs.db` og `.tmp`-filer.
- Originalfilene endres aldri; de kopieres til en midlertidig mappe når de leses.
- Slettes en fil fra kildemappa, blir registreringen stående (med historikken). Flyttes eller gis den nytt
  navn, registreres den som en ny fil.
- I detaljpanelet viser «Sti» hvor fila ligger, og «Åpne fila» åpner den. I Excel-eksporten lenker
  kolonnen Lenke rett til fila (eller mappa for en pakke).

**OneDrive**: filer som bare ligger i skyen («Filer ved behov») lastes ned når de leses første gang.
SQLite-fila tåler ikke at to PC-er skriver samtidig. Er dere flere på samme mappe, la én person kjøre
appen, eller legg registeret lokalt med `--store "$env:USERPROFILE\basedata\prosjekt.db"`.

## Prøv demoen (syntetiske data)

```powershell
python -m basedata demo
```

Åpne http://127.0.0.1:8000/basedata/ – syntetiske leveranser for et oppdiktet vegprosjekt, lagt i en
kildemappe og kontrollert av den ekte koden, med brukerbytte (KS-ansvarlig og to opplastere). Ingenting
lagres. Testene kjøres med `python -m pytest`.

## Hva den gjør

- **Registeret** er én sorterbar liste, i rekkefølgen dataene ble mottatt. Alle kolonner kan sorteres.
  Klikk på en rad, så åpnes kontrollen rett under raden: spørsmål til opplaster (besvares der),
  automatisk kontroll per regel, sammenligning med godkjent referanse, AI-oppsummering, KS-felt,
  plassering på kart, metadata og historikk. Hver rad har en egen lenke (`#entry-<id>`).
- **Pakker**: når mange filer kommer i samme mappe (fra 5 filer, kan endres per prosjekt), registreres
  hele mappen som én rad. Hver fil i pakken kontrolleres likevel, og pakken får det dårligste
  resultatet. Detaljpanelet viser resultatet per fil.
- **Sammenligning med tidligere godkjente data**: terrengmodeller og punktskyer sammenlignes med den
  beste godkjente terrengmodellen eller punktskyen som overlapper (samme koordinatsystem). Begge gjøres
  om til et høyderutenett; kontrollen regner ut systematisk høydeavvik, spredning, 95 %-intervall,
  endret areal og om det ser ut som en horisontal forskyvning, og viser et differansekart.
  Grenseverdiene står i regel R-REF-01 og kan endres i regelsettet.
- **Nye versjoner**: appen foreslår hvilken tidligere registrering en ny fil erstatter (samme type,
  likt navn, overlappende område – eller valgt manuelt). Når den nye settes som klar til bruk, settes
  den gamle som **utgått**, og en utgått terrengmodell brukes ikke lenger som referanse. Gjenåpnes den
  nye, blir den gamle gjeldende igjen.
- **Prosjektinnstillinger** i appen: navn, kildemappe, prosjekttype, fase, koordinatsystem,
  høydesystem, prosjektområde, godkjente filformater, maks alder på data, purring, pakkegrense, fag og
  standard ansvarlig fag per datatype. Nye prosjekter opprettes samme sted.
- **Regelsettet kan redigeres** i appen: slå regler av og på, endre tekst, kilde, hva de gjelder for,
  resultat ved brudd og grenseverdier, eller legg til egne regler som AI vurderer ut fra teksten og en
  veiledning. AI kan foreslå regler fra innlimt kravtekst (kontrakt, BIM-krav, håndbok); forslagene
  må godkjennes før de lagres. Lagring gir en ny versjon, og alle registreringer kontrolleres på nytt.
- **Innholdsanalyse per datatype**: hver fil leses ut fra hva den er, ikke bare filtypen. En PDF kan
  være en tegning (tegningshode, tegningsnummer, målestokk, ark, revisjon, rutenettkoordinater som
  plasserer tegningen) eller et tekstdokument (rapport/beskrivelse med overskrifter, nøkkelord og
  eventuelle koordinater i teksten). IFC-modeller leses for skjema, georeferanse (IfcMapConversion /
  IfcProjectedCRS), innhold (rør, kummer, vegger …) og hvilket fag de hører til. Alt beskrives i samme
  form – en innholdsprofil med sammendrag og faktaliste – så detaljvisningen er lik for alle typer.
- **Relasjoner**: appen finner hvordan registreringene henger sammen – versjoner, referanse for
  sammenligning, tekst som omtaler andre filer eller tegningsnummer, samme leveranse og samme område.
- **AI-chat** («Spør AI»): søk og analyse i grunnlagsdataene med vanlige spørsmål. Modellen har
  lesetilgang gjennom fem verktøy (søk i registeret, les én registrering, relasjoner, søk i tekst i
  filene, prosjektoversikt) og viser til registreringer som #nummer. Uten AI-leverandør svarer en
  regelbasert erstatning på vanlige spørsmål og sier tydelig fra om det.
- **Rette opp feil fra AI eller fila**: hver verdi i «Om dataene» (datatype, koordinatsystem, høydesystem,
  dato, kilde, kvalitet, innhold og beskrivelse) kan korrigeres med blyanten, med en kommentar om hvorfor.
  Korreksjonen går foran både fila og AI, vises som «korrigert» med hvem, når og hva verdien var, og
  dataene kontrolleres på nytt. KS-ansvarlig kan også overstyre resultatet av en enkelt regel (begrunnelse
  er påkrevd). Alt kan tilbakestilles, og alt logges i historikken og eksporteres til Excel.
- **Kommentarer** på hver registrering, fra alle brukere. Opplasteren får varsel om nye kommentarer.
- **Kart i registeret**: et lite kart ved siden av oppsummeringen viser prosjektgrensen og alle
  grunnlagsdata som klikkbare fotavtrykk, farget etter automatisk kontroll. Det kan utvides til nesten hele
  skjermen («Utvid», eller lenken `#kart`), med filtrene, bakgrunnskart, tegnforklaring og verktøy for
  prosjektområdet i et sidepanel. Kart og tabell er koblet: kartet viser de samme registreringene som
  filtrene (også det nye filteret for datatype), klikk på et fotavtrykk åpner raden, peker over en rad
  fremhever fotavtrykket, og åpen rad markeres. Data med ukjent eller feil koordinatsystem vises stiplet der
  koordinatene passer («mulig plassering»). Bakgrunnskart fra åpne data: Kartverket topografisk (gråtone
  eller farge, CC BY 4.0) eller OpenStreetMap (ODbL). Kartet er en egen lett kartmotor uten eksterne
  biblioteker.
- **Reelle fotavtrykk** (`basedata/indata/footprint.py`), ikke bare et rektangel: vektordata tegnes med sin
  egentlige geometri – punkter som punkter, linjer som linjer og flater som flater (SOSI per objekt, DXF per
  element, GeoPackage/GeoJSON/Shapefile per geometritype). Store filer forenkles til et budsjett på 5000
  punkter, og blir det for mye, tegnes omrisset. Punktskyer og høydemodeller får omrisset av cellene som
  faktisk har data; tegninger, rapporter og IFC-modeller tegnes med kartrammen eller plasseringspunktene.
  Ortofoto som dekker hele ruta vises med utstrekningen (stiplet). Detaljpanelets «Plassering» bruker den
  samme geometrien.
- **Prosjektområdet** kan tegnes som rektangel eller polygon i kartet, eller importeres fra DXF (største
  lukkede polylinje), LandXML (Parcel/Boundary, `epsgCode` leses) eller GeoJSON. DWG er et lukket format
  og må lagres som DXF/LandXML først. Området lagres i prosjektets koordinatsystem og alt kontrolleres på
  nytt. Eksempelfiler ligger i `examples/`.
- **Norsk/engelsk**: bryteren NO/EN i toppmenyen bytter språk i grensesnittet (husket i nettleseren).
  Faste tekster, regeltekster, spørsmål, vanlige kontrollbelegg og meldinger oversettes; innhold fra filene,
  kommentarer og navn står som de er. AI-chatten svarer på valgt språk (offline-erstatningen bare på norsk).
- **Excel-eksport** med arkene Register (samme kolonner og farger som i appen), Filer, Kontroller,
  Spørsmål og Regelsett.

## Hva ligger hvor

Koden er delt i fem områder. Hvert område har sin egen mappe, og importer går bare «nedover» i denne
rekkefølgen: **core ← indata ← harness ← ui ← selfcheck** (sjekkes av `tests/core/test_boundaries.py`).
Testene ligger i en mappe per område under `tests/`.

| Område | Hva det gjør |
| --- | --- |
| `basedata/core/` | Kjernen alle bygger på: datamodellen og lagringen, innstillinger, felles tekster og datatyper. |
| `basedata/indata/` | Alt som har med filene å gjøre: kildemappa, lesere per format, koordinatsystemer, fotavtrykk og høydeflater. |
| `basedata/harness/` | Kontrollmotoren: arbeideren, regelsettet, vurderingen, AI, chat, spørsmål og varsler. |
| `basedata/ui/` | Det brukeren ser: tjenestelaget bak sidene, webappen og Excel-eksporten. |
| `basedata/selfcheck/` | Selvkontroll: demoprosjektet med syntetiske filer og byggeren for den frittstående demosiden. |

| Sti | Hva den gjør |
| --- | --- |
| `core/settings.py` | Innstillinger fra kommandolinje og miljøvariabler. |
| `core/db.py`, `core/localstore.py` | Samlingene i registeret og den lokale databasen: dokumentene i minnet, hver endring skrevet til SQLite-fila. |
| `core/memory_mongo.py` | Spørremotoren (find/update i MongoDB-stil) som den lokale databasen bygger på; ren minneversjon for tester og demo. |
| `core/classify.py`, `core/text.py` | Datatyper og fag, og faste tekster (status, resultat, livsløp). |
| `indata/folder_source.py` | Eneste kode som vet hvordan filene ligger: leveransemapper, `levering.yaml`, hva som hoppes over. |
| `indata/extract/` | Lesere per format: SOSI, GeoTIFF (+ world file, .prj, .aux.xml), LAS/LAZ, DXF, GeoPackage, GeoJSON, Shapefile, GML, PDF, IFC, tekst. |
| `indata/crs.py`, `indata/data/sosi_koordsys.yaml` | Norske koordinatsystemer (EUREF89 UTM/NTM, NGO, ED50), plausibilitet og dekning; SOSI-KOORDSYS-tabellen. |
| `indata/footprint.py` | Reelle fotavtrykk: punkter, linjer og flater, omriss av punktskyer og høydemodeller. |
| `indata/surface.py`, `indata/compare.py` | Høyderutenett fra terrengmodell/punktsky, og sammenligningen med referansen. |
| `indata/content.py` | Innholdsprofil per fil/registrering. |
| `harness/worker.py` | Finner nye og endrede filer i kildemappa, kontrollerer, grupperer i registeret, varsler. |
| `harness/rules.py`, `harness/data/default_rules_v1.yaml` | Innebygde kontroller og standardregelsettet. |
| `harness/evaluate.py` | Slår sammen verdier fra fil, opplaster og AI, kjører reglene og sammenligningen, lagrer resultatet. |
| `harness/ai/` | AI-steget (Claude eller Azure OpenAI over HTTPS), ledetekster, validering, og en offline erstatning for demo. |
| `harness/chat.py` | AI-chatten: verktøyene, samtalen med Claude/Azure, og offline-erstatningen. |
| `harness/questions.py`, `harness/prompts/questions_v1.yaml` | Hvilke spørsmål en registrering trenger, ordlyden, og hvordan svar leses. |
| `harness/entries.py`, `harness/relations.py` | Registerradene (pakker, versjoner, utgått/gjeldende) og relasjoner mellom registreringer. |
| `harness/notify.py`, `harness/parsing.py` | Varsler og påminnelser; tolking av dato og koordinatsystem fra fritekst. |
| `ui/service.py` | Operasjonene bak sidene: register, detalj, svar, KS, beslutning, innstillinger, regelsett. |
| `ui/web/` | Starlette-app (JSON-API + grensesnittet). Kan monteres i FastAPI eller Starlette. |
| `ui/local.py` | `start`: oppretter prosjektet for mappa, lokal bruker (KS-ansvarlig) og lesing hvert N. minutt. |
| `ui/export_excel.py` | Excel-eksporten. |
| `selfcheck/demo/` | Syntetiske leveranser, demo-historikk og byggeren for den frittstående demosiden. |

## Greiner og arbeidsflyt (git)

- `master` skal alltid være grønn: alle tester kjøres automatisk (GitHub Actions, Windows og Ubuntu) på hver
  pull request.
- Nytt arbeid gjøres på en kort gren som heter etter området, for eksempel `indata/onedrive-skip`,
  `harness/epost-varsler`, `ui/kart-filter` eller `selfcheck/golden-mappe`, og flettes inn i `master` via en
  pull request innen noen dager.
- Endringer som går på tvers av områder (som denne mappeflyttingen) får grenen `refactor/…`.
- Utgivelser merkes med en tag, for eksempel `v0.3.0`.

Leserne er ren Python, så **GDAL trengs ikke**. Er `pyproj`, `rasterio`, `laspy` eller `pyogrio`
installert, brukes de automatisk (eksakte transformasjoner, flere formater, LAZ).

## Innstillinger (kommandolinje og miljøvariabler)

| Kommandolinje | Miljøvariabel | Standard | Betydning |
| --- | --- | --- | --- |
| `start MAPPE` / `run --folder MAPPE` | `BASEDATA_SOURCE_FOLDER` | – | Mappa med grunnlagsdata |
| `--store FIL` | `BASEDATA_STORE` | `MAPPE\_basedata\register.db` | SQLite-fila med registeret |
| `--port` | – | `8000` | Porten appen kjører på |
| `--project`, `--name` | – | ut fra mappenavnet | Prosjekt-ID og navn første gang |
| – | `BASEDATA_SCAN_MINUTES` | `5` | Hvor ofte mappa leses (0 = bare med «Kontroller nye filer») |
| – | `BASEDATA_USER_NAME`, `BASEDATA_USER_EMAIL` | Windows-brukernavnet, tom | Hvem du er i historikken og kommentarene |
| – | `BASEDATA_AI_PROVIDER` | tom | `anthropic`, `azure_openai` eller `offline_demo` |
| – | `BASEDATA_AI_MODEL`, `BASEDATA_AI_API_KEY` | tom | Modell (eller Azure-deployment) og nøkkel |
| – | `BASEDATA_AZURE_ENDPOINT`, `BASEDATA_AZURE_API_VERSION` | tom, `2024-10-21` | For Azure OpenAI |
| – | `BASEDATA_REVIEW_BELOW_CONFIDENCE` | `0.7` | AI-resultater under denne sikkerheten merkes for KS |

Sett en miljøvariabel i PowerShell før `start`, for eksempel `$env:BASEDATA_SCAN_MINUTES = "10"`.

Andre kommandoer:

```powershell
python -m basedata run --folder "C:\...\Grunnlagsdata"          # les mappa én gang, uten nettleser
python -m basedata run --folder "C:\...\Grunnlagsdata" --force  # kontroller alle filer på nytt
python -m basedata reminders --folder "C:\...\Grunnlagsdata"    # purringer på gamle spørsmål (under Varsler)
python -m basedata build-demo demo.html                         # den frittstående demosiden
```

## Hva ligger i register.db

Én tabell `docs` med ett JSON-dokument per rad i samlingene `basedata_entries` (registerradene),
`basedata_files` (hver fil, også i pakker), `basedata_checks`, `basedata_questions`, `basedata_projects`,
`basedata_rulesets` (én versjon per dokument), `basedata_runs` og `basedata_notifications`, og en tabell
`blobs` med høyderutenett for sammenligning. Ta sikkerhetskopi ved å kopiere fila mens appen er stoppet.
Fila kan åpnes med for eksempel «DB Browser for SQLite», men endre den bare gjennom appen.

Varsler og spørsmål til opplastere sendes ikke på e-post; de vises på siden Varsler og i registeret.
Ingenting sendes ut av PC-en, bortsett fra metadata og korte tekstutdrag til AI-leverandøren hvis du
setter `BASEDATA_AI_PROVIDER`.

## Før dere tar den i bruk på et ekte prosjekt

1. Kjør `start` på en **kopi** av en ekte grunnlagsdatamappe og sammenlign registeret med det dere vet om
   filene (golden-testen i `tests/harness/test_pipeline.py` viser hvordan).
2. Kontroller `basedata/indata/data/sosi_koordsys.yaml` mot Kartverkets SOSI-dokumentasjon.
3. Bytt eksempelkildene i standardregelsettet («Kontrakt pkt. x.x – avklar …») med kontraktens
   faktiske punkter, og sett toleransene i R-REF-01 sammen med fagansvarlig.
4. Få AI-leverandøren godkjent før `BASEDATA_AI_PROVIDER` settes. Bare metadata og korte tekstutdrag
   sendes, aldri selve datafilene.

## Testet her, og hva som ikke er testet

Testene dekker leserne (også PDF-tegning, rapport og IFC) og fotavtrykkene (punkter, linjer og flater per
format), innholdsprofiler, relasjoner, AI-chatten, korreksjoner, overstyringer og kommentarer, kartdata og
prosjektområde, koordinatberegningene, registeret og pakkene, sammenligning med referanse, utgått/gjeldende,
spørsmål og svar, KS-tilganger, prosjektinnstillinger, redigering og versjonering av regelsett,
AI-validering og regelforslag, Excel-eksporten og HTTP-API-et. Nytt i 0.2: kildemappa (leveransemapper,
`levering.yaml`, dato fra mappenavn, filer som hoppes over, nye versjoner ved overskriving), at registeret
i SQLite-fila overlever en omstart, `run --folder` fra kommandolinjen, «Åpne fila» og fil-lenker i Excel.

Testene er kjørt på Linux med Python 3.13. Fra 0.2.1 kjøres de også automatisk på Windows og Ubuntu (Python 3.12) på hver pull request, og `tests/core/test_boundaries.py` sjekker at områdene bare importerer nedover. **Ikke testet ennå**: på Windows, på en ekte OneDrive-mappe
(også filer som bare ligger i skyen), med to personer på samme mappe, med store mengder data (registeret
holdes i minnet mens appen kjører), og ekte AI-kall og pyproj/rasterio/laspy/pyogrio.
