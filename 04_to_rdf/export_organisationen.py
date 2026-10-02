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
from export_raum import (PRAEFIXE, txt, iri, literal,
                         sql_fuer, run_copy)

AUSGABE = pfade.ORGANISATIONEN
SCHEMA_09 = HIER.parents[0] / "schema" / "module" / "09_codelisten.ttl"


def slug(s):
    s = (s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
          .replace("ß", "ss").replace("Ä", "Ae").replace("Ö", "Oe")
          .replace("Ü", "Ue"))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return re.sub(r"_+", "_", s)


LISTEN = {
    "fraktionsart":         "fraktionsart",
    "thema":                "thema",
    "zuordnungsverfahren":  "zuordnungsverfahren",
    "kategorienart":        "kategorienart",
}

BEKANNT = set()
UNBEKANNT = set()
KAPUTT = set()
UNGUELTIG = re.compile(r'[\s<>"{}|\\^`]')


def lies_schema_kennungen():
    return set(re.findall(r"^(stkg:[a-z0-9_]+) a stkg:",
                          SCHEMA_09.read_text(encoding="utf-8"), re.M))


def code_iri(liste, wert):
    if wert is None or str(wert).strip() == "":
        return None
    k = "stkg:%s_%s" % (LISTEN[liste], slug(str(wert).strip()))
    if k not in BEKANNT:
        UNBEKANNT.add((liste, str(wert)))
        return None
    return k


MERKMALE = {
    "codieranteil": (
        "Anteil codierter Sätze",
        "Anteil der Sätze eines Wahlprogramms, die das Manifesto Project " "einer bestimmten inhaltlichen Kategorie zugeordnet hat, in Prozent " "aller codierten Sätze des Programms."),
    "stimmenanteil": (
        "Stimmenanteil der Partei",
        "Anteil der auf die Partei entfallenen Stimmen bei der Wahl, zu der " "das Programm gehört, in Prozent. Vom Manifesto Project erhoben."),
    "sitze": (
        "Sitze der Partei",
        "Zahl der Sitze, die die Partei bei dieser Wahl errungen hat, laut " "Manifesto Project."),
    "rile": (
        "Rile-Position",
        "Links-Rechts-Position des Programms nach der Standardskala des " "Manifesto Project. Berechnet aus den Anteilen der Kategorien, die " "der rechten und der linken Seite zugeordnet sind."),
    "planeco": (
        "Planwirtschaftliche Position",
        "Skala des Manifesto Project zur wirtschaftspolitischen Ausrichtung " "in Richtung Planung."),
    "markeco": (
        "Marktwirtschaftliche Position",
        "Skala des Manifesto Project zur wirtschaftspolitischen Ausrichtung " "in Richtung Markt."),
    "welfare": (
        "Position zum Wohlfahrtsstaat",
        "Skala des Manifesto Project zur Haltung gegenüber sozialstaatlichen " "Leistungen."),
    "intpeace": (
        "Position zu internationalem Frieden",
        "Skala des Manifesto Project zur aussenpolitischen Ausrichtung."),
    "anteil_uncodiert": (
        "Anteil uncodierter Sätze",
        "Anteil der Sätze eines Wahlprogramms, die keiner inhaltlichen " "Kategorie zugeordnet werden konnten, in Prozent. Die Quelle nennt " "diesen Anteil und nicht die Zahl der Sätze; sie ergibt sich erst " "aus der Multiplikation mit der Gesamtzahl."),
}


WP_NUMMER = """CASE label
        WHEN 'Bundestag 2005 - 2009' THEN 16
        WHEN 'Bundestag 2009 - 2013' THEN 17
        WHEN 'Bundestag 2013 - 2017' THEN 18
        WHEN 'Bundestag 2017 - 2021' THEN 19
        WHEN 'Bundestag 2021 - 2025' THEN 20
        WHEN 'Bundestag 2025 - 2029' THEN 21
        END"""


MANIFESTO_FILTER = ("p.land_code::text = '41' AND p.wahl_jahrmonat >= 199000")


GRUNDLAGE = """(SELECT DISTINCT x.liste_id, x.partei FROM (

                  SELECT c.liste_id, m.partei
                    FROM politiker_innen.kandidatur c
                    JOIN meta.partei_mapping m
                      ON lower(m.partei_roh) = lower(c.party_label)
                     AND m.verfahren <> 'keine_partei'
                     AND m.lieferung_ids @> ARRAY['aw_api_v2']
                   WHERE c.liste_id IS NOT NULL AND c.party_label IS NOT NULL
                  UNION





                  SELECT md.liste_id, m.partei
                    FROM politiker_innen.mandat md
                    JOIN politiker_innen.kandidatur ka ON ka.mandat_id = md.aw_id
                    JOIN meta.partei_mapping m
                      ON lower(m.partei_roh) = lower(ka.party_label)
                     AND m.verfahren <> 'keine_partei'
                     AND m.lieferung_ids @> ARRAY['aw_api_v2']
                   WHERE md.liste_id IS NOT NULL
                ) x)"""


BESTAENDE = [
    {

        "name": "wahlperiode",
        "tabelle": """(SELECT %s AS wp, label,
                              substring(label from '([0-9]{4}) - ')::int AS von_jahr,
                              substring(label from ' - ([0-9]{4})')::int AS bis_jahr
                         FROM politiker_innen.raw_parliament_periods
                        WHERE data->>'type' = 'legislature')""" % WP_NUMMER,
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": "stkg:Wahlperiode",
        "iri": "wahlperiode/{wp}",
        "geometrie": None,
        "felder": [
            ("wp",    "stkg:wahlperiodennummer",     "int"),
            ("label", "rdfs:label",                    "text"),
        ],
    },
    {


        "name": "wahl",
        "tabelle": """(SELECT DISTINCT (p.wahl_jahrmonat / 100) AS wahljahr,
                              p.wahltag
                         FROM parteien.manifesto_programm p
                        WHERE %s)""" % MANIFESTO_FILTER,
        "lieferung": "manifesto_mpds_2025a",
        "lieferung_spalte": None,
        "klasse": "stkg:Wahl",
        "iri": "wahl/{wahljahr}",
        "geometrie": None,
        "felder": [
            ("wahltag",  "stkg:ereignisDatum", "datum"),
            ("wahljahr", "rdfs:label",         "text"),
        ],
    },
    {


        "name": "partei_aw",
        "tabelle": """(SELECT p.aw_id, p.label, p.kurzname, p.langname,
                              CASE p.aw_id
                                WHEN 1   THEN 'spd'
                                WHEN 2   THEN 'cdu'
                                WHEN 3   THEN 'csu'
                                WHEN 4   THEN 'fdp'
                                WHEN 5   THEN 'gruene'
                                WHEN 8   THEN 'linke_pds'
                                WHEN 9   THEN 'afd'
                                WHEN 229 THEN 'bsw'
                              END AS partei
                         FROM politiker_innen.partei p
                        WHERE p.aw_id IN (1,2,3,4,5,8,9,229))""",
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": "stkg:Partei",
        "iri": "partei/{partei}",
        "geometrie": None,
        "felder": [
            ("label",    "stkg:organisationsbezeichnung", "text"),
            ("kurzname", "stkg:kurzbezeichnung",          "text"),
            ("langname", "stkg:langbezeichnung",          "text"),
        ],
    },
    {


        "name": "fraktion_partei",
        "tabelle": """(SELECT k.fraktion_id, x.partei
                         FROM politiker_innen.fraktion_kanonisch k
                         CROSS JOIN LATERAL (
                           SELECT unnest(CASE k.fraktion_id
                             WHEN 'AFD'     THEN ARRAY['afd']
                             WHEN 'BSW'     THEN ARRAY['bsw']
                             WHEN 'CDU/CSU' THEN ARRAY['cdu','csu']
                             WHEN 'FDP'     THEN ARRAY['fdp']
                             WHEN 'GRUENE'  THEN ARRAY['gruene']
                             WHEN 'LINKE'   THEN ARRAY['linke_pds']
                             WHEN 'SPD'     THEN ARRAY['spd']
                             ELSE ARRAY[]::text[] END) AS partei) x)""",
        "lieferung": "bt_mdb_stammdaten",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "fraktion/{fraktion_id}",
        "geometrie": None,
        "felder": [("partei", "stkg:gehoertZuPartei", "ref", "partei/{partei}")],
    },
    {


        "name": "fraktion",
        "tabelle": """(SELECT fraktion_id, name, partei
                         FROM politiker_innen.fraktion_kanonisch)""",
        "lieferung": "bt_mdb_stammdaten",
        "lieferung_spalte": None,
        "klasse": "stkg:Fraktion",
        "iri": "fraktion/{fraktion_id}",
        "geometrie": None,


        "felder": [
            ("name", "stkg:organisationsbezeichnung", "text"),
        ],
    },
    {


        "name": "fraktionsstand",
        "tabelle": """(SELECT fraktion_id, wahlperiode, art, von, bis,
                              mitglieder, amtliche_bezeichnung
                         FROM politiker_innen.fraktion_zeitraum)""",
        "lieferung": "bt_mdb_stammdaten",
        "lieferung_spalte": None,
        "klasse": "stkg:Fraktionsstand",


        "iri": "fraktionsstand/{fraktion_id}_{wahlperiode}_{von}",
        "geometrie": None,
        "felder": [
            ("fraktion_id",  "stkg:istStandDerFraktion", "ref",
             "fraktion/{fraktion_id}"),
            ("wahlperiode",  "stkg:hatFraktionsWahlperiode", "ref",
             "wahlperiode/{wahlperiode}"),
            ("art",          "stkg:hatFraktionsart", "code", "fraktionsart"),
            ("mitglieder",   "stkg:mitgliederzahl",  "int"),
            ("amtliche_bezeichnung", "stkg:amtlicheFraktionsbezeichnung", "text"),
            ("von",          "stkg:gueltigVon",      "datum"),
            ("bis",          "stkg:gueltigBis",      "datum"),
        ],
    },
    {
        "name": "fraktionsschreibweise",
        "tabelle": """(SELECT fraktion_id, quelle, schreibweise,
                              row_number() OVER (PARTITION BY fraktion_id
                                                 ORDER BY quelle, schreibweise) AS lfd
                         FROM politiker_innen.fraktion_alias)""",
        "lieferung": "bt_mdb_stammdaten",
        "lieferung_spalte": None,
        "klasse": "stkg:Fraktionsschreibweise",
        "iri": "fraktionsschreibweise/{fraktion_id}_{lfd}",
        "geometrie": None,
        "felder": [
            ("fraktion_id",  "stkg:betrifftFraktion", "ref", "fraktion/{fraktion_id}"),
            ("schreibweise", "stkg:schreibweise",     "text"),
            ("quelle",       "stkg:schreibweisenquelle", "text"),
        ],
    },
    {


        "name": "organisation",
        "tabelle": "politiker_innen.organisation",
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": "stkg:Organisation",
        "iri": "organisation/{aw_id}",
        "geometrie": None,
        "felder": [
            ("name",  "stkg:organisationsbezeichnung", "text"),
            ("stadt", "stkg:organisationssitz",        "text"),
            ("land",  "stkg:organisationsland",        "text"),
        ],
    },
    {
        "name": "organisation_thema",
        "tabelle": """(SELECT organisation_id, thema
                         FROM politiker_innen.organisation_thema
                        WHERE thema IS NOT NULL)""",
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "organisation/{organisation_id}",
        "geometrie": None,
        "felder": [("thema", "stkg:hatOrganisationsthema", "code", "thema")],
    },
    {

        "name": "gremium",
        "tabelle": """(SELECT a.aw_id, a.titel, a.url,
                              CASE a.legislatur
                                WHEN 'Bundestag 2013 - 2017' THEN 18
                                WHEN 'Bundestag 2017 - 2021' THEN 19
                                WHEN 'Bundestag 2021 - 2025' THEN 20
                              END AS wp
                         FROM politiker_innen.ausschuss a)""",
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": "stkg:Gremium",
        "iri": "gremium/{aw_id}",
        "geometrie": None,
        "felder": [
            ("titel", "stkg:organisationsbezeichnung", "text"),
            ("url",   "stkg:gremiumsadresse",          "text"),
            ("wp",    "stkg:hatGremiumsWahlperiode", "ref", "wahlperiode/{wp}"),
        ],
    },
    {


        "name": "landesliste",
        "tabelle": """(SELECT g.liste_id, g.partei, l.name, j.land_name
                         FROM %s g
                         JOIN politiker_innen.landesliste l ON l.aw_id = g.liste_id
                         LEFT JOIN politiker_innen.liste_je_land j
                           ON j.liste_id = g.liste_id)""" % GRUNDLAGE,
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": "stkg:Landesliste",
        "iri": "landesliste/{liste_id}_{partei}",
        "geometrie": None,
        "felder": [
            ("name",      "stkg:listenbezeichnung",  "text"),
            ("land_name", "stkg:listenland",         "text"),
            ("partei",    "stkg:hatListenPartei", "ref", "partei/{partei}"),
        ],
    },
    {


        "name": "wahl_wahlperiode",
        "tabelle": """(SELECT DISTINCT (p.wahl_jahrmonat / 100) AS wahljahr,
                              CASE (p.wahl_jahrmonat / 100)
                                WHEN 2005 THEN 16 WHEN 2009 THEN 17
                                WHEN 2013 THEN 18 WHEN 2017 THEN 19
                                WHEN 2021 THEN 20 WHEN 2025 THEN 21
                              END AS wp
                         FROM parteien.manifesto_programm p
                        WHERE %s AND (p.wahl_jahrmonat / 100) >= 2005)""" % MANIFESTO_FILTER,
        "lieferung": "manifesto_mpds_2025a",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "wahl/{wahljahr}",
        "geometrie": None,
        "felder": [("wp", "stkg:hatWahlperiode", "ref", "wahlperiode/{wp}")],
    },
    {


        "name": "landesliste_wahl",
        "tabelle": """(SELECT g.liste_id, g.partei,
                              substring(l.wahl from '([0-9]{4})')::int AS wahljahr
                         FROM %s g
                         JOIN politiker_innen.landesliste l ON l.aw_id = g.liste_id
                        WHERE l.wahl ~ '[0-9]{4}')""" % GRUNDLAGE,
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "landesliste/{liste_id}_{partei}",
        "geometrie": None,
        "felder": [("wahljahr", "stkg:hatListenWahl", "ref", "wahl/{wahljahr}")],
    },
    {


        "name": "landesliste_land",
        "tabelle": """(SELECT g.liste_id, g.partei, ls.ags, s.datum AS wahltag
                         FROM %s g
                         JOIN politiker_innen.landesliste l ON l.aw_id = g.liste_id
                         JOIN politiker_innen.liste_je_land j ON j.liste_id = g.liste_id
                         JOIN (SELECT DISTINCT ags, gen FROM raum.landstand) ls
                           ON ls.gen = j.land_name
                         JOIN zeit.stichtag s
                           ON s.art = 'wahltag'
                          AND extract(year from s.datum)::int
                              = substring(l.wahl from '([0-9]{4})')::int)""" % GRUNDLAGE,
        "lieferung": "aw_api_v2",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "landesliste/{liste_id}_{partei}",
        "geometrie": None,
        "felder": [("ags", "stkg:hatListenBundesland", "ref",
                    "bundesland/{ags}_{wahltag}")],
    },
    {


        "name": "wahlprogramm_partei",
        "tabelle": """(SELECT p.id_perm, g.gerda_partei
                         FROM parteien.manifesto_programm p
                         JOIN parteien.manifesto_gerda g
                           ON g.manifesto_code = p.partei_code
                          AND g.wahl_jahrmonat = p.wahl_jahrmonat
                        WHERE %s)""" % MANIFESTO_FILTER,
        "lieferung": "manifesto_mpds_2025a",
        "lieferung_spalte": None,
        "klasse": None,
        "iri": "wahlprogramm/{id_perm}",
        "geometrie": None,
        "felder": [("gerda_partei", "stkg:hatProgrammPartei", "ref",
                    "partei/{gerda_partei}")],
    },
    {

        "name": "themenkategorie",
        "tabelle": """(SELECT code, art, hauptkategorie, domaene,
                              domaene_name, bezeichnung, rile_seite,
                              gegenkategorie, zaehlt_als_uncodiert
                         FROM parteien.manifesto_kategorie)""",
        "lieferung": "manifesto_mpds_2025a",
        "lieferung_spalte": None,
        "klasse": "stkg:Themenkategorie",
        "iri": "themenkategorie/{code}",
        "geometrie": None,
        "felder": [
            ("bezeichnung",    "stkg:kategoriebezeichnung", "text"),
            ("art",            "stkg:hatKategorienart", "code", "kategorienart"),
            ("domaene",        "stkg:gehoertZuDomaene",  "ref", "domaene/{domaene}"),
            ("hauptkategorie", "stkg:hatOberkategorie",  "ref",
             "themenkategorie/{hauptkategorie}"),
            ("gegenkategorie", "stkg:hatGegenkategorie", "ref",
             "themenkategorie/{gegenkategorie}"),
            ("rile_seite",     "stkg:hatRileSeite",      "ref",
             "rileseite/{rile_seite}"),
            ("zaehlt_als_uncodiert", "stkg:zaehltAlsUncodiert", "bool"),
        ],
    },
    {
        "name": "domaene",
        "tabelle": """(SELECT DISTINCT domaene, domaene_name
                         FROM parteien.manifesto_kategorie
                        WHERE domaene IS NOT NULL)""",
        "lieferung": "manifesto_mpds_2025a",
        "lieferung_spalte": None,
        "klasse": "stkg:Domaene",
        "iri": "domaene/{domaene}",
        "geometrie": None,
        "felder": [("domaene_name", "stkg:kategoriebezeichnung", "text")],
    },
    {
        "name": "rileseite",
        "tabelle": """(SELECT DISTINCT rile_seite
                         FROM parteien.manifesto_kategorie
                        WHERE rile_seite IS NOT NULL)""",
        "lieferung": "manifesto_mpds_2025a",
        "lieferung_spalte": None,
        "klasse": "stkg:RileSeite",
        "iri": "rileseite/{rile_seite}",
        "geometrie": None,
        "felder": [("rile_seite", "stkg:kategoriebezeichnung", "text")],
    },
    {

        "name": "wahlprogramm",
        "tabelle": """(SELECT p.id_perm, p.partei_name, p.partei_kuerzel,
                              p.programmtyp::text AS programmtyp,
                              p.korpusversion, p.saetze, p.uncodiert,
                              (p.wahl_jahrmonat / 100) AS wahljahr,
                              p.partei_code
                         FROM parteien.manifesto_programm p
                        WHERE %s)""" % MANIFESTO_FILTER,
        "lieferung": "manifesto_mpds_2025a",
        "lieferung_spalte": None,
        "klasse": "stkg:Wahlprogramm",
        "iri": "wahlprogramm/{id_perm}",
        "geometrie": None,
        "felder": [
            ("id_perm",       "stkg:programmkennung", "text"),
            ("partei_name",   "stkg:programmpartei", "text"),
            ("programmtyp",   "stkg:programmtyp",   "text"),
            ("korpusversion", "stkg:codierfassung", "text"),
            ("saetze",        "stkg:saetzeGesamt",  "int"),
            ("wahljahr",      "stkg:hatProgrammWahl", "ref", "wahl/{wahljahr}"),
        ],
    },
]


BEOBACHTUNGEN = [

    {
        "name": "beob_codieranteil",
        "merkmal": "codieranteil",
        "tabelle": """(SELECT a.id_perm, a.code, a.anteil
                         FROM parteien.manifesto_anteil a
                         JOIN parteien.manifesto_programm p
                           ON p.id_perm = a.id_perm
                        WHERE %s)""" % MANIFESTO_FILTER,
        "iri": "beobachtung/codieranteil/{id_perm}_{code}",
        "wert": "anteil",
        "kanten": [("stkg:hatProgrammbezug", "wahlprogramm/{id_perm}"),
                   ("stkg:giltFuer",         "themenkategorie/{code}")],
    },
] + [
    {
        "name": "beob_" + spalte,


        "merkmal": "anteil_uncodiert" if spalte == "uncodiert" else spalte,
        "tabelle": """(SELECT p.id_perm, p.%s AS wert
                         FROM parteien.manifesto_programm p
                        WHERE %s AND p.%s IS NOT NULL)""" % (spalte, MANIFESTO_FILTER, spalte),
        "iri": "beobachtung/%s/{id_perm}" % spalte,
        "wert": "wert",
        "kanten": [("stkg:hatProgrammbezug", "wahlprogramm/{id_perm}")],
    }
    for spalte in ("stimmenanteil", "sitze", "rile", "planeco", "markeco",
                   "welfare", "intpeace", "uncodiert")
]

LIEFERUNG_BEOB = "manifesto_mpds_2025a"


def merkmal_bloecke(gebraucht):
    zeilen = []
    for schluessel in sorted(gebraucht):
        bez, definition = MERKMALE[schluessel]
        zeilen.append(
            "    %s\n        a  stkg:Merkmal ;\n" "        stkg:merkmalsbezeichnung %s ;\n" "        stkg:merkmalsdefinition  %s .\n"
            % (iri("merkmal/%s/%s" % (LIEFERUNG_BEOB, schluessel)),
               txt(bez), txt(definition)))
    return zeilen


def kopf(lieferung):
    return "\n".join([
        "# Organisationen der Lieferung %s" % lieferung,
        "#",
        "# ERZEUGT von 03_load_db/graph/export_organisationen.py.",
        "",
    ] + ["@prefix %s: <%s> ." % (pr, u) for pr, u in PRAEFIXE]
      + ["", "%s {" % iri("lieferung/%s" % lieferung), ""])


def tripel(bestand, z):
    z_iri = dict(z)
    pfad_teil = bestand["iri"].format(**z_iri)
    if UNGUELTIG.search(pfad_teil):
        KAPUTT.add((bestand["name"], pfad_teil[:70]))
        return None
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
        elif art == "bool":
            objekt = '"%s"^^xsd:boolean' % (
                "true" if str(wert).strip().lower() in ("true", "t", "1")
                else "false")
        else:
            objekt = literal(wert, art)
        zeilen.append("        %-28s %s" % (praedikat, objekt))
    if not zeilen:
        return None
    return "    %s\n" % iri(pfad_teil) + " ;\n".join(zeilen) + " .\n"


def beobachtung_tripel(b, z):
    pfad_teil = b["iri"].format(**z)
    if UNGUELTIG.search(pfad_teil):
        KAPUTT.add((b["name"], pfad_teil[:70]))
        return None
    wert = z.get(b["wert"])
    if wert is None or str(wert).strip() == "":
        return None
    zeilen = ["        a  stkg:Beobachtung",
              "        %-28s %s" % ("stkg:hatMerkmal",
                                    iri("merkmal/%s/%s" % (LIEFERUNG_BEOB,
                                                           b["merkmal"])))]
    for praedikat, muster in b["kanten"]:
        ziel = muster.format(**z)
        if UNGUELTIG.search(ziel):
            KAPUTT.add((b["name"] + " -> " + praedikat, ziel[:70]))
            continue
        zeilen.append("        %-28s %s" % (praedikat, iri(ziel)))
    zeilen.append("        %-28s %s" % ("stkg:wert", literal(wert, "dez")))
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
            for alt in AUSGABE.glob("%s_mod06*.trig" % lieferung):
                alt.unlink()
        pfad = AUSGABE / ("%s_mod06.trig" % lieferung if nr == 1
                          else "%s_mod06_%02d.trig" % (lieferung, nr))
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
        run_copy(sql_fuer(bestand, None), tmp)
        with tmp.open(encoding="utf-8", newline="") as fh:
            for z in _csv.DictReader(fh):
                lieferung = (z.get(bestand["lieferung_spalte"]) or "").strip() \
                    if bestand["lieferung_spalte"] else bestand["lieferung"]
                text = tripel(bestand, z)
                if text:
                    schreibe(lieferung, text)
                    gezaehlt[bestand["name"]] += 1
        print("  %-24s %8d Bloecke" % (bestand["name"], gezaehlt[bestand["name"]]))

    gebraucht = set()
    for b in BEOBACHTUNGEN:
        if namen and b["name"] not in namen:
            continue
        run_copy("SELECT * FROM %s x" % b["tabelle"], tmp)
        with tmp.open(encoding="utf-8", newline="") as fh:
            for z in _csv.DictReader(fh):
                text = beobachtung_tripel(b, z)
                if text:
                    schreibe(LIEFERUNG_BEOB, text)
                    gezaehlt[b["name"]] += 1
                    gebraucht.add(b["merkmal"])
        print("  %-24s %8d Bloecke" % (b["name"], gezaehlt[b["name"]]))

    for block in merkmal_bloecke(gebraucht):
        schreibe(LIEFERUNG_BEOB, block)

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
            print("    %-20s %s" % (liste, wert))

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
            print("  %-24s %s" % (b["name"], b["tabelle"].split("\n")[0][:56]))
        for b in BEOBACHTUNGEN:
            print("  %-24s Beobachtung, Merkmal %s" % (b["name"], b["merkmal"]))
        return
    baue(set(a.bestand), a.max_mb)


if __name__ == "__main__":
    main()
