import argparse
import csv as _csv
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from export_raum import (PRAEFIXE, iri, literal,
                         spalten_von, sql_fuer, run_copy)


CRS_ORT = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

AUSGABE = pfade.PERSONEN
SCHEMA_09 = HIER.parents[0] / "schema" / "module" / "09_codelisten.ttl"


def slug(s):
    s = (s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
          .replace("ß", "ss").replace("Ä", "Ae").replace("Ö", "Oe")
          .replace("Ü", "Ue"))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return re.sub(r"_+", "_", s)


LISTEN = {
    "kennungssystem":       "system",
    "verortungsgenauigkeit": "genauigkeit",
    "variantentyp":         "variantentyp",
    "plattform":            "plattform",
    "adressart":            "adressart",
    "taetigkeitskategorie": "taetigkeitskategorie",
    "thema":                "thema",
}

BEKANNT = set()
UNBEKANNT = set()
KAPUTT = set()

UNGUELTIG = re.compile(r'[\s<>"{}|\\^`]')


def lies_schema_kennungen():
    text = SCHEMA_09.read_text(encoding="utf-8")
    return set(re.findall(r"^(stkg:[a-z0-9_]+) a stkg:", text, re.M))


def code_iri(liste, wert):
    if wert is None or str(wert).strip() == "":
        return None
    k = "stkg:%s_%s" % (LISTEN[liste], slug(str(wert).strip()))
    if k not in BEKANNT:
        UNBEKANNT.add((liste, str(wert)))
        return None
    return k


LIEFERUNG_ALIAS = """CASE
        WHEN quelle = 'abgeordnetenwatch'      THEN 'aw_api_v2'
        WHEN quelle = 'dip'                    THEN 'dip_dokumente'
        WHEN quelle = 'redner'                 THEN 'cpp_bt_fobbe'
        WHEN quelle LIKE 'mdb_namensalias/%%'  THEN 'bt_mdb_stammdaten'
        END"""

LIEFERUNG_SYSTEM = """CASE
        WHEN system = 'aw'  THEN 'aw_api_v2'
        WHEN system = 'dip' THEN 'dip_dokumente'
        WHEN system = 'btv' THEN 'bt_mdb_stammdaten'
        END"""


WD_QUERY = """(SELECT k.person, e.p_nummer, e.wert,
                      row_number() OVER (PARTITION BY k.person, e.p_nummer
                                         ORDER BY e.wert) AS lfd
                 FROM (
                        SELECT aw_id, 'P227'   AS p_nummer, gnd              AS wert FROM politiker_innen.wikidata_kennung WHERE gnd IS NOT NULL
                  UNION ALL SELECT aw_id, 'P214',           viaf                     FROM politiker_innen.wikidata_kennung WHERE viaf IS NOT NULL
                  UNION ALL SELECT aw_id, 'P10632',         opensanctions            FROM politiker_innen.wikidata_kennung WHERE opensanctions IS NOT NULL
                  UNION ALL SELECT aw_id, 'P14716',         openparliamenttv         FROM politiker_innen.wikidata_kennung WHERE openparliamenttv IS NOT NULL
                  UNION ALL SELECT aw_id, 'P1713',          bt_biografie             FROM politiker_innen.wikidata_kennung WHERE bt_biografie IS NOT NULL
                  UNION ALL SELECT aw_id, 'P856',           website                  FROM politiker_innen.wikidata_kennung WHERE website IS NOT NULL
                  UNION ALL SELECT aw_id, 'P5355',          wd_aw_id                 FROM politiker_innen.wikidata_kennung WHERE wd_aw_id IS NOT NULL
                  UNION ALL SELECT w.aw_id, ee.k, tt.wert
                              FROM politiker_innen.wikidata_kennung w,
                                   LATERAL jsonb_each(w.weitere) AS ee(k, v),
                                   LATERAL jsonb_array_elements_text(
                                     CASE WHEN jsonb_typeof(v) = 'array'
                                          THEN v ELSE jsonb_build_array(v) END) AS tt(wert)
                      ) e
                 JOIN parlamentsarbeit.person_kennung k
                   ON k.system = 'aw' AND k.kennung = e.aw_id::text
                 JOIN politiker_innen.wikidata_eigenschaft_klasse kl
                   ON kl.p_nummer = e.p_nummer
                WHERE kl.klasse = '%s')"""


BESTAENDE = [
    {

        "name": "person",
        "tabelle": "parlamentsarbeit.person",
        "lieferung": "personenknoten",
        "lieferung_spalte": None,
        "klasse": "stkg:Person",
        "iri": "person/{person}",
        "geometrie": None,
        "felder": [("person", "stkg:personenkennung", "text")],
    },
    {


        "name": "kennung",
        "tabelle": """(SELECT person, system, kennung, %s AS lieferung
                         FROM parlamentsarbeit.person_kennung)""" % LIEFERUNG_SYSTEM,
        "lieferung": None,
        "lieferung_spalte": "lieferung",
        "klasse": "stkg:Kennung",
        "iri": "kennung/{system}_{kennung}",
        "geometrie": None,
        "felder": [
            ("kennung", "stkg:kennungswert", "text"),
            ("system",  "stkg:ausSystem",    "code", "kennungssystem"),
        ],
    },
    {
        "name": "kennung_kante",
        "tabelle": """(SELECT person, system, kennung, %s AS lieferung
                         FROM parlamentsarbeit.person_kennung)""" % LIEFERUNG_SYSTEM,
        "lieferung": None,
        "lieferung_spalte": "lieferung",
        "klasse": None,
        "iri": "person/{person}",
        "geometrie": None,
        "felder": [("kennung", "stkg:hatKennung", "ref",
                    "kennung/{system}_{kennung}")],
    },
    {


        "name": "namensvariante",
        "tabelle": """(SELECT person, quelle, nachname, vorname,
                              namenszusatz, titel, ortszusatz,
                              trim(coalesce(vorname,'') || ' ' ||
                                   coalesce(nachname,'')) AS schreibweise,
                              row_number() OVER (PARTITION BY person
                                                 ORDER BY quelle, nachname,
                                                          vorname) AS lfd,
                              %s AS lieferung
                         FROM parlamentsarbeit.person_alias)""" % LIEFERUNG_ALIAS,
        "lieferung": None,
        "lieferung_spalte": "lieferung",
        "klasse": "stkg:Namensvariante",
        "iri": "namensvariante/{person}_{lfd}",
        "geometrie": None,
        "felder": [
            ("person",       "stkg:hatVariantentraeger",   "ref", "person/{person}"),
            ("quelle",       "stkg:hatVariantentyp",       "code", "variantentyp"),
            ("schreibweise", "stkg:variantenschreibweise", "text"),
            ("nachname",     "stkg:variantenNachname",     "text"),
            ("vorname",      "stkg:variantenVorname",      "text"),
            ("ortszusatz",   "stkg:variantenOrtszusatz",   "text"),
            ("titel",        "stkg:variantenTitel",        "text"),
            ("namenszusatz", "stkg:variantenNamenszusatz", "text"),
        ],
    },
    {


        "name": "namensfuehrung",
        "tabelle": """(SELECT k.person, n.lfd, n.nachname, n.vorname,
                              n.ortszusatz, n.adel, n.praefix,
                              n.anrede_titel, n.akad_titel,
                              n.historie_von, n.historie_bis,
                              trim(coalesce(n.vorname,'') || ' ' ||
                                   coalesce(n.nachname,'')) AS gefuehrt
                         FROM roh_bundestag.stammdaten_mdb_name n
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'btv' AND k.kennung = n.id)""",
        "lieferung": "bt_mdb_stammdaten",
        "lieferung_spalte": None,
        "klasse": "stkg:Namensfuehrung",
        "iri": "namensfuehrung/{person}_{lfd}",
        "geometrie": None,
        "felder": [
            ("person",       "stkg:hatNamenstraeger",  "ref", "person/{person}"),
            ("nachname",     "stkg:nachname",          "text"),
            ("vorname",      "stkg:vorname",           "text"),
            ("gefuehrt",     "stkg:gefuehrterName",    "text"),
            ("ortszusatz",   "stkg:ortszusatz",        "text"),
            ("adel",         "stkg:adelspraedikat",    "text"),
            ("praefix",      "stkg:namenspraefix",     "text"),
            ("akad_titel",   "stkg:akademischerGrad",  "text"),
            ("anrede_titel", "stkg:anredetitel",       "text"),
            ("historie_von", "stkg:episodeBeginn",        "datum"),
            ("historie_bis", "stkg:episodeEnde",        "datum"),
        ],
    },
    {


        "name": "biografie",
        "tabelle": """(SELECT k.person, b.geburtsdatum, b.sterbedatum,
                              b.geschlecht, b.beruf, b.familienstand,
                              b.religion, b.vita_kurz
                         FROM politiker_innen.biografie_bt b
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'aw' AND k.kennung = b.aw_id::text)""",
        "lieferung": "bt_mdb_stammdaten",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "person/{person}",
        "geometrie": None,
        "felder": [
            ("geburtsdatum",  "stkg:geburtsdatum",   "datum"),
            ("sterbedatum",   "stkg:sterbedatum",    "datum"),
            ("geschlecht",    "stkg:geschlecht",     "text"),
            ("beruf",         "stkg:beruf",          "text"),
            ("familienstand", "stkg:familienstand",  "text"),
            ("religion",      "stkg:religion",       "text"),
            ("vita_kurz",     "stkg:kurzbiographie", "text"),
        ],
    },
    {


        "name": "aw_angaben",
        "tabelle": """(SELECT k.person, p.birth_name, p.education, p.residence
                         FROM politiker_innen.politician p
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'aw' AND k.kennung = p.aw_id::text)""",
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "person/{person}",
        "geometrie": None,
        "felder": [
            ("birth_name", "stkg:geburtsname", "text"),
            ("education",  "stkg:ausbildung",  "text"),
            ("residence",  "stkg:wohnort",     "text"),
        ],
    },
    {


        "name": "nebentaetigkeit",
        "tabelle": """(SELECT k.person, s.aw_id AS sidejob_id, s.label,
                              s.income_level, s.job_interval, s.kategorie,
                              s.ist_taetigkeit, s.job_title_extra,
                              s.organization_id,
                              s.raw->>'income' AS betrag
                         FROM politiker_innen.sidejob s
                         JOIN politiker_innen.candidacy_mandate c
                           ON c.aw_id = s.mandate_id
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'aw'
                          AND k.kennung = c.politician_id::text)""",
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": "stkg:Nebentaetigkeit",
        "iri": "nebentaetigkeit/{sidejob_id}",
        "geometrie": None,
        "felder": [
            ("person",          "stkg:hatNebentaetigkeitsPerson", "ref",
             "person/{person}"),
            ("label",           "stkg:taetigkeitsbezeichnung", "text"),
            ("job_title_extra", "stkg:taetigkeitszusatz",      "text"),
            ("income_level",    "stkg:einkommensstufe",        "text"),
            ("betrag",          "stkg:einkommensbetrag",       "dez"),
            ("job_interval",    "stkg:zahlungsintervall",      "text"),
            ("ist_taetigkeit",  "stkg:istTaetigkeit",          "bool"),
            ("kategorie",       "stkg:hatTaetigkeitskategorie", "code",
             "taetigkeitskategorie"),


            ("organization_id", "stkg:hatNebentaetigkeitsOrganisation", "ref",
             "organisation/{organization_id}"),
        ],
    },
    {
        "name": "nebentaetigkeit_thema",
        "tabelle": """(SELECT sidejob_id, thema
                         FROM politiker_innen.sidejob_thema
                        WHERE thema IS NOT NULL)""",
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "nebentaetigkeit/{sidejob_id}",
        "geometrie": None,
        "felder": [("thema", "stkg:hatThema", "code", "thema")],
    },
    {


        "name": "nebentaetigkeit_mandat",
        "tabelle": """(SELECT sidejob_id, mandat_id
                         FROM politiker_innen.sidejob_mandat
                        WHERE mandat_im_bestand)""",
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "nebentaetigkeit/{sidejob_id}",
        "geometrie": None,
        "felder": [("mandat_id", "stkg:hatNebentaetigkeitsMandat", "ref",
                    "mandat/{mandat_id}")],
    },
    {


        "name": "wikidata_kennung",
        "tabelle": WD_QUERY % "kennung",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": "stkg:Kennung",
        "iri": "kennung/{person}_{p_nummer}_{lfd}",
        "geometrie": None,
        "felder": [
            ("wert",      "stkg:kennungswert", "text"),
            ("p_nummer",  "stkg:ausSystem",    "code", "kennungssystem"),
        ],
    },
    {
        "name": "wikidata_kennung_kante",
        "tabelle": WD_QUERY % "kennung",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "person/{person}",
        "geometrie": None,
        "felder": [("wert", "stkg:hatKennung", "ref",
                    "kennung/{person}_{p_nummer}_{lfd}")],
    },
    {

        "name": "wikidata_konto",
        "tabelle": WD_QUERY % "konto",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": "stkg:Konto",
        "iri": "konto/{person}_{p_nummer}_{lfd}",
        "geometrie": None,
        "felder": [
            ("wert",     "stkg:kontoname",    "text"),
            ("p_nummer", "stkg:aufPlattform", "code", "plattform"),
        ],
    },
    {
        "name": "wikidata_konto_kante",
        "tabelle": WD_QUERY % "konto",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "person/{person}",
        "geometrie": None,
        "felder": [("wert", "stkg:hatKonto", "ref",
                    "konto/{person}_{p_nummer}_{lfd}")],
    },
    {

        "name": "wikidata_webadresse",
        "tabelle": WD_QUERY % "webadresse",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": "stkg:Webadresse",
        "iri": "webadresse/{person}_{p_nummer}_{lfd}",
        "geometrie": None,
        "felder": [
            ("wert",     "stkg:adresse",       "text"),
            ("p_nummer", "stkg:hatAdressart",  "code", "adressart"),
        ],
    },
    {
        "name": "wikidata_webadresse_kante",
        "tabelle": WD_QUERY % "webadresse",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "person/{person}",
        "geometrie": None,
        "felder": [("wert", "stkg:hatWebadresse", "ref",
                    "webadresse/{person}_{p_nummer}_{lfd}")],
    },
    {


        "name": "wikidata_namensvariante",
        "tabelle": WD_QUERY % "namensvariante",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": "stkg:Namensvariante",
        "iri": "namensvariante/wd_{person}_{p_nummer}_{lfd}",
        "geometrie": None,
        "felder": [
            ("person",   "stkg:hatVariantentraeger",   "ref", "person/{person}"),
            ("wert",     "stkg:variantenschreibweise", "text"),
            ("p_nummer", "stkg:hatVariantentyp",       "code", "variantentyp"),
        ],
    },
    {


        "name": "ort",
        "tabelle": """(SELECT DISTINCT ort_qid, genauigkeit
                         FROM politiker_innen.geburtsort)""",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": "stkg:Ort",
        "iri": "ort/{ort_qid}",
        "geometrie": None,
        "felder": [("genauigkeit", "stkg:hatVerortungsgenauigkeit", "code",
                    "verortungsgenauigkeit")],
    },
    {


        "name": "ort_geometrie",
        "tabelle": """(SELECT ort_qid, geom,
                              row_number() OVER (PARTITION BY ort_qid
                                                 ORDER BY st_astext(geom)) AS lfd
                         FROM (SELECT DISTINCT ort_qid, geom
                                 FROM politiker_innen.geburtsort) x)""",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": "stkg:Geometrie",
        "iri": "geometrie/ort/{ort_qid}_{lfd}",
        "geometrie": "geom",
        "geometrie_eigenstaendig": True,
        "haengt_an": ("ort/{ort_qid}", "geo:hasGeometry"),
        "felder": [],
    },
    {


        "name": "ort_name_amtlich",
        "tabelle": """(SELECT DISTINCT ort_qid, ort_amtlich, land
                         FROM politiker_innen.geburtsort)""",
        "lieferung": "bt_mdb_stammdaten",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "ort/{ort_qid}",
        "geometrie": None,
        "felder": [
            ("ort_amtlich", "stkg:ortsbezeichnung", "text"),
            ("land",        "stkg:ortsland",        "text"),
        ],
    },
    {


        "name": "ort_name_wikidata",
        "tabelle": """(SELECT DISTINCT ort_qid, ort_wikidata
                         FROM politiker_innen.geburtsort)""",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "ort/{ort_qid}",
        "geometrie": None,
        "felder": [("ort_wikidata", "stkg:ortsbezeichnung", "text")],
    },
    {


        "name": "geburtsort_kante",
        "tabelle": """(SELECT k.person, g.ort_qid
                         FROM politiker_innen.geburtsort g
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'aw' AND k.kennung = g.aw_id::text
                        WHERE g.ort_qid IS NOT NULL)""",
        "lieferung": "wikidata",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "person/{person}",
        "geometrie": None,
        "felder": [("ort_qid", "stkg:hatGeburtsort", "ref", "ort/{ort_qid}")],
    },
]


def kopf(lieferung):
    return "\n".join([
        "# Personen der Lieferung %s" % lieferung,
        "#",
        "# ERZEUGT von 03_load_db/graph/export_personen.py.",
        "",
    ] + ["@prefix %s: <%s> ." % (pr, u) for pr, u in PRAEFIXE]
      + ["", "%s {" % iri("lieferung/%s" % lieferung), ""])


def tripel(bestand, z):
    z_iri = dict(z)
    pfad_teil = bestand["iri"].format(**z_iri)
    if UNGUELTIG.search(pfad_teil):
        KAPUTT.add((bestand["name"], pfad_teil[:70]))
        return None
    kennung = iri(pfad_teil)

    if bestand.get("geometrie_eigenstaendig"):


        ziel, kante = bestand["haengt_an"]
        zt = ziel.format(**z_iri)
        if UNGUELTIG.search(zt):
            KAPUTT.add((bestand["name"] + " -> Ziel", zt[:70]))
            return None
        return ("    %s %s %s .\n\n" % (iri(zt), kante, kennung)
                + "    %s\n" % kennung
                + "        a          %s ;\n" % bestand["klasse"]
                + '        geo:asWKT  "<%s> %s"^^geo:wktLiteral .\n'
                  % (CRS_ORT, z["wkt"]))

    zeilen = []
    if bestand["klasse"]:
        zeilen.append("        a  %s" % bestand["klasse"])
    for feld in bestand["felder"]:
        spalte, praedikat, art = feld[0], feld[1], feld[2]
        wert = z.get(spalte)
        if wert is None or str(wert).strip() == "":
            continue
        if art == "ref":
            ziel = feld[3].format(**z_iri)
            if UNGUELTIG.search(ziel):
                KAPUTT.add((bestand["name"] + " -> " + spalte, ziel[:70]))
                continue
            objekt = iri(ziel)
        elif art == "code":
            objekt = code_iri(feld[3], wert)
            if objekt is None:
                continue
        else:
            objekt = literal(wert, art)
        zeilen.append("        %-28s %s" % (praedikat, objekt))
    if not zeilen:
        return None
    return "    %s\n" % kennung + " ;\n".join(zeilen) + " .\n"


def baue(namen, max_mb):
    global BEKANNT
    BEKANNT = lies_schema_kennungen()
    print("  %d Codelisten-Kennungen aus dem Schema gelesen" % len(BEKANNT))

    pfade.pruefe(AUSGABE)
    tmp = AUSGABE / "_export.csv"
    grenze = max_mb * 1024 * 1024 if max_mb else 0

    offen = {}
    teile = defaultdict(list)

    def dateiname(lieferung, nr):
        return AUSGABE / ("%s.trig" % lieferung if nr == 1
                          else "%s_%02d.trig" % (lieferung, nr))

    def oeffne(lieferung, nr):
        if nr == 1:
            for alt in (list(AUSGABE.glob("%s.trig" % lieferung))
                        + list(AUSGABE.glob("%s_[0-9][0-9].trig" % lieferung))):
                alt.unlink()
        pfad = dateiname(lieferung, nr)
        fh = pfad.open("w", encoding="utf-8")
        fh.write(kopf(lieferung))
        teile[lieferung].append(pfad)
        return fh

    def schreibe(lieferung, text):
        if lieferung not in offen:
            offen[lieferung] = [oeffne(lieferung, 1), 1, 0]
        e = offen[lieferung]
        if grenze and e[2] + len(text) > grenze:
            e[0].write("}\n")
            e[0].close()
            if e[1] == 1:
                erst = teile[lieferung][0]
                neu = erst.with_name("%s_01.trig" % lieferung)
                erst.replace(neu)
                teile[lieferung][0] = neu
            e[1] += 1
            e[0] = oeffne(lieferung, e[1])
            e[2] = 0
        e[0].write(text)
        e[2] += len(text)

    gezaehlt = defaultdict(int)
    ohne_lieferung = defaultdict(int)
    for bestand in BESTAENDE:
        if namen and bestand["name"] not in namen:
            continue


        run_copy(sql_fuer(bestand, 15), tmp)
        with tmp.open(encoding="utf-8", newline="") as fh:
            for z in _csv.DictReader(fh):


                if bestand["lieferung_spalte"]:
                    lieferung = (z.get(bestand["lieferung_spalte"]) or "").strip()
                    if not lieferung:
                        ohne_lieferung[bestand["name"]] += 1
                        continue
                else:
                    lieferung = bestand["lieferung"]
                text = tripel(bestand, z)
                if text:
                    schreibe(lieferung, text)
                    gezaehlt[bestand["name"]] += 1
        print("  %-22s %8d Bloecke" % (bestand["name"], gezaehlt[bestand["name"]]))

    for lieferung, e in offen.items():
        e[0].write("}\n")
        e[0].close()
    tmp.unlink(missing_ok=True)

    if ohne_lieferung:
        print("\n  OHNE LIEFERUNG -- nicht geschrieben:")
        for name, n in sorted(ohne_lieferung.items()):
            print("    %-22s %8d Zeilen" % (name, n))

    if KAPUTT:
        print("\n  UNGUELTIGE KENNUNGEN -- nicht geschrieben:")
        for name, wert in sorted(KAPUTT)[:20]:
            print("    %-28s %s" % (name, wert))
        raise SystemExit("%d ungueltige Kennungen. Die Ausgabe ist " "unvollstaendig und darf nicht geladen werden."
                         % len(KAPUTT))

    if UNBEKANNT:
        print("\n  UNBEKANNTE CODEWERTE -- nicht geschrieben:")
        for liste, wert in sorted(UNBEKANNT):
            print("    %-16s %s" % (liste, wert))

    print("\n  Dateien:")
    for lieferung, dateien in teile.items():
        for p in dateien:
            print("    %-34s %.1f MB" % (p.name, p.stat().st_size / 1024 / 1024))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bestand", nargs="*")
    ap.add_argument("--liste", action="store_true")
    ap.add_argument("--max-mb", type=int, default=200)
    a = ap.parse_args()
    if a.liste:
        for b in BESTAENDE:
            print("  %-22s %s" % (b["name"], b["tabelle"].split("\n")[0][:60]))
        return
    baue(set(a.bestand), a.max_mb)


if __name__ == "__main__":
    main()
