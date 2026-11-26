# Base Data Checker (`basedata`)

Modul for Multiconsults interne Python-app. Leser grunnlagsdata fra en lokal mappe/OneDrive-mappe,
kontrollerer hver fil mot håndbok og BIM-/kontraktskrav (redigerbart, AI-assistert regelsett), stiller
spørsmål til opplasteren og fører grunnlagsdataregisteret med de samme kolonnene som teamets Excel-register.

## Eier

BIM-/samferdselsprosjekterende, ikke utvikler: forklar oppsett ett steg om gangen, med komplette
kommandoer (Windows/PowerShell først).

## Områder (se README, «Hva ligger hvor»)

`basedata/core` ← `indata` ← `harness` ← `ui` ← `selfcheck`. Importer går bare nedover og er absolutte
(`from basedata.indata import crs`). `tests/core/test_boundaries.py` håndhever dette.
Testene ligger i `tests/<område>/`.

## Arkitektur som skal beholdes

- Starlette-weblag montert i appen, tjenestelag (`ui/service.py`), arbeider (`harness/worker.py`), lesere per format.
- Fotavtrykk i `indata/footprint.py`. Egen kartmotor i `ui/web/static` (ingen eksterne JS-biblioteker, ingen CDN).
- Egen koordinatmatematikk i `indata/crs.py` (EUREF89 UTM/NTM, NN2000).
- Grensesnittet er norsk som standard med EN-bryter. Kodekommentarer og UI-tekst på norsk.

## Kommandoer

- `pip install -r requirements.txt`
- `python -m pytest -q` (alle tester; kjøres også i GitHub Actions på Windows og Ubuntu)
- `python -m basedata demo` – demo på http://127.0.0.1:8000/basedata/
- `python -m basedata start "<mappe>"` – kjør på en ekte mappe
- `python -m basedata build-demo <fil.html>` – bygg den frittstående demosiden

## Regler for hver endring

- Kort gren oppkalt etter området (`indata/…`, `harness/…`, `ui/…`, `selfcheck/…`, `refactor/…`), pull request mot `master`, CI grønn.
- Oppdater tester, kjør dem, oppdater README, bygg demosiden på nytt, og si tydelig hva som er og ikke er testet.
- Aldri commit prosjektdata, kundedata eller hemmeligheter (se `.gitignore`). Bare syntetiske data i demo/tester.
- Ikke send eierens e-post eller prosjektdata til eksterne tjenester.
