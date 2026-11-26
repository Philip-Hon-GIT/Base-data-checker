/* Base Data Checker – grensesnitt.
   Snakker med modulens JSON-API (api/...). I demoen ligger kontrollresultatene i window.BASEDATA_DEMO,
   og en stedfortreder i siden svarer på de samme API-kallene. */
(function () {
  "use strict";

  const DEMO = window.BASEDATA_DEMO || null;
  const DONT_KNOW = "Vet ikke";
  const RESULT_ORDER = { pending: -1, ok: 0, warning: 1, missing_info: 2, needs_review: 3, deviation: 4 };
  const RESULTS = ["deviation", "needs_review", "missing_info", "warning", "ok"];
  const LABELS = { ok: "OK", warning: "Advarsel", missing_info: "Mangler info", needs_review: "Må vurderes", deviation: "Avvik", pending: "Venter" };
  const QA = { ikke_begynt: "Ikke begynt", pagar: "Pågår", utfort: "Utført" };
  const QA_ORDER = { ikke_begynt: 0, pagar: 1, utfort: 2 };
  const READY = { ja: "Ja", med_forbehold: "Med forbehold", nei: "Nei" };
  const READY_ORDER = { ja: 0, med_forbehold: 1, nei: 2 };
  const CHECKED_BY = { code: "kode", ai: "AI", manuell: "manuell", reviewer: "manuell" };
  const FROM = {
    file: ["fra fila", ""], uploader: ["opplaster", "uploader"], ai_text: ["AI · fra tekst", "ai"],
    uploader_unknown: ["opplaster: vet ikke", "uploader"], uploader_local: ["opplaster: lokale", "uploader"], manual: ["korrigert", "manual"],
  };
  const FIELD_LABELS = { horizontal_epsg: "Koordinatsystem", height_reference: "Høydesystem", data_date: "Dato",
    source: "Kilde / leverandør", quality: "Nøyaktighet", comments: "Kommentarer" };
  const ICON_LINK = '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M6.5 9.5l3-3M7 4.5l1.2-1.2a2.6 2.6 0 0 1 3.7 3.7L10.7 8.2M9 11.5l-1.2 1.2a2.6 2.6 0 0 1-3.7-3.7l1.2-1.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';
  const ICON_SPARK = '<svg class="spark" width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5l1.6 4.2 4.4 1.6-4.4 1.6L8 13.1 6.4 8.9 2 7.3l4.4-1.6zM13 11.5l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6z" fill="currentColor"/></svg>';
  const ICON_PEN = '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M10.5 2.5l3 3L5 14H2v-3z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  const ICON_READY = {
    ja: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2.5 7.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    med_forbehold: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M7 2v6M7 11v.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    nei: '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 3l8 8M11 3l-8 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  };

  const state = {
    me: null, projects: [], projectId: null, entries: [], open: null, detail: null, cmpFile: {}, pendingReady: null,
    sort: { key: "received_at", dir: 1 },
    filters: { q: "", fag: "", qa: "", ready: "", result: "", type: "", mine: false, showOld: true },
    mapData: null, map: null, mapBig: false, mapHl: null, mapDraft: null,
    view: "", newProject: false, rules: null, ruleEdit: null, drafts: null,
    blocks: {}, edit: null, chat: { pid: null, messages: [], busy: false, draft: "" }, chatOpen: false,
  };
  const mobile = window.matchMedia("(max-width: 760px)");

  // --- Hjelpere ----------------------------------------------------------------------------------
  let LANG = "nb";
  const t = (s) => (LANG === "en" ? I18N.translate(s) : s);
  const LOC = () => (LANG === "en" ? "en-GB" : "nb-NO");
  // --- Språk: norsk (standard) og engelsk -------------------------------------------------------------------
  // Grensesnittet skrives på norsk. I engelsk modus oversettes tekstnoder og attributter etter hvert som de
  // settes inn (MutationObserver): først eksakte treff i ordlisten, deretter mønstre for sammensatte tekster.
  // Data (filnavn, sitater fra filene, brukernes kommentarer, AI-svar) oversettes ikke.
  const I18N = (() => {
    const dict = {
      // Ramme og navigasjon
      "Register": "Register", "Kart": "Map", "Prosjektinnstillinger": "Project settings", "Regelsett": "Rule set", "Varsler": "Notifications",
      "Prosjekt": "Project", "Vis som": "View as", "Spør AI": "Ask AI", "Sider": "Pages", "Laster…": "Loading…",
      "Base Data Checker, register": "Base Data Checker, register", "Tilbake til registeret": "Back to the register",
      "Demo med syntetiske data for et oppdiktet prosjekt. AI-resultatene kommer fra en regelbasert erstatning, ikke en AI-modell. Ingenting du gjør her lagres.":
        "Demo with synthetic data for a fictional project. The AI results come from a rule-based stand-in, not an AI model. Nothing you do here is saved.",
      // Register
      "Grunnlagsdataregister": "Base data register", "Koordinater": "Coordinates", "Høyder": "Heights", "Eksporter til Excel": "Export to Excel",
      "Kontroller nye filer": "Check new files", "Status kontroll": "QA status", "Automatisk kontroll": "Automatic check", "registreringer": "registrations",
      "filer": "files", "klare til bruk": "ready for use", "åpne spørsmål": "open questions", "utgått": "superseded", "Ikke begynt": "Not started",
      "Pågår": "In progress", "Utført": "Done", "Ja": "Yes", "Med forbehold": "With reservations", "Nei": "No", "OK": "OK", "Advarsel": "Warning",
      "Mangler info": "Missing info", "Må vurderes": "Needs review", "Avvik": "Deviation", "Venter": "Pending",
      "Søk i navn, innhold og avsender": "Search names, content and sender", "Søk": "Search", "Alle fag": "All disciplines", "Alle statuser": "All statuses",
      "Klar til bruk: alle": "Ready for use: all", "Ikke vurdert": "Not assessed", "Alle resultater": "All results", "Mine åpne spørsmål": "My open questions",
      "Vis utgåtte": "Show superseded", "Nullstill": "Reset", "Ansvarlig fag": "Responsible discipline", "Klar til bruk": "Ready for use",
      "Status kontroll for alle registreringer": "QA status for all registrations",
      "Nr": "No.", "Dokumentnavn / pakke": "Document name / package", "Innhold i fil/mappe": "Content of file/folder", "Filtype": "File type",
      "Dato mottatt": "Date received", "Mottatt fra": "Received from", "Lenke": "Link", "Ansvarlig fag for KS": "Discipline responsible for QA",
      "Dato kontrollert": "Date checked", "Er dokument/fil klar til bruk?": "Is the document/file ready for use?", "korrigert": "corrected",
      "Verdier eller kontrollresultater er korrigert manuelt": "Values or check results have been corrected manually", "Kommentarer": "Comments",
      "Klikk på en rad for å se kontrollen, svare på spørsmål og registrere KS. Standard rekkefølge er dato mottatt; klikk på en kolonne for å sortere.":
        "Click a row to see the check, answer questions and record QA. Default order is date received; click a column to sort.",
      "Ingen registreringer passer med filtrene.": "No registrations match the filters.",
      "Ingen prosjekter ennå. Opprett et under Prosjektinnstillinger.": "No projects yet. Create one under Project settings.",
      // Detalj
      "Kopier lenke": "Copy link", "Lukk": "Close", "Lenken er kopiert.": "Link copied.", "Klar til bruk?": "Ready for use?", "Spørsmål til opplaster": "Questions to uploader",
      "Ingen åpne": "None open", "åpne": "open", "åpent": "open", "Innhold": "Content", "Om dataene": "About the data", "Fra innholdet": "From the content",
      "– klikk blyanten for å rette en verdi": "– click the pencil to correct a value", "Datatype": "Data type", "Format": "Format", "Koordinatsystem": "Coordinate system",
      "Høydesystem": "Height system", "Dato": "Date", "Kilde": "Source", "Kvalitet": "Quality", "Innhold i registeret": "Content in the register", "Plassering": "Location",
      "Ukjent": "Unknown", "Ikke georeferert": "Not georeferenced", "Ingen høyder (2D)": "No heights (2D)", "Ingen flere opplysninger.": "No further information.",
      "Dekning av prosjektområdet": "Coverage of project area", "fra fila": "from file", "opplaster": "uploader", "AI · fra tekst": "AI · from text",
      "opplaster: vet ikke": "uploader: don't know", "opplaster: lokale": "uploader: local", "Trenger oppfølging": "Needs follow-up", "Alle filer": "All files",
      "Til vurdering hos KS": "For QA review", "Overstyr resultat": "Override result", "Fjern overstyring": "Remove override", "Overstyr": "Override",
      "Begrunnelse (påkrevd)": "Reason (required)", "Begrunnelse": "Reason", "Lagre svar": "Save answer", "Vet ikke": "Don't know", "(valgfritt)": "(optional)",
      "Fila og opplysningene er uenige – velg det som er riktig.": "The file and the information disagree – choose what is correct.",
      "– hvert svar kontrollerer dataene på nytt": "– each answer re-checks the data", "Valgfritt": "Optional",
      "Firma eller organisasjon, og hvordan du fikk dataene": "Company or organisation, and how you got the data",
      "For eksempel 2024-05 eller 12.05.2024": "For example 2024-05 or 12.05.2024", "For eksempel: FKB-B, 5 pkt/m², ±5 cm": "For example: FKB-B, 5 pts/m², ±5 cm",
      "Skriv en kommentar …": "Write a comment …", "Legg til kommentar": "Add comment", "ingen ennå": "none yet", "Ny kommentar": "New comment",
      "Skriv om noe er feil, uklart eller må følges opp. Kommentarene lagres som dokumentasjon og eksporteres til Excel.":
        "Write if something is wrong, unclear or needs follow-up. Comments are kept as documentation and exported to Excel.",
      "Sammenligning med godkjent referanse": "Comparison with approved reference", "Systematisk avvik": "Systematic offset", "Spredning (std)": "Spread (std)",
      "95 % innenfor": "95 % within", "Endret areal > 0,5 m": "Changed area > 0.5 m", "Størst avvik": "Largest difference", "Forskyvning": "Shift",
      "Ingen tegn": "No sign", "Ingen": "None", "Lavere": "Lower", "Høyere": "Higher", "Mot": "Against",
      "Ny minus referanse, ±1 m full farge. Skravert: ingen data.": "New minus reference, ±1 m full colour. Hatched: no data.",
      "Fordeling av avvik innenfor ±0,5 m.": "Distribution of differences within ±0.5 m.", "Fordeling av høydeavvik": "Distribution of height differences",
      "Differansekart: ny minus referanse": "Difference map: new minus reference", "venter på koordinatsystem": "waiting for coordinate system",
      "ingen referanse ennå": "no reference yet", "ingen overlapp": "no overlap", "Velg fil": "Choose file",
      "Venter på koordinatsystem. Svar på spørsmålet om koordinatsystem, så kjøres sammenligningen med en gang.": "Waiting for the coordinate system. Answer the question about it and the comparison runs at once.",
      "Ingen godkjent terrengmodell eller punktsky overlapper ennå. Når en referanse settes som klar til bruk, sammenlignes dataene automatisk.":
        "No approved terrain model or point cloud overlaps yet. When a reference is set ready for use, the data is compared automatically.",
      "Ingen godkjente terrengdata i samme koordinatsystem overlapper.": "No approved terrain data in the same coordinate system overlaps.",
      "Relasjoner": "Relations", "ingen": "none", "Ingen kjente koblinger til andre registreringer.": "No known links to other registrations.",
      "Erstatter": "Replaces", "Erstattet av": "Replaced by", "Mulig ny versjon": "Possible new version", "Sammenlignet med": "Compared with",
      "Referanse for": "Reference for", "Omtaler": "Mentions", "Omtalt i": "Mentioned in", "Samme leveranse": "Same delivery", "Samme område": "Same area",
      "Alle kontroller": "All checks", "Filer og kontroller": "Files and checks", "alle OK": "all OK", "kode": "code", "overstyrt": "overridden", "manuell": "manual",
      "Tekst og notater fra fila": "Text and notes from the file", "Tekst lest": "Text read", "Tilhørende filer": "Related files", "Merknader": "Notes",
      "Åpne fila": "Open the file", "Kildemappe": "Source folder", "Sti": "Path", "Historikk og svar": "History and answers", "Kvalitetskontroll": "Quality control",
      "Kommentar – påkrevd for «Med forbehold» og «Nei»": "Comment – required for «With reservations» and «No»", "Lagre vurdering": "Save assessment", "Gjenåpne": "Reopen",
      "KS-felt: fag, status, merknad og versjon": "QA fields: discipline, status, note and version", "Lagre KS-felt": "Save QA fields", "KS-merknad": "QA note",
      "Hva er sjekket, hva gjenstår": "What has been checked, what remains", "Erstatter tidligere registrering": "Replaces earlier registration",
      "Den erstattede blir satt som utgått når denne er klar til bruk.": "The replaced one is set as superseded when this one is ready for use.",
      "Automatisk – ingen forslag": "Automatic – no suggestion", "Ingen – ikke en ny versjon": "None – not a new version", "KS-feltene fylles ut av KS-ansvarlig.": "The QA fields are filled in by the QA lead.",
      "Velg Ja, Med forbehold eller Nei.": "Choose Yes, With reservations or No.", "Prosjektområde": "Project area", "Dataene (farge = resultat)": "The data (colour = result)",
      "Prosjektområde og dataenes utstrekning": "Project area and extent of the data", "Kan ikke plasseres før koordinatsystemet er kjent.": "Cannot be placed until the coordinate system is known.",
      "Lagre": "Save", "Avbryt": "Cancel", "Tilbakestill": "Reset", "Kommentar – hvorfor endres verdien?": "Comment – why is the value changed?", "Kommentar til endringen": "Comment on the change",
      "Gjelder alle filene i pakken.": "Applies to every file in the package.", "Endre": "Edit", "Endre beskrivelse": "Edit description", "Endre datatype": "Edit data type",
      "Endre dato": "Edit date", "Endre høydesystem": "Edit height system", "Endre innhold i registeret": "Edit content in the register", "Endre kilde": "Edit source",
      "Endre koordinatsystem": "Edit coordinate system", "Endre kvalitet": "Edit quality", "Lokale koordinater": "Local coordinates", "Ellipsoidisk høyde": "Ellipsoidal height",
      "Ingen høyder i fila": "No heights in the file", "Enkeltfil": "Single file", "Gjeldende": "Current", "Utgått": "Superseded",
      // Typer og innhold
      "Terrengmodell": "Terrain model", "Punktsky": "Point cloud", "Ortofoto": "Orthophoto", "Ledningsdata": "Utility data", "Grunnundersøkelse": "Ground investigation",
      "Eksisterende modell": "Existing model", "Tegning / innmåling": "Drawing / survey", "Plandata": "Plan data", "Dokument / beskrivelse": "Document / description", "Annet": "Other",
      "Tegning (PDF)": "Drawing (PDF)", "CAD-tegning": "CAD drawing", "Rapport": "Report", "Tekstdokument": "Text document", "BIM-modell": "BIM model", "Kartdata": "Map data",
      "Ledningsnett": "Utility network", "Tegningsnr.": "Drawing no.", "Målestokk": "Scale", "Ark": "Sheet", "Revisjon": "Revision", "Ord": "Words", "Forfatter": "Author",
      "Overskrifter": "Headings", "Skjema": "Schema", "Prosjekt i modellen": "Project in model", "Programvare": "Software", "Georeferanse": "Georeference", "Objekter": "Objects",
      "Lag": "Layers", "Elementer": "Elements", "Enheter": "Units", "Rutenett": "Grid", "Størrelse": "Size", "Areal": "Area", "Punkter": "Points", "Tetthet": "Density",
      "Klasser": "Classes", "Piksel": "Pixel", "Bånd": "Bands", "Produkt": "Product", "Objekttyper": "Object types", "Nøyaktighet": "Accuracy", "Filer": "Files",
      "Leveransenotat": "Delivery note", "uklassifisert": "unclassified", "bakke": "ground", "lav vegetasjon": "low vegetation", "middels vegetasjon": "medium vegetation",
      "høy vegetasjon": "high vegetation", "bygning": "building", "vann": "water", "rørsegmenter": "pipe segments", "rørdeler": "pipe fittings", "kummer": "manholes",
      "mangler (lokale koordinater)": "missing (local coordinates)", "RGB-bilde": "RGB image", "énkanals høyderaster": "single-band elevation raster",
      "LAS/LAZ-punktsky": "LAS/LAZ point cloud", "tekstdokument": "text document", "IFC-modell": "IFC model", "filnavnet nevner grunnundersøkelse": "file name mentions ground investigation",
      "filnavnet nevner innmåling": "file name mentions survey", "filnavnet nevner ledninger": "file name mentions utilities", "teksten handler om grunnundersøkelser": "the text is about ground investigations",
      "dato i tegningshodet": "date in title block", "lagringsdato i IFC-fila": "save date in the IFC file", "datotagg i fila – ofte prosesseringsdato, ikke fotodato": "date tag in the file – often processing date, not photo date",
      "seneste datafangst- eller oppdateringsdato i objektene": "latest capture or update date in the objects", "opprettelsesdato i fila – ofte prosesseringsdato": "creation date in the file – often processing date",
      "koordinater i fila (koordinatsystem ukjent)": "coordinates in the file (coordinate system unknown)", "meter": "metres",
      // Kart
      "Kartoversikt": "Map overview", "Tegn rektangel": "Draw rectangle", "Tegn polygon": "Draw polygon", "Importer område": "Import area", "Bakgrunnskart": "Background map",
      "Prosjektgrensen og alle grunnlagsdata som er plassert. Klikk på et fotavtrykk for å se hva det er, og gå videre til registeret.":
        "The project boundary and all base data that can be placed. Click a footprint to see what it is, and go on to the register.",
      "Kartverket topografisk gråtone": "Kartverket topographic grey", "Kartverket topografisk": "Kartverket topographic", "OpenStreetMap": "OpenStreetMap",
      "Ingen – bare rutenett": "None – grid only", "Mulig plassering": "Possible location", "Datatyper": "Data types", "Ikke plassert": "Not placed", "Ikke satt.": "Not set.",
      "Kart over prosjektet": "Map of the project", "Zoom inn": "Zoom in", "Zoom ut": "Zoom out", "Vis hele prosjektet": "Show the whole project",
      "Bakgrunnskartet kunne ikke lastes her – rutenettet viser prosjektets koordinatsystem.": "The background map could not be loaded here – the grid shows the project's coordinate system.",
      "Rutenett i prosjektets koordinatsystem": "Grid in the project's coordinate system", "Åpne i registeret": "Open in the register", "Mottatt": "Received",
      "koordinatsystemet er ukjent eller ser feil ut.": "the coordinate system is unknown or looks wrong.", "Nytt prosjektområde": "New project area", "punkter": "points",
      "tolket som": "interpreted as", "Lagre område": "Save area", "Ferdig": "Done", "Dra i kartet for å tegne rektangelet.": "Drag on the map to draw the rectangle.",
      "Klikk for hvert hjørne. Dobbeltklikk eller klikk på første punkt for å avslutte. Esc avbryter.": "Click each corner. Double-click or click the first point to finish. Esc cancels.",
      "DWG er et lukket binærformat som ikke kan leses i nettleseren. Lagre tegningen som DXF (eller eksporter LandXML fra Civil 3D) og importer den fila.":
        "DWG is a closed binary format that cannot be read in the browser. Save the drawing as DXF (or export LandXML from Civil 3D) and import that file.",
      "Velg en DXF-, LandXML- eller GeoJSON-fil.": "Choose a DXF, LandXML or GeoJSON file.", "Fant ingen lukket polygon i fila.": "No closed polygon found in the file.",
      "Fila er ikke gyldig XML.": "The file is not valid XML.", "Koordinatsystemet i fila støttes ikke her.": "The file's coordinate system is not supported here.",
      "Tegn eller importer området i kartet": "Draw or import the area on the map",
      "Utvid": "Expand", "Utvid kartet": "Expand the map", "Gjør kartet lite igjen": "Make the map small again", "Lukk stort kart": "Close large map",
      "i kartet": "on the map", "uten plassering": "not placed", "Filtre": "Filters", "Fotavtrykk": "Footprints", "Flater og omriss": "Areas and outlines",
      "Linjer": "Lines", "Punkter": "Points", "Bare utstrekning": "Extent only", "Vis i registeret": "Show in the register", "Datatype": "Data type",
      "Alle datatyper": "All data types", "Reell geometri": "Real geometry", "Omriss av dataene": "Outline of the data", "Bare utstrekning (rektangel)": "Extent only (rectangle)",
      "geometrien til objektene i fila": "the geometry of the objects in the file", "elementene i tegningen": "the elements in the drawing",
      "geometriene i fila": "the geometries in the file", "punktene i fila": "the points in the file", "høydeceller med data": "elevation cells with data",
      "kartrammen i tegningen": "the map frame in the drawing", "koordinater i teksten": "coordinates in the text", "utstrekningen i fila": "the extent of the file",
      "plasseringspunkter i modellen": "placement points in the model",
      // Innstillinger
      "Opprett prosjekt": "Create project", "Nytt prosjekt": "New project", "Navn": "Name", "Prosjekt-ID": "Project ID",
      "Prosjekttype": "Project type", "Fase": "Phase", "Koordinater og høyder": "Coordinates and heights", "Horisontalt koordinatsystem": "Horizontal coordinate system",
      "Mottak av data": "Receiving data", "Godkjente filformater": "Accepted file formats", "Maks alder på data (år)": "Maximum data age (years)", "0 = ingen grense": "0 = no limit",
      "Purring på ubesvarte spørsmål (dager)": "Reminder for unanswered questions (days)", "0 = ingen purring": "0 = no reminder", "Pakke fra antall filer": "Package from number of files",
      "Så mange filer i samme mappe registreres som én rad. Alle filene kontrolleres likevel.": "This many files in one folder are registered as one row. Every file is still checked.",
      "Fag": "Disciplines", "Kommaseparert, for eksempel VEG, VA, KON, GEO": "Comma-separated, for example VEG, VA, KON, GEO",
      "Standard ansvarlig fag per datatype": "Default responsible discipline per data type",
      "Ledningsdata og filer med «kum», «vann» eller «avløp» i navnet går til VA når VA finnes.": "Utility data and files with «kum», «vann» or «avløp» in the name go to VA when VA exists.",
      "Lagre innstillinger": "Save settings", "Lagre endringene. Registreringene kontrolleres på nytt ved behov.": "Save the changes. Registrations are re-checked when needed.",
      "Opprett prosjektet med disse innstillingene.": "Create the project with these settings.", "Kort ID uten mellomrom, for eksempel prosjektnummeret.": "A short ID without spaces, for example the project number.", "Hele stien til mappa der grunnlagsdata legges, for eksempel en OneDrive-mappe. Hver undermappe er én leveranse.": "The full path to the folder where base data is placed, for example a OneDrive folder. Each subfolder is one delivery.", "Ingen data er mottatt ennå. Legg filer i kildemappa (én undermappe per leveranse), så registreres de her automatisk.": "No data received yet. Put files in the source folder (one subfolder per delivery) and they are registered here automatically.", "Ingen nye filer i kildemappa. (I demoen kommer det ikke nye filer.)": "No new files in the source folder. (No new files arrive in the demo.)",
      "Bare KS-ansvarlige kan endre innstillingene. Bytt bruker øverst for å prøve.": "Only QA leads can change the settings. Switch user at the top to try.",
      "Grunnleggende innstillinger for kontrollen i dette prosjektet. Endrer du koordinatsystem, høydesystem, formater, aldersgrense eller prosjektområde, kontrolleres alle registreringene på nytt.":
        "Basic settings for checking this project. If you change coordinate system, height system, formats, age limit or project area, every registration is re-checked.",
      "Ett «øst nord»-par per linje, i prosjektets koordinatsystem. Brukes til plausibilitet og dekning.": "One «east north» pair per line, in the project's coordinate system. Used for plausibility and coverage.",
      "Veg": "Road", "Bru og konstruksjon": "Bridge and structures", "Jernbane": "Railway", "Bygg": "Building", "Landskap": "Landscape",
      "Kommunedelplan": "Municipal sub-plan", "Reguleringsplan": "Zoning plan", "Byggeplan": "Construction plan", "Som bygget": "As built", "Drift og vedlikehold": "Operation and maintenance",
      // Regelsett
      "Kravene hver fil kontrolleres mot. Regler med «Automatisk» bruker innebygd kode; regler med «AI» vurderes av AI ut fra regelteksten, så nye krav kan skrives med vanlige ord. Lagring gir en ny versjon, og alle registreringer kontrolleres på nytt.":
        "The requirements every file is checked against. «Automatic» rules use built-in code; «AI» rules are judged by AI from the rule text, so new requirements can be written in plain words. Saving creates a new version and re-checks every registration.",
      "Foreslå regler med AI": "Suggest rules with AI", "fra kontrakt, BIM-krav eller håndbok": "from contract, BIM requirements or handbook", "Lim inn kravtekst": "Paste requirement text",
      "Foreslå regler": "Suggest rules", "Legg til valgte": "Add selected", "Ny regel": "New rule", "Aktiv": "Active", "Regel": "Rule", "Krav": "Requirement",
      "Gjelder for": "Applies to", "Kontrolleres av": "Checked by", "Ved brudd": "If broken", "Versjoner": "Versions", "Regel-ID": "Rule ID", "Resultat ved brudd": "Result if broken",
      "Veiledning til AI": "Guidance for AI", "Alle datatyper": "All data types", "Bruk endringene": "Apply changes", "Fjern regelen": "Remove rule", "Automatisk": "Automatic",
      "Manuell": "Manual", "alle": "all", "Ulagrede endringer": "Unsaved changes", "Forkast": "Discard", "Lagre som ny versjon": "Save as new version",
      "Hva skal AI se etter, og hva regnes som manglende informasjon?": "What should AI look for, and what counts as missing information?",
      "f.eks. Kontrakt kap. C2 pkt. 3.4": "e.g. Contract ch. C2 item 3.4", "f.eks. e18-sandvika": "e.g. e18-sandvika",
      "Bare KS-ansvarlige kan endre regelsettet. Bytt bruker øverst for å prøve.": "Only QA leads can change the rule set. Switch user at the top to try.",
      "Egen regel. Med «AI» vurderer AI regelen for hver fil ut fra teksten og veiledningen, metadata og leveransenotater.": "Custom rule. With «AI», AI judges the rule for each file from the text and guidance, metadata and delivery notes.",
      "Fant ingen krav med «skal», «må» eller «bør» i teksten.": "Found no requirements with «skal», «må» or «bør» in the text.", "Ingen regler valgt.": "No rules selected.",
      "Horisontalt koordinatsystem er oppgitt og samsvarer med prosjektets": "Horizontal coordinate system is stated and matches the project's",
      "Høydesystem er oppgitt og samsvarer med prosjektets": "Height system is stated and matches the project's",
      "Koordinatene er troverdige for oppgitt koordinatsystem og ligger ved prosjektet": "Coordinates are plausible for the stated coordinate system and lie at the project",
      "Dataene dekker prosjektområdet": "The data covers the project area", "Kilde og leverandør er dokumentert": "Source and supplier are documented",
      "Dato for innsamling eller oppdatering er oppgitt og innenfor prosjektets aldersgrense": "Capture or update date is stated and within the project's age limit",
      "Filformatet er på prosjektets liste over godkjente formater": "File format is on the project's list of accepted formats",
      "Terrengdata stemmer med godkjent referanse i plassering og høyde": "Terrain data agrees with the approved reference in position and height",
      "Nøyaktighet eller kvalitetsklasse er oppgitt og tilstrekkelig for prosjektfasen": "Accuracy or quality class is stated and sufficient for the project phase",
      "Internt kvalitetssystem": "Internal quality system", "Internt kvalitetssystem – avklar toleranser": "Internal quality system – agree tolerances",
      // Varsler og eksport
      "Det kontrollen har sendt deg. I appen går de ut på e-post eller Teams.": "What the checker has sent you. In the app they go out by e-mail or Teams.", "Ingen varsler.": "No notifications.",
      "Forhåndsvisning av Excel-eksport": "Preview of Excel export", "Arket «Register»": "The «Register» sheet",
      "I appen laster knappen ned arbeidsboka med arkene Register, Filer, Kontroller, Spørsmål og Regelsett. Demoen viser registerarket slik det står nå.":
        "In the app the button downloads the workbook with the sheets Register, Files, Checks, Questions and Rule set. The demo shows the register sheet as it is now.",
      "Rekkefølge": "Order", "Dokumentnavn/Pakke": "Document name/Package", "Innhold i fil/folder": "Content of file/folder", "Gjeldende/utgått": "Current/superseded",
      // Chat
      "AI-assistent": "AI assistant", "Ny samtale": "New conversation", "Lukk AI-assistenten": "Close the AI assistant", "Send": "Send", "Stopp": "Stop",
      "Skriv et spørsmål … (Enter sender)": "Ask a question … (Enter sends)", "Spørsmål til AI-assistenten": "Question for the AI assistant", "Tenker…": "Thinking…",
      "Spør om grunnlagsdataene i": "Ask about the base data in", ": søk etter innhold, finn hva som henger sammen, eller få en analyse av kvalitet og avvik.": ": search content, find what is connected, or get an analysis of quality and deviations.",
      "Oppsummer status for grunnlagsdataene": "Summarise the status of the base data", "Hvilke data mangler koordinatsystem?": "Which data is missing a coordinate system?",
      "Hva er relatert til tegning C101?": "What is related to drawing C101?", "Er laserdataene i samsvar med godkjent terrengmodell?": "Do the laser data agree with the approved terrain model?",
      "Hvor står det noe om kvikkleire?": "Where is quick clay mentioned?", "Hvilke data er eldre enn 10 år?": "Which data is older than 10 years?",
      "Svarene bygger på registeret og kan inneholde feil – sjekk mot registreringen. I demoen svarer Claude via din egen Claude-konto når du tillater det.":
        "Answers are based on the register and may contain errors – check against the registration. In the demo Claude answers through your own Claude account when you allow it.",
      "Svarene bygger på registeret og kan inneholde feil – sjekk mot registreringen.": "Answers are based on the register and may contain errors – check against the registration.",
      "Stoppet.": "Stopped.",
      // Meldinger
      "Kommentaren er lagret.": "The comment has been saved.", "Skriv en kommentar.": "Write a comment.", "Skriv et svar, eller velg «Vet ikke».": "Write an answer, or choose «Don't know».",
      "Skriv hvorfor resultatet overstyres, slik at det er dokumentert.": "Write why the result is overridden, so it is documented.",
      "Skriv hvorfor dataene ikke kan brukes, slik at opplasteren vet hva som må rettes.": "Write why the data cannot be used, so the uploader knows what to fix.",
      "Beskriv forbeholdet, slik at de som bruker dataene ser det.": "Describe the reservation, so those using the data can see it.",
      "Bare den som leverte dataene (eller en KS-ansvarlig) kan svare på dette spørsmålet.": "Only the person who delivered the data (or a QA lead) can answer this question.",
      "Bare den som leverte dataene (eller en KS-ansvarlig) kan korrigere verdiene.": "Only the person who delivered the data (or a QA lead) can correct the values.",
      "Bare KS-ansvarlige kan overstyre kontrollresultater.": "Only QA leads can override check results.", "Bare KS-ansvarlige kan endre prosjektområdet.": "Only QA leads can change the project area.",
      "Bare KS-ansvarlige kan avgjøre om data er klare til bruk.": "Only QA leads can decide whether data is ready for use.",
      "Regel-ID må se ut som «R-EGEN-01».": "Rule ID must look like «R-EGEN-01».", "Skriv kravet som en hel setning.": "Write the requirement as a full sentence.",
      "Ingen kilde eller leverandør i fila, i leveransenotater eller fra opplaster.": "No source or supplier in the file, delivery notes or from the uploader.",
      "Ingen høydesystem i fila, og ikke oppgitt av opplaster.": "No height system in the file, and not given by the uploader.",
      "Ingen innsamlings- eller oppdateringsdato i fila, i leveransenotater eller fra opplaster.": "No capture or update date in the file, delivery notes or from the uploader.",
      "Ingen koordinatsystem i fila eller tilhørende filer (.prj, .aux.xml).": "No coordinate system in the file or related files (.prj, .aux.xml).",
      "Dekning er ukjent til koordinatsystemet er kjent.": "Coverage is unknown until the coordinate system is known.",
      "Sammenligning med godkjent referanse venter på koordinatsystem.": "Comparison with approved reference is waiting for the coordinate system.",
      "Be opplasteren om opplysninger om nøyaktighet.": "Ask the uploader about accuracy.",
      "Nøyaktighet står bare i teksten; KS-ansvarlig bør vurdere om det holder.": "Accuracy is only stated in the text; the QA lead should judge whether it is sufficient.",
      "Modellen er georeferert; detaljeringsgraden må vurderes av fagansvarlig.": "The model is georeferenced; the level of detail must be judged by the discipline lead.",
      "GeoPackage lagrer bare når innholdet sist ble endret, ikke når dataene ble samlet inn.": "GeoPackage only stores when the content was last changed, not when the data was captured.",
      "DXF har ikke koordinatsystem – det er vanlig for DXF, så opplasteren blir spurt.": "DXF has no coordinate system – this is common for DXF, so the uploader is asked.",
      "Sammenligner koordinatsystemet med prosjektets": "Compares the coordinate system with the project's", "Sammenligner høydesystemet med prosjektets": "Compares the height system with the project's",
      "Sjekker at koordinatene havner i prosjektområdet": "Checks that the coordinates land in the project area", "Beregner hvor stor del av prosjektområdet som dekkes": "Calculates how much of the project area is covered",
      "Ser etter kilde i fila, leveransenotater og svar": "Looks for the source in the file, delivery notes and answers", "Sjekker datoen mot prosjektets aldersgrense": "Checks the date against the project's age limit",
      "Sjekker filformatet mot prosjektets liste": "Checks the file format against the project's list", "Sammenligner høyder med godkjent terrengmodell eller punktsky": "Compares heights with the approved terrain model or point cloud",
      "Minste dekning (%)": "Minimum coverage (%)", "Største systematiske avvik (m)": "Largest systematic offset (m)", "Største spredning, std (m)": "Largest spread, std (m)",
      "Endring regnes fra (m)": "Change counted from (m)", "Største endrede areal (m²)": "Largest changed area (m²)", "Ny kommentar": "New comment",
      "For eksempel: «3.2 Terrengmodell. Terrengmodell skal leveres som rutenett med maksimalt 1 m oppløsning. Punktskyer skal være klassifisert etter ASPRS-standard. Ortofoto bør ikke være eldre enn 3 år.»":
        "For example: «3.2 Terrain model. The terrain model shall be delivered as a grid with at most 1 m resolution. Point clouds shall be classified to the ASPRS standard. Orthophotos should not be older than 3 years.»",
      "Språk / Language": "Language / Språk", "FKB": "FKB",
    };
    const D = (s) => dict[s] || s;
    const P = [
      [/^(.+) \(utgått\)$/, (m) => `${m[1]} (superseded)`],
      [/^Data fra (\S+) – eldre enn prosjektets grense på (\d+) år(.*)$/, (m) => `Data from ${m[1]} – older than the project's limit of ${m[2]} years${m[3].replace(/\(fra fila; (.+)\)/, (x, k) => `(from the file; ${D(k)})`)}`],
      [/^(IFC\w*)-modell · (.+)$/, (m) => `${m[1]} model · ${trList(m[2])}`],
      [/^som tegning (.+)$/, (m) => `as drawing ${m[1]}`], [/^tegning (\S+)$/, (m) => `drawing ${m[1]}`],
      [/^Ø (\d+)$/, (m) => `E ${m[1]}`],
      [/^Hvis (.+)$/, (m) => `If ${m[1]}`],
      [/^([^·]+) · ([^·]+)$/, (m) => (dict[m[1].trim()] && dict[m[2].trim()] ? `${D(m[1].trim())} · ${D(m[2].trim())}` : null)],
      [/^\d+ [a-zæøå][a-zæøå -]+(, \d+ [a-zæøå][a-zæøå -]+)*$/, (m) => { const r = trList(m[0]); return r === m[0] ? null : r; }],
      [/^[^,]+(, [^,]+)+$/, (m) => { const parts = m[0].split(", "); return parts.filter((x) => dict[x]).length * 2 >= parts.length ? parts.map(D).join(", ") : null; }],
      [/^(#\d+) · (.+) · Enkeltfil$/, (m) => `${m[1]} · ${D(m[2])} · Single file`],
      [/^(#\d+) · (.+) · Pakke med (\d+) filer$/, (m) => `${m[1]} · ${D(m[2])} · Package of ${m[3]} files`],
      [/^Mottatt (.+) fra (.+) · leveranse$/, (m) => `Received ${m[1]} from ${m[2]} · delivery`],
      [/^· mappe$/, () => "· folder"],
      [/^Lenke til #(\d+)$/, (m) => `Link to #${m[1]}`], [/^Lenke til registrering (\d+)$/, (m) => `Link to registration ${m[1]}`],
      [/^Aktiv: (.+)$/, (m) => `Active: ${m[1]}`], [/^(\d+) av (\d+) OK$/, (m) => `${m[1]} of ${m[2]} OK`],
      [/^(\d+) koblinger?$/, (m) => `${m[1]} link${m[1] === "1" ? "" : "s"}`],
      [/^(\d+) regler? · (\d+) spørsmål$/, (m) => `${m[1]} rule${m[1] === "1" ? "" : "s"} · ${m[2]} question${m[2] === "1" ? "" : "s"}`],
      [/^(\d+) regler?$/, (m) => `${m[1]} rule${m[1] === "1" ? "" : "s"}`], [/^(\d+) spørsmål$/, (m) => `${m[1]} question${m[1] === "1" ? "" : "s"}`],
      [/^(\d+) spm\.$/, (m) => `${m[1]} q.`], [/^(\d+) (åpne spørsmål|åpent spørsmål)$/, (m) => `${m[1]} open question${m[1] === "1" ? "" : "s"}`],
      [/^(\d+) (kommentar|kommentarer)$/, (m) => `${m[1]} comment${m[1] === "1" ? "" : "s"}`], [/^(\d+) (fil|filer)$/, (m) => `${m[1]} file${m[1] === "1" ? "" : "s"}`],
      [/^(\d+) (hendelse|hendelser)$/, (m) => `${m[1]} event${m[1] === "1" ? "" : "s"}`],
      [/^(Ikke begynt|Pågår|Utført): (\d+)$/, (m) => `${D(m[1])}: ${m[2]}`],
      [/^Ingen oppfølging\. Alle (\d+) kontroller er OK\.(.*)$/, (m) => `Nothing to follow up. All ${m[1]} checks are OK.${m[2]}`],
      [/^Ingen oppfølging\. Alle (\d+) filer er OK\.(.*)$/, (m) => `Nothing to follow up. All ${m[1]} files are OK.${m[2]}`],
      [/^Før du godkjenner: (.+)\.$/, (m) => `Before you approve: ${m[1].replace(/(\d+) åpne spørsmål/, "$1 open questions").replace(/(\d+) åpent spørsmål/, "$1 open question").replace(/automatisk kontroll: ([^;]+)/, (x, r) => `automatic check: ${D(r)}`)}.`],
      [/^Automatisk – forslag: (.+)$/, (m) => `Automatic – suggestion: ${m[1]}`],
      [/^(.+) – dekker (\d+) % av denne$/, (m) => `${D(m[1])} – covers ${m[2]} % of this`],
      [/^(.+) – som tegning (.+)$/, (m) => `${D(m[1])} – as drawing ${m[2]}`], [/^(.+) – tegning (.+)$/, (m) => `${D(m[1])} – drawing ${m[2]}`],
      [/^(.+): (OK|Avvik|Mangler info|Advarsel|Må vurderes)$/, (m) => `${m[1]}: ${D(m[2])}`],
      [/^Regelsett (v[\d.]+)$/, (m) => `Rule set ${m[1]}`],
      [/^Regelsett (v[\d.]+) · kontrollert (.+) · versjon (\d+) av fila$/, (m) => `Rule set ${m[1]} · checked ${m[2]} · version ${m[3]} of the file`],
      [/^Spørsmål til (.+)$/, (m) => `Questions for ${m[1]}`], [/^Erstatter #(\d+)$/, (m) => `Replaces #${m[1]}`], [/^Ny versjon av #(\d+)(\??)$/, (m) => `New version of #${m[1]}${m[2]}`],
      [/^Utgått → #(\d+)$/, (m) => `Superseded → #${m[1]}`], [/^Pakke · (\d+) filer$/, (m) => `Package · ${m[1]} files`],
      [/^(.+) – opplaster$/, (m) => `${m[1]} – uploader`], [/^(.+) – KS-ansvarlig (.+)$/, (m) => `${m[1]} – QA lead ${m[2]}`],
      [/^Du ser nå appen som (.+)\.$/, (m) => `You are now viewing the app as ${m[1]}.`], [/^Til (.+@.+)$/, (m) => `To ${m[1]}`],
      [/^Nytt resultat for (.+)$/, (m) => `New result for ${m[1]}`], [/^(\d+) punkter i (.+)$/, (m) => `${m[1]} points in ${m[2].replace("· fil:", "· file:").replace("parsell (Parcel)", "parcel").replace("lukket polylinje", "closed polyline").replace("tegnet i kartet", "drawn on the map").replace("rektangel", "rectangle")}`],
      [/^Korrigert av (.+?) (\d[\d./]+\d)(.*)$/, (m) => `Corrected by ${m[1]} ${m[2]}${m[3].replace(/\. Var: /, ". Was: ")}`],
      [/^Overstyrt fra «(.+)» av (.+?) (\d[\d./]+\d) – (.*)$/, (m) => `Overridden from «${D(m[1])}» by ${m[2]} ${m[3]} – ${m[4]}`],
      [/^\((\d+) (regel|regler) overstyrt manuelt – se «Alle kontroller»\)$/, (m) => `(${m[1]} rule${m[1] === "1" ? "" : "s"} overridden manually – see «All checks»)`],
      [/^Gjelder (\d+) filer$/, (m) => `Applies to ${m[1]} files`], [/^Venter på svar fra (.+) · spurt (.+)$/, (m) => `Waiting for an answer from ${m[1]} · asked ${m[2]}`],
      [/^Kommentar fra opplaster: (.*)$/, (m) => `Comment from uploader: ${m[1]}`],
      [/^(A\d) (liggende|stående)$/, (m) => `${m[1]} ${m[2] === "liggende" ? "landscape" : "portrait"}`],
      [/^PDF-tegning \((A\d) (liggende|stående), tegningshode\)$/, (m) => `PDF drawing (${m[1]} ${m[2] === "liggende" ? "landscape" : "portrait"}, title block)`],
      [/^SOSI-produktspesifikasjon (.+)$/, (m) => `SOSI product specification ${m[1]}`],
      [/^(\d+) av (\d+)$/, (m) => `${m[1]} of ${m[2]}`],
      [/^Ser ut til å være en ny versjon av$/, () => "Looks like a new version of"], [/^\. Den blir utgått når denne settes som klar til bruk\.$/, () => ". It is superseded when this one is set ready for use."],
      [/^, som nå er utgått\.$/, () => ", which is now superseded."], [/^– erstattet av$/, () => "– replaced by"],
      [/^(\S+)\. Brukes ikke som referanse\.$/, (m) => `${m[1]}. Not used as a reference.`],
      [/^, data fra (.+), godkjent (.+)\. Sammenlignet (.+) i (.+) rutenett\.$/, (m) => `, data from ${m[1]}, approved ${m[2]}. Compared ${m[3]} on a ${m[4]} grid.`],
      [/^(.+) systematisk( \(største\))?$/, (m) => `${m[1]} systematic${m[2] ? " (largest)" : ""}`],
      [/^\(aktiv\) · (.*)$/, (m) => `(active) · ${m[1]}`], [/^Regelsett (v[\d.]+) er lagret og tatt i bruk\.(.*)$/, (m) => `Rule set ${m[1]} is saved and in use.${tm(m[2])}`],
      // Innholdsbeskrivelser
      [/^Tegning (\S+) «(.+)» i (1:\d+) på (A\d)\.(.*)$/, (m) => `Drawing ${m[1]} «${m[2]}» at ${m[3]} on ${m[4]}.${tm(m[5])}`],
      [/^Georeferert med koordinater i tegningen \((.+)\)\.$/, (m) => `Georeferenced by coordinates in the drawing (${m[1]}).`],
      [/^(Rapport|Tekstdokument) på (\d+) sider(: «.+»)?\.(.*)$/, (m) => `${D(m[1])} of ${m[2]} pages${m[3] || ""}.${tm(m[4])}`],
      [/^Inneholder koordinater som plasserer innholdet\.$/, () => "Contains coordinates that place the content."],
      [/^(IFC\w*)-modell med (\d+) objekter \((.+)\)\. (.*)$/, (m) => `${m[1]} model with ${m[2]} objects (${trList(m[3])}). ${tm(m[4])}`],
      [/^Georeferert med (\S+) til (.+)\.$/, (m) => `Georeferenced with ${m[1]} to ${m[2]}.`], [/^Ligger i lokale koordinater\.$/, () => "Lies in local coordinates."],
      [/^Terrengmodell som rutenett på (.+) over (.+)\.$/, (m) => `Terrain model as a ${m[1]} grid over ${m[2]}.`],
      [/^Punktsky med (.+) punkter, (.+) pkt\/m², (klassifisert|ikke klassifisert)\.$/, (m) => `Point cloud with ${m[1]} points, ${m[2]} pts/m², ${m[3] === "klassifisert" ? "classified" : "not classified"}.`],
      [/^Ortofoto med (.+) m piksler over (.+)\.$/, (m) => `Orthophoto with ${m[1]} m pixels over ${m[2]}.`],
      [/^CAD-tegning med (\d+) elementer i (\d+) lag( \(.+\))?\.$/, (m) => `CAD drawing with ${m[1]} elements in ${m[2]} layers${m[3] || ""}.`],
      [/^Pakke med (\d+) filer: (.+?)(, til sammen (.+) punkter)?( over ca\. (.+))?\.$/, (m) => `Package of ${m[1]} files: ${D(m[2].charAt(0).toUpperCase() + m[2].slice(1)).toLowerCase()}${m[4] ? `, ${m[4]} points in total` : ""}${m[6] ? ` over approx. ${m[6]}` : ""}.`],
      [/^(.+) med (\d+) objekter( \(.+\))?\.$/, (m) => `${D(m[1])} with ${m[2]} objects${m[3] || ""}.`],
      [/^(.+) · (\d+) objekter$/, (m) => `${D(m[1])} · ${m[2]} objects`], [/^(.+) · (.+) m piksler$/, (m) => `${D(m[1])} · ${m[2]} m pixels`],
      [/^(.+) · (.+) m rutenett$/, (m) => `${D(m[1])} · ${m[2]} m grid`], [/^Tegning (\S+) · (.+)$/, (m) => `Drawing ${m[1]} · ${m[2].replace("rev.", "rev.")}`],
      [/^Rapport · (.+) · (\d+) sider$/, (m) => `Report · ${m[1]} · ${m[2]} pages`], [/^(.+) · (\d+) objekter i (\d+) lag$/, (m) => `${D(m[1])} · ${m[2]} objects in ${m[3]} layers`],
      [/^(\d+) filer · Punktsky · (.+) punkter · ca\. (.+?)( · med leveransenotat)?$/, (m) => `${m[1]} files · Point cloud · ${m[2]} points · approx. ${m[3]}${m[4] ? " · with delivery note" : ""}`],
      [/^(.+) holder for reguleringsplan\.$/, (m) => `${m[1].replace("m piksler", "m pixels").replace("m rutenett", "m grid").replace("Tegning i målestokk", "Drawing at scale").replace("punkter/m²", "points/m²")} is sufficient for a zoning plan.`],
      [/^(.+) holder for planlegging\.$/, (m) => `${m[1].replace("punkter/m²", "points/m²")} is sufficient for planning.`],
      [/^(.+) m piksler er grovere enn vanlige 0,25 m\.$/, (m) => `${m[1]} m pixels is coarser than the usual 0.25 m.`],
      [/^Median nøyaktighet (.+) cm er i tråd med FKB-A\/B\.$/, (m) => `Median accuracy ${m[1]} cm is in line with FKB-A/B.`],
      [/^(.+), nøyaktighet (.+) cm \(median\)$/, (m) => `${m[1]}, accuracy ${m[2]} cm (median)`], [/^median (.+) cm$/, (m) => `median ${m[1]} cm`],
      [/^(.+) m piksler$/, (m) => `${m[1]} m pixels`], [/^(.+) punkter\/m²$/, (m) => `${m[1]} points/m²`], [/^ca\. (.+)$/, (m) => `approx. ${m[1]}`],
      [/^(.+) × (.+) celler$/, (m) => `${m[1]} × ${m[2]} cells`], [/^(.+) til (.+) m: (.+) celler$/, (m) => `${m[1]} to ${m[2]} m: ${m[3]} cells`],
      [/^(\d+): (.+)$/, (m) => /^[A-ZÆØÅ_ ,]+$/.test(m[2]) ? `${m[1]}: ${m[2]}` : null],
      [/^(.+), fra fila\.$/, (m) => `${m[1]}, from the file.`], [/^(.+) \(fra fila\)\.$/, (m) => `${m[1]} (from the file).`],
      [/^(.+), EUREF89 (.+)$/, (m) => `${D(m[1]).replace("koordinater i tegningen", "coordinates in the drawing").replace("koordinater i teksten", "coordinates in the text").replace("koordinater i fila", "coordinates in the file").replace("GeoTIFF-nøkler", "GeoTIFF keys")}, EUREF89 ${m[2]}`],
      // Kontrollbelegg
      [/^(.+) \((\.\w+)\) er på listen over godkjente formater\.$/, (m) => `${m[1]} (${m[2]}) is on the list of accepted formats.`],
      [/^Koordinatene passer med (.+) i prosjektområdet\.$/, (m) => `The coordinates fit ${m[1]} in the project area.`],
      [/^Koordinatene passer ikke med (.+) i prosjektområdet, men med (.+) – oppgitt koordinatsystem kan være feil\.$/, (m) => `The coordinates do not fit ${m[1]} in the project area, but ${m[2]} – the stated coordinate system may be wrong.`],
      [/^Dekker (\d+) % av prosjektområdet\.$/, (m) => `Covers ${m[1]} % of the project area.`],
      [/^(.+) \(fra fila; (.+)\)\.$/, (m) => `${m[1]} (from the file; ${D(m[2])}).`],
      [/^(.+) \(lest fra tekst av AI\)\. Belegg: (.+)$/, (m) => `${m[1]} (read from text by AI). Evidence: ${m[2]}`],
      [/^Data fra (.+) – eldre enn prosjektets grense på (\d+) år(.*)$/, (m) => `Data from ${m[1]} – older than the project's limit of ${m[2]} years${m[3]}`],
      [/^Systematisk høydeavvik (.+) mot (.+) \(std (.+), grense (.+)\)\.$/, (m) => `Systematic height offset ${m[1]} against ${m[2]} (std ${m[3]}, limit ${m[4]}).`],
      [/^Stemmer med (.+): middelavvik (.+), std (.+), 95 % innenfor (.+) \((.+) celler à (.+)\)\.$/, (m) => `Agrees with ${m[1]}: mean difference ${m[2]}, std ${m[3]}, 95 % within ${m[4]} (${m[5]} cells of ${m[6]}).`],
      [/^Ingen koordinatsystem i fila eller tilhørende filer, og ikke oppgitt av opplaster\.(.*)$/, (m) => `No coordinate system in the file or related files, and not given by the uploader.${tm(m[1])}`],
      [/^Koordinatsystem ukjent; koordinatene passer med (.+)$/, (m) => `Coordinate system unknown; the coordinates fit ${m[1]}`],
      [/^(.+) \(fra fila\); prosjektet bruker (.+)\. Transformer før bruk, eller avtal unntak\.$/, (m) => `${m[1]} (from the file); the project uses ${m[2]}. Transform before use, or agree an exception.`],
      [/^Innebygd sjekk: (.+)\. Velg AI for å la AI vurdere regelen ut fra teksten i stedet\.$/, (m) => `Built-in check: ${D(m[1])}. Choose AI to let AI judge the rule from the text instead.`],
      // Spørsmål
      [/^Hvilket koordinatsystem er (.+) i\?$/, (m) => `Which coordinate system is ${m[1]} in?`],
      [/^Hvilket høydesystem bruker høydene i (.+)\?$/, (m) => `Which height system do the heights in ${m[1]} use?`],
      [/^Når ble dataene i (.+) samlet inn eller sist oppdatert\?$/, (m) => `When were the data in ${m[1]} captured or last updated?`],
      [/^Hvem har produsert dataene i (.+), og hvor har du fått dem fra\?$/, (m) => `Who produced the data in ${m[1]}, and where did you get it from?`],
      [/^Har du kommentarer til (.+) – kjente mangler, begrensninger eller tiltenkt bruk\?$/, (m) => `Any comments on ${m[1]} – known gaps, limitations or intended use?`],
      [/^Har du opplysninger om nøyaktigheten til (.+) – FKB-standard, punkttetthet eller en innmålingsrapport\?$/, (m) => `Do you have information on the accuracy of ${m[1]} – FKB standard, point density or a survey report?`],
      [/^(.+) oppgir (.+), men koordinatene passer med (.+)\. Hva er riktig\?$/, (m) => `${m[1]} states ${m[2]}, but the coordinates fit ${m[3]}. Which is correct?`],
      [/^(EPSG:\d+ – .+) \(koordinatene passer\)$/, (m) => `${m[1]} (the coordinates fit)`], [/^(EPSG:\d+ – .+) \(som oppgitt i fila\)$/, (m) => `${m[1]} (as stated in the file)`],
      // Meldinger (toast)
      [/^(#\d+ .+) kontrollert på nytt: (.+?)\.(.*)$/, (m) => `${m[1]} re-checked: ${D(m[2])}.${tm(m[3])}`],
      [/^(.+) (korrigert|tilbakestilt)\. (.*)$/, (m) => `${D(m[1])} ${m[2] === "korrigert" ? "corrected" : "reset"}. ${tm(m[3])}`],
      [/^(.+) er (korrigert|tilbakestilt)\.$/, (m) => `${D(m[1])} has been ${m[2] === "korrigert" ? "corrected" : "reset"}.`],
      [/^(R-[\w-]+) (overstyrt|tilbakestilt)\. (.*)$/, (m) => `${m[1]} ${m[2] === "overstyrt" ? "overridden" : "reset"}. ${tm(m[3])}`],
      [/^(#\d+ .+): (.+)\.$/, (m) => `${m[1]}: ${D(m[2].charAt(0).toUpperCase() + m[2].slice(1))}.`.replace(": With reservations.", ": with reservations.")],
      [/^Lagret\. (.*)$/, (m) => `Saved. ${tm(m[1])}`], [/^(#\d+ .+): KS-feltene er lagret\.$/, (m) => `${m[1]}: QA fields saved.`],
      [/^Prosjektområdet er lagret \((\d+) punkter\)\.(.*)$/, (m) => `Project area saved (${m[1]} points).${tm(m[2])}`],
      [/^I demoen kontrolleres ikke dekningen på nytt; i appen skjer det automatisk\.$/, () => "The demo does not re-check coverage; the app does it automatically."],
      [/^I demoen kontrolleres ikke andre filer på nytt; i appen skjer det automatisk\.$/, () => "The demo does not re-check other files; the app does it automatically."],
      [/^\(Forenklet kontroll i demoen\.\)$/, () => "(Simplified check in the demo.)"], [/^(\d+) registreringer er kontrollert på nytt\.$/, (m) => `${m[1]} registrations re-checked.`],
      [/^Innstillingene er lagret\.(.*)$/, (m) => `Settings saved.${m[1] ? " " + tm(m[1].trim()) : ""}`],
      [/^Kontroll ferdig: (\d+) nye filer, (\d+) nye versjoner, (\d+) uendret\.$/, (m) => `Check finished: ${m[1]} new files, ${m[2]} new versions, ${m[3]} unchanged.`],
      [/^(\d+) (regel|regler) lagt til\. Husk å lagre som ny versjon\.$/, (m) => `${m[1]} rule${m[1] === "1" ? "" : "s"} added. Remember to save as a new version.`],
    ];
    function tm(s) {
      const x = (s || "").trim();
      if (!x) return s || "";
      const r = translate(x);
      return (s.startsWith(" ") ? " " : "") + r;
    }
    function trList(s) { return s.split(", ").map((p) => { const m = p.match(/^(\S+) (.+)$/); return m ? `${m[1]} ${D(m[2])}` : D(p); }).join(", "); }
    function translate(s) {
      if (dict[s]) return dict[s];
      if (s.length > 400 || !/[A-Za-zÆØÅæøå]/.test(s)) return s;
      for (const [re, fn] of P) {
        const m = s.match(re);
        if (m) { const r = fn(m); if (r != null) return r; }
      }
      return s;
    }
    const SKIP = ".excerpt, .cm-t, .msg-u, .msg-a, .mono, textarea, script, style, .name-text, .fname, .qwait .muted, [data-noi18n]";
    const ATTRS = ["placeholder", "title", "aria-label"];
    function node(n) {
      if (n.nodeType === 3) {
        const p = n.parentElement;
        if (!p || p.closest(SKIP)) return;
        const raw = n.nodeValue, s = raw.trim();
        if (!s) return;
        const r = translate(s);
        if (r !== s) n.nodeValue = raw.replace(s, r);
        return;
      }
      if (n.nodeType !== 1) return;
      if (n.tagName === "TEXTAREA" || n.tagName === "INPUT") { ATTRS.forEach((a) => { const v = n.getAttribute(a); if (v) { const r = translate(v.trim()); if (r !== v.trim()) n.setAttribute(a, r); } }); return; }
      if (n.closest(SKIP)) return;
      ATTRS.forEach((a) => { const v = n.getAttribute(a); if (v) { const r = translate(v.trim()); if (r !== v.trim()) n.setAttribute(a, r); } });
      const w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
      while (w.nextNode()) {
        const c = w.currentNode;
        if (c.nodeType === 1) { if (c.matches(SKIP) && c.tagName !== "TEXTAREA") continue; ATTRS.forEach((a) => { const v = c.getAttribute(a); if (v) { const r = translate(v.trim()); if (r !== v.trim()) c.setAttribute(a, r); } }); }
        else node(c);
      }
    }
    let obs = null;
    function apply(lang) {
      LANG = lang;
      document.documentElement.lang = lang === "en" ? "en" : "nb";
      if (obs) { obs.disconnect(); obs = null; }
      if (lang !== "en") return;
      node(document.body);
      obs = new MutationObserver((muts) => muts.forEach((m) => m.addedNodes.forEach(node)));
      obs.observe(document.body, { childList: true, subtree: true });
    }
    return { dict, translate, apply };
  })();

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = encodeURIComponent;
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const numFmt = {};
  function num(v, d = 0) {
    if (typeof v !== "number" || !isFinite(v)) return esc(v ?? "");
    const key = LANG + d;
    numFmt[key] = numFmt[key] || new Intl.NumberFormat(LOC(), { minimumFractionDigits: d, maximumFractionDigits: d });
    return numFmt[key].format(Math.abs(v) < Math.pow(10, -d) / 2 ? 0 : v);
  }
  const signed = (v, d = 2) => (typeof v === "number" && Math.round(v * Math.pow(10, d)) > 0 ? "+" : "") + num(v, d);
  const metres = (v, d = 2, sign = false) => `${sign ? signed(v, d) : num(v, d)} m`;
  function areaText(m2) { return m2 >= 1000 ? `${num(m2 / 1000, 1)} daa` : `${num(m2, 0)} m²`; }
  function fmtDate(v) {
    if (!v) return "";
    const s = String(v);
    if (/^\d{4}$/.test(s)) return s;
    if (/^\d{4}-\d{2}$/.test(s)) {
      const d = new Date(s + "-01T00:00:00");
      return isNaN(d) ? s : d.toLocaleDateString(LOC(), { month: "short", year: "numeric" });
    }
    const d = new Date(s.length === 10 ? s + "T00:00:00" : s);
    return isNaN(d) ? s : d.toLocaleDateString(LOC(), { day: "numeric", month: "short", year: "numeric" });
  }
  function fmtShort(v) {
    if (!v) return "";
    const d = new Date(String(v).length === 10 ? v + "T00:00:00" : v);
    return isNaN(d) ? fmtDate(v) : d.toLocaleDateString(LOC(), { day: "2-digit", month: "2-digit", year: "numeric" });
  }
  const chip = (r) => `<span class="chip r-${esc(r)}">${esc(LABELS[r] || r)}</span>`;
  const qaPill = (s) => `<span class="qa qa-${esc(s)}">${esc(QA[s] || s)}</span>`;
  const readyBadge = (r) => (r ? `<span class="ready ready-${esc(r)}">${ICON_READY[r]}${esc(READY[r])}</span>` : '<span class="muted">–</span>');
  const plural = (n, one, many) => `${num(n)} ${n === 1 ? one : many}`;
  const dash = '<span class="muted">–</span>';
  const worst = (rs) => rs.reduce((w, r) => ((RESULT_ORDER[r] ?? -1) > (RESULT_ORDER[w] ?? -1) ? r : w), "ok");

  // --- API ---------------------------------------------------------------------------------------
  async function http(method, path, body) {
    const res = await fetch("api" + path, {
      method, credentials: "same-origin",
      headers: body ? { "content-type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Serveren svarte ${res.status}.`);
    return data;
  }
  const api = DEMO ? demoApi(DEMO) : {
    get: (p) => http("GET", p), post: (p, b) => http("POST", p, b || {}),
    chat: (pid, messages) => http("POST", `/projects/${enc(pid)}/chat`, { messages, lang: LANG }),
  };

  // --- Ruter og ramme -------------------------------------------------------------------------------
  function route() {
    const h = location.hash.replace(/^#/, "");
    if (h.startsWith("entry-")) return { name: "register", open: h.slice(6) };
    if (h === "kart") return { name: "register", open: null, big: true };
    if (["prosjekt", "regler", "varsler"].includes(h)) return { name: h };
    return { name: "register", open: null };
  }
  const project = () => state.projects.find((p) => p.id === state.projectId) || state.projects[0];

  async function loadProjects() {
    state.projects = await api.get("/projects");
    if (!state.projects.find((p) => p.id === state.projectId)) state.projectId = state.projects[0] && state.projects[0].id;
  }

  function shell(r) {
    const me = state.me;
    const items = [["register", "Register"], ["prosjekt", "Prosjektinnstillinger"], ["regler", "Regelsett"], ["varsler", "Varsler"]];
    const nav = items.map(([k, label]) => `<a href="#${k}"${r.name === k ? ' aria-current="page"' : ""}>${label}</a>`).join("");
    const projectPick = `<label for="project-switch"><span class="lbl">Prosjekt</span><select id="project-switch">${state.projects.map((p) => `<option value="${esc(p.id)}"${p.id === state.projectId ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>`;
    const users = me.demo_users || [];
    const who = users.length
      ? `<label for="user-switch"><span class="lbl">Vis som</span><select id="user-switch">${users.map((u) => `<option value="${esc(u.email)}"${u.email === me.user.email ? " selected" : ""}>${esc(u.name)} – ${esc(u.role_label || "opplaster")}</option>`).join("")}</select></label>`
      : `<span class="small muted">${esc(me.user.name)}</span>`;
    return `<header class="appbar"><div class="wrap">
        <a class="brand" href="#register" aria-label="Base Data Checker, register">
          <svg width="26" height="24" viewBox="0 0 26 24" aria-hidden="true"><path d="M13 2.5 24 21H2z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="13" cy="14.6" r="2.5" fill="var(--accent)"/></svg>
          <b>Base Data Checker</b></a>
        <nav class="nav" aria-label="Sider">${nav}</nav><div class="pickers"><div class="lang" role="group" aria-label="Språk / Language"><button type="button" data-lang="nb" aria-pressed="${LANG !== "en"}" title="Norsk">NO</button><button type="button" data-lang="en" aria-pressed="${LANG === "en"}" title="English">EN</button></div><button class="btn chat-btn" type="button" data-action="chat-toggle" aria-expanded="${state.chatOpen}" aria-label="Spør AI">${ICON_SPARK}<span class="chat-btn-t">Spør AI</span></button>${projectPick}${who}</div></div></header>
      ${me.banner ? `<div class="banner"><div class="wrap">${esc(me.banner)}</div></div>` : ""}
      <main><div class="wrap" id="view"></div></main><div id="toast-slot" aria-live="polite"></div>`;
  }

  async function render() {
    const r = route();
    state.view = r.name;
    if (state.map) { state.map.destroy(); state.map = null; }
    if (r.big) state.mapBig = true;
    if (r.name !== "register") state.mapBig = false;
    document.body.classList.remove("map-big");
    state.mapHl = null;
    document.getElementById("app").innerHTML = shell(r);
    const el = document.getElementById("view");
    el.innerHTML = '<p class="loading">Laster…</p>';
    renderChat();
    try {
      await VIEWS[r.name](el, r);
    } catch (e) {
      el.innerHTML = `<p class="error">${esc(e.message)}</p><p><a href="#register">Tilbake til registeret</a></p>`;
    }
  }

  function toast(text) {
    const slot = document.getElementById("toast-slot");
    if (!slot) return;
    slot.innerHTML = `<div class="toast">${esc(text)}</div>`;
    clearTimeout(toast.t);
    toast.t = setTimeout(() => { slot.innerHTML = ""; }, 5200);
  }

  // --- Register ------------------------------------------------------------------------------------
  const COLS = [
    { key: "seq", label: "Nr", cls: "c-seq", val: (e) => e.seq },
    { key: "name", label: "Dokumentnavn / pakke", cls: "c-name", val: (e) => e.name.toLowerCase() },
    { key: "content", label: "Innhold i fil/mappe", cls: "c-content", val: (e) => (e.content || "").toLowerCase() },
    { key: "file_types", label: "Filtype", cls: "c-type", val: (e) => e.file_types || "" },
    { key: "received_at", label: "Dato mottatt", cls: "c-date", val: (e) => e.received_at || "" },
    { key: "received_from", label: "Mottatt fra", cls: "c-from", val: (e) => (e.received_from || "").toLowerCase() },
    { key: "link", label: "Lenke", cls: "c-link", sortable: false },
    { key: "discipline", label: "Ansvarlig fag for KS", cls: "c-fag", val: (e) => e.discipline || "" },
    { key: "check_result", label: "Automatisk kontroll", cls: "c-auto", val: (e) => RESULT_ORDER[e.check_result] },
    { key: "qa_status", label: "Status kontroll", cls: "c-qa", val: (e) => QA_ORDER[e.qa_status] },
    { key: "qa_date", label: "Dato kontrollert", cls: "c-date", val: (e) => e.qa_date || "" },
    { key: "ready", label: "Er dokument/fil klar til bruk?", cls: "c-ready", val: (e) => (e.ready ? READY_ORDER[e.ready] : "") },
  ];

  function visibleEntries() {
    const f = state.filters, me = (state.me.user.email || "").toLowerCase();
    const q = f.q.toLowerCase();
    const rows = state.entries.filter((e) => (f.showOld || e.lifecycle !== "utgatt")
      && (!f.fag || e.discipline === f.fag) && (!f.qa || e.qa_status === f.qa)
      && (!f.ready || (f.ready === "none" ? !e.ready : e.ready === f.ready)) && (!f.result || e.check_result === f.result)
      && (!f.type || e.data_type === f.type)
      && (!f.mine || ((e.uploader || {}).email === me && e.open_questions > 0))
      && (!q || `${e.name} ${e.content} ${e.received_from} ${e.file_types}`.toLowerCase().includes(q)));
    const col = COLS.find((c) => c.key === state.sort.key) || COLS[4];
    const dir = state.sort.dir;
    return rows.map((e, i) => [e, i]).sort(([a, ia], [b, ib]) => {
      const va = col.val(a), vb = col.val(b);
      const ea = va === "" || va == null, eb = vb === "" || vb == null;
      if (ea !== eb) return ea ? 1 : -1;
      if (va < vb) return -dir;
      if (va > vb) return dir;
      const t = String(a.received_at).localeCompare(String(b.received_at)) || a.seq - b.seq;
      return t || ia - ib;
    }).map(([e]) => e);
  }

  function nameTags(e) {
    const tags = [];
    if (e.kind === "package") tags.push(`<span class="tag">Pakke · ${plural(e.file_count, "fil", "filer")}</span>`);
    if (e.lifecycle === "utgatt" && e.superseded_by) tags.push(`<span class="tag">Utgått → #${esc(e.superseded_by.seq)}</span>`);
    else if (e.replaces) tags.push(`<span class="tag version">${e.ready ? "Erstatter" : "Ny versjon av"} #${esc(e.replaces.seq)}${!e.ready && e.replaces.mode === "auto" ? "?" : ""}</span>`);
    if (e.corrections) tags.push(`<span class="tag manual" title="Verdier eller kontrollresultater er korrigert manuelt">korrigert</span>`);
    if (e.comments) tags.push(`<span class="tag" title="Kommentarer">${e.comments} ${e.comments === 1 ? "kommentar" : "kommentarer"}</span>`);
    return tags.join("");
  }

  function rowHtml(e) {
    const open = state.open === e.id;
    const q = e.open_questions ? `<span class="qbadge" title="${plural(e.open_questions, "åpent spørsmål", "åpne spørsmål")}">${e.open_questions} spm.</span>` : "";
    return `<tr class="entry-row s-${esc(e.check_result)}${e.lifecycle === "utgatt" ? " old" : ""}${open ? " open" : ""}" data-id="${esc(e.id)}" tabindex="0" aria-expanded="${open}">
      <td class="c-seq">${esc(e.seq)}</td>
      <td class="c-name"><span class="name-text">${esc(e.name)}</span><div class="sub">${nameTags(e)}</div></td>
      <td class="c-content">${esc(e.content)}</td>
      <td class="c-type">${esc(e.file_types)}</td>
      <td class="c-date">${fmtShort(e.received_at)}</td>
      <td class="c-from">${esc(e.received_from)}</td>
      <td class="c-link"><a href="#entry-${esc(e.id)}" title="Lenke til #${esc(e.seq)}" aria-label="Lenke til registrering ${esc(e.seq)}">${ICON_LINK}</a></td>
      <td class="c-fag">${esc(e.discipline || "")}</td>
      <td class="c-auto">${chip(e.check_result)}${q}</td>
      <td class="c-qa">${qaPill(e.qa_status)}</td>
      <td class="c-date">${fmtShort(e.qa_date) || dash}</td>
      <td class="c-ready">${readyBadge(e.ready)}</td>
    </tr>${open ? '<tr class="detail-row"><td colspan="12"><div class="detail-host loading">Laster…</div></td></tr>' : ""}`;
  }

  function cardHtml(e) {
    const open = state.open === e.id;
    return `<article class="card s-${esc(e.check_result)}${e.lifecycle === "utgatt" ? " old" : ""}">
      <button type="button" class="card-head" data-toggle="${esc(e.id)}" aria-expanded="${open}">
        <span class="top"><span class="muted num">#${esc(e.seq)}</span><span class="name-text">${esc(e.name)}</span>${chip(e.check_result)}</span>
        <span class="meta"><span>${esc(e.content)}</span></span>
        <span class="meta"><span>${fmtDate(e.received_at)}</span><span>${esc(e.received_from)}</span><span><b>${esc(e.discipline || "")}</b></span>${qaPill(e.qa_status)}${readyBadge(e.ready)}${e.open_questions ? `<span class="qbadge">${e.open_questions} spm.</span>` : ""}</span>
        ${nameTags(e) ? `<span class="meta">${nameTags(e)}</span>` : ""}
      </button>${open ? '<div class="card-detail"><div class="detail-host loading">Laster…</div></div>' : ""}</article>`;
  }

  function renderList() {
    const host = document.getElementById("list");
    if (!host) return;
    const rows = visibleEntries();
    if (!state.entries.length) { host.innerHTML = `<div class="panel empty">Ingen data er mottatt ennå. Legg filer i kildemappa (én undermappe per leveranse), så registreres de her automatisk.</div>`; return; }
    if (!rows.length) { host.innerHTML = '<div class="panel empty">Ingen registreringer passer med filtrene.</div>'; return; }
    if (mobile.matches) { host.innerHTML = `<div class="cards">${rows.map(cardHtml).join("")}</div>`; return; }
    const head = COLS.map((c) => {
      if (c.sortable === false) return `<th class="${c.cls}"><button type="button" disabled>${c.label}</button></th>`;
      const on = state.sort.key === c.key;
      const sort = on ? ` aria-sort="${state.sort.dir > 0 ? "ascending" : "descending"}"` : "";
      return `<th class="${c.cls}"${sort}><button type="button" data-sort="${c.key}">${c.label}<span class="arrow">${on && state.sort.dir < 0 ? "▼" : "▲"}</span></button></th>`;
    }).join("");
    host.innerHTML = `<div class="panel table-wrap reg-wrap"><table class="reg"><thead><tr>${head}</tr></thead><tbody>${rows.map(rowHtml).join("")}</tbody></table></div>`;
  }

  function renderSummary() {
    const host = document.getElementById("summary");
    if (!host) return;
    const es = state.entries;
    const n = es.length || 1;
    const qa = Object.keys(QA).map((k) => [k, es.filter((e) => e.qa_status === k).length]);
    const colors = { ikke_begynt: "var(--todo)", pagar: "var(--busy)", utfort: "var(--done)" };
    const bar = qa.filter(([, c]) => c).map(([k, c]) => `<span style="width:${(100 * c) / n}%;background:${colors[k]}" title="${QA[k]}: ${c}"></span>`).join("");
    const legend = qa.map(([k, c]) => `<button type="button" data-filter="qa" data-value="${k}" aria-pressed="${state.filters.qa === k}"><span class="dot" style="background:${colors[k]}"></span>${QA[k]} <b>${c}</b></button>`).join("");
    const res = RESULTS.map((k) => [k, es.filter((e) => e.check_result === k).length]).filter(([, c]) => c);
    const resLegend = res.map(([k, c]) => `<button type="button" data-filter="result" data-value="${k}" aria-pressed="${state.filters.result === k}">${chip(k)} <b>${c}</b></button>`).join("");
    const files = es.reduce((s, e) => s + (e.file_count || 0), 0);
    const oq = es.reduce((s, e) => s + (e.open_questions || 0), 0);
    const old = es.filter((e) => e.lifecycle === "utgatt").length;
    const ready = es.filter((e) => e.ready === "ja" || e.ready === "med_forbehold").length;
    host.innerHTML = `<div><div class="row"><span class="eyebrow">Status kontroll</span></div><div class="bar" role="img" aria-label="Status kontroll for alle registreringer">${bar}</div><div class="legend">${legend}</div></div>
      <div><div class="figures"><span><b>${es.length}</b> registreringer</span><span><b>${files}</b> filer</span><span><b>${ready}</b> klare til bruk</span><span><b>${oq}</b> åpne spørsmål</span>${old ? `<span><b>${old}</b> utgått</span>` : ""}</div>
      <div class="row" style="margin-top:8px"><span class="eyebrow">Automatisk kontroll</span></div><div class="legend" style="margin-top:4px">${resLegend}</div></div>`;
  }

  function filtersHtml() {
    const f = state.filters, opts = state.me.options;
    const fag = [...new Set(state.entries.map((e) => e.discipline).filter(Boolean))].sort();
    const types = [...new Set(state.entries.map((e) => e.data_type).filter(Boolean))].map((k) => [k, (opts.data_types || {})[k] || k]).sort((a, b) => a[1].localeCompare(b[1]));
    const sel = (id, label, all, items, value) => `<select id="${id}" aria-label="${label}"><option value="">${all}</option>${items.map(([k, v]) => `<option value="${esc(k)}"${value === k ? " selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
    return `<div class="filters">
      <input type="search" id="f-q" placeholder="Søk i navn, innhold og avsender" value="${esc(f.q)}" aria-label="Søk">
      ${sel("f-type", "Datatype", "Alle datatyper", types, f.type)}
      ${sel("f-fag", "Ansvarlig fag", "Alle fag", fag.map((x) => [x, x]), f.fag)}
      ${sel("f-qa", "Status kontroll", "Alle statuser", Object.entries(QA), f.qa)}
      ${sel("f-ready", "Klar til bruk", "Klar til bruk: alle", [...Object.entries(READY), ["none", "Ikke vurdert"]], f.ready)}
      ${sel("f-result", "Automatisk kontroll", "Alle resultater", RESULTS.map((k) => [k, LABELS[k]]), f.result)}
      <label class="check"><input type="checkbox" id="f-mine"${f.mine ? " checked" : ""}> Mine åpne spørsmål</label>
      <label class="check"><input type="checkbox" id="f-old"${f.showOld ? " checked" : ""}> Vis utgåtte</label>
      <button class="btn ghost small" type="button" data-action="clear-filters">Nullstill</button>
    </div>`;
  }

  async function viewRegister(el, r) {
    await loadProjects();
    const p = project();
    if (!p) { el.innerHTML = '<div class="panel empty">Ingen prosjekter ennå. Opprett et under Prosjektinnstillinger.</div>'; return; }
    state.entries = await api.get(`/projects/${enc(p.id)}/entries`);
    state.open = r.open || null;
    const exportBtn = DEMO ? '<button class="btn" type="button" data-action="export-preview">Eksporter til Excel</button>'
      : `<a class="btn" href="api/projects/${enc(p.id)}/export.xlsx">Eksporter til Excel</a>`;
    el.innerHTML = `<section class="stack">
      <div class="project-head"><div>
        <div class="eyebrow">Grunnlagsdataregister</div>
        <h1>${esc(p.name)}</h1>
        <div class="facts"><span>${esc(p.project_type || "")} · ${esc(p.phase || "")}</span><span>Koordinater <b class="mono">${esc(p.horizontal_crs)}</b></span>
          <span>Høyder <b>${esc(p.height_reference)}</b></span><span>Regelsett <b class="mono">${esc(p.active_ruleset || "standard")}</b></span></div>
      </div><div class="row">${exportBtn}${state.me.is_reviewer ? '<button class="btn" type="button" data-action="run">Kontroller nye filer</button>' : ""}</div></div>
      <div class="reg-top"><div class="panel summary" id="summary"></div>${mapBoxHtml()}</div>
      <div id="filters-slot">${filtersHtml()}</div>
      <div id="list"></div>
      <p class="small muted">Klikk på en rad for å se kontrollen, svare på spørsmål og registrere KS. Standard rekkefølge er dato mottatt; klikk på en kolonne for å sortere.</p>
    </section>`;
    renderSummary();
    renderList();
    const mapReady = setupMap(p);
    if (state.open) await loadDetail(true);
    await mapReady;
  }

  async function syncOpen(scroll) {
    renderList();
    mapSync(scroll);
    if (state.open) await loadDetail(scroll);
  }

  async function loadDetail(scroll) {
    const host = document.querySelector(".detail-host");
    if (!host) return;
    try {
      state.detail = await api.get(`/entries/${enc(state.open)}`);
      state.pendingReady = state.detail.entry.ready || null;
      host.classList.remove("loading");
      host.innerHTML = detailHtml(state.detail);
      if (scroll) {
        const row = document.querySelector(`#list [data-id="${CSS.escape(state.open)}"], #list [data-toggle="${CSS.escape(state.open)}"]`);
        const bar = document.querySelector(".appbar");
        if (row) window.scrollTo(0, row.getBoundingClientRect().top + window.scrollY - (bar ? bar.offsetHeight : 0) - 8);
      }
    } catch (e) {
      host.classList.remove("loading");
      host.innerHTML = `<p class="error" style="padding:16px">${esc(e.message)}</p>`;
    }
  }

  function redrawDetail() {
    const host = document.querySelector(".detail-host");
    if (host && state.detail) host.innerHTML = detailHtml(state.detail);
  }

  async function refreshAfterAction(message) {
    const p = project();
    state.entries = await api.get(`/projects/${enc(p.id)}/entries`);
    state.projects = await api.get("/projects");
    renderSummary();
    renderList();
    if (state.map) { try { state.mapData = await api.get(`/projects/${enc(p.id)}/map`); } catch (e) { /* kartet beholder forrige data */ } mapSync(false); }
    if (state.open) await loadDetail(false);
    if (message) toast(message);
  }

  // --- Detaljpanel ----------------------------------------------------------------------------------
  // Samme oppbygging for alle datatyper: hode, statuslinje, «Innhold», «Trenger oppfølging», og deretter
  // sammenleggbare blokker (sammenligning, relasjoner, alle kontroller, tekst, historikk). KS og kart til høyre.
  function provenance(e) {
    if (!e || !e.from) return "";
    const [label, cls] = FROM[e.from] || [e.from, ""];
    return ` <span class="tag ${cls}">${esc(label)}</span>`;
  }

  function blk(id, title, meta, body, opts = {}) {
    const head = `<h3>${title}</h3>${meta ? `<span class="blk-meta">${meta}</span>` : ""}`;
    if (!opts.collapsible) return `<section class="blk${opts.cls ? " " + opts.cls : ""}"><header class="blk-h">${head}</header><div class="blk-b">${body}</div></section>`;
    const key = `${state.open}:${id}`;
    const open = key in state.blocks ? state.blocks[key] : !!opts.open;
    return `<details class="blk${opts.cls ? " " + opts.cls : ""}" data-blk="${esc(key)}"${open ? " open" : ""}><summary class="blk-h">${head}<span class="chev" aria-hidden="true"></span></summary><div class="blk-b">${body}</div></details>`;
  }

  function statusStrip(d) {
    const e = d.entry;
    const q = e.open_questions ? `<span class="qbadge">${e.open_questions}</span> ${e.open_questions === 1 ? "åpent" : "åpne"}` : '<span class="muted">Ingen åpne</span>';
    return `<div class="d-status">
      <div><span class="lbl">Automatisk kontroll</span>${chip(e.check_result)}</div>
      <div><span class="lbl">Status kontroll</span>${qaPill(e.qa_status)}${e.qa_date ? `<span class="muted small">${fmtShort(e.qa_date)}</span>` : ""}</div>
      <div><span class="lbl">Klar til bruk?</span>${e.ready ? readyBadge(e.ready) : '<span class="muted">Ikke vurdert</span>'}</div>
      <div><span class="lbl">Spørsmål til opplaster</span><span>${q}</span></div>
      <div><span class="lbl">Ansvarlig fag</span><b>${esc(e.discipline || "–")}</b></div>
    </div>`;
  }

  // Felt som kan korrigeres, med type redigering. Rekkefølgen er rekkefølgen i «Om dataene».
  const EDIT_FIELDS = {
    data_type: { label: "Datatype", kind: "select" },
    horizontal_epsg: { label: "Koordinatsystem", kind: "crs" },
    height_reference: { label: "Høydesystem", kind: "select", options: ["NN2000", "NN1954", "Ellipsoidisk høyde", "Ingen høyder i fila"] },
    data_date: { label: "Dato", kind: "text", hint: "f.eks. 2024-05 eller 12.05.2024" },
    source: { label: "Kilde", kind: "text" },
    quality: { label: "Kvalitet", kind: "text", hint: "f.eks. FKB-B, 5 pkt/m², ±5 cm" },
    content: { label: "Innhold i registeret", kind: "text" },
    summary: { label: "Beskrivelse", kind: "textarea" },
  };

  function corrNote(c, was) {
    if (!c) return "";
    const who = c.by_name || c.by || "";
    return `<span class="corr">Korrigert av ${esc(who)} ${fmtShort(c.at)}${c.comment ? ` – «${esc(c.comment)}»` : ""}${was != null && was !== "" ? `. Var: ${esc(String(was))}` : ""}</span>`;
  }

  function editForm(d, field, current) {
    const f = EDIT_FIELDS[field];
    const corrected = isCorrected(d, field);
    let input;
    if (f.kind === "select" && field === "data_type") {
      input = `<select name="value" aria-label="${f.label}">${Object.entries(state.me.options.data_types).map(([k, v]) => `<option value="${k}"${k === d.entry.data_type ? " selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
    } else if (f.kind === "select") {
      input = `<select name="value" aria-label="${f.label}">${f.options.map((o) => `<option${o === current ? " selected" : ""}>${o}</option>`).join("")}</select>`;
    } else if (f.kind === "crs") {
      input = `<input type="text" name="value" list="crs-list" value="${esc(current || "")}" placeholder="f.eks. EPSG:25832" aria-label="${f.label}" autocomplete="off">
        <datalist id="crs-list">${(state.me.options.crs || []).map((c) => `<option value="${esc(c.value)}">${esc(c.label)}</option>`).join("")}</datalist>`;
    } else if (f.kind === "textarea") {
      input = `<textarea name="value" rows="2" aria-label="${f.label}">${esc(current || "")}</textarea>`;
    } else {
      input = `<input type="text" name="value" value="${esc(current || "")}" placeholder="${esc(f.hint || "")}" aria-label="${f.label}" autocomplete="off">`;
    }
    return `<form class="edit-f" data-field="${field}">${input}
      <input type="text" name="comment" placeholder="Kommentar – hvorfor endres verdien?" aria-label="Kommentar til endringen" autocomplete="off">
      <div class="row"><button class="btn primary small" type="submit">Lagre</button><button class="btn small" type="button" data-action="edit-cancel">Avbryt</button>${corrected ? '<button class="btn ghost small" type="button" data-action="edit-reset">Tilbakestill</button>' : ""}<span class="error" role="alert"></span></div>
      ${d.entry.kind === "package" && !["summary", "content", "data_type"].includes(field) ? '<span class="hint">Gjelder alle filene i pakken.</span>' : ""}</form>`;
  }

  function isCorrected(d, field) {
    if (field === "summary" || field === "content") return !!(d.entry.text_overrides || {})[field];
    return d.files.some((f) => ((f.effective || {})[field] || {}).from === "manual") || (field === "data_type" && ((d.files[0].uploader_values || {}).data_type || {}).via === "korreksjon");
  }

  function editable(d, field, valueHtml, current, note = "") {
    const editing = state.edit && state.edit.eid === d.entry.id && state.edit.field === field;
    if (editing) return editForm(d, field, current);
    const btn = d.permissions.can_correct ? `<button class="edit-b" type="button" data-edit="${field}" aria-label="Endre ${EDIT_FIELDS[field].label.toLowerCase()}" title="Endre">${ICON_PEN}</button>` : "";
    return `<div class="ed"><div class="ed-v">${valueHtml}${note}</div>${btn}</div>`;
  }

  function standardRows(d) {
    const files = d.files, f = files[0], pkg = d.entry.kind === "package";
    const uniq = (arr) => [...new Set(arr.filter((x) => x != null && x !== ""))];
    const eff = f.effective || {};
    const fmtVal = (k, v) => (k === "data_date" ? fmtDate(v) : k === "horizontal_epsg" ? crsLabel(v) : String(v));
    const show = (k) => {
      const vs = uniq(files.map((x) => ((x.effective || {})[k] || {}).value));
      if (!vs.length) return '<span class="muted">Ukjent</span>' + provenance(eff[k]);
      const e = eff[k] || {};
      return vs.map((v) => (k === "horizontal_epsg" ? crsHtml(v) : esc(fmtVal(k, v)))).join(", ") + provenance(e)
        + (e.conflict != null ? ` <span class="tag warn">uenig: ${esc(String(e.conflict))}</span>` : "")
        + (k === "data_date" && e.kind && e.from === "file" ? `<span class="sub">${esc(e.kind)}</span>` : "");
    };
    const raw = (k) => { const v = (eff[k] || {}).value; return v == null ? "" : k === "horizontal_epsg" ? `EPSG:${v}` : k === "data_date" ? String(v) : String(v); };
    const note = (k) => { const e = eff[k] || {}; return e.from === "manual" ? corrNote(e.corrected, e.was != null ? fmtVal(k, e.was) : null) : ""; };
    const formats = pkg ? esc(d.entry.file_types) : `${esc(f.metadata.format || "")}${f.metadata.format_version ? ` <span class="muted">${esc(f.metadata.format_version)}</span>` : ""}`;
    const hv = (eff.height_reference || {}).value;
    const dtCorr = (f.uploader_values || {}).data_type;
    const to = (d.entry.text_overrides || {}).content;
    return [
      ["Datatype", editable(d, "data_type", esc(d.entry.data_type_label) + (dtCorr && dtCorr.via === "korreksjon" ? provenance({ from: "manual" }) : ""), d.entry.data_type,
        dtCorr && dtCorr.via === "korreksjon" ? corrNote(dtCorr, null) : `<span class="sub">${esc(f.data_type_reason || "")}</span>`)],
      ["Format", formats],
      ["Koordinatsystem", editable(d, "horizontal_epsg", show("horizontal_epsg"), raw("horizontal_epsg"), note("horizontal_epsg"))],
      ["Høydesystem", editable(d, "height_reference", hv === "NONE" ? "Ingen høyder (2D)" + provenance(eff.height_reference) : show("height_reference"), hv || "", note("height_reference"))],
      ["Dato", editable(d, "data_date", show("data_date"), raw("data_date"), note("data_date"))],
      ["Kilde", editable(d, "source", show("source"), raw("source"), note("source"))],
      ["Kvalitet", editable(d, "quality", show("quality"), raw("quality"), note("quality"))],
      ["Innhold i registeret", editable(d, "content", esc(d.entry.content) + (to ? provenance({ from: "manual" }) : ""), d.entry.content, to ? corrNote(to, d.entry.content_auto) : "")],
      ["Plassering", d.profile.georef ? esc(d.profile.georef) : '<span class="muted">Ikke georeferert</span>'],
    ].concat(f.source_path ? [["Sti", `<span class="mono">${esc(pkg ? f.source_path.split("/").slice(0, -1).join("/") + "/" : f.source_path)}</span>`
      + (f.link && !pkg ? ` · <a href="${esc(f.link)}" target="_blank" rel="noopener">Åpne fila</a>` : "")]] : []);
  }

  function crsLabel(v) {
    const c = (state.me.options.crs || []).find((x) => x.value === `EPSG:${v}`);
    return c ? c.label : `EPSG:${v}`;
  }
  function crsHtml(v) {
    const c = (state.me.options.crs || []).find((x) => x.value === `EPSG:${v}`);
    return c ? `${esc(c.label.replace(/ \(EPSG:\d+\)/, ""))} <span class="mono muted">${v}</span>` : `EPSG:${esc(v)}`;
  }

  function aboutBlock(d) {
    const p = d.profile || {};
    const f = d.files[0];
    let ai = d.entry.kind !== "package" && f.ai && f.ai.status === "done" && f.ai.comment ? f.ai.comment.trim() : "";
    const base = (p.summary_original || p.summary || "").trim();
    if (base && ai.startsWith(base)) ai = ai.slice(base.length).trim();
    const facts = (p.facts || []).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
    const kw = (p.keywords || []).length ? `<div class="kw">${p.keywords.map((k) => `<span>${esc(k)}</span>`).join("")}</div>` : "";
    const cov = d.entry.kind !== "package" && f.coverage != null ? `<dt>Dekning av prosjektområdet</dt><dd>${num(f.coverage * 100, 0)} %</dd>` : "";
    const sc = p.summary_corrected;
    const lead = editable(d, "summary", `<p class="lead">${esc(p.summary || d.entry.content || "")}</p>`, p.summary || "", sc ? corrNote(sc, p.summary_original) : "");
    return blk("innhold", "Innhold", `<span class="tag kind">${esc(p.label || "Annet")}</span>`, `
      ${lead}
      ${ai ? `<p class="ai-line"><span class="tag ai">AI</span> ${esc(ai)}</p>` : ""}
      <div class="facts2">
        <dl class="fx"><div class="fx-h">Om dataene${d.permissions.can_correct ? ' <span class="fx-hint">– klikk blyanten for å rette en verdi</span>' : ""}</div>${standardRows(d).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
        <dl class="fx"><div class="fx-h">Fra innholdet</div>${facts || '<dd class="muted full">Ingen flere opplysninger.</dd>'}${cov}${kw ? `<dd class="full">${kw}</dd>` : ""}</dl>
      </div>`);
  }

  function overrideForm(d, c) {
    const opts = ["ok", "warning", "missing_info", "needs_review", "deviation"];
    return `<form class="edit-f ovr-f" data-rule="${esc(c.rule_id)}">
      <label class="small">Nytt resultat for ${esc(c.rule_id)}</label>
      <select name="result">${opts.map((o) => `<option value="${o}"${o === "ok" ? " selected" : ""}>${LABELS[o]}</option>`).join("")}</select>
      <input type="text" name="comment" placeholder="Begrunnelse (påkrevd)" aria-label="Begrunnelse" autocomplete="off">
      <div class="row"><button class="btn primary small" type="submit">Overstyr</button><button class="btn small" type="button" data-action="edit-cancel">Avbryt</button><span class="error" role="alert"></span></div>
      ${d.entry.kind === "package" ? '<span class="hint">Gjelder alle filene i pakken.</span>' : ""}</form>`;
  }

  function overrideNote(c) {
    const o = c.override;
    if (!o) return "";
    return `<div class="corr">Overstyrt fra «${esc(LABELS[o.original] || o.original)}» av ${esc(o.by || "")} ${fmtShort(o.at)} – «${esc(o.comment)}»</div>`;
  }

  function checkTools(d, c, where) {
    if (!d.permissions.can_override) return "";
    if (state.edit && state.edit.eid === d.entry.id && state.edit.rule === c.rule_id && state.edit.where === where) return overrideForm(d, c);
    return c.override
      ? `<button class="link-b" type="button" data-unoverride="${esc(c.rule_id)}">Fjern overstyring</button>`
      : `<button class="link-b" type="button" data-override="${esc(c.rule_id)}" data-where="${where}">Overstyr resultat</button>`;
  }

  function issuesOf(d) {
    const by = new Map();
    d.files.forEach((f) => f.checks.forEach((c) => {
      if (c.result === "ok") return;
      const cur = by.get(c.rule_id) || { ...c, files: [] };
      if ((RESULT_ORDER[c.result] ?? 0) > (RESULT_ORDER[cur.result] ?? 0)) Object.assign(cur, { result: c.result, evidence: c.evidence, comment: c.comment });
      cur.files.push(f.file_name);
      by.set(c.rule_id, cur);
    }));
    return [...by.values()].sort((a, b) => (RESULT_ORDER[b.result] ?? 0) - (RESULT_ORDER[a.result] ?? 0));
  }

  function followBlock(d) {
    const issues = issuesOf(d);
    const open = d.questions.filter((q) => q.status === "open");
    const nChecks = d.files.reduce((s, f) => s + f.checks.length, 0);
    const nOver = Object.keys(d.entry.check_overrides || {}).length;
    const pkg = d.entry.kind === "package";
    const who = (d.entry.uploader || {}).name || "opplaster";
    const overNote = nOver ? ` <span class="muted small">(${plural(nOver, "regel", "regler")} overstyrt manuelt – se «Alle kontroller»)</span>` : "";
    if (!issues.length && !open.length) {
      return blk("oppfolging", "Trenger oppfølging", "", `<p class="all-ok">${ICON_READY.ja} Ingen oppfølging. ${pkg ? `Alle ${d.files.length} filer` : `Alle ${nChecks} kontroller`} er OK.${overNote}</p>`);
    }
    const rows = issues.map((c) => `<li>${chip(c.result)}<div><div class="it-t"><span class="mono muted">${esc(c.rule_id)}</span> ${esc(c.rule_text)}${c.checked_by === "ai" ? ' <span class="tag ai">AI</span>' : ""}</div>
      <div class="it-e">${esc(c.checked_by === "ai" && c.comment ? c.comment : c.evidence)}</div>
      ${pkg ? `<div class="it-f">${c.files.length === d.files.length ? "Alle filer" : esc(c.files.map((x) => x.replace(/^.*_(blokk\d+)/i, "$1")).join(", "))}</div>` : ""}
      ${c.flagged_for_review ? '<div class="it-f flag">Til vurdering hos KS</div>' : ""}${overrideNote(c)}${checkTools(d, c, "follow")}</div></li>`).join("");
    const qs = open.map((q) => (d.permissions.can_answer ? questionForm(q, pkg)
      : `<div class="qwait"><div class="qtext">${esc(q.question)}</div><div class="muted small">Venter på svar fra ${esc(who)} · spurt ${fmtShort(q.asked_at)}</div></div>`)).join("");
    return blk("oppfolging", "Trenger oppfølging", `${issues.length ? plural(issues.length, "regel", "regler") : ""}${issues.length && open.length ? " · " : ""}${open.length ? plural(open.length, "spørsmål", "spørsmål") : ""}`, `
      ${issues.length ? `<ul class="issues">${rows}</ul>` : ""}${overNote ? `<p>${overNote}</p>` : ""}
      ${open.length ? `<div class="qlist"><div class="q-h">Spørsmål til ${esc(who)}${d.permissions.can_answer ? ' <span class="muted small">– hvert svar kontrollerer dataene på nytt</span>' : ""}</div>${qs}</div>` : ""}`, { cls: "follow" });
  }

  function commentsBlock(d) {
    const list = d.entry.comment_list || [];
    const items = list.map((c) => `<li><div class="cm-h"><b>${esc(c.by_name || c.by)}</b><span class="muted small">${fmtDate(c.at)}</span></div><div class="cm-t">${esc(c.text)}</div></li>`).join("");
    return blk("kommentarer", "Kommentarer", list.length ? String(list.length) : "ingen ennå", `
      ${list.length ? `<ul class="cm">${items}</ul>` : '<p class="muted small">Skriv om noe er feil, uklart eller må følges opp. Kommentarene lagres som dokumentasjon og eksporteres til Excel.</p>'}
      <form class="cm-f" id="comment-form" data-eid="${esc(d.entry.id)}"><textarea name="text" rows="2" placeholder="Skriv en kommentar …" aria-label="Ny kommentar"></textarea>
        <div class="row"><button class="btn small" type="submit">Legg til kommentar</button><span class="error" role="alert"></span></div></form>`,
    { collapsible: true, open: list.length > 0 });
  }

  function questionForm(q, pkg) {
    const real = (q.choices || []).filter((c) => c !== DONT_KNOW);
    const hasDk = (q.choices || []).includes(DONT_KNOW);
    let body;
    if (real.length) {
      body = `<div class="choices" role="radiogroup" aria-label="${esc(q.question)}">${q.choices.map((c, i) => `<label><input type="radio" name="ans-${esc(q.id)}" id="ans-${esc(q.id)}-${i}" value="${esc(c)}"${c === q.suggested ? " checked" : ""}><span>${esc(c)}</span></label>`).join("")}</div>`;
    } else if (q.optional) {
      body = `<textarea id="ans-${esc(q.id)}" name="text" rows="2" placeholder="${esc(q.hint || "")}"></textarea>`;
    } else {
      body = `<input type="text" id="ans-${esc(q.id)}" name="text" placeholder="${esc(q.hint || "")}" autocomplete="off">`;
    }
    const applies = pkg && q.file_names && q.file_names.length > 1 && !q.optional ? `<span class="hint">Gjelder ${q.file_names.length} filer</span>` : "";
    return `<form class="qform" data-qid="${esc(q.id)}">
      <div class="qtext">${esc(q.question)}${q.optional ? ' <span class="muted small">(valgfritt)</span>' : ""}${applies}</div>
      ${q.kind === "contradiction" ? '<div class="hint">Fila og opplysningene er uenige – velg det som er riktig.</div>' : ""}
      ${body}
      <div class="row"><button class="btn primary small" type="submit">Lagre svar</button>${!real.length && hasDk ? `<button class="btn small" type="button" data-action="dont-know">${DONT_KNOW}</button>` : ""}<span class="error" role="alert"></span></div>
    </form>`;
  }

  function diffMap(c) {
    const rows = c.map.values;
    const ny = rows.length, nx = rows[0] ? rows[0].length : 0;
    if (!nx) return "";
    const k = Math.max(3, Math.floor(360 / Math.max(nx, ny)));
    const W = nx * k, H = ny * k;
    let cells = "";
    rows.forEach((row, y) => row.forEach((v, x) => {
      if (v === null) return;
      const s = Math.max(-5, Math.min(5, Math.round(v / 0.2)));
      cells += `<rect x="${x * k}" y="${y * k}" width="${k}" height="${k}" class="${s === 0 ? "d0" : (s < 0 ? "dn" : "dp") + Math.abs(s)}"/>`;
    }));
    const widthM = c.map.width_m;
    const steps = [10, 20, 50, 100, 200, 250, 500, 1000, 2000];
    const bar = steps.reduce((b, s) => (s <= widthM * 0.3 ? s : b), steps[0]);
    const barPx = (bar / widthM) * W;
    return `<svg viewBox="-1 -1 ${W + 2} ${H + 26}" role="img" aria-label="Differansekart: ny minus referanse">
      <defs><pattern id="bd-nodata" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><path d="M0 0V6" class="nodata-line"/></pattern></defs>
      <rect x="0" y="0" width="${W}" height="${H}" fill="var(--surface)"/><rect x="0" y="0" width="${W}" height="${H}" fill="url(#bd-nodata)" stroke="var(--line)"/>${cells}
      <g transform="translate(${W - 18},6)"><path d="M0 12 5 0 10 12 5 9z" fill="var(--ink)"/><text x="5" y="22" text-anchor="middle" font-size="9" font-family="var(--font-display)" fill="var(--ink)">N</text></g>
      <g transform="translate(0,${H + 14})"><path d="M0 0H${barPx.toFixed(1)}" stroke="var(--ink-2)" stroke-width="2"/><path d="M0 -4V4M${barPx.toFixed(1)} -4V4" stroke="var(--ink-2)" stroke-width="1.5"/>
        <text x="${(barPx + 6).toFixed(1)}" y="4" font-size="10" font-family="var(--font-mono)" fill="var(--ink-2)">${bar >= 1000 ? bar / 1000 + " km" : bar + " m"}</text></g></svg>`;
  }

  function histogram(c) {
    const h = c.hist, n = h.counts.length;
    const max = Math.max(...h.counts, 1);
    const W = 320, H = 70, bw = W / n;
    const bars = h.counts.map((v, i) => {
      const mid = (h.edges[i] + h.edges[i + 1]) / 2;
      const s = Math.max(-5, Math.min(5, Math.round(mid / 0.1)));
      const cls = s === 0 ? "d0" : (s < 0 ? "dn" : "dp") + Math.min(5, Math.abs(s));
      const bh = (v / max) * (H - 16);
      return `<rect x="${(i * bw + 1).toFixed(1)}" y="${(H - 14 - bh).toFixed(1)}" width="${(bw - 2).toFixed(1)}" height="${bh.toFixed(1)}" class="${cls}" stroke="var(--line)" stroke-width="0.5"><title>${num(h.edges[i], 2)} til ${num(h.edges[i + 1], 2)} m: ${num(v)} celler</title></rect>`;
    }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Fordeling av høydeavvik">
      ${bars}<path d="M${W / 2} 0V${H - 12}" stroke="var(--ink-3)" stroke-dasharray="2 2"/>
      <text x="0" y="${H - 1}" font-size="10" font-family="var(--font-mono)" fill="var(--ink-3)">−0,5 m</text>
      <text x="${W / 2}" y="${H - 1}" text-anchor="middle" font-size="10" font-family="var(--font-mono)" fill="var(--ink-3)">0</text>
      <text x="${W}" y="${H - 1}" text-anchor="end" font-size="10" font-family="var(--font-mono)" fill="var(--ink-3)">+0,5 m</text></svg>`;
  }

  function cmpBody(f) {
    const c = f.comparison;
    if (c.status === "no_reference") return '<p class="muted">Ingen godkjent terrengmodell eller punktsky overlapper ennå. Når en referanse settes som klar til bruk, sammenlignes dataene automatisk.</p>';
    if (c.status === "no_overlap") return '<p class="muted">Ingen godkjente terrengdata i samme koordinatsystem overlapper.</p>';
    if (c.status === "crs_unknown") return '<p class="notice warn">Venter på koordinatsystem. Svar på spørsmålet om koordinatsystem, så kjøres sammenligningen med en gang.</p>';
    if (c.status !== "done") return `<p class="notice warn">${esc(c.note || "Høydene kunne ikke leses.")}</p>`;
    const ref = c.reference || {};
    const sh = c.shift || {};
    const changed = (c.area_over_m2 || {})["0.5"] || 0;
    const refRow = state.entries.find((x) => x.id === ref.entry_id);
    const stale = refRow && (refRow.lifecycle === "utgatt" || !refRow.ready)
      ? `<p class="notice warn">#${esc(ref.entry_seq)} er ikke lenger godkjent referanse${refRow.superseded_by ? ` (erstattet av #${esc(refRow.superseded_by.seq)})` : ""}. ${DEMO ? "I demoen vises forrige sammenligning; i appen sammenlignes dataene på nytt med en gang." : "Sammenligningen kjøres på nytt ved neste kontroll."}</p>` : "";
    return `${stale}<p class="small muted">Mot <a href="#entry-${esc(ref.entry_id)}">#${esc(ref.entry_seq)} ${esc(ref.file_name)}</a>${ref.data_date ? `, data fra ${fmtDate(ref.data_date)}` : ""}, godkjent ${fmtShort(ref.approved_at)}. Sammenlignet ${areaText(c.area_m2)} i ${num(c.cell_m, c.cell_m < 1 ? 1 : 0)} m rutenett.</p>
      <div class="stats">
        <div><span class="lbl">Systematisk avvik</span><span class="big">${metres(c.mean_m, 2, true)}</span></div>
        <div><span class="lbl">Spredning (std)</span><span class="big">${metres(c.std_m)}</span></div>
        <div><span class="lbl">95 % innenfor</span><span class="big">±${metres(c.p95_abs_m)}</span></div>
        <div><span class="lbl">Endret areal &gt; 0,5 m</span><span class="big">${changed ? areaText(changed) : "Ingen"}</span></div>
        <div><span class="lbl">Størst avvik</span><span class="big">${metres(c.max_m, 2, true)}</span></div>
        <div><span class="lbl">Forskyvning</span><span class="big">${sh.suspected ? `ca. ${metres(sh.distance_m, 1)} ${esc(sh.direction)}` : "Ingen tegn"}</span></div>
      </div>
      <div class="cmp"><div>${diffMap(c)}<div class="scale"><span>Lavere</span><span class="ramp"></span><span>Høyere</span></div>
          <p class="small muted">Ny minus referanse, ±1 m full farge. Skravert: ingen data.</p></div>
        <div>${histogram(c)}<p class="small muted">Fordeling av avvik innenfor ±0,5 m.</p></div></div>`;
  }

  function compareBlock(d) {
    const files = d.files.filter((f) => f.comparison);
    if (!files.length) return "";
    const eid = d.entry.id;
    let sel = files.find((f) => f.id === state.cmpFile[eid]);
    const done = files.filter((f) => f.comparison.status === "done");
    if (!sel) sel = (done.length ? done : files).slice().sort((a, b) => Math.abs((b.comparison.mean_m || 0)) - Math.abs((a.comparison.mean_m || 0)))[0];
    let meta = "";
    if (done.length) {
      const w = done.slice().sort((a, b) => Math.abs(b.comparison.mean_m) - Math.abs(a.comparison.mean_m))[0];
      meta = `${metres(w.comparison.mean_m, 2, true)} systematisk${done.length > 1 ? " (største)" : ""}`;
    } else meta = { crs_unknown: "venter på koordinatsystem", no_reference: "ingen referanse ennå", no_overlap: "ingen overlapp" }[files[0].comparison.status] || "";
    const picker = files.length > 1 ? `<div class="picker" role="group" aria-label="Velg fil">${files.map((f) => `<button type="button" data-cmp="${esc(f.id)}" aria-pressed="${f.id === sel.id}"><span class="dot" style="background:var(--${f.check_result === "ok" ? "ok" : f.check_result === "deviation" ? "bad" : "warn"})"></span>${esc(f.file_name.replace(/^.*_(blokk\d+)/i, "$1"))}</button>`).join("")}</div>` : "";
    return blk("sammenligning", "Sammenligning med godkjent referanse", meta, `${picker}${cmpBody(sel)}`, { collapsible: true, open: done.length > 0 });
  }

  function relationsBlock(d) {
    const groups = d.relations || [];
    const n = groups.reduce((s, g) => s + g.entries.length, 0);
    if (!n) return blk("relasjoner", "Relasjoner", "ingen", '<p class="muted">Ingen kjente koblinger til andre registreringer.</p>', { collapsible: true });
    const body = groups.map((g) => `<div class="rel-g"><div class="rel-l">${esc(g.label)}</div><div class="rel-list">${g.entries.map((x) =>
      `<a class="rel${x.lifecycle === "utgatt" ? " old" : ""}" href="#entry-${esc(x.id)}" title="${esc(x.type_label)}${x.note ? " – " + esc(x.note) : ""}"><b>#${esc(x.seq)}</b> ${esc(x.name)}${x.note && g.type !== "samme_omrade" ? ` <span class="muted">${esc(x.note)}</span>` : ""}</a>`).join("")}</div></div>`).join("");
    return blk("relasjoner", "Relasjoner", plural(n, "kobling", "koblinger"), body, { collapsible: true, open: true });
  }

  function checksBlock(d) {
    const files = d.files, pkg = d.entry.kind === "package";
    const all = files.flatMap((f) => f.checks);
    const okN = all.filter((c) => c.result === "ok").length;
    const row = (c) => `<tr><td>${chip(c.result)}</td><td class="mono muted">${esc(c.rule_id)}</td><td>${esc(c.rule_text)}<div class="ev">${esc(c.checked_by === "ai" && c.comment ? c.comment : c.evidence)}</div>${overrideNote(c)}${pkg ? "" : checkTools(d, c, "table")}</td><td class="by">${c.override ? '<span class="tag manual">overstyrt</span>' : c.checked_by === "ai" ? '<span class="tag ai">AI</span>' : esc(CHECKED_BY[c.checked_by] || c.checked_by)}</td></tr>`;
    let body;
    if (!pkg) {
      body = `<table class="ctable"><tbody>${files[0].checks.map(row).join("")}</tbody></table>
        <p class="small muted">Regelsett ${esc(files[0].ruleset_version || "")} · kontrollert ${fmtShort(files[0].last_checked_at)} · versjon ${files[0].version} av fila</p>`;
    } else {
      body = `<div class="files">${files.map((f) => {
        const issues = f.checks.filter((x) => x.result !== "ok").map((x) => x.rule_id).join(", ");
        return `<details><summary><span class="fname">${esc(f.file_name)}</span>${chip(f.check_result)}<span class="small muted">${issues || "alle OK"}</span></summary>
          <table class="ctable"><tbody>${f.checks.map(row).join("")}</tbody></table></details>`;
      }).join("")}</div>`;
    }
    return blk("kontroller", pkg ? `Filer og kontroller` : "Alle kontroller", pkg ? `${files.length} filer` : `${okN} av ${all.length} OK`, body, { collapsible: true, open: false });
  }

  function textBlock(d) {
    const p = d.profile || {};
    const f = d.files[0];
    const notes = [...new Set(d.files.flatMap((x) => (x.metadata.notes || [])))];
    const ctx = [...new Map(d.files.flatMap((x) => x.context_texts || []).map((t) => [t.name, t])).values()];
    const sidecars = [...new Set(d.files.flatMap((x) => x.sidecars || []))];
    const mentions = [...((p.mentions || {}).files || []), ...((p.mentions || {}).drawings || []).map((x) => `tegning ${x}`)];
    if (!p.text_excerpt && !notes.length && !ctx.length && !sidecars.length && !mentions.length) return "";
    const body = `${p.text_excerpt ? `<blockquote class="excerpt">${esc(p.text_excerpt)}${p.text_excerpt.length >= 600 ? "…" : ""}</blockquote>` : ""}
      <dl class="fx">
        ${mentions.length ? `<dt>Omtaler</dt><dd>${esc(mentions.join(", "))}</dd>` : ""}
        ${ctx.length ? `<dt>Tekst lest</dt><dd>${ctx.map((t) => `${esc(t.name)} <span class="muted">(${esc(t.kind)})</span>`).join(", ")}</dd>` : ""}
        ${sidecars.length ? `<dt>Tilhørende filer</dt><dd class="mono">${esc(sidecars.join(", "))}</dd>` : ""}
        ${notes.length ? `<dt>Merknader</dt><dd>${notes.map((n) => esc(n)).join("<br>")}</dd>` : ""}
      </dl>`;
    return blk("tekst", "Tekst og notater fra fila", "", body, { collapsible: true });
  }

  function historyBlock(d) {
    const items = [];
    if (d.entry.uploader_comment) items.push(`Kommentar fra opplaster: «${esc(d.entry.uploader_comment)}»`);
    d.questions.filter((q) => q.status === "answered").forEach((q) => items.push(`${fmtShort(q.answered_at)}: svar på «${esc(q.question)}» – <b>${esc(q.answer)}</b>`));
    (d.entry.history || []).forEach((h) => items.push(`${fmtShort(h.at)}: ${esc(h.event)}${h.ready ? ` (var «${esc(READY[h.ready])}»)` : ""}`));
    d.files.forEach((f) => (f.history || []).forEach((h) => items.push(`${fmtShort(h.replaced_at)}: ${esc(f.file_name)} versjon ${h.version} erstattet`)));
    if (!items.length) return "";
    return blk("historikk", "Historikk og svar", plural(items.length, "hendelse", "hendelser"), `<ul class="notes">${items.map((x) => `<li>${x}</li>`).join("")}</ul>`, { collapsible: true });
  }

  function ksBlock(d) {
    const e = d.entry, can = d.permissions.can_review;
    const rev = e.review;
    const current = rev ? `<p class="small">${readyBadge(e.ready)} · ${esc(rev.by)} · ${fmtShort(rev.at)}${rev.comment ? `<br><span class="muted">«${esc(rev.comment)}»</span>` : ""}</p>` : "";
    if (!can) {
      return blk("ks", "Kvalitetskontroll", "", `<dl class="fx">
        <dt>Ansvarlig fag</dt><dd><b>${esc(e.discipline || "")}</b></dd><dt>Status kontroll</dt><dd>${qaPill(e.qa_status)}</dd>
        <dt>Dato kontrollert</dt><dd>${fmtShort(e.qa_date) || dash}</dd><dt>Klar til bruk?</dt><dd>${readyBadge(e.ready)}</dd>
        ${e.qa_note ? `<dt>KS-merknad</dt><dd>${esc(e.qa_note)}</dd>` : ""}</dl>${current}
        <p class="small muted">KS-feltene fylles ut av KS-ansvarlig.</p>`, { cls: "ks" });
    }
    const fag = d.options.disciplines;
    const cand = e.replaces_candidate;
    const repOpts = [["auto", `Automatisk${cand ? ` – forslag: #${cand.seq} ${cand.name}` : " – ingen forslag"}`], ["none", "Ingen – ikke en ny versjon"],
      ...d.replace_choices.map((x) => [x.id, `#${x.seq} ${x.name}${x.lifecycle === "utgatt" ? " (utgått)" : ""}`])];
    const repVal = e.replaces_mode === "manual" && e.replaces ? e.replaces.id : e.replaces_mode;
    const warn = [];
    if (e.open_questions) warn.push(plural(e.open_questions, "åpent spørsmål", "åpne spørsmål"));
    if (e.check_result !== "ok") warn.push(`automatisk kontroll: ${LABELS[e.check_result]}`);
    const pend = state.pendingReady;
    const key = `${state.open}:ksfelt`;
    return blk("ks", "Kvalitetskontroll", "", `
      <div class="decision-box" data-eid="${esc(e.id)}">
        <span class="lbl">Er dokument/fil klar til bruk?</span>${current}
        ${warn.length && !e.ready ? `<p class="notice warn small">Før du godkjenner: ${esc(warn.join("; "))}.</p>` : ""}
        <div class="seg" role="group" aria-label="Klar til bruk">${Object.entries(READY).map(([k, v]) => `<button type="button" class="${k}" data-ready="${k}" aria-pressed="${pend === k}">${ICON_READY[k]} ${v}</button>`).join("")}</div>
        <textarea id="dec-comment" rows="2" placeholder="Kommentar – påkrevd for «Med forbehold» og «Nei»"></textarea>
        <div class="row"><button class="btn primary" type="button" data-action="decide">Lagre vurdering</button>${e.ready ? '<button class="btn ghost" type="button" data-action="reopen">Gjenåpne</button>' : ""}<span class="error" role="alert"></span></div>
      </div>
      <details class="sub-d" data-blk="${esc(key)}"${state.blocks[key] ? " open" : ""}><summary>KS-felt: fag, status, merknad og versjon</summary>
      <form id="qa-form" class="stack" style="gap:10px;margin-top:10px" data-eid="${esc(e.id)}">
        <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px">
          <div class="field"><label for="qa-fag">Ansvarlig fag</label><select id="qa-fag" name="discipline">${fag.map((x) => `<option${x === e.discipline ? " selected" : ""}>${esc(x)}</option>`).join("")}</select></div>
          <div class="field"><label for="qa-status">Status kontroll</label><select id="qa-status" name="qa_status">${Object.entries(QA).map(([k, v]) => `<option value="${k}"${k === e.qa_status ? " selected" : ""}>${v}</option>`).join("")}</select></div>
        </div>
        <div class="field"><label for="qa-from">Mottatt fra</label><input type="text" id="qa-from" name="received_from" value="${esc(e.received_from_override || "")}" placeholder="${esc((e.uploader || {}).name || "")}"></div>
        <div class="field"><label for="qa-rep">Erstatter tidligere registrering</label><select id="qa-rep" name="replaces">${repOpts.map(([k, v]) => `<option value="${esc(k)}"${k === repVal ? " selected" : ""}>${esc(v)}</option>`).join("")}</select>
          <span class="hint">Den erstattede blir satt som utgått når denne er klar til bruk.</span></div>
        <div class="field"><label for="qa-note">KS-merknad</label><textarea id="qa-note" name="qa_note" rows="2" placeholder="Hva er sjekket, hva gjenstår">${esc(e.qa_note || "")}</textarea></div>
        <div class="row"><button class="btn" type="submit">Lagre KS-felt</button><span class="error" role="alert"></span></div>
      </form></details>`, { cls: "ks" });
  }

  function niceLength(m) {
    const steps = [50, 100, 200, 250, 500, 1000, 2000, 2500, 5000];
    return steps.reduce((best, s) => (s <= m ? s : best), steps[0]);
  }

  function sketchBlock(d) {
    const s = d.sketch;
    if (!s) return "";
    const gpts = (x) => (x.geom ? x.geom.points.concat(...x.geom.lines, ...x.geom.polygons) : x.pts);
    const pts = s.area.concat(...s.shapes.map(gpts));
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    let minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
    const padx = (maxx - minx) * 0.06 || 50, pady = (maxy - miny) * 0.06 || 50;
    minx -= padx; maxx += padx; miny -= pady; maxy += pady;
    const W = 340, H = Math.round(Math.max(170, Math.min(260, (W * (maxy - miny)) / (maxx - minx))));
    const k = Math.min((W - 20) / (maxx - minx), (H - 20) / (maxy - miny));
    const ox = (W - (maxx - minx) * k) / 2, oy = (H - (maxy - miny) * k) / 2;
    const tx = (x) => (ox + (x - minx) * k).toFixed(1), ty = (y) => (H - oy - (y - miny) * k).toFixed(1);
    const path = (arr) => "M" + arr.map((p) => `${tx(p[0])},${ty(p[1])}`).join("L") + "Z";
    const col = { ok: "var(--ok)", warning: "var(--warn)", missing_info: "var(--info)", needs_review: "var(--review)", deviation: "var(--bad)" };
    const line = (arr) => "M" + arr.map((p) => `${tx(p[0])},${ty(p[1])}`).join("L");
    const shapes = s.shapes.map((x) => {
      const c = col[x.result] || "var(--accent)", dash = x.mode === "candidate" ? ' stroke-dasharray="5 4"' : x.geom && x.geom.kind === "box" ? ' stroke-dasharray="2 3"' : "";
      const g = x.geom || { polygons: [x.pts], lines: [], points: [] };
      let inner = "";
      if (g.polygons.length) inner += `<path d="${g.polygons.map(path).join("")}" fill="${c}" fill-opacity="0.16" fill-rule="evenodd" stroke="${c}" stroke-width="1.5"${dash}/>`;
      if (g.lines.length) inner += `<path d="${g.lines.map(line).join("")}" fill="none" stroke="${c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"${dash}/>`;
      if (g.points.length) inner += g.points.map((p) => `<circle cx="${tx(p[0])}" cy="${ty(p[1])}" r="2.6" fill="${c}" stroke="var(--surface)" stroke-width="0.8"/>`).join("");
      return `<g><title>${esc(x.name)}: ${esc(LABELS[x.result] || "")}${x.geom ? ` – ${esc(geomText(x.geom))}` : ""}</title>${inner}</g>`;
    }).join("");
    const bar = niceLength((maxx - minx) * 0.28), barPx = bar * k;
    const cand = s.shapes.find((x) => x.mode === "candidate");
    const note = s.missing && !s.shapes.length ? "Kan ikke plasseres før koordinatsystemet er kjent." : s.missing ? `${plural(s.missing, "fil", "filer")} mangler plassering.` : "";
    return blk("kart", "Plassering", esc(s.crs_name), `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Prosjektområde og dataenes utstrekning">
        <rect x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" rx="6" fill="var(--surface-2)" stroke="var(--line)"/>
        <path d="${path(s.area)}" fill="var(--contour-soft)" stroke="var(--contour)" stroke-width="1.6"/>${shapes}
        <g transform="translate(${W - 24},14)"><path d="M0 14 6 0 12 14 6 10z" fill="var(--ink-2)"/><text x="6" y="27" text-anchor="middle" font-size="10" font-family="var(--font-display)" fill="var(--ink-2)">N</text></g>
        <g transform="translate(12,${H - 14})"><path d="M0 0H${barPx.toFixed(1)}" stroke="var(--ink-2)" stroke-width="2"/><path d="M0 -4V4M${barPx.toFixed(1)} -4V4" stroke="var(--ink-2)" stroke-width="1.5"/>
          <text x="${(barPx / 2).toFixed(1)}" y="-7" text-anchor="middle" font-size="10" font-family="var(--font-mono)" fill="var(--ink-2)">${bar >= 1000 ? bar / 1000 + " km" : bar + " m"}</text></g></svg>
      <div class="legend-map"><span><i style="background:var(--contour-soft);border:1.5px solid var(--contour)"></i>Prosjektområde</span>${s.shapes.length ? '<span><i style="border:2px solid var(--ink-3)"></i>Dataene (farge = resultat)</span>' : ""}${cand ? `<span><i style="border:2px dashed var(--ink-3)"></i>Hvis ${esc(cand.crs_name)}</span>` : ""}</div>
      ${note ? `<p class="small muted">${note}</p>` : ""}`, { cls: "sketch" });
  }

  function detailHtml(d) {
    const e = d.entry, pkg = e.kind === "package";
    let notice = "";
    if (e.lifecycle === "utgatt" && e.superseded_by) notice = `<p class="notice old"><b>Utgått</b> – erstattet av <a href="#entry-${esc(e.superseded_by.id)}">#${esc(e.superseded_by.seq)} ${esc(e.superseded_by.name)}</a>${e.superseded_at ? ` ${fmtShort(e.superseded_at)}` : ""}. Brukes ikke som referanse.</p>`;
    else if (e.replaces) {
      const ref = `<a href="#entry-${esc(e.replaces.id)}">#${esc(e.replaces.seq)} ${esc(e.replaces.name)}</a>`;
      notice = e.ready === "ja" || e.ready === "med_forbehold"
        ? `<p class="notice version">Erstatter ${ref}, som nå er utgått.</p>`
        : `<p class="notice version">${e.replaces.mode === "auto" ? "Ser ut til å være en ny versjon av" : "Erstatter"} ${ref}. Den blir utgått når denne settes som klar til bruk.</p>`;
    }
    return `<div class="detail">
      <header class="d-head"><div class="d-title">
          <div class="eyebrow">#${esc(e.seq)} · ${esc(e.data_type_label)} · ${pkg ? `Pakke med ${d.files.length} filer` : "Enkeltfil"}</div>
          <h2>${esc(e.name)}</h2>
          <div class="d-meta">Mottatt ${fmtShort(e.received_at)} fra ${esc(e.received_from)} · leveranse <span class="mono">${esc(e.delivery_id)}</span>${e.folder ? ` · mappe <span class="mono">${esc(e.folder)}</span>` : ""}</div>
        </div><div class="row d-actions"><button class="btn small" type="button" data-action="ask-entry">${ICON_SPARK} Spør AI</button><button class="btn small" type="button" data-action="copy-link">Kopier lenke</button><button class="btn small" type="button" data-action="close">Lukk</button></div></header>
      ${statusStrip(d)}
      ${notice}
      <div class="d-grid">
        <div class="d-main">${aboutBlock(d)}${followBlock(d)}${commentsBlock(d)}${compareBlock(d)}${relationsBlock(d)}${checksBlock(d)}${textBlock(d)}${historyBlock(d)}</div>
        <aside class="d-side">${ksBlock(d)}${sketchBlock(d)}</aside>
      </div></div>`;
  }

  // --- AI-chat ----------------------------------------------------------------------------------------
  const CHAT_SUGGESTIONS = [
    "Oppsummer status for grunnlagsdataene",
    "Hvilke data mangler koordinatsystem?",
    "Hva er relatert til tegning C101?",
    "Er laserdataene i samsvar med godkjent terrengmodell?",
    "Hvor står det noe om kvikkleire?",
    "Hvilke data er eldre enn 10 år?",
  ];

  function chatDrawer() {
    let el = document.getElementById("chat-drawer");
    if (!el) {
      el = document.createElement("aside");
      el.id = "chat-drawer";
      el.className = "chat";
      el.setAttribute("aria-label", "AI-assistent");
      el.hidden = true;
      document.body.appendChild(el);
    }
    return el;
  }

  function linkRefs(html) {
    return html.replace(/(^|[\s(«"'>])#(\d{1,4})\b/g, (m, pre, n) => {
      const e = state.entries.find((x) => String(x.seq) === n);
      return e ? `${pre}<a class="ref" href="#entry-${esc(e.id)}" title="${esc(e.name)}">#${n}</a>` : m;
    });
  }

  function formatAnswer(text) {
    const lines = esc(text || "").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split(/\n/);
    let html = "", list = false, para = [];
    const flush = () => { if (para.length) { html += `<p>${para.join(" ")}</p>`; para = []; } };
    for (const raw of lines) {
      const line = raw.trim();
      const li = line.match(/^(?:[-•*]|\d+[.)])\s+(.*)$/);
      if (li) {
        flush();
        if (!list) { html += "<ul>"; list = true; }
        html += `<li>${li[1]}</li>`;
      } else {
        if (list) { html += "</ul>"; list = false; }
        if (!line) flush();
        else para.push(line.replace(/^#{1,4}\s+/, ""));
      }
    }
    flush();
    if (list) html += "</ul>";
    return linkRefs(html);
  }

  function renderChat() {
    const el = chatDrawer();
    const c = state.chat;
    el.hidden = !state.chatOpen;
    document.body.classList.toggle("chat-open", state.chatOpen);
    if (!state.chatOpen) return;
    const p = project();
    const msgs = c.messages.map((m) => m.role === "user"
      ? `<div class="msg-u">${esc(m.content)}</div>`
      : `<div class="msg-a${m.error ? " err" : ""}">${m.content ? formatAnswer(m.content) : `<p class="thinking">${esc(m.status || "Tenker…")}</p>`}
          ${m.model ? `<div class="msg-meta">${esc(m.model)}${m.tools && m.tools.length ? ` · slo opp: ${esc([...new Set(m.tools)].map((t) => TOOL_LABELS[t] || t).join(", "))}` : ""}</div>` : ""}</div>`).join("");
    const empty = `<div class="chat-empty"><p>Spør om grunnlagsdataene i <b>${esc(p ? p.name : "prosjektet")}</b>: søk etter innhold, finn hva som henger sammen, eller få en analyse av kvalitet og avvik.</p>
      <div class="sugg">${CHAT_SUGGESTIONS.map((s) => `<button type="button" data-chat-q="${esc(s)}">${esc(s)}</button>`).join("")}</div></div>`;
    el.innerHTML = `<header class="chat-h"><div><b>${ICON_SPARK} AI-assistent</b><span class="muted small">${esc(p ? p.name : "")}</span></div>
        <div class="row">${c.messages.length ? '<button class="btn ghost small" type="button" data-action="chat-clear">Ny samtale</button>' : ""}<button class="btn small" type="button" data-action="chat-close" aria-label="Lukk AI-assistenten">Lukk</button></div></header>
      <div class="chat-log" id="chat-log" aria-live="polite">${c.messages.length ? msgs : empty}</div>
      <form class="chat-f" id="chat-form">
        <textarea id="chat-input" rows="2" placeholder="Skriv et spørsmål … (Enter sender)" aria-label="Spørsmål til AI-assistenten"${c.busy ? " disabled" : ""}>${esc(c.draft || "")}</textarea>
        ${c.busy ? '<button class="btn" type="button" data-action="chat-stop">Stopp</button>' : '<button class="btn primary" type="submit">Send</button>'}
      </form>
      <p class="chat-foot">Svarene bygger på registeret og kan inneholde feil – sjekk mot registreringen. ${DEMO ? "I demoen svarer Claude via din egen Claude-konto når du tillater det." : ""}</p>`;
    const log = el.querySelector("#chat-log");
    log.scrollTop = log.scrollHeight;
    if (!c.busy) el.querySelector("#chat-input").focus({ preventScroll: true });
  }

  const TOOL_LABELS = { search_entries: "registeret", get_entry: "registrering", related: "relasjoner", search_text: "tekst i filer", project_overview: "oversikt" };

  function openChat() {
    const pid = project() && project().id;
    if (state.chat.pid !== pid) state.chat = { pid, messages: [], busy: false, draft: "" };
    state.chatOpen = true;
    renderChat();
  }

  async function sendChat(text) {
    const q = (text || "").trim();
    const c = state.chat;
    if (!q || c.busy) return;
    c.messages.push({ role: "user", content: q });
    const answer = { role: "assistant", content: "", status: "Tenker…" };
    c.messages.push(answer);
    c.busy = true;
    c.draft = "";
    c.ctl = new AbortController();
    renderChat();
    const turns = c.messages.filter((m) => m !== answer && !m.error && m.content).map((m) => ({ role: m.role, content: m.content }));
    let pending = 0;
    const update = () => { if (!pending) { pending = requestAnimationFrame(() => { pending = 0; renderChat(); }); } };
    try {
      const res = await api.chat(c.pid, turns, {
        signal: c.ctl.signal,
        onText: (t) => { answer.content = t; update(); },
        onTool: (label) => { answer.status = label; update(); },
      });
      Object.assign(answer, { content: res.answer, model: res.model, tools: res.tools || [] });
    } catch (e) {
      if (e && e.code === "cancelled") answer.content = answer.content || "Stoppet.";
      else Object.assign(answer, { content: (answer.content ? answer.content + "\n\n" : "") + (e.message || "Noe gikk galt."), error: !answer.content });
    } finally {
      c.busy = false;
      renderChat();
    }
  }

  // --- Koordinater (Transversal Mercator for EUREF89 UTM/NTM, samme formler som crs.py) ---------------------
  const GEO = (() => {
    const A = 6378137.0, F = 1 / 298.257222101, E2 = F * (2 - F), EP2 = E2 / (1 - E2);
    const R = Math.PI / 180;
    function info(epsg) {
      if (epsg >= 25831 && epsg <= 25836) return { lon0: (epsg - 25800) * 6 - 183, k0: 0.9996, fe: 500000, fn: 0, lat0: 0 };
      if (epsg >= 32631 && epsg <= 32636) return { lon0: (epsg - 32600) * 6 - 183, k0: 0.9996, fe: 500000, fn: 0, lat0: 0 };
      if (epsg >= 5105 && epsg <= 5130) return { lon0: epsg - 5100 + 0.5, k0: 1.0, fe: 100000, fn: 1000000, lat0: 58 };
      if (epsg === 4326 || epsg === 4258) return { geo: true };
      return null;
    }
    const arc = (phi) => A * ((1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256) * phi - (3 * E2 / 8 + 3 * E2 ** 2 / 32 + 45 * E2 ** 3 / 1024) * Math.sin(2 * phi)
      + (15 * E2 ** 2 / 256 + 45 * E2 ** 3 / 1024) * Math.sin(4 * phi) - (35 * E2 ** 3 / 3072) * Math.sin(6 * phi));
    function fwd(lon, lat, i) {
      const phi = lat * R, lam = (lon - i.lon0) * R;
      const n = A / Math.sqrt(1 - E2 * Math.sin(phi) ** 2), t = Math.tan(phi) ** 2, c = EP2 * Math.cos(phi) ** 2, a = Math.cos(phi) * lam;
      const x = i.k0 * n * (a + (1 - t + c) * a ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * EP2) * a ** 5 / 120);
      const y = i.k0 * (arc(phi) - arc(i.lat0 * R) + n * Math.tan(phi) * (a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a ** 4 / 24 + (61 - 58 * t + t * t + 600 * c - 330 * EP2) * a ** 6 / 720));
      return [x + i.fe, y + i.fn];
    }
    function inv(x, y, i) {
      const m = arc(i.lat0 * R) + (y - i.fn) / i.k0;
      const mu = m / (A * (1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256));
      const e1 = (1 - Math.sqrt(1 - E2)) / (1 + Math.sqrt(1 - E2));
      const p1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
        + (151 * e1 ** 3 / 96) * Math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu);
      const c1 = EP2 * Math.cos(p1) ** 2, t1 = Math.tan(p1) ** 2, n1 = A / Math.sqrt(1 - E2 * Math.sin(p1) ** 2);
      const r1 = A * (1 - E2) / (1 - E2 * Math.sin(p1) ** 2) ** 1.5, d = (x - i.fe) / (n1 * i.k0);
      const phi = p1 - (n1 * Math.tan(p1) / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * d ** 4 / 24 + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * d ** 6 / 720);
      const lam = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * d ** 5 / 120) / Math.cos(p1);
      return [i.lon0 + lam / R, phi / R];
    }
    const toLonLat = (epsg, x, y) => { const i = info(epsg); if (!i) return null; return i.geo ? [x, y] : inv(x, y, i); };
    const fromLonLat = (epsg, lon, lat) => { const i = info(epsg); if (!i) return null; return i.geo ? [lon, lat] : fwd(lon, lat, i); };
    const transform = (x, y, src, dst) => { if (src === dst) return [x, y]; const ll = toLonLat(src, x, y); return ll && fromLonLat(dst, ll[0], ll[1]); };
    const area = (pts) => Math.abs(pts.reduce((s, p, k) => { const q = pts[(k + 1) % pts.length]; return s + p[0] * q[1] - q[0] * p[1]; }, 0)) / 2;
    return { toLonLat, fromLonLat, transform, area, supported: (e) => !!info(e) };
  })();
  const epsgOf = (s) => Number(String(s || "").replace(/^\D+/, "")) || null;

  // --- Kartvisning: egen lett kartmotor (Web Mercator-fliser + SVG), ingen biblioteker -------------------
  const BASEMAPS = {
    graatone: { label: "Kartverket topografisk gråtone", url: "https://cache.kartverket.no/v1/wmts/1.0.0/topograatone/default/webmercator/{z}/{y}/{x}.png", attr: "© Kartverket (CC BY 4.0)", max: 18 },
    topo: { label: "Kartverket topografisk", url: "https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png", attr: "© Kartverket (CC BY 4.0)", max: 18 },
    osm: { label: "OpenStreetMap", url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", attr: "© OpenStreetMap-bidragsytere (ODbL)", max: 19 },
    none: { label: "Ingen – bare rutenett", url: null, attr: "Rutenett i prosjektets koordinatsystem", max: 19 },
  };
  const COLORS = { ok: "var(--ok)", warning: "var(--warn)", missing_info: "var(--info)", needs_review: "var(--review)", deviation: "var(--bad)", pending: "var(--ink-3)" };

  function createMap(el, opts) {
    const m = { z: 13, cx: 0, cy: 0, w: 0, h: 0, tiles: new Map(), base: opts.base || "graatone", tileOk: 0, tileErr: 0, layers: () => "", onClick: null, onDraw: null, draw: null };
    el.innerHTML = `<div class="mp-tiles"></div><svg class="mp-svg" xmlns="http://www.w3.org/2000/svg"></svg>
      <div class="mp-zoom"><button type="button" data-mz="1" aria-label="Zoom inn">+</button><button type="button" data-mz="-1" aria-label="Zoom ut">−</button><button type="button" data-mz="fit" aria-label="Vis hele prosjektet" title="Vis hele prosjektet">⤢</button></div>
      <div class="mp-attr"></div><div class="mp-note" hidden></div><div class="mp-pop" hidden></div>`;
    const tl = el.querySelector(".mp-tiles"), svg = el.querySelector(".mp-svg"), attr = el.querySelector(".mp-attr"), note = el.querySelector(".mp-note");
    const scale = () => 256 * Math.pow(2, m.z);
    m.px = (lon, lat) => { const s = scale(), sin = Math.sin(lat * Math.PI / 180); return [(lon + 180) / 360 * s - (m.cx - m.w / 2), (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s - (m.cy - m.h / 2)]; };
    m.ll = (x, y) => { const s = scale(), wx = x + m.cx - m.w / 2, wy = y + m.cy - m.h / 2; const lon = wx / s * 360 - 180; const n = Math.PI - 2 * Math.PI * wy / s; return [lon, 180 / Math.PI * Math.atan(Math.sinh(n))]; };
    m.center = (lon, lat, z) => { if (z != null) m.z = Math.max(4, Math.min(BASEMAPS[m.base].max, z)); const s = scale(), sin = Math.sin(lat * Math.PI / 180); m.cx = (lon + 180) / 360 * s; m.cy = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s; m.render(); };
    m.fit = (pts, maxZ = 18) => {
      if (!pts.length) return m.center(10.75, 59.91, 11);
      const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
      const c = [(Math.min(...lons) + Math.max(...lons)) / 2, (Math.min(...lats) + Math.max(...lats)) / 2];
      let z = Math.min(maxZ, BASEMAPS[m.base].max);
      for (; z > 4; z--) { m.z = z; m.center(c[0], c[1]); const a = m.px(Math.min(...lons), Math.max(...lats)), b = m.px(Math.max(...lons), Math.min(...lats)); if (b[0] - a[0] < m.w - 60 && b[1] - a[1] < m.h - 60) break; }
      m.center(c[0], c[1], z);
    };
    m.zoomAt = (dz, x = m.w / 2, y = m.h / 2) => { const ll = m.ll(x, y); const z = Math.max(4, Math.min(BASEMAPS[m.base].max, m.z + dz)); if (z === m.z) return; m.z = z; const s = scale(), sin = Math.sin(ll[1] * Math.PI / 180); m.cx = (ll[0] + 180) / 360 * s - (x - m.w / 2); m.cy = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s - (y - m.h / 2); m.render(); };
    m.setBase = (b) => { m.base = b; m.tiles.forEach((img) => img.remove()); m.tiles.clear(); m.tileOk = 0; m.tileErr = 0; note.hidden = true; m.render(); };
    m.render = () => {
      m.w = el.clientWidth; m.h = el.clientHeight;
      const bm = BASEMAPS[m.base];
      attr.textContent = bm.attr;
      const keep = new Set();
      if (bm.url && !(m.tileErr >= 6 && !m.tileOk)) {
        const x0 = Math.floor((m.cx - m.w / 2) / 256), x1 = Math.floor((m.cx + m.w / 2) / 256), y0 = Math.floor((m.cy - m.h / 2) / 256), y1 = Math.floor((m.cy + m.h / 2) / 256);
        const n = Math.pow(2, m.z);
        for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) {
          if (y < 0 || y >= n) continue;
          const xx = ((x % n) + n) % n, key = `${m.base}/${m.z}/${xx}/${y}`;
          keep.add(key);
          let img = m.tiles.get(key);
          if (!img) {
            img = document.createElement("img");
            img.alt = ""; img.draggable = false; img.decoding = "async";
            img.onload = () => { m.tileOk++; img.classList.add("on"); note.hidden = true; };
            img.onerror = () => { m.tileErr++; img.remove(); if (!m.tileOk && m.tileErr >= 2) { note.hidden = false; note.textContent = t("Bakgrunnskartet kunne ikke lastes her – rutenettet viser prosjektets koordinatsystem."); m.drawOverlay(); } };
            img.src = bm.url.replace("{z}", m.z).replace("{x}", xx).replace("{y}", y);
            m.tiles.set(key, img); tl.appendChild(img);
          }
          img.style.transform = `translate(${Math.round(x * 256 - (m.cx - m.w / 2))}px, ${Math.round(y * 256 - (m.cy - m.h / 2))}px)`;
        }
      }
      m.tiles.forEach((img, k) => { if (!keep.has(k)) { img.remove(); m.tiles.delete(k); } });
      m.drawOverlay();
    };
    m.grid = () => {
      if (!(m.base === "none" || (!m.tileOk && m.tileErr >= 2)) || !opts.epsg || !GEO.supported(opts.epsg) || m.z < 9) return "";
      const c = [m.ll(0, 0), m.ll(m.w, m.h), m.ll(0, m.h), m.ll(m.w, 0)].map((p) => GEO.fromLonLat(opts.epsg, p[0], p[1]));
      // Rutenettavstand slik at linjene ligger minst ~90 px fra hverandre
      const perPx = (Math.max(...c.map((p) => p[0])) - Math.min(...c.map((p) => p[0]))) / Math.max(1, m.w);
      const step = [100, 200, 500, 1000, 2000, 5000, 10000].find((s) => s / perPx >= 90) || 10000;
      const xs = c.map((p) => p[0]), ys = c.map((p) => p[1]);
      let out = "";
      for (let x = Math.ceil(Math.min(...xs) / step) * step; x <= Math.max(...xs); x += step) {
        const a = m.px(...GEO.toLonLat(opts.epsg, x, Math.min(...ys))), b = m.px(...GEO.toLonLat(opts.epsg, x, Math.max(...ys)));
        out += `<path class="mp-grid" d="M${a[0].toFixed(1)},${a[1].toFixed(1)}L${b[0].toFixed(1)},${b[1].toFixed(1)}"/>`;
        const l = m.px(...GEO.toLonLat(opts.epsg, x, Math.max(...ys)));
        out += `<text class="mp-gl" x="${(l[0] + 3).toFixed(1)}" y="14">Ø ${x}</text>`;
      }
      for (let y = Math.ceil(Math.min(...ys) / step) * step; y <= Math.max(...ys); y += step) {
        const a = m.px(...GEO.toLonLat(opts.epsg, Math.min(...xs), y)), b = m.px(...GEO.toLonLat(opts.epsg, Math.max(...xs), y));
        out += `<path class="mp-grid" d="M${a[0].toFixed(1)},${a[1].toFixed(1)}L${b[0].toFixed(1)},${b[1].toFixed(1)}"/><text class="mp-gl" x="4" y="${(a[1] - 3).toFixed(1)}">N ${y}</text>`;
      }
      return out;
    };
    m.path = (ring, close = true) => "M" + ring.map((p) => m.px(p[0], p[1]).map((v) => v.toFixed(1)).join(",")).join("L") + (close ? "Z" : "");
    m.drawOverlay = () => {
      svg.setAttribute("viewBox", `0 0 ${m.w} ${m.h}`);
      let d = m.grid() + m.layers(m);
      if (m.draw && m.draw.pts.length) {
        const pts = m.draw.hover ? m.draw.pts.concat([m.draw.hover]) : m.draw.pts;
        d += `<path class="mp-draft" d="${m.path(pts, m.draw.mode !== "polygon" || !m.draw.hover ? pts.length > 2 : false)}"/>`;
        d += m.draw.pts.map((p, k) => { const q = m.px(p[0], p[1]); return `<circle class="mp-vx${k === 0 ? " first" : ""}" cx="${q[0].toFixed(1)}" cy="${q[1].toFixed(1)}" r="${k === 0 ? 6 : 4}"/>`; }).join("");
      }
      svg.innerHTML = d;
    };
    // Panorering, zoom og tegning med pekerhendelser
    let drag = null;
    el.addEventListener("pointerdown", (ev) => {
      if (ev.target.closest(".mp-zoom, .mp-pop, .mp-attr")) return;
      el.setPointerCapture(ev.pointerId);
      const r = el.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
      drag = { x, y, cx: m.cx, cy: m.cy, moved: false };
      if (m.draw && m.draw.mode === "rect") { m.draw.start = m.ll(x, y); m.draw.pts = [m.draw.start]; }
    });
    el.addEventListener("pointermove", (ev) => {
      const r = el.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
      if (m.draw && m.draw.mode === "polygon" && m.draw.pts.length) { m.draw.hover = m.ll(x, y); m.drawOverlay(); }
      if (!drag && !m.draw && m.onHover && ev.pointerType === "mouse") m.onHover(document.elementFromPoint(ev.clientX, ev.clientY));
      if (!drag) return;
      if (Math.abs(x - drag.x) + Math.abs(y - drag.y) > 4) drag.moved = true;
      if (m.draw && m.draw.mode === "rect" && m.draw.start) {
        const a = m.draw.start, b = m.ll(x, y);
        m.draw.pts = [a, [b[0], a[1]], b, [a[0], b[1]]];
        m.drawOverlay();
        return;
      }
      if (drag.moved) { m.cx = drag.cx - (x - drag.x); m.cy = drag.cy - (y - drag.y); m.render(); }
    });
    el.addEventListener("pointerup", (ev) => {
      const r = el.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
      const d0 = drag; drag = null;
      if (!d0) return;
      if (m.draw && m.draw.mode === "rect" && m.draw.start) {
        m.draw.start = null;
        if (m.draw.pts.length === 4 && d0.moved && m.onDraw) m.onDraw(m.draw.pts.slice());
        return;
      }
      if (d0.moved) return;
      if (m.draw && m.draw.mode === "polygon") {
        const p = m.ll(x, y), nowT = Date.now(), last = m.draw.lastClick;
        m.draw.lastClick = { t: nowT, x, y };
        if (last && nowT - last.t < 400 && Math.hypot(last.x - x, last.y - y) < 8) { m.finishPolygon(); return; }
        if (m.draw.pts.length >= 3) { const f = m.px(...m.draw.pts[0]); if (Math.hypot(f[0] - x, f[1] - y) < 10) { m.finishPolygon(); return; } }
        m.draw.pts.push(p); m.drawOverlay();
        return;
      }
      if (m.onClick) m.onClick(document.elementFromPoint(ev.clientX, ev.clientY) || el, x, y);
    });
    el.addEventListener("pointerleave", () => { if (m.onHover) m.onHover(null); });
    el.addEventListener("dblclick", (ev) => { ev.preventDefault(); if (m.draw && m.draw.mode === "polygon") { m.draw.pts.pop(); m.finishPolygon(); } else { const r = el.getBoundingClientRect(); m.zoomAt(1, ev.clientX - r.left, ev.clientY - r.top); } });
    let wheelAt = 0;
    el.addEventListener("wheel", (ev) => { ev.preventDefault(); const now = Date.now(); if (now - wheelAt < 180) return; wheelAt = now; const r = el.getBoundingClientRect(); m.zoomAt(ev.deltaY < 0 ? 1 : -1, ev.clientX - r.left, ev.clientY - r.top); }, { passive: false });
    el.querySelector(".mp-zoom").addEventListener("click", (ev) => { const b = ev.target.closest("[data-mz]"); if (!b) return; if (b.dataset.mz === "fit") { if (opts.fit) opts.fit(); } else m.zoomAt(Number(b.dataset.mz)); });
    m.finishPolygon = () => { const pts = m.draw.pts.slice(); m.draw.hover = null; if (pts.length >= 3 && m.onDraw) m.onDraw(pts); };
    m.popup = (html, x, y) => { const p = el.querySelector(".mp-pop"); if (!html) { p.hidden = true; return; } p.innerHTML = html; p.hidden = false; const pw = p.offsetWidth, ph = p.offsetHeight; p.style.left = `${Math.max(8, Math.min(m.w - pw - 8, x - pw / 2))}px`; p.style.top = `${y - ph - 14 < 8 ? y + 14 : y - ph - 14}px`; };
    const ro = new ResizeObserver(() => m.render());
    ro.observe(el);
    m.destroy = () => ro.disconnect();
    return m;
  }

  // --- Import av prosjektgrense: DXF, LandXML, GeoJSON ------------------------------------------------------
  function largestRing(rings) {
    const ok = rings.filter((r) => r.length >= 3);
    return ok.sort((a, b) => GEO.area(b) - GEO.area(a))[0] || null;
  }
  function parseDxf(text) {
    const lines = text.split(/\r?\n/), pairs = [];
    for (let i = 0; i + 1 < lines.length; i += 2) pairs.push([lines[i].trim(), lines[i + 1].trim()]);
    const rings = [];
    let cur = null, inPoly = false;
    for (const [code, val] of pairs) {
      if (code === "0") {
        if (cur && cur.kind === "LWPOLYLINE") rings.push(cur.pts);
        if (val === "LWPOLYLINE") cur = { kind: "LWPOLYLINE", pts: [], x: null };
        else if (val === "POLYLINE") { cur = null; inPoly = true; rings.push([]); }
        else if (val === "VERTEX" && inPoly) cur = { kind: "VERTEX", x: null };
        else if (val === "SEQEND") { inPoly = false; cur = null; }
        else cur = null;
        continue;
      }
      if (!cur) continue;
      if (code === "10") cur.x = parseFloat(val);
      if (code === "20" && cur.x != null) {
        const p = [cur.x, parseFloat(val)];
        if (cur.kind === "LWPOLYLINE") cur.pts.push(p); else rings[rings.length - 1].push(p);
        cur.x = null;
      }
    }
    if (cur && cur.kind === "LWPOLYLINE") rings.push(cur.pts);
    return { ring: largestRing(rings), epsg: null, what: "lukket polylinje" };
  }
  function parseLandXml(text) {
    const doc = new DOMParser().parseFromString(text, "application/xml");
    if (doc.querySelector("parsererror")) throw new Error(t("Fila er ikke gyldig XML."));
    const all = (name) => [...doc.getElementsByTagName("*")].filter((e) => e.localName === name);
    const cs = all("CoordinateSystem")[0];
    let epsg = cs ? Number(cs.getAttribute("epsgCode")) || epsgOf(cs.getAttribute("ogcWktCode") || "") : null;
    const ne = (s) => { const v = s.trim().split(/[\s,]+/).map(Number); return [v[1], v[0]]; };
    const rings = [];
    all("PntList2D").concat(all("PntList3D")).forEach((el) => {
      const step = el.localName === "PntList3D" ? 3 : 2;
      const v = el.textContent.trim().split(/[\s,]+/).map(Number), pts = [];
      for (let k = 0; k + 1 < v.length; k += step) pts.push([v[k + 1], v[k]]);
      rings.push(pts);
    });
    all("CoordGeom").forEach((cg) => {
      const pts = [];
      [...cg.children].forEach((g) => {
        const s = [...g.children].find((c) => c.localName === "Start"), e = [...g.children].find((c) => c.localName === "End");
        if (s && !pts.length) pts.push(ne(s.textContent));
        if (e) pts.push(ne(e.textContent));
      });
      rings.push(pts);
    });
    const r = largestRing(rings);
    return { ring: r, epsg, what: all("Parcel").length ? "parsell (Parcel)" : "grense (Boundary/PntList)" };
  }
  function parseGeoJson(text) {
    const g = JSON.parse(text);
    const geoms = g.type === "FeatureCollection" ? g.features.map((f) => f.geometry) : g.type === "Feature" ? [g.geometry] : [g];
    const rings = [];
    geoms.forEach((x) => { if (!x) return; if (x.type === "Polygon") rings.push(x.coordinates[0]); if (x.type === "MultiPolygon") x.coordinates.forEach((p) => rings.push(p[0])); });
    const name = ((g.crs || {}).properties || {}).name;
    return { ring: largestRing(rings.map((r) => r.map((p) => [p[0], p[1]]))), epsg: name ? epsgOf(name.replace(/.*EPSG:+/, "")) : null, what: "polygon" };
  }
  async function importArea(file, projectEpsg) {
    const name = file.name.toLowerCase();
    if (/\.dwg$/.test(name)) throw new Error(t("DWG er et lukket binærformat som ikke kan leses i nettleseren. Lagre tegningen som DXF (eller eksporter LandXML fra Civil 3D) og importer den fila."));
    const text = await file.text();
    let res;
    if (/\.dxf$/.test(name)) res = parseDxf(text);
    else if (/\.(xml|landxml)$/.test(name)) res = parseLandXml(text);
    else if (/\.(geo)?json$/.test(name)) res = parseGeoJson(text);
    else throw new Error(t("Velg en DXF-, LandXML- eller GeoJSON-fil."));
    if (!res.ring) throw new Error(t("Fant ingen lukket polygon i fila."));
    let ring = res.ring;
    if (ring.length > 2 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]) ring = ring.slice(0, -1);
    const geographic = ring.every((p) => Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90);
    const epsg = geographic ? 4326 : (res.epsg || projectEpsg);
    if (!GEO.supported(epsg)) throw new Error(t("Koordinatsystemet i fila støttes ikke her."));
    const lonlat = ring.map((p) => GEO.toLonLat(epsg, p[0], p[1]));
    return { points: ring, epsg, lonlat, what: res.what, assumed: !geographic && !res.epsg, file: file.name };
  }

  // --- Kartet i registeret -------------------------------------------------------------------------------
  // Et lite kart ved siden av oppsummeringen som kan utvides til nesten hele skjermen. Det viser de samme
  // registreringene som tabellen (samme filtre), og kart og tabell er koblet: klikk på et fotavtrykk åpner
  // raden, peker over en rad fremhever fotavtrykket, og åpen rad markeres i kartet.
  function geomOf(f) {
    return f.geom || { kind: "box", polygons: [f.ring], lines: [], points: [] };
  }
  function geomText(g) {
    const en = LANG === "en";
    const n = (k, one, many) => (k ? `${k} ${k === 1 ? one : many}` : "");
    if (g.kind === "features") {
      const parts = [n(g.points.length, en ? "point" : "punkt", en ? "points" : "punkter"), n(g.lines.length, en ? "line" : "linje", en ? "lines" : "linjer"),
        n(g.polygons.length, en ? "area" : "flate", en ? "areas" : "flater")].filter(Boolean);
      return `${t("Reell geometri")}: ${parts.join(", ")}`;
    }
    if (g.kind === "outline") return t("Omriss av dataene");
    if (g.kind === "points") return `${t("Plassering")}: ${n(g.points.length, en ? "point" : "punkt", en ? "points" : "punkter")}`;
    return t("Bare utstrekning (rektangel)");
  }
  function footArea(x) { return x.footprints.reduce((s, f) => s + GEO.area(f.ring), 0); }
  function mapItems() {
    const data = state.mapData;
    if (!data) return [];
    const shown = new Set(visibleEntries().map((e) => e.id));
    const byId = new Map(state.entries.map((e) => [e.id, e]));
    return data.items.filter((x) => shown.has(x.id)).map((x) => ({ ...x, ...(byId.get(x.id) || {}), footprints: x.footprints, summary: x.summary }));
  }
  function mapLayers(map) {
    const data = state.mapData, area = data.area || {};
    const items = mapItems();
    const rank = (x) => (x.id === state.open ? 2 : x.id === state.mapHl ? 1 : 0);
    items.sort((a, b) => rank(a) - rank(b) || footArea(b) - footArea(a));
    let s = "";
    if (area.lonlat && area.lonlat.length > 2 && !state.mapDraft) s += `<path class="mp-area" d="${map.path(area.lonlat)}"/>`;
    // Flater nederst (store under små), så linjer, så punkter – da kan alt klikkes selv om det overlapper
    let sa = "", sl = "", sp = "";
    items.forEach((x) => x.footprints.forEach((f) => {
      const g = geomOf(f);
      const col = x.lifecycle === "utgatt" ? "var(--ink-3)" : COLORS[f.result || x.check_result] || COLORS.pending;
      const r = x.id === state.open ? 5 : 3.5;
      const cls = `mp-fp k-${g.kind}${x.lifecycle === "utgatt" ? " old" : ""}${f.guess ? " guess" : ""}${x.id === state.open ? " sel" : ""}${x.id === state.mapHl ? " hl" : ""}`;
      const open = `<g class="${cls}" data-eid="${esc(x.id)}" data-file="${esc(f.file)}" style="--c:${col}"><title>#${x.seq} ${esc(x.name)}${x.kind === "package" ? ` – ${esc(f.file)}` : ""}</title>`;
      if (g.polygons.length) sa += `${open}<path class="fp-a" d="${g.polygons.map((q) => map.path(q)).join("")}"/></g>`;
      if (g.lines.length) { const d = g.lines.map((q) => map.path(q, false)).join(""); sl += `${open}<path class="fp-l" d="${d}"/><path class="fp-h" d="${d}"/></g>`; }
      if (g.points.length) sp += `${open}<path class="fp-p" d="${g.points.map((p) => { const q = map.px(p[0], p[1]); return `M${(q[0] - r).toFixed(1)},${q[1].toFixed(1)}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0`; }).join("")}"/></g>`;
    }));
    s += sa + sl + sp;
    if (state.mapDraft) s += `<path class="mp-area draft" d="${map.path(state.mapDraft.lonlat)}"/>`;
    return s;
  }
  function geomPts(x) {
    return x.footprints.flatMap((f) => { const g = geomOf(f); return g.points.concat(...g.lines, ...g.polygons); });
  }
  function fitAll() {
    const map = state.map, data = state.mapData;
    if (!map || !data) return;
    const items = mapItems();
    map.fit(((data.area || {}).lonlat || []).concat(...items.map((x) => x.footprints.map((f) => f.ring)).flat()));
  }
  function mapCount() {
    const el = document.getElementById("mb-count");
    if (!el || !state.mapData) return;
    const shown = new Set(visibleEntries().map((e) => e.id));
    const placed = state.mapData.items.filter((x) => shown.has(x.id)).length;
    const un = state.mapData.unplaced.filter((x) => shown.has(x.id)).length;
    el.textContent = `${placed} ${t("i kartet")}${un ? ` · ${un} ${t("uten plassering")}` : ""}`;
  }
  // Etter filterendring, åpning av rad eller ny data
  function mapSync(focus) {
    if (!state.map) return;
    mapCount();
    state.map.drawOverlay();
    if (state.mapBig) renderMapSide();
    if (focus && state.open) mapFocus(state.open);
  }
  // Vis den åpne registreringen i kartet hvis den ligger utenfor utsnittet
  function mapFocus(id) {
    const map = state.map, x = state.mapData && state.mapData.items.find((i) => i.id === id);
    if (!map || !x) return;
    const pts = geomPts(x);
    if (!pts.length) return;
    const inside = pts.every((p) => { const q = map.px(p[0], p[1]); return q[0] > 8 && q[1] > 8 && q[0] < map.w - 8 && q[1] < map.h - 8; });
    if (!inside) map.fit(pts, 16);
  }
  function setMapHl(id) {
    if (state.mapHl === id) return;
    state.mapHl = id;
    document.querySelectorAll("#list .hl").forEach((r) => r.classList.remove("hl"));
    if (id) document.querySelectorAll(`#list [data-id="${CSS.escape(id)}"], #list [data-toggle="${CSS.escape(id)}"]`).forEach((r) => r.classList.add("hl"));
    // Bare klassebytte, ikke ny tegning: elementet under pekeren må ikke byttes ut midt i et klikk
    document.querySelectorAll(".mp-fp").forEach((g) => {
      const on = g.dataset.eid === id;
      g.classList.toggle("hl", on);
    });
  }
  function openFromMap(id) {
    if (state.mapBig) setMapBig(false);
    if (state.open === id) { syncOpen(true); return; }
    location.hash = `#entry-${id}`;
  }

  function mapBoxHtml() {
    return `<div class="mapbox panel" id="mapbox">
      <div class="mb-head"><span class="eyebrow">Kart</span><span class="small muted" id="mb-count"></span><span class="spacer"></span>
        <button class="btn small ghost mb-x" type="button" data-action="map-expand" aria-expanded="false" title="Utvid kartet">${ICON_EXPAND}<span>Utvid</span></button></div>
      <div class="draw-bar" id="draw-bar" hidden></div>
      <div class="mb-body"><div class="map" id="map" role="application" aria-label="Kart over prosjektet"></div><aside class="map-side" id="map-side" hidden></aside></div>
    </div>`;
  }
  const ICON_EXPAND = '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M9.5 2.5h4v4M6.5 13.5h-4v-4M13.5 2.5 9 7M2.5 13.5 7 9" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const ICON_SHRINK = '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M13.5 6.5h-4v-4M2.5 9.5h4v4M9.5 6.5 14 2M6.5 9.5 2 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  async function setupMap(p) {
    const box = document.getElementById("mapbox");
    if (!box) return;
    try {
      state.mapData = await api.get(`/projects/${enc(p.id)}/map`);
    } catch (e) {
      box.querySelector(".mb-body").innerHTML = `<p class="small muted" style="padding:12px">${esc(e.message)}</p>`;
      return;
    }
    if (!document.getElementById("map")) return;
    let base = "graatone";
    try { base = localStorage.getItem("bd-basemap") || base; } catch (e) { /* ingen lagring */ }
    if (!BASEMAPS[base]) base = "graatone";
    const map = createMap(document.getElementById("map"), { base, epsg: epsgOf(state.mapData.crs), fit: fitAll });
    state.map = map;
    map.layers = mapLayers;
    map.onHover = (target) => {
      const g = target && target.closest && target.closest("[data-eid]");
      setMapHl(g ? g.dataset.eid : null);
    };
    map.onClick = (target, x, y) => {
      const g = target.closest && target.closest("[data-eid]");
      if (!g) { map.popup(null); return; }
      const it = mapItems().find((i) => i.id === g.dataset.eid);
      if (!it) return;
      if (!state.mapBig) { openFromMap(it.id); return; }
      const f = it.footprints.find((q) => q.file === g.dataset.file) || it.footprints[0];
      const gm = geomOf(f);
      map.popup(`<div class="pop-h"><b>#${it.seq}</b> ${esc(it.name)}</div>
        <div class="pop-t">${esc(it.data_type_label)}${it.kind === "package" ? ` · ${esc(f.file)} (${it.footprints.findIndex((q) => q === f) + 1} / ${it.footprints.length})` : ""}</div>
        <p class="pop-s">${esc(it.summary || it.content || "")}</p>
        <div class="pop-c">${chip(f.result || it.check_result)}${qaPill(it.qa_status)}${it.ready ? readyBadge(it.ready) : ""}${it.lifecycle === "utgatt" ? '<span class="tag old">Utgått</span>' : ""}</div>
        <div class="pop-g2">${esc(geomText(gm))}${gm.source ? ` · ${esc(t(gm.source))}` : ""}</div>
        ${f.guess ? `<p class="pop-g">${esc(t("Mulig plassering"))}: ${esc(f.crs_name)} – ${esc(t("koordinatsystemet er ukjent eller ser feil ut."))}</p>` : ""}
        <div class="pop-m">${esc(t("Mottatt"))} ${fmtShort(it.received_at)} · ${esc(it.received_from)}</div>
        <button class="btn small primary" type="button" data-action="map-open" data-id="${esc(it.id)}">${esc(t("Vis i registeret"))} →</button>`, x, y);
    };
    map.onDraw = (lonlat) => {
      map.draw = null;
      document.getElementById("map").classList.remove("drawing");
      setDraft({ lonlat, points: lonlat, epsg: 4326, source: lonlat.length === 4 && state.drawMode === "rect" ? "rektangel tegnet i kartet" : "polygon tegnet i kartet" });
    };
    state.setDraft = setDraft;
    mapCount();
    if (state.mapBig) setMapBig(true, true);
    fitAll();
    if (state.open) mapFocus(state.open);
  }

  function setDraft(dr) {
    const map = state.map, data = state.mapData;
    state.mapDraft = dr;
    map.popup(null);
    const bar = document.getElementById("draw-bar");
    const a = GEO.area(dr.lonlat.map((p) => GEO.fromLonLat(epsgOf(data.crs) || 25832, p[0], p[1])));
    bar.hidden = false;
    bar.innerHTML = `<span><b>${esc(t("Nytt prosjektområde"))}</b> · ${dr.lonlat.length} ${esc(t("punkter"))} · ${areaText(a)}${dr.file ? ` · ${esc(dr.file)}` : ""}${dr.assumed ? ` · <span class="tag warn">${esc(t("tolket som"))} ${esc(data.crs_name)}</span>` : ""}</span><span class="spacer"></span>
      <button class="btn" type="button" data-area="cancel">${esc(t("Avbryt"))}</button><button class="btn primary" type="button" data-area="save">${esc(t("Lagre område"))}</button>`;
    map.drawOverlay();
    map.fit(dr.lonlat.concat((data.area || {}).lonlat || []));
  }

  // Sidepanelet i utvidet kart: filtrene (flyttet hit fra registeret), bakgrunnskart, tegnforklaring,
  // prosjektområde og det som ikke kan plasseres.
  function renderMapSide() {
    const side = document.getElementById("map-side"), data = state.mapData;
    if (!side || !data) return;
    const area = data.area || {}, base = state.map ? state.map.base : "graatone";
    const shown = new Set(visibleEntries().map((e) => e.id));
    const un = data.unplaced.filter((x) => shown.has(x.id));
    let filt = side.querySelector(".filters");
    side.innerHTML = `<div class="ms-b ms-f"><div class="ms-h">Filtre</div><div class="ms-fslot"></div></div>
      <div class="ms-b"><div class="ms-h">Bakgrunnskart</div><select id="basemap" aria-label="Bakgrunnskart">${Object.entries(BASEMAPS).map(([k, v]) => `<option value="${k}"${k === base ? " selected" : ""}>${esc(v.label)}</option>`).join("")}</select></div>
      <div class="ms-b"><div class="ms-h">Automatisk kontroll</div><div class="ms-legend">${["ok", "warning", "missing_info", "needs_review", "deviation"].map((r) => `<span><i style="border-color:${COLORS[r]};background:color-mix(in srgb, ${COLORS[r]} 22%, transparent)"></i>${LABELS[r]}</span>`).join("")}</div></div>
      <div class="ms-b"><div class="ms-h">Fotavtrykk</div><div class="ms-legend">
        <span><svg class="lg" viewBox="0 0 22 14" aria-hidden="true"><path d="M2 12 6 3l7 2 7-3v10z" fill="color-mix(in srgb, var(--ink-2) 18%, transparent)" stroke="var(--ink-2)" stroke-width="1.6"/></svg>Flater og omriss</span>
        <span><svg class="lg" viewBox="0 0 22 14" aria-hidden="true"><path d="M1 11 7 4l6 6 8-8" fill="none" stroke="var(--ink-2)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>Linjer</span>
        <span><svg class="lg" viewBox="0 0 22 14" aria-hidden="true"><circle cx="5" cy="9" r="3" fill="var(--ink-2)"/><circle cx="13" cy="5" r="3" fill="var(--ink-2)"/><circle cx="18" cy="10" r="3" fill="var(--ink-2)"/></svg>Punkter</span>
        <span><i class="lg-box"></i>Bare utstrekning</span><span><i class="lg-guess"></i>Mulig plassering</span><span><i class="lg-old"></i>Utgått</span><span><i class="lg-area"></i>Prosjektområde</span></div></div>
      <div class="ms-b"><div class="ms-h">Prosjektområde</div><p class="small">${area.lonlat && area.lonlat.length ? `${area.lonlat.length} punkter i ${esc(data.crs_name || "")}${area.source ? ` · ${esc(area.source)}` : ""}${area.updated_by ? ` · ${esc(area.updated_by)} ${fmtShort(area.updated_at)}` : ""}` : '<span class="muted">Ikke satt.</span>'}</p>
        ${data.can_edit ? `<div class="row area-tools"><button class="btn small" type="button" data-area="rect">Tegn rektangel</button><button class="btn small" type="button" data-area="polygon">Tegn polygon</button>
          <label class="btn small" for="area-file">Importer område<input type="file" id="area-file" accept=".dxf,.dwg,.xml,.landxml,.geojson,.json" hidden></label></div>` : ""}</div>
      ${un.length ? `<div class="ms-b"><div class="ms-h">Ikke plassert</div><ul class="ms-un">${un.map((x) => `<li><button type="button" class="link-b" data-action="map-open" data-id="${esc(x.id)}"><b>#${x.seq}</b> ${esc(x.name)}</button><span class="muted small">${esc(x.reason)}</span></li>`).join("")}</ul></div>` : ""}`;
    filt = filt || document.querySelector(".filters");
    if (filt) side.querySelector(".ms-fslot").appendChild(filt);
  }

  function setMapBig(on, initial) {
    const box = document.getElementById("mapbox");
    if (!box) return;
    state.mapBig = on;
    box.classList.toggle("expanded", on);
    document.body.classList.toggle("map-big", on);
    const btn = box.querySelector("[data-action=map-expand]");
    btn.setAttribute("aria-expanded", String(on));
    btn.title = t(on ? "Gjør kartet lite igjen" : "Utvid kartet");
    btn.innerHTML = on ? `${ICON_SHRINK}<span>${t("Lukk stort kart")}</span>` : `${ICON_EXPAND}<span>${t("Utvid")}</span>`;
    const side = document.getElementById("map-side");
    if (on) { side.hidden = false; renderMapSide(); }
    else {
      stopDraw();
      const filt = side.querySelector(".filters"), slot = document.getElementById("filters-slot");
      if (filt && slot) slot.appendChild(filt);
      side.hidden = true; side.innerHTML = "";
      if (state.map) state.map.popup(null);
      if (location.hash === "#kart") { try { history.replaceState(null, "", "#register"); } catch (e) { /* ignorer */ } }
    }
    if (state.map && !initial) requestAnimationFrame(() => { state.map.render(); if (on) fitAll(); else if (state.open) mapFocus(state.open); });
  }

  function startDraw(mode) {
    const map = state.map;
    if (!map) return;
    state.drawMode = mode;
    state.mapDraft = null;
    map.popup(null);
    map.draw = { mode, pts: [], hover: null };
    const bar = document.getElementById("draw-bar");
    bar.hidden = false;
    bar.innerHTML = `<span>${mode === "rect" ? t("Dra i kartet for å tegne rektangelet.") : t("Klikk for hvert hjørne. Dobbeltklikk eller klikk på første punkt for å avslutte. Esc avbryter.")}</span><span class="spacer"></span><button class="btn" type="button" data-area="cancel">${t("Avbryt")}</button>${mode === "polygon" ? `<button class="btn primary" type="button" data-area="finish">${t("Ferdig")}</button>` : ""}`;
    document.getElementById("map").classList.add("drawing");
    map.drawOverlay();
  }

  function stopDraw() {
    if (state.map) { state.map.draw = null; state.map.drawOverlay(); }
    state.mapDraft = null;
    const bar = document.getElementById("draw-bar");
    if (bar) bar.hidden = true;
    const m = document.getElementById("map");
    if (m) m.classList.remove("drawing");
  }

  // --- Prosjektinnstillinger ------------------------------------------------------------------------
  async function viewProsjekt(el) {
    await loadProjects();
    const p = project();
    let s;
    if (state.newProject || !p) {
      const base = p ? await api.get(`/projects/${enc(p.id)}/settings`) : { options: state.me.options, can_edit: state.me.is_reviewer };
      s = { id: "", name: "", source_folder: "", project_type: "Veg", phase: "Reguleringsplan", horizontal_crs: "EPSG:25832", height_reference: "NN2000",
        accepted_formats: base.accepted_formats || ["sos", "gpkg", "tif", "las", "laz", "dxf", "ifc", "pdf"], max_data_age_years: 10, question_reminder_days: 5, package_threshold: 5,
        disciplines: base.disciplines || ["VEG", "VA", "KON", "GEO"], discipline_map: base.discipline_map || {}, project_area: { coordinates: [] }, options: base.options, can_edit: base.can_edit, isNew: true };
    } else {
      s = await api.get(`/projects/${enc(p.id)}/settings`);
    }
    const o = s.options, dis = !s.can_edit ? " disabled" : "";
    const sel = (id, name, items, value) => `<select id="${id}" name="${name}"${dis}>${items.map((it) => { const [v, l] = Array.isArray(it) ? it : [it, it]; return `<option value="${esc(v)}"${v === value ? " selected" : ""}>${esc(l)}</option>`; }).join("")}</select>`;
    const area = ((s.project_area || {}).coordinates || []).map((pt) => `${pt[0]} ${pt[1]}`).join("\n");
    el.innerHTML = `<form id="settings-form" class="stack" data-new="${s.isNew ? "1" : ""}">
      <div class="project-head"><div><div class="eyebrow">${s.isNew ? "Nytt prosjekt" : "Prosjektinnstillinger"}</div><h1>${esc(s.isNew ? "Opprett prosjekt" : s.name)}</h1>
        <p class="muted" style="max-width:70ch;margin-top:6px">Grunnleggende innstillinger for kontrollen i dette prosjektet. Endrer du koordinatsystem, høydesystem, formater, aldersgrense eller prosjektområde, kontrolleres alle registreringene på nytt.</p></div>
        <div class="row">${s.isNew ? '<button class="btn" type="button" data-action="cancel-new">Avbryt</button>' : (s.can_edit ? '<button class="btn" type="button" data-action="new-project">Nytt prosjekt</button>' : "")}</div></div>
      ${!s.can_edit ? '<p class="notice old">Bare KS-ansvarlige kan endre innstillingene. Bytt bruker øverst for å prøve.</p>' : ""}
      <div class="settings-grid">
        <section class="panel"><header><h2>Prosjekt</h2></header><div class="body form-grid">
          <div class="field" style="grid-column:1/-1"><label for="s-name">Navn</label><input type="text" id="s-name" name="name" value="${esc(s.name)}"${dis}></div>
          ${s.isNew ? `<div class="field"><label for="s-id">Prosjekt-ID</label><input type="text" id="s-id" name="id" placeholder="f.eks. e18-sandvika"${dis}><span class="hint">Kort ID uten mellomrom, for eksempel prosjektnummeret.</span></div>` : ""}
          <div class="field"><label for="s-folder">Kildemappe</label><input type="text" id="s-folder" name="source_folder" value="${esc(s.source_folder || "")}" placeholder="C:\\Users\\navn\\OneDrive - Multiconsult\\Prosjekt\\Grunnlagsdata"${dis}><span class="hint">Hele stien til mappa der grunnlagsdata legges, for eksempel en OneDrive-mappe. Hver undermappe er én leveranse.</span></div>
          <div class="field"><label for="s-type">Prosjekttype</label>${sel("s-type", "project_type", o.project_types, s.project_type)}</div>
          <div class="field"><label for="s-phase">Fase</label>${sel("s-phase", "phase", o.phases, s.phase)}</div>
        </div></section>
        <section class="panel"><header><h2>Koordinater og høyder</h2></header><div class="body form-grid">
          <div class="field" style="grid-column:1/-1"><label for="s-crs">Horisontalt koordinatsystem</label>${sel("s-crs", "horizontal_crs", o.crs.map((c) => [c.value, c.label]), s.horizontal_crs)}</div>
          <div class="field"><label for="s-h">Høydesystem</label>${sel("s-h", "height_reference", o.heights, s.height_reference)}</div>
          <div class="field" style="grid-column:1/-1"><label for="s-area">Prosjektområde</label><textarea id="s-area" name="project_area" rows="6" class="mono"${dis}>${esc(area)}</textarea><span class="hint">Ett «øst nord»-par per linje, i prosjektets koordinatsystem. Brukes til plausibilitet og dekning. <a href="#kart">Tegn eller importer området i kartet</a></span></div>
        </div></section>
        <section class="panel"><header><h2>Mottak av data</h2></header><div class="body stack" style="gap:14px">
          <div class="field"><span class="lbl">Godkjente filformater</span><div class="checks-grid">${o.formats.map((f) => `<label><input type="checkbox" name="accepted_formats" value="${f}"${(s.accepted_formats || []).includes(f) ? " checked" : ""}${dis}>.${f}</label>`).join("")}</div></div>
          <div class="form-grid">
            <div class="field"><label for="s-age">Maks alder på data (år)</label><input type="number" id="s-age" name="max_data_age_years" min="0" max="100" value="${esc(s.max_data_age_years)}"${dis}><span class="hint">0 = ingen grense</span></div>
            <div class="field"><label for="s-rem">Purring på ubesvarte spørsmål (dager)</label><input type="number" id="s-rem" name="question_reminder_days" min="0" max="60" value="${esc(s.question_reminder_days)}"${dis}><span class="hint">0 = ingen purring</span></div>
            <div class="field"><label for="s-pkg">Pakke fra antall filer</label><input type="number" id="s-pkg" name="package_threshold" min="2" value="${esc(s.package_threshold)}"${dis}><span class="hint">Så mange filer i samme mappe registreres som én rad. Alle filene kontrolleres likevel.</span></div>
          </div>
        </div></section>
        <section class="panel"><header><h2>Kvalitetskontroll</h2></header><div class="body stack" style="gap:14px">
          <div class="field"><label for="s-fag">Fag</label><input type="text" id="s-fag" name="disciplines" value="${esc((s.disciplines || []).join(", "))}"${dis}><span class="hint">Kommaseparert, for eksempel VEG, VA, KON, GEO</span></div>
          <div class="field"><span class="lbl">Standard ansvarlig fag per datatype</span><div class="map-table">${Object.entries(state.me.options.data_types).map(([k, v]) => `<label for="m-${k}">${esc(v)}</label><select id="m-${k}" name="map-${k}"${dis}>${(s.disciplines || []).map((f) => `<option${(s.discipline_map || {})[k] === f ? " selected" : ""}>${esc(f)}</option>`).join("")}</select>`).join("")}</div>
            <span class="hint">Ledningsdata og filer med «kum», «vann» eller «avløp» i navnet går til VA når VA finnes.</span></div>
        </div></section>
      </div>
      ${s.can_edit ? `<div class="savebar"><span>${s.isNew ? "Opprett prosjektet med disse innstillingene." : "Lagre endringene. Registreringene kontrolleres på nytt ved behov."}</span><span class="spacer"></span><span class="error" role="alert"></span><button class="btn primary" type="submit">${s.isNew ? "Opprett prosjekt" : "Lagre innstillinger"}</button></div>` : ""}
    </form>`;
  }

  function settingsValues(form) {
    const fd = new FormData(form);
    const v = {};
    for (const k of ["id", "name", "source_folder", "project_type", "phase", "horizontal_crs", "height_reference", "project_area", "max_data_age_years", "question_reminder_days", "package_threshold", "disciplines"]) if (fd.has(k)) v[k] = fd.get(k);
    v.accepted_formats = fd.getAll("accepted_formats");
    v.discipline_map = {};
    for (const [k, val] of fd.entries()) if (k.startsWith("map-")) v.discipline_map[k.slice(4)] = val;
    return v;
  }

  // --- Regelsett ------------------------------------------------------------------------------------
  const APPLIES_ALL = "alle";

  function appliesText(r, dt) {
    const a = r.applies_to || ["all"];
    return a.includes("all") ? APPLIES_ALL : a.map((x) => dt[x] || x).join(", ");
  }

  function ruleEditor(r, rs, isNew) {
    const builtin = rs.builtin[r.id];
    const dt = rs.data_types;
    const kinds = Object.entries(rs.check_kinds).filter(([k]) => k !== "auto" || builtin);
    const params = builtin ? Object.entries(builtin.params) : [];
    const pv = r.params || {};
    const all = (r.applies_to || ["all"]).includes("all");
    return `<form class="rule-editor" id="rule-form" data-rid="${esc(r.id)}" data-new="${isNew ? "1" : ""}">
      ${builtin ? `<p class="small muted">Innebygd sjekk: ${esc(builtin.label)}. Velg AI for å la AI vurdere regelen ut fra teksten i stedet.</p>` : '<p class="small muted">Egen regel. Med «AI» vurderer AI regelen for hver fil ut fra teksten og veiledningen, metadata og leveransenotater.</p>'}
      <div class="form-grid">
        <div class="field"><label for="r-id">Regel-ID</label><input type="text" id="r-id" name="id" value="${esc(r.id)}"${isNew ? "" : " readonly"}></div>
        <div class="field"><label for="r-check">Kontrolleres av</label><select id="r-check" name="check">${kinds.map(([k, v]) => `<option value="${k}"${(r.check || "ai") === k ? " selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
        <div class="field"><label for="r-fail">Resultat ved brudd</label><select id="r-fail" name="if_failed">${Object.entries(rs.results).map(([k, v]) => `<option value="${k}"${(r.if_failed || "deviation") === k ? " selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
      </div>
      <div class="field"><label for="r-text">Krav</label><textarea id="r-text" name="text" rows="2">${esc(r.text || "")}</textarea></div>
      <div class="field"><label for="r-src">Kilde</label><input type="text" id="r-src" name="source" value="${esc(r.source || "")}" placeholder="f.eks. Kontrakt kap. C2 pkt. 3.4"></div>
      <div class="field"><span class="lbl">Gjelder for</span><div class="applies"><label><input type="checkbox" name="applies" value="all"${all ? " checked" : ""}> Alle datatyper</label>${Object.entries(dt).map(([k, v]) => `<label><input type="checkbox" name="applies" value="${k}"${!all && (r.applies_to || []).includes(k) ? " checked" : ""}> ${esc(v)}</label>`).join("")}</div></div>
      <div class="field"><label for="r-guid">Veiledning til AI</label><textarea id="r-guid" name="guidance" rows="3" placeholder="Hva skal AI se etter, og hva regnes som manglende informasjon?">${esc(r.guidance || "")}</textarea></div>
      ${params.length ? `<div class="form-grid">${params.map(([k, def]) => `<div class="field"><label for="r-p-${k}">${esc(rs.param_labels[k] || k)}</label><input type="number" step="any" id="r-p-${k}" name="p-${k}" value="${esc(pv[k] ?? def)}"></div>`).join("")}</div>` : ""}
      <label class="check small"><input type="checkbox" name="active"${r.active !== false ? " checked" : ""}> Aktiv</label>
      <div class="row"><button class="btn primary" type="submit">Bruk endringene</button><button class="btn" type="button" data-action="rule-cancel">Avbryt</button>${!builtin && !isNew ? '<button class="btn ghost" type="button" data-action="rule-delete">Fjern regelen</button>' : ""}<span class="error" role="alert"></span></div>
    </form>`;
  }

  async function viewRegler(el) {
    await loadProjects();
    const p = project();
    const rs = await api.get(`/projects/${enc(p.id)}/rules`);
    state.rules = rs;
    if (!state.ruleEdit || state.ruleEdit.pid !== p.id || state.ruleEdit.base !== rs.version) {
      state.ruleEdit = { pid: p.id, base: rs.version, rules: clone(rs.rules), dirty: false, editing: null, changed: new Set() };
      state.drafts = null;
    }
    renderRules(el);
  }

  function renderRules(el) {
    el = el || document.getElementById("view");
    const rs = state.rules, ed = state.ruleEdit, p = project(), dt = rs.data_types, can = rs.can_edit;
    const rows = ed.rules.map((r) => {
      const editing = ed.editing === r.id;
      return `<tr class="${r.active === false ? "inactive" : ""}${ed.changed.has(r.id) ? " changed" : ""}">
        <td><input type="checkbox" data-toggle-rule="${esc(r.id)}" aria-label="Aktiv: ${esc(r.id)}"${r.active !== false ? " checked" : ""}${can ? "" : " disabled"}></td>
        <td class="mono rid">${esc(r.id)}</td><td><span class="rtext">${esc(r.text)}</span>${r.check === "ai" && r.guidance ? `<div class="small muted" style="margin-top:3px">${esc(r.guidance.slice(0, 160))}${r.guidance.length > 160 ? "…" : ""}</div>` : ""}</td>
        <td class="small muted">${esc(r.source || "")}</td><td class="small">${esc(appliesText(r, dt))}</td>
        <td>${r.check === "ai" ? '<span class="tag ai">AI</span>' : `<span class="tag">${esc(rs.check_kinds[r.check] || r.check)}</span>`}</td>
        <td>${chip(r.if_failed)}</td><td>${can ? `<button class="btn small" type="button" data-edit-rule="${esc(r.id)}">Endre</button>` : ""}</td></tr>
        ${editing ? `<tr><td colspan="8">${ruleEditor(r, rs, false)}</td></tr>` : ""}`;
    }).join("");
    const newEditor = ed.editing === "__new" ? `<div class="panel"><header><h3>Ny regel</h3></header><div class="body">${ruleEditor(ed.newRule, rs, true)}</div></div>` : "";
    const drafts = state.drafts ? `<div class="stack" style="gap:8px">${state.drafts.rules.length ? state.drafts.rules.map((r, i) => `<label class="draft"><input type="checkbox" data-draft="${i}" checked><span><b>${esc(r.text)}</b><br><span class="small muted">${esc(r.source)} · gjelder ${esc(appliesText(r, dt))} · ved brudd: ${esc(LABELS[r.if_failed])}</span><br><span class="small">${esc(r.guidance)}</span></span></label>`).join("") + `<div class="row"><button class="btn primary" type="button" data-action="add-drafts">Legg til valgte</button><span class="small muted">Foreslått av ${esc(state.drafts.model)}. Les gjennom før du lagrer.</span></div>` : '<p class="muted">Fant ingen krav med «skal», «må» eller «bør» i teksten.</p>'}</div>` : "";
    const versions = rs.versions.map((v) => `<li><span class="mono">${esc(v.version)}</span>${v.version === rs.active ? " (aktiv)" : ""} · ${esc(v.approved_by || "")} ${fmtDate(v.approved_at)}${v.note ? ` – ${esc(v.note)}` : ""}</li>`).join("");
    el.innerHTML = `<section class="stack">
      <div class="project-head"><div><div class="eyebrow">${esc(p.name)}</div><h1>Regelsett ${esc(rs.version)}</h1>
        <p class="muted" style="max-width:72ch;margin-top:6px">Kravene hver fil kontrolleres mot. Regler med «Automatisk» bruker innebygd kode; regler med «AI» vurderes av AI ut fra regelteksten, så nye krav kan skrives med vanlige ord. Lagring gir en ny versjon, og alle registreringer kontrolleres på nytt.</p></div>
        ${can ? '<div class="row"><button class="btn" type="button" data-action="rule-new">Ny regel</button></div>' : ""}</div>
      ${!can ? '<p class="notice old">Bare KS-ansvarlige kan endre regelsettet. Bytt bruker øverst for å prøve.</p>' : ""}
      ${can ? `<section class="panel"><header><h2>Foreslå regler med AI</h2><span class="muted small">fra kontrakt, BIM-krav eller håndbok</span></header><div class="body stack" style="gap:10px">
        <div class="field"><label for="draft-text">Lim inn kravtekst</label><textarea id="draft-text" rows="5" data-keep="draftText" placeholder="For eksempel: «3.2 Terrengmodell. Terrengmodell skal leveres som rutenett med maksimalt 1 m oppløsning. Punktskyer skal være klassifisert etter ASPRS-standard. Ortofoto bør ikke være eldre enn 3 år.»">${esc(state.draftText || "")}</textarea></div>
        <div class="row"><button class="btn" type="button" data-action="draft">Foreslå regler</button><span class="error" role="alert" id="draft-err"></span></div>${drafts}</div></section>` : ""}
      ${newEditor}
      <div class="panel table-wrap"><table class="rules"><thead><tr><th>Aktiv</th><th>Regel</th><th>Krav</th><th>Kilde</th><th>Gjelder for</th><th>Kontrolleres av</th><th>Ved brudd</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <section class="panel"><header><h3>Versjoner</h3></header><div class="body"><ul class="notes small">${versions}</ul></div></section>
      ${ed.dirty ? `<div class="savebar"><b>Ulagrede endringer</b><input type="text" id="rule-note" placeholder="Endringsnotat, f.eks. «La til krav fra kontrakt C2»" style="flex:1 1 260px;width:auto"><span class="error" role="alert"></span><button class="btn" type="button" data-action="rules-discard">Forkast</button><button class="btn primary" type="button" data-action="rules-save">Lagre som ny versjon</button></div>` : ""}
    </section>`;
  }

  function readRuleForm(form, rs) {
    const fd = new FormData(form);
    const applies = fd.getAll("applies");
    const r = { id: String(fd.get("id") || "").trim().toUpperCase(), text: String(fd.get("text") || "").trim(), source: String(fd.get("source") || "").trim(),
      check: fd.get("check"), if_failed: fd.get("if_failed"), guidance: String(fd.get("guidance") || "").trim(), active: fd.get("active") === "on",
      applies_to: applies.includes("all") || !applies.length ? ["all"] : applies };
    const builtin = rs.builtin[r.id];
    if (builtin && Object.keys(builtin.params).length) {
      r.params = {};
      for (const k of Object.keys(builtin.params)) r.params[k] = Number(String(fd.get("p-" + k)).replace(",", "."));
    }
    if (!/^R-[A-Z0-9][A-Z0-9-]{1,20}$/.test(r.id)) throw new Error("Regel-ID må se ut som «R-EGEN-01».");
    if (r.text.length < 5) throw new Error("Skriv kravet som en hel setning.");
    return r;
  }

  // --- Varsler ----------------------------------------------------------------------------------------
  async function viewVarsler(el) {
    await loadProjects();
    const msgs = await api.get("/notifications");
    el.innerHTML = `<section class="stack">
      <div><div class="eyebrow">Til ${esc(state.me.user.email)}</div><h1>Varsler</h1>
      <p class="muted" style="max-width:62ch;margin-top:6px">Det kontrollen har sendt deg. I appen går de ut på e-post eller Teams.</p></div>
      <div class="panel">${msgs.length ? msgs.map((m) => {
        const hash = (m.link || "").split("#")[1];
        return `<article class="msg"><div class="row"><b>${esc(m.subject)}</b><span class="spacer"></span><span class="muted small">${fmtDate(m.created_at)}</span></div><pre>${esc(m.body)}</pre>${hash ? `<div><a class="btn" href="#${esc(hash)}">Åpne i registeret</a></div>` : ""}</article>`;
      }).join("") : '<p class="empty">Ingen varsler.</p>'}</div></section>`;
  }

  const VIEWS = { register: viewRegister, prosjekt: viewProsjekt, regler: viewRegler, varsler: viewVarsler };

  // --- Eksport-forhåndsvisning (bare i demoen; appen laster ned .xlsx) ------------------------------
  function exportPreview() {
    const rows = visibleEntries().slice().sort((a, b) => String(a.received_at).localeCompare(String(b.received_at)) || a.seq - b.seq);
    const cols = ["Rekkefølge", "Dokumentnavn/Pakke", "Innhold i fil/folder", "Filtype", "Dato mottatt", "Mottatt fra", "Lenke", "Ansvarlig fag for KS", "Status kontroll", "Dato kontrollert", "Er dokument/fil klar til bruk?", "Automatisk kontroll", "Gjeldende/utgått"];
    const bg = { ikke_begynt: "var(--todo-soft)", pagar: "var(--busy-soft)", utfort: "var(--done-soft)" };
    const body = rows.map((e) => `<tr><td>${e.seq}</td><td>${esc(e.name)}</td><td>${esc(e.content)}</td><td>${esc(e.file_types)}</td><td>${fmtDate(e.received_at)}</td><td>${esc(e.received_from)}</td><td class="mono small">…/#entry-${esc(e.id)}</td><td>${esc(e.discipline || "")}</td><td style="background:${bg[e.qa_status]}">${QA[e.qa_status]}</td><td>${fmtDate(e.qa_date)}</td><td>${READY[e.ready] || ""}</td><td>${LABELS[e.check_result]}</td><td>${e.lifecycle === "utgatt" ? "Utgått" : "Gjeldende"}</td></tr>`).join("");
    const div = document.createElement("div");
    div.className = "overlay";
    div.innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-label="Forhåndsvisning av Excel-eksport"><header><b>Arket «Register»</b><span class="muted small">Grunnlagsdata_register_${esc(project().id)}.xlsx</span><span class="spacer"></span><button class="btn" type="button" data-action="close-overlay">Lukk</button></header>
      <div style="padding:14px 16px" class="stack"><p class="small muted">I appen laster knappen ned arbeidsboka med arkene Register, Filer, Kontroller, Spørsmål og Regelsett. Demoen viser registerarket slik det står nå.</p>
      <div class="table-wrap"><table class="xl"><thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div></div></div>`;
    document.body.appendChild(div);
    div.querySelector("button").focus();
  }

  // --- Hendelser ------------------------------------------------------------------------------------
  function toggleEntry(id) {
    location.hash = state.open === id ? "#register" : `#entry-${id}`;
  }

  document.addEventListener("click", async (ev) => {
    const t = ev.target;
    const sortBtn = t.closest("[data-sort]");
    if (sortBtn) {
      const k = sortBtn.dataset.sort;
      state.sort = state.sort.key === k ? { key: k, dir: -state.sort.dir } : { key: k, dir: 1 };
      await syncOpen(false);
      return;
    }
    const row = t.closest("tr.entry-row");
    if (row && !t.closest("a")) { toggleEntry(row.dataset.id); return; }
    const card = t.closest("[data-toggle]");
    if (card) { toggleEntry(card.dataset.toggle); return; }
    const lb = t.closest("[data-lang]");
    if (lb) {
      const lang = lb.dataset.lang;
      try { localStorage.setItem("bd-lang", lang); } catch (e) { /* ingen lagring */ }
      I18N.apply(lang);
      await render();
      renderChat();
      return;
    }
    const ab = t.closest("[data-area]");
    if (ab) {
      const k = ab.dataset.area;
      if (k === "rect" || k === "polygon") startDraw(k);
      else if (k === "cancel") stopDraw();
      else if (k === "finish" && state.map && state.map.draw) state.map.finishPolygon();
      else if (k === "save" && state.mapDraft) {
        const dr = state.mapDraft;
        ab.disabled = true;
        try {
          const res = await api.post(`/projects/${enc(project().id)}/area`, { points: dr.points, crs: `EPSG:${dr.epsg}`, source: dr.source || (dr.file ? `fil: ${dr.file}` : "") });
          stopDraw();
          await render();
          toast(res.message);
        } catch (e) { toast(e.message); ab.disabled = false; }
      }
      return;
    }
    const eb = t.closest("[data-edit]");
    if (eb) { state.edit = { eid: state.open, field: eb.dataset.edit }; redrawDetail(); const inp = document.querySelector(".edit-f [name=value]"); if (inp) inp.focus(); return; }
    const ob = t.closest("[data-override]");
    if (ob) { state.edit = { eid: state.open, rule: ob.dataset.override, where: ob.dataset.where }; redrawDetail(); const sel = document.querySelector(".ovr-f [name=comment]"); if (sel) sel.focus(); return; }
    const ub = t.closest("[data-unoverride]");
    if (ub) {
      try { const res = await api.post(`/entries/${enc(state.open)}/override`, { rule_id: ub.dataset.unoverride, result: null }); state.edit = null; await refreshAfterAction(res.message); }
      catch (e) { toast(e.message); }
      return;
    }
    const cq = t.closest("[data-chat-q]");
    if (cq) { sendChat(cq.textContent.trim()); return; }
    if (t.closest(".chat a.ref") && mobile.matches) { state.chatOpen = false; renderChat(); }
    const cmp = t.closest("[data-cmp]");
    if (cmp) { state.cmpFile[state.open] = cmp.dataset.cmp; document.querySelector(".detail-host").innerHTML = detailHtml(state.detail); return; }
    const rb = t.closest("[data-ready]");
    if (rb) { state.pendingReady = rb.dataset.ready; rb.parentElement.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === rb))); return; }
    const flt = t.closest("[data-filter]");
    if (flt) { const k = flt.dataset.filter; state.filters[k] = state.filters[k] === flt.dataset.value ? "" : flt.dataset.value; const s = document.getElementById(k === "qa" ? "f-qa" : "f-result"); if (s) s.value = state.filters[k]; renderSummary(); await syncOpen(false); return; }
    const toggleRule = t.closest("[data-toggle-rule]");
    if (toggleRule) { const r = state.ruleEdit.rules.find((x) => x.id === toggleRule.dataset.toggleRule); r.active = toggleRule.checked; state.ruleEdit.dirty = true; state.ruleEdit.changed.add(r.id); renderRules(); return; }
    const editRule = t.closest("[data-edit-rule]");
    if (editRule) { state.ruleEdit.editing = state.ruleEdit.editing === editRule.dataset.editRule ? null : editRule.dataset.editRule; renderRules(); return; }
    if (t.classList && t.classList.contains("overlay")) { t.remove(); return; }
    const a = t.closest("[data-action]");
    if (!a) return;
    const act = a.dataset.action;
    try {
      if (act === "close") { location.hash = "#register"; }
      else if (act === "edit-cancel") { state.edit = null; redrawDetail(); }
      else if (act === "edit-reset") {
        const form = a.closest("form");
        const res = await api.post(`/entries/${enc(state.open)}/correct`, { field: form.dataset.field, value: "", comment: form.comment.value });
        state.edit = null;
        await refreshAfterAction(res.message);
      }
      else if (act === "chat-toggle") { if (state.chatOpen) { state.chatOpen = false; renderChat(); } else openChat(); document.querySelectorAll("[data-action=chat-toggle]").forEach((b) => b.setAttribute("aria-expanded", String(state.chatOpen))); }
      else if (act === "chat-close") { state.chatOpen = false; renderChat(); document.querySelectorAll("[data-action=chat-toggle]").forEach((b) => b.setAttribute("aria-expanded", "false")); }
      else if (act === "chat-clear") { state.chat = { pid: state.chat.pid, messages: [], busy: false, draft: "" }; renderChat(); }
      else if (act === "chat-stop") { if (state.chat.ctl) state.chat.ctl.abort(); }
      else if (act === "ask-entry") {
        const e = state.detail.entry;
        openChat();
        sendChat(`Hva bør jeg vite om #${e.seq} ${e.name}? Ta med innhold, kvalitet, hva som må følges opp, og hvordan den henger sammen med andre data.`);
      }
      else if (act === "copy-link") {
        const url = location.href.split("#")[0] + "#entry-" + state.open;
        try { await navigator.clipboard.writeText(url); toast("Lenken er kopiert."); } catch (e) { toast(url); }
      } else if (act === "clear-filters") { state.filters = { q: "", fag: "", qa: "", ready: "", result: "", type: "", mine: false, showOld: true }; await render(); }
      else if (act === "export-preview") exportPreview();
      else if (act === "map-expand") setMapBig(!state.mapBig);
      else if (act === "map-open") openFromMap(a.dataset.id);
      else if (act === "close-overlay") a.closest(".overlay").remove();
      else if (act === "run") {
        a.disabled = true;
        const run = await api.post("/worker/run", {});
        const c = run.counts || {};
        await refreshAfterAction(run.message || `Kontroll ferdig: ${c.new || 0} nye filer, ${c["new version"] || 0} nye versjoner, ${c.skipped || 0} uendret.`);
      } else if (act === "dont-know") { await submitAnswer(a.closest("form"), DONT_KNOW); }
      else if (act === "decide" || act === "reopen") {
        const box = a.closest(".decision-box");
        const err = box.querySelector(".error");
        err.textContent = "";
        const ready = act === "reopen" ? "" : state.pendingReady;
        if (act === "decide" && !ready) { err.textContent = "Velg Ja, Med forbehold eller Nei."; return; }
        a.disabled = true;
        try {
          const res = await api.post(`/entries/${enc(box.dataset.eid)}/decision`, { ready, comment: document.getElementById("dec-comment").value });
          await refreshAfterAction(res.message);
        } catch (e) { err.textContent = e.message; a.disabled = false; }
      } else if (act === "new-project") { state.newProject = true; await render(); }
      else if (act === "cancel-new") { state.newProject = false; await render(); }
      else if (act === "rule-new") {
        let n = 1;
        while (state.ruleEdit.rules.find((r) => r.id === `R-EGEN-${String(n).padStart(2, "0")}`)) n++;
        state.ruleEdit.newRule = { id: `R-EGEN-${String(n).padStart(2, "0")}`, text: "", source: "", applies_to: ["all"], check: "ai", if_failed: "deviation", guidance: "", active: true };
        state.ruleEdit.editing = "__new"; renderRules();
      } else if (act === "rule-cancel") { state.ruleEdit.editing = null; renderRules(); }
      else if (act === "rule-delete") {
        const id = a.closest("form").dataset.rid;
        state.ruleEdit.rules = state.ruleEdit.rules.filter((r) => r.id !== id);
        state.ruleEdit.editing = null; state.ruleEdit.dirty = true; renderRules();
      } else if (act === "draft") {
        const err = document.getElementById("draft-err");
        err.textContent = "";
        a.disabled = true;
        try { state.drafts = await api.post(`/projects/${enc(project().id)}/rules/draft`, { text: document.getElementById("draft-text").value }); renderRules(); }
        catch (e) { err.textContent = e.message; a.disabled = false; }
      } else if (act === "add-drafts") {
        state.draftText = "";
        const taken = new Set(state.ruleEdit.rules.map((r) => r.id));
        let added = 0;
        document.querySelectorAll("[data-draft]").forEach((cb) => {
          if (!cb.checked) return;
          const r = clone(state.drafts.rules[Number(cb.dataset.draft)]);
          let n = 1;
          while (taken.has(r.id)) r.id = `R-AI-${String(n++).padStart(2, "0")}`;
          taken.add(r.id);
          state.ruleEdit.rules.push(r); state.ruleEdit.changed.add(r.id); added++;
        });
        state.drafts = null;
        if (added) state.ruleEdit.dirty = true;
        renderRules();
        toast(added ? `${plural(added, "regel", "regler")} lagt til. Husk å lagre som ny versjon.` : "Ingen regler valgt.");
      } else if (act === "rules-discard") { state.ruleEdit = null; await render(); }
      else if (act === "rules-save") {
        const bar = a.closest(".savebar");
        const err = bar.querySelector(".error");
        err.textContent = "";
        a.disabled = true;
        try {
          const res = await api.post(`/projects/${enc(project().id)}/rules`, { rules: state.ruleEdit.rules, note: document.getElementById("rule-note").value });
          state.ruleEdit = null;
          await render();
          toast(res.message);
        } catch (e) { err.textContent = e.message; a.disabled = false; }
      }
    } catch (e) { toast(e.message); }
  });

  async function submitAnswer(form, forced) {
    const err = form.querySelector(".error");
    err.textContent = "";
    let answer = forced;
    if (!answer) {
      const checked = form.querySelector("input[type=radio]:checked");
      const text = form.querySelector("input[type=text], textarea");
      answer = checked ? checked.value : text ? text.value : "";
    }
    if (!answer || !answer.trim()) { err.textContent = "Skriv et svar, eller velg «Vet ikke»."; return; }
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      const res = await api.post(`/questions/${enc(form.dataset.qid)}/answer`, { answer });
      await refreshAfterAction(res.message);
    } catch (e) { err.textContent = e.message; btn.disabled = false; }
  }

  document.addEventListener("submit", async (ev) => {
    const form = ev.target;
    const fid = form.getAttribute("id");  // not form.id: an input named "id" shadows it
    ev.preventDefault();
    const err = form.querySelector(".error");
    if (err) err.textContent = "";
    try {
      if (form.classList.contains("edit-f") && form.dataset.field) {
        const res = await api.post(`/entries/${enc(state.open)}/correct`, { field: form.dataset.field, value: form.value.value, comment: form.comment.value });
        state.edit = null;
        await refreshAfterAction(res.message);
        return;
      }
      if (form.classList.contains("ovr-f")) {
        const res = await api.post(`/entries/${enc(state.open)}/override`, { rule_id: form.dataset.rule, result: form.result.value, comment: form.comment.value });
        state.edit = null;
        await refreshAfterAction(res.message);
        return;
      }
      if (fid === "comment-form") {
        const res = await api.post(`/entries/${enc(form.dataset.eid)}/comments`, { text: form.text.value });
        await refreshAfterAction(res.message);
        return;
      }
      if (fid === "chat-form") { const v = document.getElementById("chat-input").value; await sendChat(v); return; }
      if (form.classList.contains("qform")) await submitAnswer(form);
      else if (fid === "info-form") {
        const res = await api.post(`/entries/${enc(form.dataset.eid)}/info`, Object.fromEntries(new FormData(form).entries()));
        await refreshAfterAction(res.message);
      } else if (fid === "qa-form") {
        const res = await api.post(`/entries/${enc(form.dataset.eid)}/qa`, Object.fromEntries(new FormData(form).entries()));
        await refreshAfterAction(res.message);
      } else if (fid === "settings-form") {
        const v = settingsValues(form);
        const isNew = form.dataset.new === "1";
        const res = await api.post(isNew ? "/projects" : `/projects/${enc(project().id)}/settings`, v);
        if (isNew) { state.projectId = res.id; state.newProject = false; }
        await render();
        toast(res.message);
      } else if (fid === "rule-form") {
        const r = readRuleForm(form, state.rules);
        const ed = state.ruleEdit;
        if (form.dataset.new === "1") {
          if (ed.rules.find((x) => x.id === r.id)) throw new Error(`Regel-ID ${r.id} finnes allerede.`);
          ed.rules.push(r);
        } else {
          const i = ed.rules.findIndex((x) => x.id === form.dataset.rid);
          ed.rules[i] = Object.assign({}, ed.rules[i], r);
        }
        ed.changed.add(r.id); ed.editing = null; ed.dirty = true;
        renderRules();
      }
    } catch (e) { if (err) err.textContent = e.message; else toast(e.message); }
  });

  document.addEventListener("toggle", (ev) => {
    const d = ev.target;
    if (d.dataset && d.dataset.blk) state.blocks[d.dataset.blk] = d.open;
  }, true);

  document.addEventListener("keydown", (ev) => {
    if (ev.target.id === "chat-input" && ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      sendChat(ev.target.value);
      return;
    }
    if (state.map && state.map.draw && ev.target.tagName !== "INPUT" && ev.target.tagName !== "TEXTAREA") {
      if (ev.key === "Escape") { stopDraw(); return; }
      if (ev.key === "Enter" && state.map.draw.mode === "polygon") { state.map.finishPolygon(); return; }
      if (ev.key === "Backspace" && state.map.draw.pts.length) { state.map.draw.pts.pop(); state.map.drawOverlay(); ev.preventDefault(); return; }
    }
    if (ev.key === "Escape" && state.mapBig && !document.querySelector(".overlay")) { if (state.map && !document.querySelector(".mp-pop[hidden]")) state.map.popup(null); else setMapBig(false); return; }
    if (ev.key === "Escape" && state.chatOpen && !document.querySelector(".overlay")) { state.chatOpen = false; renderChat(); }
    if (ev.key === "Escape") document.querySelectorAll(".overlay").forEach((o) => o.remove());
    const row = ev.target.closest && ev.target.closest("tr.entry-row");
    if (row && (ev.key === "Enter" || ev.key === " ") && ev.target === row) { ev.preventDefault(); toggleEntry(row.dataset.id); }
  });

  document.addEventListener("change", async (ev) => {
    const t = ev.target;
    const map = { "f-fag": "fag", "f-qa": "qa", "f-ready": "ready", "f-result": "result", "f-type": "type" };
    if (map[t.id]) { state.filters[map[t.id]] = t.value; renderSummary(); await syncOpen(false); }
    else if (t.id === "area-file" && t.files[0]) {
      try {
        const res = await importArea(t.files[0], epsgOf(state.mapData.crs));
        stopDraw();
        state.setDraft({ ...res, source: `fil: ${res.file} (${res.what})` });
      } catch (e) { toast(e.message); }
      t.value = "";
    }
    else if (t.id === "basemap" && state.map) { state.map.setBase(t.value); try { localStorage.setItem("bd-basemap", t.value); } catch (e) { /* ingen lagring */ } }
    else if (t.id === "f-mine") { state.filters.mine = t.checked; await syncOpen(false); }
    else if (t.id === "f-old") { state.filters.showOld = t.checked; await syncOpen(false); }
    else if (t.id === "project-switch") { state.projectId = t.value; state.open = null; state.chat = { pid: t.value, messages: [], busy: false, draft: "" }; state.newProject = false; state.ruleEdit = null; if (location.hash.startsWith("#entry-")) location.hash = "#register"; else await render(); }
    else if (t.id === "user-switch") {
      await api.post("/demo/login", { email: t.value });
      state.me = await api.get("/me");
      state.ruleEdit = null;
      await render();
      toast(`Du ser nå appen som ${state.me.user.name}.`);
    }
  });

  let searchTimer;
  document.addEventListener("input", (ev) => {
    if (ev.target.dataset && ev.target.dataset.keep) state[ev.target.dataset.keep] = ev.target.value;
    if (ev.target.id === "chat-input") state.chat.draft = ev.target.value;
    if (ev.target.id !== "f-q") return;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => { state.filters.q = ev.target.value.trim(); await syncOpen(false); }, 200);
  });

  window.addEventListener("hashchange", async () => {
    const r = route();
    if (r.name === "register" && state.view === "register" && document.getElementById("list")) {
      if (r.big) { setMapBig(true); return; }
      state.open = r.open || null;
      await syncOpen(true);
    } else await render();
  });
  mobile.addEventListener("change", () => { if (state.view === "register") syncOpen(false); });
  // Rad i registeret ↔ fotavtrykk i kartet
  document.addEventListener("mouseover", (ev) => {
    if (!state.map || state.mapBig || !ev.target.closest || ev.target.closest("#mapbox")) return;
    const row = ev.target.closest("#list [data-id], #list [data-toggle]");
    setMapHl(row ? row.dataset.id || row.dataset.toggle : null);
  });

  async function boot() {
    let lang = "nb";
    try { lang = localStorage.getItem("bd-lang") || "nb"; } catch (e) { /* ingen lagring */ }
    I18N.apply(lang);
    try {
      state.me = await api.get("/me");
      await loadProjects();
      await render();
    } catch (e) {
      document.getElementById("app").innerHTML = `<div class="wrap"><p class="error" style="padding-top:40px">${esc(e.message)}</p></div>`;
    }
  }

  // --- Demo: stedfortreder for API-et --------------------------------------------------------------------
  function demoApi(D) {
    const S = clone(D);
    let current = S.users[0].email;
    const user = () => S.users.find((u) => u.email === current);
    const isRev = (u) => (u.roles || []).some((r) => r === "reviewer" || r === "admin");
    const fail = (msg) => { throw new Error(msg); };
    const now = () => new Date().toISOString();
    const details = (pid) => Object.values(S.details).filter((d) => !pid || d.entry.project_id === pid);
    const NOTE = " I demoen kontrolleres ikke andre filer på nytt; i appen skjer det automatisk.";

    function recompute(d) {
      d.files.forEach((f) => { f.check_result = worst(f.checks.map((c) => c.result)); f.deviations = f.checks.filter((c) => c.result !== "ok").map((c) => c.rule_id); });
      d.entry.check_result = worst(d.files.map((f) => f.check_result));
      d.entry.deviations = [...new Set(d.files.flatMap((f) => f.deviations))].sort();
      d.entry.open_questions = d.questions.filter((q) => q.status === "open").length;
      d.questions.sort((a, b) => (a.status !== "open") - (b.status !== "open"));
    }

    function merge3(base, cur, prev) {
      for (const k of Object.keys(prev.entry)) if (!same(prev.entry[k], base.entry[k]) && same(cur.entry[k], base.entry[k])) cur.entry[k] = clone(prev.entry[k]);
      for (const pf of prev.files) {
        const bf = base.files.find((x) => x.id === pf.id), cf = cur.files.find((x) => x.id === pf.id);
        if (!bf || !cf) continue;
        for (const k of Object.keys(pf)) {
          if (k === "checks") continue;
          if (k === "effective" || k === "uploader_values") {
            cf[k] = cf[k] || {};
            for (const sk of Object.keys(pf[k] || {})) if (!same(pf[k][sk], (bf[k] || {})[sk]) && same(cf[k][sk], (bf[k] || {})[sk])) cf[k][sk] = clone(pf[k][sk]);
          } else if (!same(pf[k], bf[k]) && same(cf[k], bf[k])) cf[k] = clone(pf[k]);
        }
        for (const pc of pf.checks) {
          const bc = bf.checks.find((c) => c.rule_id === pc.rule_id);
          const i = cf.checks.findIndex((c) => c.rule_id === pc.rule_id);
          if (!bc) { if (i < 0) cf.checks.push(clone(pc)); } else if (!same(pc, bc) && i >= 0 && same(cf.checks[i], bc)) cf.checks[i] = clone(pc);
        }
        for (const bc of bf.checks) if (!pf.checks.find((c) => c.rule_id === bc.rule_id)) cf.checks = cf.checks.filter((c) => !(c.rule_id === bc.rule_id && same(c, bc)));
      }
      for (const pq of prev.questions) {
        const bq = base.questions.find((q) => q.id === pq.id);
        const i = cur.questions.findIndex((q) => q.id === pq.id);
        if (!bq) { if (i < 0) cur.questions.push(clone(pq)); } else if (!same(pq, bq) && i >= 0 && same(cur.questions[i], bq)) cur.questions[i] = clone(pq);
      }
      for (const bq of base.questions) if (bq.status === "open" && !prev.questions.find((q) => q.id === bq.id)) cur.questions = cur.questions.filter((q) => !(q.id === bq.id && q.status === "open"));
      if (!same(prev.sketch, base.sketch) && same(cur.sketch, base.sketch)) cur.sketch = clone(prev.sketch);
    }

    function parseDate(s) {
      const months = { jan: 1, januar: 1, feb: 2, februar: 2, mar: 3, mars: 3, apr: 4, april: 4, mai: 5, jun: 6, juni: 6, jul: 7, juli: 7, aug: 8, august: 8, sep: 9, september: 9, okt: 10, oktober: 10, nov: 11, november: 11, des: 12, desember: 12 };
      let m;
      if ((m = s.match(/(\d{1,2})\.(\d{1,2})\.(\d{4})/))) return `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
      if ((m = s.match(/(\d{4})-(\d{2})(-\d{2})?/))) return m[0];
      if ((m = s.match(/([A-Za-zæøå]{3,9})\.?\s+(\d{4})/)) && months[m[1].toLowerCase()]) return `${m[2]}-${String(months[m[1].toLowerCase()]).padStart(2, "0")}`;
      if ((m = s.match(/\b(19\d{2}|20\d{2})\b/))) return m[1];
      return null;
    }

    function answer(qid, text) {
      const d = details().find((x) => x.questions.some((q) => q.id === qid)) || fail("Fant ikke spørsmålet.");
      const q = d.questions.find((x) => x.id === qid);
      if (q.status !== "open") fail("Spørsmålet er allerede besvart.");
      const u = user();
      if (((d.entry.uploader || {}).email || "") !== u.email && !isRev(u)) fail("Bare den som leverte dataene (eller en KS-ansvarlig) kan svare på dette spørsmålet.");
      const pv = S.previews[qid];
      let preview = pv && pv.choices ? pv.choices[text] : null;
      if (!preview && pv && pv.text) {
        let value = text.trim();
        if (q.field === "data_date") value = parseDate(text) || fail("Fant ikke en dato i svaret – prøv «2024-05» eller «12.05.2024».");
        preview = JSON.parse(JSON.stringify(pv.text).split(pv.token).join(JSON.stringify(value).slice(1, -1)));
      }
      if (!preview) fail("Svaret kunne ikke leses. Velg et av alternativene.");
      merge3(D.details[d.entry.id], d, preview);
      const cq = d.questions.find((x) => x.id === qid);
      if (cq) Object.assign(cq, { status: "answered", answer: text, answered_at: now(), answered_by: u.email });
      if (d.entry.qa_status === "ikke_begynt") d.entry.qa_status = "pagar";
      recompute(d);
      return { entry: d.entry, message: `#${d.entry.seq} ${d.entry.name} kontrollert på nytt: ${LABELS[d.entry.check_result]}.` };
    }

    function supersede(d) {
      const e = d.entry;
      const target = (e.ready === "ja" || e.ready === "med_forbehold") && e.lifecycle === "gjeldende" && e.replaces ? e.replaces.id : null;
      details().forEach((x) => {
        if (x.entry.superseded_by && x.entry.superseded_by.id === e.id && x.entry.id !== target) Object.assign(x.entry, { lifecycle: "gjeldende", superseded_by: null, superseded_at: null });
      });
      const t = target && S.details[target];
      if (t && t.entry.lifecycle === "gjeldende") Object.assign(t.entry, { lifecycle: "utgatt", superseded_by: { id: e.id, seq: e.seq, name: e.name }, superseded_at: now() });
    }

    function rowsFor(pid) { return details(pid).map((d) => d.entry).sort((a, b) => String(a.received_at).localeCompare(String(b.received_at)) || a.seq - b.seq); }

    function draftRules(text, existing) {
      const known = new Set(existing.map((r) => r.text.toLowerCase().replace(/[^a-z0-9æøå]+/g, " ").trim()));
      const words = /\b(skal|må|bør|shall|must|should)\b/i;
      const types = [["point_cloud", /punktsk|laser|lidar/i], ["terrain", /terreng|dtm|høydemodell/i], ["orthophoto", /ortofoto|flyfoto/i], ["fkb", /\bfkb/i], ["utility", /ledning|va-|kabel/i], ["ground_investigation", /grunnunders|geotekn|boring/i], ["model", /\bifc\b|eksisterende modell|bim-modell|fagmodell/i], ["drawing", /tegning|innmål|dwg|dxf/i]];
      let heading = "";
      const out = [];
      text.split(/(?<=[.!?])\s+|\n+/).forEach((raw) => {
        const s = raw.trim().replace(/^[-•\s]+/, "");
        if (!s) return;
        if (/^(\d+(\.\d+)*|[A-ZÆØÅ][A-ZÆØÅ ]{3,})\s/.test(s) && !words.test(s)) { heading = s.slice(0, 80); return; }
        if (!words.test(s) || s.length < 15) return;
        if (known.has(s.toLowerCase().replace(/[^a-z0-9æøå]+/g, " ").trim())) return;
        const applies = types.filter(([, re]) => re.test(s)).map(([k]) => k);
        const t = s.replace(/\.$/, "");
        out.push({ id: `R-AI-${String(out.length + 1).padStart(2, "0")}`, text: t[0].toUpperCase() + t.slice(1), source: `Innlimt tekst${heading ? " – " + heading : ""}`,
          applies_to: applies.length ? applies : ["all"], check: "ai", if_failed: /\b(bør|should)\b/i.test(s) ? "warning" : "deviation",
          guidance: "Vurder om metadata, leveransenotater eller svar fra opplaster viser at kravet er oppfylt. Står det ingenting om det, er resultatet missing_info.", active: true });
      });
      return out.slice(0, 15);
    }

    // --- Demo: korrigering, overstyring og kommentarer -------------------------------------------------
    const FIELD_RULE = { horizontal_epsg: ["R-CRS-01", "R-CRS-03"], height_reference: ["R-CRS-02"], data_date: ["R-DATE-01"], source: ["R-SRC-01"], quality: ["R-QUA-01"] };
    function parseValue(field, raw) {
      if (field === "horizontal_epsg") {
        if (/^lokal/i.test(raw)) return "LOCAL";
        const m = raw.match(/\b(\d{4,5})\b/) || fail("Fant ikke et koordinatsystem – skriv for eksempel «EPSG:25832».");
        return Number(m[1]);
      }
      if (field === "height_reference") return /ingen/i.test(raw) ? "NONE" : /ellips/i.test(raw) ? "Ellipsoidisk" : raw.replace(/\s/g, "").toUpperCase();
      if (field === "data_date") return parseDate(raw) || fail("Fant ikke en dato – skriv for eksempel «2024-05» eller «12.05.2024».");
      return raw;
    }
    function simpleCheck(d, rule, field, value) {
      const st = S.settings[d.entry.project_id] || {};
      const pe = Number(String(st.horizontal_crs || "").replace(/\D/g, ""));
      if (rule === "R-CRS-01") return value === pe ? ["ok", `Korrigert manuelt til EPSG:${value}, som er prosjektets.`] : ["deviation", `Korrigert manuelt til EPSG:${value}, men prosjektet bruker EPSG:${pe}.`];
      if (rule === "R-CRS-03") {
        const fits = d.files.every((f) => { const p = f.plausibility || {}; return (p.candidates || []).some((c) => c.epsg === value) || (p.declared_fits && f.crs.epsg === value); });
        return fits ? ["ok", `Koordinatene passer med EPSG:${value}.`] : ["warning", `Koordinatene er ikke kontrollert mot EPSG:${value} i demoen.`];
      }
      if (rule === "R-CRS-02") return value === "NONE" ? ["ok", "Ingen høyder i fila (2D)."] : value === st.height_reference ? ["ok", `${value}, som er prosjektets.`] : ["deviation", `${value}, men prosjektet bruker ${st.height_reference}.`];
      if (rule === "R-DATE-01") { const y = parseInt(value, 10), lim = Number(st.max_data_age_years || 0); return !lim || new Date().getFullYear() - y <= lim ? ["ok", `${value} – innenfor aldersgrensen.`] : ["warning", `${value} – eldre enn ${lim} år.`]; }
      if (rule === "R-SRC-01") return ["ok", `Kilde: ${value} (korrigert manuelt).`];
      if (rule === "R-QUA-01") return ["ok", `Oppgitt manuelt: «${value}». KS bør vurdere om det holder.`];
      return null;
    }
    function correct(id, body) {
      const d = S.details[id] || fail("Fant ikke registreringen.");
      const u = user();
      if ((d.entry.uploader || {}).email !== u.email && !isRev(u)) fail("Bare den som leverte dataene (eller en KS-ansvarlig) kan korrigere verdiene.");
      const field = body.field, raw = String(body.value || "").trim(), comment = String(body.comment || "").trim();
      const stamp = { by: u.email, by_name: u.name, at: now(), comment };
      const label = { data_type: "Datatype", horizontal_epsg: "Koordinatsystem", height_reference: "Høydesystem", data_date: "Dato", source: "Kilde", quality: "Kvalitet", summary: "Beskrivelse av innholdet", content: "Innhold i fil/mappe" }[field] || fail("Dette feltet kan ikke korrigeres.");
      const e = d.entry;
      const log = (ev) => { e.history = (e.history || []).concat([{ at: now(), event: ev + (comment ? ` – «${comment}»` : ""), by: u.name }]); };
      const done = (msg) => { recompute(d); e.corrections = (e.corrected_fields || []).length + Object.keys(e.check_overrides || {}).length + Object.keys(e.text_overrides || {}).length; return { entry: e, message: msg }; };
      if (field === "summary" || field === "content") {
        e.text_overrides = e.text_overrides || {};
        if (raw) {
          e.text_overrides[field] = { value: raw, ...stamp };
          if (field === "summary") { d.profile.summary_original = d.profile.summary_original || d.profile.summary; d.profile.summary = raw; d.profile.summary_corrected = e.text_overrides.summary; }
          else e.content = raw;
        } else {
          delete e.text_overrides[field];
          if (field === "summary" && d.profile.summary_original) { d.profile.summary = d.profile.summary_original; delete d.profile.summary_corrected; delete d.profile.summary_original; }
          if (field === "content") e.content = e.content_auto;
        }
        log(`${label} ${raw ? "korrigert" : "tilbakestilt"}`);
        return done(`${label} er ${raw ? "korrigert" : "tilbakestilt"}.`);
      }
      if (field === "data_type") {
        if (raw) { const v = S.options.data_types[raw] ? raw : fail("Velg en datatype fra listen."); e.data_type = v; e.data_type_label = S.options.data_types[v]; d.files.forEach((f) => { f.uploader_values = { ...(f.uploader_values || {}), data_type: { value: v, raw: v, via: "korreksjon", ...stamp } }; f.data_type_label = e.data_type_label; }); }
        else { const o = D.details[id].entry; e.data_type = o.data_type; e.data_type_label = o.data_type_label; d.files.forEach((f) => { if (f.uploader_values) delete f.uploader_values.data_type; }); }
        log(`${label} ${raw ? "korrigert" : "tilbakestilt"}`);
        return done(`${label} ${raw ? "korrigert" : "tilbakestilt"}. I demoen kjøres ikke kontrollene på nytt for ny datatype.`);
      }
      const set = new Set(e.corrected_fields || []);
      if (!raw) {
        const base = D.details[id];
        d.files.forEach((f, i) => { const bf = base.files.find((x) => x.id === f.id) || base.files[i]; f.effective[field] = clone(bf.effective[field]); (FIELD_RULE[field] || []).forEach((r) => { const k = f.checks.findIndex((c) => c.rule_id === r); const bc = bf.checks.find((c) => c.rule_id === r); if (k >= 0 && bc && !f.checks[k].override) f.checks[k] = clone(bc); }); });
        set.delete(field);
        e.corrected_fields = [...set];
        log(`${label} tilbakestilt`);
        return done(`${label} tilbakestilt.`);
      }
      const value = parseValue(field, raw);
      const q = d.questions.find((x) => x.status === "open" && x.field === field);
      let exact = false;
      if (q) {
        const choice = (q.choices || []).find((c) => c.toLowerCase() === raw.toLowerCase() || (field === "horizontal_epsg" && c.startsWith(`EPSG:${value} `)));
        try { answer(q.id, choice || raw); exact = true; } catch (err) { /* ingen forhåndsberegning: forenklet kontroll under */ }
        const cq = d.questions.find((x) => x.id === q.id);
        if (cq) Object.assign(cq, { status: "answered", answer: `${raw} (korrigert)`, answered_at: now() });
      }
      d.files.forEach((f) => {
        const prev = f.effective[field] || {};
        const was = prev.from === "manual" ? prev.was : (prev.value != null ? prev.value : prev.file_value);
        f.effective[field] = { value: value === "LOCAL" ? null : value, from: value === "LOCAL" ? "uploader_local" : "manual", corrected: { ...stamp, raw }, was: was == null ? null : was, ...(field === "horizontal_epsg" && typeof value === "number" ? { name: (S.options.crs.find((c) => c.value === `EPSG:${value}`) || {}).label || `EPSG:${value}` } : {}) };
        if (field === "horizontal_epsg" && typeof value === "number") f.crs = { ...f.crs, epsg: value };
        if (!exact) (FIELD_RULE[field] || []).forEach((r) => {
          const c = f.checks.find((x) => x.rule_id === r);
          const res = c && !c.override && simpleCheck(d, r, field, value);
          if (res) Object.assign(c, { result: res[0], evidence: res[1], checked_by: "code" });
        });
      });
      set.add(field);
      e.corrected_fields = [...set];
      if (e.qa_status === "ikke_begynt") e.qa_status = "pagar";
      log(`${label} korrigert til «${raw}»`);
      const r = done("");
      return { ...r, message: `${label} korrigert. #${e.seq} ${e.name} kontrollert på nytt: ${LABELS[e.check_result]}.${exact ? "" : " (Forenklet kontroll i demoen.)"}` };
    }
    function override(id, body) {
      const u = user();
      isRev(u) || fail("Bare KS-ansvarlige kan overstyre kontrollresultater.");
      const d = S.details[id] || fail("Fant ikke registreringen.");
      const e = d.entry, rule = body.rule_id, comment = String(body.comment || "").trim();
      e.check_overrides = e.check_overrides || {};
      if (body.result) {
        LABELS[body.result] || fail("Ugyldig resultat.");
        comment || fail("Skriv hvorfor resultatet overstyres, slik at det er dokumentert.");
        e.check_overrides[rule] = { result: body.result, by: u.email, by_name: u.name, at: now(), comment };
        d.files.forEach((f) => f.checks.forEach((c) => { if (c.rule_id !== rule) return; const orig = c.override ? c.override.original : c.result; c.override = { result: body.result, original: orig, comment, by: u.name, at: now() }; c.result = body.result; c.flagged_for_review = false; }));
      } else {
        delete e.check_overrides[rule];
        d.files.forEach((f) => f.checks.forEach((c) => { if (c.rule_id === rule && c.override) { c.result = c.override.original; delete c.override; } }));
      }
      e.history = (e.history || []).concat([{ at: now(), event: body.result ? `${rule} overstyrt til «${LABELS[body.result]}»${comment ? ` – «${comment}»` : ""}` : `Overstyring av ${rule} fjernet`, by: u.name }]);
      recompute(d);
      e.corrections = (e.corrected_fields || []).length + Object.keys(e.check_overrides).length + Object.keys(e.text_overrides || {}).length;
      return { entry: e, message: `${rule} ${body.result ? "overstyrt" : "tilbakestilt"}. #${e.seq} ${e.name}: ${LABELS[e.check_result]}.` };
    }
    function addComment(id, body) {
      const d = S.details[id] || fail("Fant ikke registreringen.");
      const text = String(body.text || "").trim() || fail("Skriv en kommentar.");
      const u = user();
      const c = { id: "k" + Date.now(), text, by: u.email, by_name: u.name, at: now() };
      d.entry.comment_list = (d.entry.comment_list || []).concat([c]);
      d.entry.comments = d.entry.comment_list.length;
      const up = d.entry.uploader || {};
      if (up.email && up.email !== u.email) S.notifications.push({ id: "n" + Date.now(), to: up.email, subject: `Ny kommentar på #${d.entry.seq} ${d.entry.name}`, body: `${u.name} skrev:\n\n${text}`, link: `#entry-${id}`, kind: "comment", created_at: now() });
      return { comment: c, message: "Kommentaren er lagret." };
    }

    // --- Demo: kartdata regnet ut i nettleseren fra registreringene -------------------------------------------
    function ringOf(ext, epsg) {
      const c = [[ext.minx, ext.miny], [ext.maxx, ext.miny], [ext.maxx, ext.maxy], [ext.minx, ext.maxy]], out = [];
      for (let k = 0; k < 4; k++) { const a = c[k], b = c[(k + 1) % 4]; for (let j = 0; j < 4; j++) { const ll = GEO.toLonLat(epsg, a[0] + (b[0] - a[0]) * j / 4, a[1] + (b[1] - a[1]) * j / 4); if (!ll) return null; out.push(ll); } }
      return out;
    }
    // Samme som service._geom: fotavtrykket i filas koordinatsystem regnet om til lon/lat
    function geomLonLat(fp, ext, epsg) {
      if (!fp && ext) fp = { kind: "box", source: "utstrekningen i fila", rings: [[[ext.minx, ext.miny], [ext.maxx, ext.miny], [ext.maxx, ext.maxy], [ext.minx, ext.maxy]]] };
      if (!fp) return null;
      const conv = (arr) => (arr || []).map((q) => GEO.toLonLat(epsg, q[0], q[1])).filter(Boolean);
      const g = { kind: fp.kind, source: fp.source, polygons: [], lines: [], points: [] };
      if (fp.kind === "outline" || fp.kind === "box") g.polygons = (fp.rings || []).map(conv).filter((r) => r.length >= 3);
      else if (fp.kind === "points") g.points = conv(fp.points);
      else if (fp.kind === "features") {
        g.polygons = (fp.polygons || []).map(conv).filter((r) => r.length >= 3);
        g.lines = (fp.lines || []).map(conv).filter((l) => l.length >= 2);
        g.points = conv(fp.points);
      }
      return g.polygons.length || g.lines.length || g.points.length ? g : null;
    }
    function mapData(pid) {
      const st = S.settings[pid] || {}, area = st.project_area || {};
      const epsg = epsgOf(area.crs || st.horizontal_crs);
      const lonlat = (area.coordinates || []).map((q) => GEO.toLonLat(epsg, q[0], q[1])).filter(Boolean);
      const items = [], unplaced = [];
      projectDetails(pid).forEach((d) => {
        const fps = []; let why = null;
        d.files.forEach((f) => {
          const ext = (f.metadata || {}).extent, fe = ((f.effective || {}).horizontal_epsg || {}).value;
          if (!ext) { why = why || "ingen koordinater i fila"; return; }
          const pl = f.plausibility || {}, cands = (pl.candidates || []).map((c) => c.epsg).filter(Boolean);
          let use = typeof fe === "number" ? fe : null, guess = false;
          if ((use == null || (pl.declared_fits === false && ((f.effective || {}).horizontal_epsg || {}).from !== "manual")) && cands.length) { use = cands[0]; guess = true; }
          if (use == null) { why = why || "koordinatsystem ukjent"; return; }
          const ring = ringOf(ext, use);
          if (ring) fps.push({ file: f.file_name, ring, geom: geomLonLat((f.metadata || {}).footprint, ext, use), result: f.check_result, guess, crs_name: ((S.options.crs.find((c) => c.value === `EPSG:${use}`) || {}).label || `EPSG:${use}`).replace(/ \(EPSG:\d+\)/, "") });
        });
        const row = { ...d.entry, summary: (d.profile || {}).summary };
        if (fps.length) items.push({ ...row, footprints: fps }); else unplaced.push({ ...row, reason: why || "ingen koordinater" });
      });
      return { crs: `EPSG:${epsg}`, crs_name: ((S.options.crs.find((c) => c.value === `EPSG:${epsg}`) || {}).label || "").replace(/ \(EPSG:\d+\)/, ""),
        area: { coordinates: area.coordinates || [], lonlat, source: area.source, updated_by: area.updated_by, updated_at: area.updated_at }, items, unplaced, can_edit: isRev(user()) };
    }
    function saveArea(pid, body) {
      isRev(user()) || fail("Bare KS-ansvarlige kan endre prosjektområdet.");
      const st = S.settings[pid];
      const target = epsgOf(st.horizontal_crs), src = epsgOf(body.crs || "EPSG:4326");
      let pts = (body.points || []).map((q) => [Number(q[0]), Number(q[1])]);
      if (pts.length > 2 && pts[0][0] === pts[pts.length - 1][0] && pts[0][1] === pts[pts.length - 1][1]) pts = pts.slice(0, -1);
      if (pts.length < 3) fail("Prosjektområdet trenger minst tre punkter.");
      const out = pts.map((q) => GEO.transform(q[0], q[1], src, target) || fail("Koordinatene kunne ikke regnes om.")).map((q) => [Math.round(q[0] * 100) / 100, Math.round(q[1] * 100) / 100]);
      if (GEO.area(out) < 100) fail("Området er for lite – sjekk at koordinatene er i riktig koordinatsystem.");
      st.project_area = { crs: `EPSG:${target}`, coordinates: out, source: body.source || "tegnet i kartet", updated_by: user().name, updated_at: now() };
      details(pid).forEach((d) => { if (d.sketch) d.sketch.area = out; });
      return { ...mapData(pid), message: `Prosjektområdet er lagret (${out.length} punkter). I demoen kontrolleres ikke dekningen på nytt; i appen skjer det automatisk.` };
    }

    const routes = {
      "GET /me": () => ({ user: user(), is_reviewer: isRev(user()), demo_users: S.users, banner: S.banner, options: S.options }),
      "GET /projects": () => S.projects.map((p) => {
        const es = rowsFor(p.id);
        const qa = { ikke_begynt: 0, pagar: 0, utfort: 0 };
        es.forEach((e) => { qa[e.qa_status] = (qa[e.qa_status] || 0) + 1; });
        return Object.assign({}, p, { entries: es.length, files: es.reduce((s, e) => s + e.file_count, 0), open_questions: es.reduce((s, e) => s + e.open_questions, 0), qa_status: qa, superseded: es.filter((e) => e.lifecycle === "utgatt").length });
      }),
      "POST /projects": (id, q, body) => {
        isRev(user()) || fail("Bare KS-ansvarlige kan opprette prosjekter.");
        const name = (body.name || "").trim() || fail("Prosjektet må ha et navn.");
        const pid = String(body.id || name).toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-|-$/g, "");
        if (!pid || S.projects.find((p) => p.id === pid)) fail("Prosjekt-ID mangler eller finnes allerede.");
        (body.accepted_formats || []).length || fail("Velg minst ett godkjent filformat.");
        const area = String(body.project_area || "").split("\n").map((l) => l.match(/-?\d+(?:[.,]\d+)?/g)).filter((m) => m && m.length >= 2).map((m) => [Number(m[0].replace(",", ".")), Number(m[1].replace(",", "."))]);
        const disc = String(body.disciplines || "").split(",").map((x) => x.trim().toUpperCase()).filter(Boolean);
        S.projects.push({ id: pid, name, project_type: body.project_type, phase: body.phase, horizontal_crs: body.horizontal_crs, height_reference: body.height_reference, active_ruleset: "v1.0" });
        S.settings[pid] = Object.assign(clone(Object.values(S.settings)[0]), { id: pid, name, source_folder: body.source_folder || "", project_type: body.project_type, phase: body.phase, horizontal_crs: body.horizontal_crs, height_reference: body.height_reference, accepted_formats: body.accepted_formats, max_data_age_years: Number(body.max_data_age_years), question_reminder_days: Number(body.question_reminder_days), package_threshold: Number(body.package_threshold), disciplines: disc, discipline_map: body.discipline_map, project_area: { coordinates: area } });
        S.rules[pid] = Object.assign(clone(Object.values(S.rules)[0]), { versions: [Object.assign(clone(Object.values(S.rules)[0].versions.slice(-1)[0]), { note: "Standardregelsett" })] });
        return Object.assign({}, S.settings[pid], { message: `Prosjektet «${name}» er opprettet. I appen leses kildemappa med en gang; i demoen kommer det ikke nye filer.` });
      },
      "GET /projects/:id/entries": (id) => rowsFor(id),
      "GET /projects/:id/settings": (id) => Object.assign({}, S.settings[id], { can_edit: isRev(user()) }),
      "POST /projects/:id/settings": (id, q, body) => {
        isRev(user()) || fail("Bare KS-ansvarlige kan endre prosjektinnstillinger.");
        (body.name || "").trim() || fail("Prosjektet må ha et navn.");
        (body.accepted_formats || []).length || fail("Velg minst ett godkjent filformat.");
        const disc = String(body.disciplines || "").split(",").map((x) => x.trim().toUpperCase()).filter(Boolean);
        disc.length || fail("Skriv minst ett fag.");
        const area = String(body.project_area || "").split("\n").map((l) => l.match(/-?\d+(?:[.,]\d+)?/g)).filter((m) => m && m.length >= 2).map((m) => [Number(m[0].replace(",", ".")), Number(m[1].replace(",", "."))]);
        if (area.length && area.length < 3) fail("Prosjektområdet trenger minst tre punkter.");
        Object.assign(S.settings[id], { name: body.name.trim(), source_folder: body.source_folder, project_type: body.project_type, phase: body.phase, horizontal_crs: body.horizontal_crs, height_reference: body.height_reference,
          accepted_formats: body.accepted_formats, max_data_age_years: Number(body.max_data_age_years), question_reminder_days: Number(body.question_reminder_days), package_threshold: Number(body.package_threshold), disciplines: disc, discipline_map: body.discipline_map, project_area: { coordinates: area } });
        Object.assign(S.projects.find((p) => p.id === id), { name: body.name.trim(), project_type: body.project_type, phase: body.phase, horizontal_crs: body.horizontal_crs, height_reference: body.height_reference });
        details(id).forEach((d) => { d.options.disciplines = disc; });
        return Object.assign({}, S.settings[id], { message: "Innstillingene er lagret. I demoen kontrolleres ikke filene på nytt; i appen skjer det automatisk når koordinatsystem, høydesystem, formater, aldersgrense eller prosjektområde endres." });
      },
      "GET /projects/:id/rules": (id) => Object.assign({}, S.rules[id], { can_edit: isRev(user()) }),
      "POST /projects/:id/rules": (id, q, body) => {
        isRev(user()) || fail("Bare KS-ansvarlige kan endre regelsettet.");
        const rules = body.rules || [];
        rules.length || fail("Regelsettet må ha minst én regel.");
        const ids = new Set();
        rules.forEach((r) => { if (ids.has(r.id)) fail(`Regel-ID ${r.id} er brukt to ganger.`); ids.add(r.id); if (r.check === "auto" && !S.rules[id].builtin[r.id]) fail(`${r.id}: bare innebygde regler kan kontrolleres automatisk.`); });
        const rs = S.rules[id];
        const nums = rs.versions.map((v) => v.version.match(/\d+/g).map(Number)).sort((a, b) => b[0] - a[0] || b[1] - a[1])[0];
        const version = `v${nums[0]}.${nums[1] + 1}`;
        Object.assign(rs, { version, active: version, rules: clone(rules), approved_by: user().name, approved_at: now(), note: (body.note || "").trim() });
        rs.versions.unshift({ version, approved_by: user().name, approved_at: now(), note: (body.note || "").trim(), rules: rules.length });
        S.projects.find((p) => p.id === id).active_ruleset = version;
        return Object.assign({}, rs, { message: `Regelsett ${version} er lagret og tatt i bruk.${NOTE}` });
      },
      "POST /projects/:id/rules/draft": (id, q, body) => {
        isRev(user()) || fail("Bare KS-ansvarlige kan foreslå regler.");
        (body.text || "").trim().length >= 20 || fail("Lim inn litt mer tekst – minst én hel setning med et krav.");
        return { rules: draftRules(body.text, S.rules[id].rules), model: "offline-demo (regelbasert erstatning, ikke en AI-modell)" };
      },
      "GET /entries/:id": (id) => {
        const d = S.details[id] || fail("Fant ikke registreringen.");
        const u = user(), own = (d.entry.uploader || {}).email === u.email;
        return Object.assign(clone(d), { permissions: { can_review: isRev(u), can_answer: own || isRev(u), can_edit_info: own || isRev(u), can_correct: own || isRev(u), can_override: isRev(u), can_comment: true } });
      },
      "POST /questions/:id/answer": (id, q, body) => answer(id, body.answer || ""),
      "POST /entries/:id/info": (id, q, body) => {
        const d = S.details[id] || fail("Fant ikke registreringen.");
        const u = user();
        if ((d.entry.uploader || {}).email !== u.email && !isRev(u)) fail("Bare den som leverte dataene (eller en KS-ansvarlig) kan endre opplysningene.");
        let used = 0, stored = 0;
        for (const f of ["horizontal_epsg", "height_reference", "data_date", "source", "quality", "comment"]) {
          const v = (body[f] || "").trim();
          if (!v) continue;
          const open = d.questions.find((x) => x.status === "open" && x.field === (f === "comment" ? "comments" : f));
          if (open) {
            const code = f === "horizontal_epsg" && (v.match(/\b\d{4,5}\b/) || [])[0];
            const choice = (open.choices || []).find((c) => c.toLowerCase() === v.toLowerCase() || (code && c.startsWith(`EPSG:${code} `)));
            answer(open.id, choice || v); used++;
          } else if (f === "comment") { d.entry.uploader_comment = v; stored++; }
          else { d.files.forEach((x) => { x.uploader_values[f] = { raw: v, via: "skjema" }; }); stored++; }
        }
        if (body.data_type) { d.entry.data_type = body.data_type; d.entry.data_type_label = S.options.data_types[body.data_type]; stored++; }
        if (!used && !stored) fail("Fyll ut minst ett felt.");
        recompute(d);
        return { entry: d.entry, message: used ? `Lagret. #${d.entry.seq} ${d.entry.name} kontrollert på nytt: ${LABELS[d.entry.check_result]}.` : "Lagret. I demoen kontrolleres dataene bare på nytt når et åpent spørsmål gjelder samme felt." };
      },
      "GET /projects/:id/map": (id) => mapData(id),
      "POST /projects/:id/area": (id, q, body) => saveArea(id, body),
      "POST /entries/:id/correct": (id, q, body) => correct(id, body),
      "POST /entries/:id/override": (id, q, body) => override(id, body),
      "POST /entries/:id/comments": (id, q, body) => addComment(id, body),
      "POST /entries/:id/qa": (id, q, body) => {
        isRev(user()) || fail("Bare KS-ansvarlige kan endre KS-feltene.");
        const d = S.details[id] || fail("Fant ikke registreringen.");
        const e = d.entry;
        if (body.discipline) e.discipline = body.discipline;
        if (body.qa_status) { e.qa_status = body.qa_status; if (body.qa_status === "utfort" && !e.qa_date) e.qa_date = now(); if (body.qa_status !== "utfort" && !e.ready) e.qa_date = null; }
        if ("qa_note" in body) e.qa_note = String(body.qa_note || "").trim();
        if ("received_from" in body) { e.received_from_override = String(body.received_from || "").trim() || null; e.received_from = e.received_from_override || (e.uploader || {}).name || ""; }
        if (body.replaces) {
          if (body.replaces === "auto") { e.replaces_mode = "auto"; e.replaces = e.replaces_candidate ? Object.assign({ mode: "auto" }, e.replaces_candidate) : null; }
          else if (body.replaces === "none") { e.replaces_mode = "none"; e.replaces = null; }
          else { const t = S.details[body.replaces] || fail("Velg en tidligere registrering."); e.replaces_mode = "manual"; e.replaces = { id: t.entry.id, seq: t.entry.seq, name: t.entry.name, mode: "manual" }; }
        }
        supersede(d);
        return { entry: e, message: `#${e.seq} ${e.name}: KS-feltene er lagret.` };
      },
      "POST /entries/:id/decision": (id, q, body) => {
        const u = user();
        isRev(u) || fail("Bare KS-ansvarlige kan avgjøre om data er klare til bruk.");
        const d = S.details[id] || fail("Fant ikke registreringen.");
        const e = d.entry;
        const ready = body.ready || null;
        const comment = (body.comment || "").trim();
        if (ready === "nei" && !comment) fail("Skriv hvorfor dataene ikke kan brukes, slik at opplasteren vet hva som må rettes.");
        if (ready === "med_forbehold" && !comment) fail("Beskriv forbeholdet, slik at de som bruker dataene ser det.");
        if (!ready) {
          e.history = (e.history || []).concat([{ at: now(), event: "Gjenåpnet", by: u.name, ready: e.ready }]);
          Object.assign(e, { ready: null, qa_status: "pagar", qa_date: null, review: null });
        } else Object.assign(e, { ready, qa_status: "utfort", qa_date: now(), review: { by: u.name, email: u.email, at: now(), decision: ready, comment } });
        supersede(d);
        if (ready === "nei") S.notifications.push({ id: "n" + Date.now(), to: (e.uploader || {}).email, subject: `#${e.seq} ${e.name}: ikke klar til bruk`, body: `${u.name} har vurdert #${e.seq} ${e.name} som ikke klar til bruk:\n\n${comment}\n\nLegg en rettet versjon i kildemappa (samme navn erstatter den gamle); den kontrolleres og registreres på nytt.`, link: `#entry-${id}`, kind: "review", created_at: now() });
        const surface = e.data_type === "terrain" || e.data_type === "point_cloud";
        return { entry: e, message: `#${e.seq} ${e.name}: ${ready ? READY[ready].toLowerCase() : "gjenåpnet"}.${surface ? NOTE : ""}` };
      },
      "GET /notifications": () => S.notifications.filter((n) => n.to === current).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))),
      "POST /worker/run": () => (isRev(user()) ? { counts: { new: 0, "new version": 0, skipped: Object.values(S.details).reduce((s, d) => s + d.files.length, 0) }, message: "Ingen nye filer i kildemappa. (I demoen kommer det ikke nye filer.)" } : fail("Bare KS-ansvarlige kan starte en kontroll.")),
      "POST /demo/login": (id, q, body) => { current = body.email; return { ok: true }; },
    };

    // --- Demo-chat: Claude via sample-kapabiliteten, med verktøy som leser demoens data ---------------------
    const CHAT_RULES = `Du er en assistent for grunnlagsdata i et samferdselsprosjekt (veg, VA, konstruksjon). Brukeren er
prosjekterende eller KS-ansvarlig. Svar på norsk (bokmål), kort og konkret.

Grunnlagsdata kan være tegninger (PDF/DXF), dokumenter og rapporter, BIM-modeller (IFC), kartdata (SOSI, GeoPackage),
terrengmodeller, punktskyer og ortofoto. Hver registrering har et nummer (#1, #2 …) og kan være en enkeltfil eller en pakke.

Regler:
- Bruk verktøyene for å finne svaret. Ikke gjett på innhold du ikke har slått opp.
- Vis til registreringer som #nummer (for eksempel «#9 Terrengmodell_DTM2_2026.tif»), så blir de lenker.
- Si tydelig når noe mangler i dataene eller ikke er kontrollert.
- Ved analyse: forklar hva tallene betyr for prosjekteringen (nøyaktighet, alder, dekning, avvik).
- Utgåtte registreringer er erstattet av nyere versjoner; nevn det hvis de dukker opp.
- Skriv ren tekst: korte avsnitt og punktlister som starter med «- ». Ingen overskrifter, ingen tabeller.`;
    const TYPES = S.options.data_types;
    const QA_L = QA, READY_L = READY;
    const effOf = (d, k) => { for (const f of d.files) { const v = ((f.effective || {})[k] || {}).value; if (v != null && v !== "") return v; } return null; };
    const rowOf = (d) => {
      const e = d.entry;
      return { nr: e.seq, navn: e.name, type: TYPES[e.data_type] || "Annet", pakke: e.kind === "package", filer: e.file_count,
        innhold: (d.profile || {}).summary || e.content, mottatt: String(e.received_at).slice(0, 10), fra: e.received_from, fag: e.discipline,
        automatisk_kontroll: LABELS[e.check_result], regler_med_merknad: e.deviations, status_kontroll: QA_L[e.qa_status],
        klar_til_bruk: READY_L[e.ready] || "ikke vurdert", gjeldende: e.lifecycle === "utgatt" ? "Utgått" : "Gjeldende", åpne_spørsmål: e.open_questions };
    };
    const projectDetails = (pid) => details(pid).sort((a, b) => a.entry.seq - b.entry.seq);
    const bySeq = (pid, n) => projectDetails(pid).find((d) => d.entry.seq === Number(n)) || fail(`Fant ikke registrering #${n}.`);
    const textOf = (d) => [d.entry.name, (d.profile || {}).summary, ((d.profile || {}).keywords || []).join(" "), d.entry.content,
      d.files.map((f) => f.file_name).join(" "), TYPES[d.entry.data_type]].join(" ").toLowerCase();
    const MISSING = { koordinatsystem: "horizontal_epsg", høydesystem: "height_reference", dato: "data_date", kilde: "source", kvalitet: "quality" };
    const tools = (pid) => ({
      search_entries(a) {
        const words = String(a.text || "").toLowerCase().match(/\w+/g) || [];
        const now = new Date().getFullYear();
        const rows = projectDetails(pid).filter((d) => {
          const e = d.entry;
          if (a.data_type && e.data_type !== a.data_type) return false;
          if (a.check_result && e.check_result !== a.check_result) return false;
          if (a.qa_status && e.qa_status !== a.qa_status) return false;
          if (a.ready && (a.ready === "ikke_vurdert" ? !!e.ready : e.ready !== a.ready)) return false;
          if (a.lifecycle && e.lifecycle !== a.lifecycle) return false;
          if (a.discipline && String(e.discipline).toUpperCase() !== String(a.discipline).toUpperCase()) return false;
          if (a.has_open_questions != null && !!e.open_questions !== !!a.has_open_questions) return false;
          if (a.missing) {
            const k = MISSING[a.missing], v = effOf(d, k);
            if (k === "horizontal_epsg" ? typeof v === "number" : !!v) return false;
            if (e.data_type === "document" && /system/.test(a.missing)) return false;
          }
          if (a.older_than_years) { const y = parseInt(String(effOf(d, "data_date") || ""), 10); if (!y || now - y <= Number(a.older_than_years)) return false; }
          if (words.length) { const t = textOf(d); if (!words.every((w) => t.includes(w))) return false; }
          return true;
        }).map(rowOf);
        return { antall: rows.length, registreringer: rows.slice(0, 30) };
      },
      get_entry(a) {
        const d = bySeq(pid, a.nr), e = d.entry;
        const out = { ...rowOf(d), beskrivelse: (d.profile || {}).summary, fakta: Object.fromEntries((d.profile || {}).facts || []),
          georeferanse: (d.profile || {}).georef, ks_merknad: e.qa_note || null, beslutning: (e.review || {}).comment || null,
          verdier: Object.fromEntries(Object.values(MISSING).map((k) => [k, effOf(d, k)])) };
        out.merknader = d.files.flatMap((f) => f.checks.filter((c) => c.result !== "ok").map((c) => ({ fil: f.file_name, regel: c.rule_id, krav: c.rule_text, resultat: LABELS[c.result], belegg: String(c.evidence || "").slice(0, 220) }))).slice(0, 20);
        const comps = d.files.filter((f) => f.comparison).map((f) => {
          const c = f.comparison;
          return c.status === "done" ? { fil: f.file_name, referanse: `#${c.reference.entry_seq} ${c.reference.file_name}`, systematisk_avvik_m: c.mean_m, spredning_m: c.std_m, p95_m: c.p95_abs_m, størst_avvik_m: c.max_m, endret_areal_over_0_5m_m2: (c.area_over_m2 || {})["0.5"], forskyvning: c.shift && c.shift.suspected ? c.shift : false } : { fil: f.file_name, status: c.status };
        });
        if (comps.length) out.sammenligning_med_referanse = comps;
        out.åpne_spørsmål_tekst = d.questions.filter((q) => q.status === "open").map((q) => q.question);
        if ((e.comment_list || []).length) out.kommentarer = e.comment_list.slice(-10).map((c) => `${c.by_name || c.by}: ${c.text}`);
        const corr = (e.corrected_fields || []).map((k) => `${k} korrigert manuelt`).concat(Object.entries(e.check_overrides || {}).map(([k, o]) => `${k} overstyrt til ${LABELS[o.result]}: ${o.comment}`));
        if (corr.length) out.manuelle_korreksjoner = corr;
        if (e.superseded_by) out.erstattet_av = `#${e.superseded_by.seq} ${e.superseded_by.name}`;
        return out;
      },
      related(a) {
        const d = bySeq(pid, a.nr);
        return { nr: d.entry.seq, navn: d.entry.name, relasjoner: (d.relations || []).map((g) => ({ type: g.label, registreringer: g.entries.map((x) => `#${x.seq} ${x.name}${x.note ? ` (${x.note})` : ""}${(S.details[x.id] || { entry: {} }).entry.lifecycle === "utgatt" ? " – utgått" : ""}`) })) };
      },
      search_text(a) {
        const words = (String(a.query || "").toLowerCase().match(/\w+/g) || []).filter((w) => w.length > 2);
        if (!words.length) fail("Skriv hva du leter etter.");
        const hits = [];
        projectDetails(pid).forEach((d) => (S.texts[d.entry.id] || []).forEach((t) => {
          const low = t.text.toLowerCase();
          const pos = words.map((w) => low.indexOf(w)).filter((p) => p >= 0);
          if (!pos.length) return;
          const p = Math.min(...pos);
          hits.push({ nr: d.entry.seq, registrering: d.entry.name, kilde: t.name, treff: pos.length, utdrag: t.text.slice(Math.max(0, p - 120), p + 200).replace(/\s+/g, " ").trim() });
        }));
        hits.sort((x, y) => y.treff - x.treff);
        return { antall: hits.length, treff: hits.slice(0, 12) };
      },
      project_overview() {
        const ds = projectDetails(pid), count = (f) => ds.reduce((m, d) => { const k = f(d); m[k] = (m[k] || 0) + 1; return m; }, {});
        const p = S.projects.find((x) => x.id === pid) || {};
        return { prosjekt: p.name, koordinatsystem: p.horizontal_crs, høydesystem: p.height_reference, registreringer: ds.length,
          filer: ds.reduce((s, d) => s + d.files.length, 0), per_type: count((d) => TYPES[d.entry.data_type]),
          automatisk_kontroll: count((d) => LABELS[d.entry.check_result]), status_kontroll: count((d) => QA_L[d.entry.qa_status]),
          klar_til_bruk: count((d) => READY_L[d.entry.ready] || "ikke vurdert"),
          utgått: ds.filter((d) => d.entry.lifecycle === "utgatt").map((d) => `#${d.entry.seq} ${d.entry.name}`),
          åpne_spørsmål: ds.reduce((s, d) => s + d.entry.open_questions, 0),
          med_avvik: ds.filter((d) => d.entry.check_result === "deviation").map((d) => `#${d.entry.seq} ${d.entry.name} (${d.entry.deviations.join(", ")})`) };
      },
    });
    const TOOL_DEFS = [
      { name: "search_entries", description: "Søk og filtrer i registeret. Returnerer registreringer med nummer, navn, type, innhold, mottatt, resultat av automatisk kontroll, KS-status og om de er klare til bruk. Alle felt er valgfrie.",
        inputSchema: { type: "object", properties: { text: { type: "string", description: "Fritekst mot navn, innhold, nøkkelord og filnavn" }, data_type: { type: "string", enum: Object.keys(TYPES) }, check_result: { type: "string", enum: Object.keys(LABELS) }, qa_status: { type: "string", enum: Object.keys(QA) }, ready: { type: "string", enum: [...Object.keys(READY), "ikke_vurdert"] }, lifecycle: { type: "string", enum: ["gjeldende", "utgatt"] }, missing: { type: "string", enum: Object.keys(MISSING) }, older_than_years: { type: "number" }, discipline: { type: "string" }, has_open_questions: { type: "boolean" } } } },
      { name: "get_entry", description: "Alt om én registrering: innhold, metadata, kontroller som ikke er OK, åpne spørsmål, sammenligning med referanse og KS.", inputSchema: { type: "object", properties: { nr: { type: "integer" } }, required: ["nr"] } },
      { name: "related", description: "Hvordan en registrering henger sammen med andre: versjoner, referanse, omtaler i tekst, samme leveranse og samme område.", inputSchema: { type: "object", properties: { nr: { type: "integer" } }, required: ["nr"] } },
      { name: "search_text", description: "Søk i teksten inne i dokumenter, rapporter, tegningshoder og leveransenotater. Returnerer utdrag med registreringsnummer.", inputSchema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] } },
      { name: "project_overview", description: "Oversikt over prosjektet: antall per datatype, kontrollresultat, KS-status, utgåtte og åpne spørsmål.", inputSchema: { type: "object", properties: {} } },
    ];
    const STATUS = { search_entries: "Søker i registeret …", get_entry: "Leser registreringen …", related: "Finner koblinger …", search_text: "Søker i tekst i filene …", project_overview: "Henter oversikt …" };
    const samplePromise = window.claude && typeof window.claude.use === "function" ? Promise.resolve(window.claude.use("sample")).catch(() => null) : Promise.resolve(null);
    let sampleOff = false;

    function localAnswer(pid, question) {
      const t = tools(pid);
      const m = question.match(/#\s*(\d+)/);
      if (m) {
        const e = t.get_entry({ nr: m[1] });
        return `#${e.nr} ${e.navn}: ${e.beskrivelse}\n- Automatisk kontroll: ${e.automatisk_kontroll}; status kontroll: ${e.status_kontroll}; klar til bruk: ${e.klar_til_bruk}.\n` +
          e.merknader.slice(0, 4).map((x) => `- ${x.regel} ${x.resultat}: ${x.belegg}`).join("\n");
      }
      const words = (question.toLowerCase().match(/[a-zæøå0-9]{4,}/g) || []);
      const hits = projectDetails(pid).map((d) => [words.filter((w) => textOf(d).includes(w) || (S.texts[d.entry.id] || []).some((x) => x.text.toLowerCase().includes(w))).length, d]).filter(([n]) => n).sort((a, b) => b[0] - a[0]);
      if (!hits.length) return "Fant ingen registreringer som passer med ordene i spørsmålet.";
      return "Registreringer som passer best:\n" + hits.slice(0, 8).map(([, d]) => `- #${d.entry.seq} ${d.entry.name} – ${String((d.profile || {}).summary || d.entry.content).replace(/\.$/, "")}`).join("\n");
    }

    async function chat(pid, turns, opts = {}) {
      const sample = sampleOff ? null : await samplePromise;
      const q = turns[turns.length - 1].content;
      const fallback = (why) => ({ answer: `${why} Her er et enkelt søk i stedet:\n\n${localAnswer(pid, q)}`, model: "enkelt søk i nettleseren (ikke AI)", tools: [] });
      if (!sample) return fallback("AI er ikke tilgjengelig i denne visningen.");
      const p = S.projects.find((x) => x.id === pid) || {};
      const used = [];
      const T = tools(pid);
      const defs = TOOL_DEFS.map((d) => ({ ...d, execute: (input) => { used.push(d.name); if (opts.onTool) opts.onTool(STATUS[d.name]); return T[d.name](input || {}); } }));
      const intro = `${CHAT_RULES}${LANG === "en" ? "\n\nThe user has chosen English: answer in English (keep Norwegian names of files, fields and rules as they are)." : ""}\n\nProsjekt: ${p.name} (${p.project_type}, ${p.phase}), ${p.horizontal_crs}, ${p.height_reference}. I dag: ${new Date().toISOString().slice(0, 10)}.\nSvar på brukerens siste spørsmål nedenfor.`;
      try {
        const res = await sample([{ role: "user", content: intro }, ...turns.slice(-10)], { tools: defs, signal: opts.signal, onText: ({ text }) => opts.onText && opts.onText(text) });
        return { answer: res.text, model: `Claude (${res.modelTierApplied || "default"}) via din Claude-konto`, tools: used };
      } catch (e) {
        if (e && e.code === "cancelled") throw e;
        if (e && ["not_granted", "sampling_disabled", "not_declared", "capability_disabled", "capability_removed", "tools_unavailable"].includes(e.code)) {
          sampleOff = true;
          return fallback(e.code === "not_granted" ? "Du tillot ikke at siden bruker Claude." : "AI er ikke tilgjengelig i denne visningen.");
        }
        if (e && e.code === "rate_limited") throw new Error("For mange spørsmål akkurat nå. Vent litt og prøv igjen.");
        if (e && e.text) return { answer: e.text + "\n\n(Svaret ble avbrutt.)", model: "Claude", tools: used };
        throw new Error("AI-svaret feilet. Prøv igjen.");
      }
    }

    function dispatch(method, path, body) {
      const [p, qs] = path.split("?");
      const query = new URLSearchParams(qs || "");
      for (const [key, fn] of Object.entries(routes)) {
        const [m, pattern] = key.split(" ");
        if (m !== method) continue;
        const re = new RegExp("^" + pattern.replace(":id", "([^/]+)") + "$");
        const hit = p.match(re);
        if (hit) return Promise.resolve().then(() => clone(fn(hit[1] && decodeURIComponent(hit[1]), query, body || {})));
      }
      return Promise.reject(new Error("Ikke tilgjengelig i demoen."));
    }
    return { get: (p) => dispatch("GET", p), post: (p, b) => dispatch("POST", p, b), chat };
  }

  boot();
})();
