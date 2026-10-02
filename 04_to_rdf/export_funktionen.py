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
                         sql_fuer, run_copy)

AUSGABE = pfade.FUNKTIONEN
SCHEMA_09 = HIER.parents[0] / "schema" / "module" / "09_codelisten.ttl"


def slug(s):
    s = (s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
          .replace("ß", "ss").replace("Ä", "Ae").replace("Ö", "Oe")
          .replace("Ü", "Ue"))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return re.sub(r"_+", "_", s)


BEKANNT = set()
UNBEKANNT = set()
KAPUTT = set()
UNGUELTIG = re.compile(r'[\s<>"{}|\\^`]')


def lies_schema_kennungen():
    return set(re.findall(r"^(stkg:[a-z0-9_]+) a stkg:",
                          SCHEMA_09.read_text(encoding="utf-8"), re.M))


MANDATSTYP = {
    "constituency": "stkg:mandatstyp_direktmandat",
    "list":         "stkg:mandatstyp_listenmandat",
}


FRAKTIONSROLLE = {
    "vorsitzender": "stkg:fraktionsrolle_vorsitz",
    "vorsitzende":  "stkg:fraktionsrolle_vorsitz",
    "stellvertretender vorsitzender": "stkg:fraktionsrolle_stellvertretender_vorsitz",
    "stellvertretende vorsitzende":   "stkg:fraktionsrolle_stellvertretender_vorsitz",
    "erste stellvertretende vorsitzende": "stkg:fraktionsrolle_erster_stellvertretender_vorsitz",
    "ehrenvorsitzender": "stkg:fraktionsrolle_ehrenvorsitz",
    "parlamentarischer geschaeftsfuehrer":  "stkg:fraktionsrolle_parl_geschaeftsfuehrung",
    "parlamentarische geschaeftsfuehrerin": "stkg:fraktionsrolle_parl_geschaeftsfuehrung",
    "erster parlamentarischer geschaeftsfuehrer":  "stkg:fraktionsrolle_erste_parl_geschaeftsfuehrung",
    "erste parlamentarische geschaeftsfuehrerin":  "stkg:fraktionsrolle_erste_parl_geschaeftsfuehrung",
    "stellvertretender erster parlamentarischer geschaeftsfuehrer":
        "stkg:fraktionsrolle_stellv_erste_parl_geschaeftsfuehrung",
    "justiziar":   "stkg:fraktionsrolle_justiziariat",
    "justiziarin": "stkg:fraktionsrolle_justiziariat",
    "revisor":     "stkg:fraktionsrolle_revision",
    "revisorin":   "stkg:fraktionsrolle_revision",
    "sicherheitsbeauftragte/r der fraktion": "stkg:fraktionsrolle_sicherheitsbeauftragung",
    "frauenpolitische sprecherin": "stkg:fraktionsrolle_frauenpolitische_sprache",
    "sprecher der cdu-landesgruppen-vorsitzenden":
        "stkg:fraktionsrolle_sprecher_landesgruppenvorsitzende",
    "erster stellvertr. vorsitzender und vorsitzender der csu-landesgruppe":
        "stkg:fraktionsrolle_stellv_vorsitz_und_csu_landesgruppe",
    "erste stellvertretende vorsitzende und vorsitzende der csu-landesgruppe":
        "stkg:fraktionsrolle_stellv_vorsitz_und_csu_landesgruppe",
}


GREMIENROLLE = {
    "member":            "stkg:gremienrolle_ordentliches_mitglied",
    "alternate_member":  "stkg:gremienrolle_stellvertretendes_mitglied",
    "chairperson":       "stkg:gremienrolle_vorsitz",
    "vice_chairperson":  "stkg:gremienrolle_stellvertretender_vorsitz",
    "foreperson":        "stkg:gremienrolle_obleute",
    "advisory_member":   "stkg:gremienrolle_beratend_gobt",
    "eligible_member":   "stkg:gremienrolle_berechtigtes_mitglied",
    "spokesperson":      "stkg:gremienrolle_sprecher",
}

VOKABULAR = {"mandatstyp": MANDATSTYP, "fraktionsrolle": FRAKTIONSROLLE,
             "gremienrolle": GREMIENROLLE}


def code_iri(liste, wert):
    if wert is None or str(wert).strip() == "":
        return None
    k = VOKABULAR[liste].get(str(wert).strip().lower().replace("ä", "ae")
                             .replace("ö", "oe").replace("ü", "ue")
                             .replace("ß", "ss"))
    if k is None:
        UNBEKANNT.add((liste, str(wert)))
        return None
    if k not in BEKANNT:
        UNBEKANNT.add((liste, "%s -> %s fehlt im Schema" % (wert, k)))
        return None
    return k


PARTEI_AW = """(SELECT DISTINCT lower(partei_roh) AS roh, partei
                 FROM meta.partei_mapping
                WHERE verfahren <> 'keine_partei'
                  AND lieferung_ids @> ARRAY['aw_api_v2'])"""


WP = """CASE m.legislatur
          WHEN 'Bundestag 2013 - 2017' THEN 18
          WHEN 'Bundestag 2017 - 2021' THEN 19
          WHEN 'Bundestag 2021 - 2025' THEN 20
        END"""


WJ = """CASE m.legislatur
          WHEN 'Bundestag 2013 - 2017' THEN 2013
          WHEN 'Bundestag 2017 - 2021' THEN 2017
          WHEN 'Bundestag 2021 - 2025' THEN 2021
        END"""


MANDAT = """(SELECT m.aw_id, k.person, %s AS wp, %s AS wahljahr,
                    m.mandatsart, m.wkr_nr, m.liste_id, m.listenplatz,
                    m.beginn, m.ende, pm.partei
               FROM politiker_innen.mandat m
               JOIN parlamentsarbeit.person_kennung k
                 ON k.system = 'aw' AND k.kennung = m.politician_id::text
               LEFT JOIN politiker_innen.kandidatur ka ON ka.mandat_id = m.aw_id
               LEFT JOIN %s pm ON pm.roh = lower(ka.party_label))""" % (WP, WJ, PARTEI_AW)

BESTAENDE = [
    {

        "name": "mandat",
        "tabelle": MANDAT,
        "lieferung": "aw_api_v2",
        "klasse": "stkg:Mandat",
        "iri": "mandat/{aw_id}",
        "geometrie": None,
        "felder": [
            ("person",      "stkg:hatMandatstraeger", "ref", "person/{person}"),
            ("wp",          "stkg:hatMandatsWahlperiode", "ref", "wahlperiode/{wp}"),
            ("mandatsart",  "stkg:hatMandatstyp", "code", "mandatstyp"),
            ("partei",      "stkg:errungenFuerPartei", "ref", "partei/{partei}"),
            ("wkr_nr",      "stkg:hatMandatsWahlkreis", "ref",
             "wahlkreisstand/{wahljahr}_{wkr_nr}"),
            ("liste_id",    "stkg:hatMandatsLandesliste", "ref",
             "landesliste/{liste_id}_{partei}"),


            ("beginn",      "stkg:episodeBeginn",  "datum"),
            ("ende",        "stkg:episodeEnde",  "datum"),
        ],
    },
    {


        "name": "kandidatur",
        "tabelle": """(SELECT c.aw_id, k.person,
                              substring(c.wahl from '([0-9]{4})')::int AS wahljahr,
                              c.wkr_nr, c.liste_id, c.mandat_id,




                              coalesce(c.listenplatz, m.listenplatz)
                                AS listenplatz,
                              CASE WHEN c.listenplatz IS NULL
                                    AND m.listenplatz IS NOT NULL
                                   THEN 'aus_mandat' ELSE 'geliefert'
                              END AS listenplatz_herkunft,
                              pm.partei
                         FROM politiker_innen.kandidatur c
                         LEFT JOIN politiker_innen.mandat m
                           ON m.aw_id = c.mandat_id
                         LEFT JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'aw' AND k.kennung = c.politician_id::text
                         LEFT JOIN %s pm ON pm.roh = lower(c.party_label)
                        WHERE c.wahl ~ '[0-9]{4}')""" % PARTEI_AW,
        "lieferung": "aw_api_v2",
        "klasse": "stkg:Kandidatur",
        "iri": "kandidatur/{aw_id}",
        "geometrie": None,
        "felder": [
            ("person",      "stkg:hatKandidat", "ref", "person/{person}"),
            ("wahljahr",    "stkg:hatKandidaturWahl", "ref", "wahl/{wahljahr}"),
            ("partei",      "stkg:hatKandidaturPartei", "ref", "partei/{partei}"),
            ("wkr_nr",      "stkg:hatKandidaturWahlkreis", "ref",
             "wahlkreisstand/{wahljahr}_{wkr_nr}"),
            ("liste_id",    "stkg:hatKandidaturLandesliste", "ref",
             "landesliste/{liste_id}_{partei}"),
            ("listenplatz", "stkg:listenplatz", "int"),
            ("mandat_id",   "stkg:fuehrteZuMandat", "ref", "mandat/{mandat_id}"),
        ],
    },
    {


        "name": "fraktionszugehoerigkeit",
        "tabelle": """(SELECT f.mandat_id, f.lfd, a.fraktion_id,
                              f.von, f.bis_geliefert AS bis
                         FROM politiker_innen.fraktion_mitgliedschaft f
                         JOIN (SELECT DISTINCT schreibweise, fraktion_id
                                 FROM politiker_innen.fraktion_alias) a
                           ON a.schreibweise = f.fraktion)""",
        "lieferung": "bt_mdb_stammdaten",
        "klasse": "stkg:Fraktionszugehoerigkeit",
        "iri": "fraktionszugehoerigkeit/{mandat_id}_{lfd}",
        "geometrie": None,
        "felder": [
            ("mandat_id",   "stkg:hatZugehoerigkeitsMandat", "ref",
             "mandat/{mandat_id}"),
            ("fraktion_id", "stkg:hatZugehoerigkeitsFraktion", "ref",
             "fraktion/{fraktion_id}"),
            ("von", "stkg:episodeBeginn", "datum"),
            ("bis", "stkg:episodeEnde", "datum"),
        ],
    },
    {


        "name": "fraktionsfunktion",


        "tabelle": """(SELECT f.mandat_id, f.lfd, f.funktion, f.von,
                              f.bis_geliefert AS bis, m.lfd AS zug_lfd
                         FROM politiker_innen.fraktion_funktion f
                         JOIN politiker_innen.fraktion_mitgliedschaft m
                           ON m.mandat_id = f.mandat_id
                          AND m.fraktion  = f.fraktion)""",
        "lieferung": "bt_mdb_stammdaten",
        "klasse": "stkg:Fraktionsfunktion",
        "iri": "fraktionsfunktion/{mandat_id}_{lfd}",
        "geometrie": None,
        "felder": [
            ("zug_lfd", "stkg:hatFunktionsZugehoerigkeit", "ref",
             "fraktionszugehoerigkeit/{mandat_id}_{zug_lfd}"),
            ("funktion",  "stkg:hatFraktionsrolle", "code", "fraktionsrolle"),
            ("von", "stkg:episodeBeginn", "datum"),
            ("bis", "stkg:episodeEnde", "datum"),
        ],
    },
    {

        "name": "gremienmitgliedschaft",
        "tabelle": """(SELECT aw_id, mandat_id, ausschuss_id
                         FROM politiker_innen.ausschussmitgliedschaft)""",
        "lieferung": "aw_api_v2",
        "klasse": "stkg:Gremienmitgliedschaft",
        "iri": "gremienmitgliedschaft/{aw_id}",
        "geometrie": None,
        "felder": [
            ("mandat_id",    "stkg:hatMitgliedschaftsMandat", "ref",
             "mandat/{mandat_id}"),
            ("ausschuss_id", "stkg:hatGremium", "ref", "gremium/{ausschuss_id}"),
        ],
    },
    {


        "name": "gremienfunktion",
        "tabelle": """(SELECT aw_id, rolle
                         FROM politiker_innen.ausschussmitgliedschaft
                        WHERE rolle IS NOT NULL)""",
        "lieferung": "aw_api_v2",
        "klasse": "stkg:Gremienfunktion",
        "iri": "gremienfunktion/{aw_id}",
        "geometrie": None,
        "felder": [
            ("aw_id", "stkg:hatFunktionsMitgliedschaft", "ref",
             "gremienmitgliedschaft/{aw_id}"),
            ("rolle", "stkg:hatGremienrolle", "code", "gremienrolle"),
        ],
    },
    {


        "name": "amt",
        "tabelle": """(SELECT DISTINCT amt_qid, amt
                         FROM politiker_innen.wikidata_amt
                        WHERE amt_qid <> '')""",
        "lieferung": "wikidata",
        "klasse": "stkg:Amt",
        "iri": "amt/{amt_qid}",
        "geometrie": None,
        "felder": [("amt", "stkg:amtsbezeichnung", "text")],
    },
    {


        "name": "regierungsamt",
        "tabelle": """(SELECT DISTINCT amt_qid FROM politiker_innen.wikidata_amt
                        WHERE amt_qid IN (

                          'Q4970706',
                          'Q504272',
                          'Q568605',
                          'Q22575092',
                          'Q22575628',
                          'Q23016036',
                          'Q30533247',
                          'Q30542236',
                          'Q30533351',
                          'Q30533368',
                          'Q30543192',
                          'Q30543319',
                          'Q30543531',
                          'Q30543924',
                          'Q30544097',
                          'Q30544193',
                          'Q30106113',
                          'Q110090747',
                          'Q518564',

                          'Q19731005',
                          'Q2325058',
                          'Q736559',
                          'Q22703996',
                          'Q30545012'
                        ))""",
        "lieferung": "regierungsamt_zuordnung",
        "klasse": None,
        "iri": "amt/{amt_qid}",
        "geometrie": None,
        "felder": [],
        "fest": [("stkg:istRegierungsamt", '"true"^^xsd:boolean')],
    },
    {


        "name": "amtszeit",


        "tabelle": """(SELECT a.aw_id, a.amt_qid, a.von, k.person,
                              CASE WHEN a.von_genauigkeit = 'tag'
                                   THEN a.von::text END AS von_tag,
                              CASE WHEN a.von_genauigkeit = 'monat'
                                   THEN to_char(a.von,'YYYY-MM') END AS von_monat,
                              CASE WHEN a.von_genauigkeit = 'jahr'
                                   THEN to_char(a.von,'YYYY') END AS von_jahr,
                              CASE WHEN a.bis_genauigkeit = 'tag'
                                   THEN a.bis::text END AS bis_tag,
                              CASE WHEN a.bis_genauigkeit = 'monat'
                                   THEN to_char(a.bis,'YYYY-MM') END AS bis_monat,
                              CASE WHEN a.bis_genauigkeit = 'jahr'
                                   THEN to_char(a.bis,'YYYY') END AS bis_jahr,




                              CASE a.von_genauigkeit
                                WHEN 'jahr'  THEN to_char(a.von,'YYYY')
                                WHEN 'monat' THEN to_char(a.von,'YYYY-MM')
                                ELSE a.von::text END AS von_kennung
                         FROM politiker_innen.wikidata_amt a
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'aw' AND k.kennung = a.aw_id::text
                        WHERE a.von IS NOT NULL AND a.amt_qid <> '')""",
        "lieferung": "wikidata",
        "klasse": "stkg:Amtszeit",
        "iri": "amtszeit/{person}_{amt_qid}_{von_kennung}",
        "geometrie": None,
        "felder": [
            ("person",  "stkg:hatAmtsinhaber", "ref", "person/{person}"),
            ("amt_qid", "stkg:hatAmt",         "ref", "amt/{amt_qid}"),
            ("von_tag",   "stkg:episodeBeginn", "datum"),
            ("von_monat", "stkg:episodeBeginnMonat", "jahrmonat"),
            ("von_jahr",  "stkg:episodeBeginnJahr", "jahr"),
            ("bis_tag",   "stkg:episodeEnde", "datum"),
            ("bis_monat", "stkg:episodeEndeMonat", "jahrmonat"),
            ("bis_jahr",  "stkg:episodeEndeJahr", "jahr"),
        ],
    },
    {


        "name": "parteimitgliedschaft",
        "tabelle": """(SELECT DISTINCT k.person,






                              CASE
                                WHEN s.partei_kurz LIKE 'B%NDNIS 90%' THEN 'gruene'
                                WHEN s.partei_kurz LIKE 'DIE LINKE%'  THEN 'linke_pds'
                                WHEN s.partei_kurz = 'BSW'            THEN 'bsw'
                                ELSE m.partei END AS partei
                         FROM roh_bundestag.stammdaten_mdb s
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'btv' AND k.kennung = s.id
                         LEFT JOIN meta.partei_mapping m
                           ON lower(m.partei_roh) = lower(s.partei_kurz)
                          AND m.verfahren <> 'keine_partei'
                        WHERE s.partei_kurz IS NOT NULL
                          AND s.partei_kurz <> 'Plos')""",
        "lieferung": "bt_mdb_stammdaten",
        "klasse": "stkg:Parteimitgliedschaft",
        "iri": "parteimitgliedschaft/{person}_{partei}",
        "geometrie": None,
        "felder": [
            ("person", "stkg:hatParteimitglied", "ref", "person/{person}"),
            ("partei", "stkg:hatMitgliedschaftsPartei", "ref", "partei/{partei}"),
        ],
    },
    {


        "name": "nachfolge",


        "tabelle": """(SELECT n.wp, n.lfd, n.ausgeschieden_am,
                              n.eingetreten_am, n.verstorben,
                              n.nachfolger_benannt,
                              mv.aw_id AS vorgaenger_mandat,
                              mn.aw_id AS nachfolger_mandat
                         FROM politiker_innen.nachfolge n
                         LEFT JOIN politiker_innen.mandat mv
                           ON mv.politician_id = n.vorgaenger_aw_id
                          AND mv.legislatur = CASE n.wp
                                WHEN 18 THEN 'Bundestag 2013 - 2017'
                                WHEN 19 THEN 'Bundestag 2017 - 2021'
                                WHEN 20 THEN 'Bundestag 2021 - 2025' END
                         LEFT JOIN politiker_innen.mandat mn
                           ON mn.politician_id = n.nachfolger_aw_id
                          AND mn.legislatur = CASE n.wp
                                WHEN 18 THEN 'Bundestag 2013 - 2017'
                                WHEN 19 THEN 'Bundestag 2017 - 2021'
                                WHEN 20 THEN 'Bundestag 2021 - 2025' END)""",
        "lieferung": "bt_ausgeschiedene",
        "klasse": "stkg:Nachfolge",
        "iri": "nachfolge/{wp}_{lfd}",
        "geometrie": None,
        "felder": [
            ("vorgaenger_mandat",  "stkg:hatVorgaengermandat", "ref",
             "mandat/{vorgaenger_mandat}"),
            ("nachfolger_mandat",  "stkg:hatNachfolgemandat", "ref",
             "mandat/{nachfolger_mandat}"),


            ("eingetreten_am",     "stkg:ereignisDatum",   "datum"),
            ("ausgeschieden_am",   "stkg:ausscheidedatum", "datum"),
            ("verstorben",         "stkg:ausgeschiedenDurchTod", "bool"),
            ("nachfolger_benannt", "stkg:nachfolgerBenannt", "bool"),
        ],
    },
]


def kopf(lieferung):
    return "\n".join([
        "# Funktionen der Lieferung %s" % lieferung,
        "#",
        "# ERZEUGT von 03_load_db/graph/export_funktionen.py.",
        "",
    ] + ["@prefix %s: <%s> ." % (pr, u) for pr, u in PRAEFIXE]
      + ["", "%s {" % iri("lieferung/%s" % lieferung), ""])


def tripel(bestand, z):
    pfad_teil = bestand["iri"].format(**z)
    if UNGUELTIG.search(pfad_teil):
        KAPUTT.add((bestand["name"], pfad_teil[:70]))
        return None
    zeilen = []
    if bestand["klasse"]:
        zeilen.append("        a  %s" % bestand["klasse"])

    for praedikat, objekt in bestand.get("fest", []):
        zeilen.append("        %-30s %s" % (praedikat, objekt))
    for feld in bestand["felder"]:
        spalte, praedikat, art = feld[0], feld[1], feld[2]
        wert = z.get(spalte)
        if wert is None or str(wert).strip() == "":
            continue
        if art == "ref":


            try:
                ziel = feld[3].format(**z)
            except KeyError:
                continue
            if any(("{%s}" % s) in feld[3] and not str(z.get(s, "")).strip()
                   for s in re.findall(r"\{(\w+)\}", feld[3])):
                continue
            if UNGUELTIG.search(ziel):
                KAPUTT.add((bestand["name"] + " -> " + spalte, ziel[:70]))
                continue
            objekt = iri(ziel)
        elif art == "code":
            objekt = code_iri(feld[3], wert)
            if objekt is None:
                continue
        elif art == "jahr":
            objekt = '"%s"^^xsd:gYear' % str(wert).strip()[:4]
        elif art == "jahrmonat":
            objekt = '"%s"^^xsd:gYearMonth' % str(wert).strip()[:7]
        elif art == "bool":
            objekt = '"%s"^^xsd:boolean' % (
                "true" if str(wert).strip().lower() in ("true", "t", "1")
                else "false")
        else:
            objekt = literal(wert, art)
        zeilen.append("        %-30s %s" % (praedikat, objekt))
    if not zeilen:
        return None
    return "    %s\n" % iri(pfad_teil) + " ;\n".join(zeilen) + " .\n"


def baue(namen, max_mb):
    global BEKANNT
    BEKANNT = lies_schema_kennungen()
    print("  %d Codelisten-Kennungen aus dem Schema gelesen" % len(BEKANNT))

    pfade.pruefe(AUSGABE)
    tmp = AUSGABE / "_export.csv"
    grenze = max_mb * 1024 * 1024 if max_mb else 0

    offen = {}
    teile = defaultdict(list)

    def oeffne(lieferung, nr):
        if nr == 1:
            for alt in AUSGABE.glob("%s_mod07*.trig" % lieferung):
                alt.unlink()
        pfad = AUSGABE / ("%s_mod07.trig" % lieferung if nr == 1
                          else "%s_mod07_%02d.trig" % (lieferung, nr))
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
            e[1] += 1
            e[0] = oeffne(lieferung, e[1])
            e[2] = 0
        e[0].write(text)
        e[2] += len(text)

    gezaehlt = defaultdict(int)
    for bestand in BESTAENDE:
        if namen and bestand["name"] not in namen:
            continue
        if not bestand["felder"] and not bestand["klasse"] \
                and not bestand.get("fest"):
            continue
        bestand.setdefault("lieferung_spalte", None)
        run_copy(sql_fuer(bestand, None), tmp)
        with tmp.open(encoding="utf-8", newline="") as fh:
            for z in _csv.DictReader(fh):
                text = tripel(bestand, z)
                if text:
                    schreibe(bestand["lieferung"], text)
                    gezaehlt[bestand["name"]] += 1
        print("  %-26s %8d Bloecke" % (bestand["name"], gezaehlt[bestand["name"]]))

    for lieferung, e in offen.items():
        e[0].write("}\n")
        e[0].close()
    tmp.unlink(missing_ok=True)

    if KAPUTT:
        print("\n  UNGUELTIGE KENNUNGEN -- nicht geschrieben:")
        for name, wert in sorted(KAPUTT)[:20]:
            print("    %-30s %s" % (name, wert))
        raise SystemExit("%d ungueltige Kennungen." % len(KAPUTT))

    if UNBEKANNT:
        print("\n  UNBEKANNTE CODEWERTE -- nicht geschrieben:")
        for liste, wert in sorted(UNBEKANNT):
            print("    %-18s %s" % (liste, wert))

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
            print("  %-26s %s" % (b["name"], b["tabelle"].split("\n")[0][:52]))
        return
    baue(set(a.bestand), a.max_mb)


if __name__ == "__main__":
    main()
