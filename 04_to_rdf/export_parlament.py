import argparse
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from export_raum import (BASIS, PRAEFIXE, txt, iri, literal,
                         spalten_von, sql_fuer, run_copy)

AUSGABE = pfade.PARLAMENT
SCHEMA_09 = HIER.parents[0] / "schema" / "module" / "09_codelisten.ttl"


def slug(s):
    s = (s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
          .replace("ß", "ss").replace("Ä", "Ae").replace("Ö", "Oe")
          .replace("Ü", "Ue"))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return re.sub(r"_+", "_", s)


LISTEN = {
    "rednerrolle":       "rednerrolle",
    "reaktionsart":      "reaktion",
    "urheberart":        "urheberart",
    "urheberumfang":     "urheberumfang",
    "votum":             "votum",
    "abwesenheitsgrund": "abwesenheitsgrund",
    "vorgangstyp":    "vorgangstyp",
    "beratungsstand": "beratungsstand",
    "sachgebiet":     "sachgebiet",
    "aktivitaetsart": "aktivitaetsart",
}

BEKANNT = set()
UNBEKANNT = set()
KAPUTT = set()


OHNE_LIEFERUNG = set()


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


OHNE_18_20 = ("kommentar_id NOT IN (SELECT kommentar_id " "FROM parlamentsarbeit.kommentar WHERE protokoll_nr = '18/20')")

BESTAENDE = [
    {
        "name": "vorgang",
        "tabelle": "parlamentsarbeit.vorgang",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Vorgang",
        "iri": "vorgang/{vorgang_id}",
        "geometrie": None,
        "felder": [
            ("titel",           "stkg:vorgangstitel",         "text"),
            ("datum",           "stkg:ereignisDatum",         "datum"),
            ("vorgangstyp",     "stkg:hatVorgangstyp",        "code", "vorgangstyp"),
            ("beratungsstand",  "stkg:hatBeratungsstand",     "code", "beratungsstand"),
            ("wahlperiode",     "stkg:hatVorgangsWahlperiode", "ref",
             "wahlperiode/{wahlperiode}"),
        ],
    },
    {


        "name": "deskriptor",
        "tabelle": """(SELECT DISTINCT name, typ FROM parlamentsarbeit.vorgang_deskriptor
                       UNION
                       SELECT DISTINCT name, typ FROM parlamentsarbeit.aktivitaet_deskriptor)""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Deskriptor",
        "iri": "deskriptor/{name}",
        "geometrie": None,
        "felder": [
            ("name", "stkg:deskriptorbezeichnung", "text"),
            ("typ",  "stkg:hatDeskriptortyp",      "deskriptortyp"),
        ],
    },
    {
        "name": "vorgang_deskriptor",
        "tabelle": "parlamentsarbeit.vorgang_deskriptor",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "vorgang/{vorgang_id}",
        "geometrie": None,
        "felder": [("name", "stkg:hatDeskriptor", "ref",
                    "deskriptor/{name}")],
    },
    {

        "name": "drucksache",
        "tabelle": "parlamentsarbeit.drucksache",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Drucksache",
        "iri": "drucksache/{drucksache_id}",
        "geometrie": None,
        "felder": [
            ("titel",          "stkg:dokumenttitel",     "text"),
            ("dokumentnummer", "stkg:drucksachennummer", "text"),
            ("datum",          "stkg:ereignisDatum",     "datum"),
            ("pdf_url",        "stkg:volltextadresse",   "text"),
        ],
    },
    {


        "name": "drucksache_vorgang",
        "tabelle": """(SELECT d.vorgang_id, d.drucksache_id
                         FROM parlamentsarbeit.drucksache_vorgang d
                        WHERE EXISTS (SELECT 1 FROM parlamentsarbeit.vorgang v
                                       WHERE v.vorgang_id = d.vorgang_id))""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "vorgang/{vorgang_id}",
        "geometrie": None,
        "felder": [("drucksache_id", "stkg:hatVorgangsDokument", "ref",
                    "drucksache/{drucksache_id}")],
    },
    {
        "name": "vorgangsposition",
        "tabelle": "parlamentsarbeit.vorgangsposition",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Vorgangsposition",
        "iri": "vorgangsposition/{position_id}",
        "geometrie": None,
        "felder": [
            ("vorgangsposition", "stkg:positionsbezeichnung", "text"),
            ("datum",            "stkg:ereignisDatum",        "datum"),


            ("vorgang_id",       "stkg:hatPositionsVorgang",  "ref",
             "vorgang/{vorgang_id}"),
        ],
    },
    {


        "name": "vorgangsposition_urheber",
        "tabelle": """(SELECT position_id, bezeichnung, einbringer,
                              row_number() OVER (PARTITION BY position_id
                                                 ORDER BY bezeichnung) AS lfd
                         FROM parlamentsarbeit.vorgangsposition_urheber)""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Positionsurheber",
        "iri": "positionsurheber/{position_id}_{lfd}",
        "geometrie": None,
        "felder": [
            ("bezeichnung", "stkg:urheberbezeichnung", "text"),
            ("einbringer",  "stkg:einbringer",         "text"),
        ],
    },
    {
        "name": "position_urheber_kante",
        "tabelle": """(SELECT position_id,
                              row_number() OVER (PARTITION BY position_id
                                                 ORDER BY bezeichnung) AS lfd
                         FROM parlamentsarbeit.vorgangsposition_urheber)""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "vorgangsposition/{position_id}",
        "geometrie": None,
        "felder": [("lfd", "stkg:hatPositionsurheber", "ref",
                    "positionsurheber/{position_id}_{lfd}")],
    },
    {


        "name": "drucksache_urheber",
        "tabelle": """(SELECT drucksache_id, bezeichnung, einbringer,
                              row_number() OVER (PARTITION BY drucksache_id
                                                 ORDER BY bezeichnung) AS lfd
                         FROM parlamentsarbeit.drucksache_urheber)""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Dokumenturheber",
        "iri": "dokumenturheber/{drucksache_id}_{lfd}",
        "geometrie": None,
        "felder": [
            ("bezeichnung", "stkg:urheberbezeichnung", "text"),
            ("einbringer",  "stkg:einbringer",         "text"),
        ],
    },
    {
        "name": "drucksache_urheber_kante",
        "tabelle": """(SELECT drucksache_id,
                              row_number() OVER (PARTITION BY drucksache_id
                                                 ORDER BY bezeichnung) AS lfd
                         FROM parlamentsarbeit.drucksache_urheber)""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "drucksache/{drucksache_id}",
        "geometrie": None,
        "felder": [("lfd", "stkg:hatDokumenturheber", "ref",
                    "dokumenturheber/{drucksache_id}_{lfd}")],
    },
    {


        "name": "initiative_fraktion",
        "tabelle": """(SELECT i.vorgang_id,
                              CASE i.initiative
                                WHEN 'Fraktion der SPD'     THEN 'SPD'
                                WHEN 'Fraktion der FDP'     THEN 'FDP'
                                WHEN 'Fraktion der AfD'     THEN 'AFD'
                                WHEN 'Fraktion der CDU/CSU' THEN 'CDU/CSU'
                                WHEN 'Fraktion DIE LINKE'   THEN 'LINKE'
                                WHEN 'Gruppe Die Linke'     THEN 'LINKE'
                                WHEN 'Gruppe BSW'           THEN 'BSW'
                                ELSE CASE WHEN i.initiative LIKE 'Fraktion B%NDNIS 90%'
                                          THEN 'GRUENE' END
                              END AS fraktion_id
                         FROM parlamentsarbeit.vorgang_initiative i
                        WHERE i.initiative LIKE 'Fraktion %'
                           OR i.initiative LIKE 'Gruppe %')""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "vorgang/{vorgang_id}",
        "geometrie": None,
        "felder": [("fraktion_id", "stkg:hatInitiative", "ref",
                    "fraktion/{fraktion_id}")],
    },
    {


        "name": "initiative_land",
        "tabelle": """(SELECT i.vorgang_id, ls.ags, s.datum AS wahltag
                         FROM parlamentsarbeit.vorgang_initiative i
                         JOIN parlamentsarbeit.vorgang v
                           ON v.vorgang_id = i.vorgang_id
                         JOIN (SELECT DISTINCT ags, gen FROM raum.landstand) ls
                           ON ls.gen = i.initiative
                         JOIN zeit.stichtag s ON s.art = 'wahltag'
                          AND extract(year from s.datum)::int = CASE v.wahlperiode
                                WHEN 18 THEN 2013 WHEN 19 THEN 2017
                                WHEN 20 THEN 2021 END)""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "vorgang/{vorgang_id}",
        "geometrie": None,
        "felder": [("ags", "stkg:hatInitiative", "ref",
                    "bundesland/{ags}_{wahltag}")],
    },
    {


        "name": "initiative_organisation",
        "tabelle": """(SELECT DISTINCT i.initiative AS name
                         FROM parlamentsarbeit.vorgang_initiative i
                        WHERE i.initiative NOT LIKE 'Fraktion %'
                          AND i.initiative NOT LIKE 'Gruppe %'
                          AND NOT EXISTS (SELECT 1 FROM raum.landstand l
                                          WHERE l.gen = i.initiative))""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Organisation",
        "iri": "organisation/{name}",
        "geometrie": None,
        "felder": [("name", "stkg:organisationsbezeichnung", "text")],
    },
    {
        "name": "initiative_organisation_kante",
        "tabelle": """(SELECT i.vorgang_id, i.initiative AS name
                         FROM parlamentsarbeit.vorgang_initiative i
                        WHERE i.initiative NOT LIKE 'Fraktion %'
                          AND i.initiative NOT LIKE 'Gruppe %'
                          AND NOT EXISTS (SELECT 1 FROM raum.landstand l
                                          WHERE l.gen = i.initiative))""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "vorgang/{vorgang_id}",
        "geometrie": None,
        "felder": [("name", "stkg:hatInitiative", "ref",
                    "organisation/{name}")],
    },
    {


        "name": "initiative_zugehoerigkeit",
        "tabelle": """(SELECT DISTINCT i.initiative AS name
                         FROM parlamentsarbeit.vorgang_initiative i
                        WHERE i.initiative LIKE 'Bundesministerium%'
                           OR i.initiative LIKE 'Beauftragte%Bundesregierung%'
                           OR i.initiative LIKE 'Beauftr.%Bundesregierung%'
                           OR i.initiative LIKE 'Fachkommission%Bundesregierung%')""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "organisation/{name}",
        "geometrie": None,
        "felder": [("name", "stkg:gehoertZuOrganisation", "ref",
                    "organisation/Bundesregierung")],
    },
    {
        "name": "vorgang_verlinkung",
        "tabelle": """(SELECT vorgang_id, ziel_vorgang_id, verweisung
                         FROM parlamentsarbeit.vorgang_verlinkung
                        WHERE ziel_vorgang_id IS NOT NULL)""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Vorgangsverweis",
        "iri": "vorgangsverweis/{vorgang_id}_{ziel_vorgang_id}",
        "geometrie": None,
        "felder": [
            ("vorgang_id",      "stkg:hatAusgangsvorgang", "ref",
             "vorgang/{vorgang_id}"),
            ("ziel_vorgang_id", "stkg:hatZielvorgang",     "ref",
             "vorgang/{ziel_vorgang_id}"),
            ("verweisung",      "stkg:verweisungsart",     "text"),
        ],
    },
    {


        "name": "rede",
        "tabelle": """(SELECT r.rede_id, k.person, r.wahlperiode,
                              r.sitzung_nr, r.seite, r.redeart
                         FROM parlamentsarbeit.rede r
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'btv' AND k.kennung = r.redner_id)""",
        "lieferung": "cpp_bt_fobbe",
        "klasse": "stkg:Rede",
        "iri": "rede/{rede_id}",
        "geometrie": None,
        "felder": [
            ("person",      "stkg:hatRedner",       "ref", "person/{person}"),


            ("person",      "stkg:hatBeteiligtePerson", "ref", "person/{person}"),
            ("sitzung_nr",  "stkg:hatRedeSitzung",  "ref",
             "sitzung/{wahlperiode}_{sitzung_nr}"),
            ("seite",       "stkg:redefundstelle",  "text"),
        ],
    },
    {


        "name": "redetext",
        "tabelle": "parlamentsarbeit.rede_text",
        "lieferung": "cpp_bt_fobbe",
        "klasse": None,
        "iri": "rede/{rede_id}",
        "geometrie": None,
        "felder": [("text", "stkg:volltext", "text")],
    },
    {


        "name": "rede_rolle",
        "tabelle": """(SELECT r.rede_id, n.rolle_normalisiert AS rolle
                         FROM parlamentsarbeit.rede r
                         JOIN parlamentsarbeit.rollen_normalisierung n
                           ON n.art = 'rolle_lang' AND n.wert = r.rolle_lang
                        WHERE n.rolle_normalisiert IS NOT NULL)""",
        "lieferung": "person_rolle_erschlossen",
        "klasse": None,
        "iri": "rede/{rede_id}",
        "geometrie": None,
        "felder": [("rolle", "stkg:hatRednerrolle", "code", "rednerrolle")],
    },
    {


        "name": "rede_fraktion",
        "tabelle": """(SELECT rede_id, fraktion_id,
                              CASE fraktion_herkunft
                                WHEN 'stammdaten'           THEN 'bt_mdb_stammdaten'
                                WHEN 'protokoll_entscheidet' THEN 'cpp_bt_fobbe'
                              END AS lieferung
                         FROM parlamentsarbeit.rede_fraktion
                        WHERE fraktion_id IS NOT NULL)""",
        "lieferung": None,
        "lieferung_spalte": "lieferung",
        "klasse": None,
        "iri": "rede/{rede_id}",
        "geometrie": None,
        "felder": [("fraktion_id", "stkg:hatBeteiligteFraktion", "ref",
                    "fraktion/{fraktion_id}")],
    },
    {


        "name": "rede_tagesordnungspunkt",
        "tabelle": """(SELECT rede_id, replace(protokoll_nr,'/','_') AS pnr,
                              top_id, lfd
                         FROM parlamentsarbeit.rede_tagesordnungspunkt)""",
        "lieferung": "rede_top_zuordnung",
        "klasse": None,
        "iri": "rede/{rede_id}",
        "geometrie": None,
        "felder": [("lfd", "stkg:hatRedeTagesordnungspunkt", "ref",
                    "tagesordnungspunkt/{pnr}_{top_id}_{lfd}")],
    },
    {


        "name": "rede_aktivitaet",
        "tabelle": """(SELECT rede_id, aktivitaet_id
                         FROM parlamentsarbeit.rede_aktivitaet
                        WHERE aktivitaet_id IS NOT NULL)""",
        "lieferung": "rede_aktivitaet_zuordnung",
        "klasse": None,
        "iri": "aktivitaet/{aktivitaet_id}",
        "geometrie": None,
        "felder": [("rede_id", "stkg:istRede", "ref", "rede/{rede_id}")],
    },
    {


        "name": "sitzung",
        "tabelle": """(SELECT wahlperiode, sitzung_nr, min(sitzung_datum) AS datum
                         FROM (SELECT wahlperiode, sitzung_nr, sitzung_datum
                                 FROM parlamentsarbeit.rede
                               UNION
                               SELECT wahlperiode, sitzung_nr, sitzung_datum
                                 FROM parlamentsarbeit.entschuldigt) x
                        WHERE sitzung_nr IS NOT NULL
                        GROUP BY wahlperiode, sitzung_nr)""",
        "lieferung": "dip_plenarprotokolle",
        "klasse": "stkg:Sitzung",
        "iri": "sitzung/{wahlperiode}_{sitzung_nr}",
        "geometrie": None,
        "felder": [
            ("sitzung_nr",  "stkg:sitzungsnummer",        "int"),
            ("datum",       "stkg:ereignisDatum",         "datum"),
            ("wahlperiode", "stkg:hatSitzungsWahlperiode", "ref",
             "wahlperiode/{wahlperiode}"),
        ],
    },
    {


        "name": "tagesordnungspunkt",
        "tabelle": """(SELECT replace(protokoll_nr, '/', '_') AS pnr,
                              split_part(protokoll_nr, '/', 1) AS wahlperiode,
                              split_part(protokoll_nr, '/', 2) AS sitzung_nr,
                              top_id, lfd, titel, zusatztitel
                         FROM parlamentsarbeit.tagesordnungspunkt)""",
        "lieferung": "dip_plenarprotokolle",
        "klasse": "stkg:Tagesordnungspunkt",
        "iri": "tagesordnungspunkt/{pnr}_{top_id}_{lfd}",
        "geometrie": None,
        "felder": [
            ("titel", "stkg:tagesordnungspunktTitel", "text"),
        ],
    },
    {


        "name": "top_verhandlungsgegenstand",
        "tabelle": """(SELECT replace(protokoll_nr, '/', '_') AS pnr,
                              top_id, lfd, vorgang_id
                         FROM (
                           SELECT protokoll_nr, top_id, lfd, vorgang_id
                             FROM parlamentsarbeit.tagesordnungspunkt_deskriptor
                            WHERE vorgang_id IS NOT NULL AND vorgang_id <> ''
                           UNION
                           SELECT protokoll_nr, top_id, lfd, vorgang_id
                             FROM parlamentsarbeit.tagesordnungspunkt_sachgebiet
                            WHERE vorgang_id IS NOT NULL AND vorgang_id <> ''
                         ) x)""",
        "lieferung": "top_deskriptor_zuordnung",
        "klasse": None,
        "iri": "tagesordnungspunkt/{pnr}_{top_id}_{lfd}",
        "geometrie": None,
        "felder": [("vorgang_id", "stkg:hatVerhandlungsgegenstand", "ref",
                    "vorgang/{vorgang_id}")],
    },
    {


        "name": "top_sachgebiet",
        "tabelle": """(SELECT DISTINCT replace(protokoll_nr, '/', '_') AS pnr,
                              top_id, lfd, sachgebiet
                         FROM parlamentsarbeit.tagesordnungspunkt_sachgebiet
                        WHERE sachgebiet IS NOT NULL AND btrim(sachgebiet) <> '')""",
        "lieferung": "top_sachgebiet_zuordnung",
        "klasse": None,
        "iri": "tagesordnungspunkt/{pnr}_{top_id}_{lfd}",
        "geometrie": None,
        "felder": [("sachgebiet", "stkg:hatSachgebiet", "code", "sachgebiet")],
    },
    {
        "name": "sitzung_top_kante",
        "tabelle": """(SELECT replace(protokoll_nr, '/', '_') AS pnr,
                              split_part(protokoll_nr, '/', 1) AS wahlperiode,
                              split_part(protokoll_nr, '/', 2) AS sitzung_nr,
                              top_id, lfd
                         FROM parlamentsarbeit.tagesordnungspunkt)""",
        "lieferung": "dip_plenarprotokolle",
        "klasse": None,
        "iri": "sitzung/{wahlperiode}_{sitzung_nr}",
        "geometrie": None,
        "felder": [("lfd", "stkg:hatTagesordnungspunkt", "ref",
                    "tagesordnungspunkt/{pnr}_{top_id}_{lfd}")],
    },
    {


        "name": "plenarprotokoll",
        "tabelle": """(SELECT DISTINCT ON (fundstelle_id)
                              fundstelle_id, dokumentnummer,
                              fundstelle_datum AS datum, pdf_url
                         FROM parlamentsarbeit.vorgangsposition
                        WHERE dokumentart = 'Plenarprotokoll'
                          AND fundstelle_id IS NOT NULL
                        ORDER BY fundstelle_id, position_id)""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Plenarprotokoll",
        "iri": "plenarprotokoll/{fundstelle_id}",
        "geometrie": None,
        "felder": [
            ("dokumentnummer", "stkg:protokollnummer",  "text"),
            ("datum",          "stkg:ereignisDatum",    "datum"),
            ("pdf_url",        "stkg:volltextadresse",  "text"),
        ],
    },
    {


        "name": "sitzung_protokoll_kante",
        "tabelle": """(SELECT DISTINCT
                              split_part(vp.dokumentnummer, '/', 1) AS wahlperiode,
                              split_part(vp.dokumentnummer, '/', 2) AS sitzung_nr,
                              vp.fundstelle_id
                         FROM parlamentsarbeit.vorgangsposition vp
                        WHERE vp.dokumentart = 'Plenarprotokoll'
                          AND vp.fundstelle_id IS NOT NULL
                          AND EXISTS (
                                SELECT 1
                                  FROM (SELECT wahlperiode, sitzung_nr
                                          FROM parlamentsarbeit.rede
                                        UNION
                                        SELECT wahlperiode, sitzung_nr
                                          FROM parlamentsarbeit.entschuldigt) s
                                 WHERE s.sitzung_nr IS NOT NULL
                                   AND s.wahlperiode::text
                                       = split_part(vp.dokumentnummer, '/', 1)
                                   AND s.sitzung_nr::text
                                       = split_part(vp.dokumentnummer, '/', 2)))""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "sitzung/{wahlperiode}_{sitzung_nr}",
        "geometrie": None,
        "felder": [("fundstelle_id", "stkg:hatProtokoll", "ref",
                    "plenarprotokoll/{fundstelle_id}")],
    },
    {


        "name": "ressort",
        "tabelle": """(SELECT DISTINCT titel FROM parlamentsarbeit.drucksache_ressort
                        WHERE titel IS NOT NULL)""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Ressort",
        "iri": "ressort/{titel}",
        "geometrie": None,
        "felder": [("titel", "stkg:ressortbezeichnung", "text")],
    },
    {
        "name": "ressortzuordnung",
        "tabelle": """(SELECT drucksache_id, titel, federfuehrend,
                              row_number() OVER (PARTITION BY drucksache_id
                                                 ORDER BY titel) AS lfd
                         FROM parlamentsarbeit.drucksache_ressort
                        WHERE titel IS NOT NULL)""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Ressortzuordnung",
        "iri": "ressortzuordnung/{drucksache_id}_{lfd}",
        "geometrie": None,
        "felder": [
            ("titel",         "stkg:hatRessort",    "ref", "ressort/{titel}"),
            ("federfuehrend", "stkg:federfuehrend", "bool"),
        ],
    },
    {
        "name": "drucksache_ressort_kante",
        "tabelle": """(SELECT drucksache_id,
                              row_number() OVER (PARTITION BY drucksache_id
                                                 ORDER BY titel) AS lfd
                         FROM parlamentsarbeit.drucksache_ressort
                        WHERE titel IS NOT NULL)""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "drucksache/{drucksache_id}",
        "geometrie": None,
        "felder": [("lfd", "stkg:hatRessortzuordnung", "ref",
                    "ressortzuordnung/{drucksache_id}_{lfd}")],
    },
    {
        "name": "vorgang_sachgebiet",
        "tabelle": "parlamentsarbeit.vorgang_sachgebiet",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "vorgang/{vorgang_id}",
        "geometrie": None,
        "felder": [("sachgebiet", "stkg:hatSachgebiet", "code", "sachgebiet")],
    },


    {


        "name": "aktivitaet",
        "tabelle": """(SELECT a.aktivitaet_id, k.person, a.aktivitaetsart, a.datum
                         FROM parlamentsarbeit.aktivitaet a
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'dip' AND k.kennung = a.person_id)""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Aktivitaet",
        "iri": "aktivitaet/{aktivitaet_id}",
        "geometrie": None,
        "felder": [
            ("person",         "stkg:hatBeteiligtePerson", "ref", "person/{person}"),
            ("aktivitaetsart", "stkg:hatAktivitaetsart",   "code", "aktivitaetsart"),
            ("datum",          "stkg:ereignisDatum",       "datum"),
        ],
    },
    {


        "name": "aktivitaet_vorgang",
        "tabelle": """(SELECT a.aktivitaet_id, trim(v.vid) AS vorgang_id
                         FROM parlamentsarbeit.aktivitaet a,
                              unnest(string_to_array(a.vorgang_ids, '|')) AS v(vid)
                        WHERE trim(v.vid) <> ''
                          AND EXISTS (SELECT 1 FROM parlamentsarbeit.vorgang x
                                       WHERE x.vorgang_id = trim(v.vid)))""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "aktivitaet/{aktivitaet_id}",
        "geometrie": None,
        "felder": [("vorgang_id", "stkg:betrifftVorgang", "ref",
                    "vorgang/{vorgang_id}")],
    },
    {
        "name": "aktivitaet_deskriptor",
        "tabelle": "parlamentsarbeit.aktivitaet_deskriptor",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "aktivitaet/{aktivitaet_id}",
        "geometrie": None,
        "felder": [("name", "stkg:hatDeskriptor", "ref", "deskriptor/{name}")],
    },
    {


        "name": "drucksache_aktivitaet",
        "tabelle": """(SELECT d.aktivitaet_id, k.person, d.aktivitaetsart,
                              d.datum, d.drucksache_id
                         FROM parlamentsarbeit.drucksache_person d
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'dip' AND k.kennung = d.person_id)""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Aktivitaet",
        "iri": "aktivitaet/{aktivitaet_id}",
        "geometrie": None,
        "felder": [
            ("person",         "stkg:hatBeteiligtePerson", "ref", "person/{person}"),
            ("aktivitaetsart", "stkg:hatAktivitaetsart",   "code", "aktivitaetsart"),
            ("datum",          "stkg:ereignisDatum",       "datum"),
            ("drucksache_id",  "stkg:betrifftDokument",    "ref",
             "drucksache/{drucksache_id}"),
        ],
    },


    {


        "name": "reaktionsblock",
        "tabelle": """(SELECT kommentar_id, text FROM parlamentsarbeit.kommentar
                        WHERE protokoll_nr <> '18/20')""",
        "lieferung": "plenarkommentare",
        "klasse": "stkg:Reaktionsblock",
        "iri": "reaktionsblock/{kommentar_id}",
        "geometrie": None,
        "felder": [("text", "stkg:reaktionstext", "text")],
    },
    {


        "name": "reaktionsblock_rede",
        "tabelle": """(SELECT kommentar_id, rede_id FROM parlamentsarbeit.kommentar
                        WHERE kontext = 'rede' AND rede_id IS NOT NULL
                          AND protokoll_nr <> '18/20')""",
        "lieferung": "plenarkommentare",
        "klasse": None,
        "iri": "reaktionsblock/{kommentar_id}",
        "geometrie": None,
        "felder": [("rede_id", "stkg:betrifftRede", "ref", "rede/{rede_id}")],
    },
    {
        "name": "reaktionsblock_top",
        "tabelle": """(SELECT kommentar_id, replace(protokoll_nr,'/','_') AS pnr,
                              top_id, lfd
                         FROM parlamentsarbeit.kommentar
                        WHERE kontext = 'tagesordnungspunkt'
                          AND protokoll_nr <> '18/20')""",
        "lieferung": "plenarkommentare",
        "klasse": None,
        "iri": "reaktionsblock/{kommentar_id}",
        "geometrie": None,
        "felder": [("lfd", "stkg:betrifftTagesordnungspunkt", "ref",
                    "tagesordnungspunkt/{pnr}_{top_id}_{lfd}")],
    },
    {
        "name": "reaktionsblock_sitzung",
        "tabelle": """(SELECT kommentar_id,
                              split_part(protokoll_nr,'/',1) AS wp,
                              split_part(protokoll_nr,'/',2) AS snr
                         FROM parlamentsarbeit.kommentar
                        WHERE kontext IN ('sitzungsbeginn','anlage')
                          AND protokoll_nr <> '18/20')""",
        "lieferung": "plenarkommentare",
        "klasse": None,
        "iri": "reaktionsblock/{kommentar_id}",
        "geometrie": None,
        "felder": [("snr", "stkg:betrifftSitzung", "ref", "sitzung/{wp}_{snr}")],
    },
    {


        "name": "reaktion",
        "tabelle": f"""(SELECT kommentar_id, lfd_ereignis,
                              CASE WHEN art = 'zuruf' THEN 'zwischenruf'
                                   ELSE art END AS art
                         FROM parlamentsarbeit.kommentar_art
                        WHERE {OHNE_18_20})""",
        "lieferung": "plenarkommentare",
        "klasse": "stkg:Reaktion",
        "iri": "reaktion/{kommentar_id}_{lfd_ereignis}",
        "geometrie": None,
        "felder": [("art", "stkg:hatReaktionsart", "code", "reaktionsart")],
    },
    {
        "name": "reaktionsblock_reaktion",
        "tabelle": f"""(SELECT kommentar_id, lfd_ereignis
                         FROM parlamentsarbeit.kommentar_art
                        WHERE {OHNE_18_20})""",
        "lieferung": "plenarkommentare",
        "klasse": None,
        "iri": "reaktionsblock/{kommentar_id}",
        "geometrie": None,
        "felder": [("lfd_ereignis", "stkg:enthaeltReaktion", "ref",
                    "reaktion/{kommentar_id}_{lfd_ereignis}")],
    },
    {


        "name": "reaktionsurheber",
        "tabelle": f"""(SELECT kommentar_id, lfd_ereignis, lfd_urheber,
                              urheber_art, umfang, schreibweise
                         FROM parlamentsarbeit.kommentar_urheber
                        WHERE {OHNE_18_20})""",
        "lieferung": "plenarkommentare",
        "klasse": "stkg:Reaktionsurheber",
        "iri": "reaktionsurheber/{kommentar_id}_{lfd_ereignis}_{lfd_urheber}",
        "geometrie": None,
        "felder": [
            ("urheber_art", "stkg:hatUrheberart",    "code", "urheberart"),
            ("umfang",      "stkg:hatUrheberumfang", "code", "urheberumfang"),
        ],
    },
    {
        "name": "reaktion_urheber_kante",
        "tabelle": f"""(SELECT kommentar_id, lfd_ereignis, lfd_urheber
                         FROM parlamentsarbeit.kommentar_urheber
                        WHERE {OHNE_18_20})""",
        "lieferung": "plenarkommentare",
        "klasse": None,
        "iri": "reaktion/{kommentar_id}_{lfd_ereignis}",
        "geometrie": None,
        "felder": [("lfd_urheber", "stkg:hatUrheber", "ref",
                    "reaktionsurheber/{kommentar_id}_{lfd_ereignis}_{lfd_urheber}")],
    },
    {


        "name": "reaktionsurheber_fraktion",
        "tabelle": f"""(SELECT kommentar_id, lfd_ereignis, lfd_urheber, fraktion_id
                         FROM parlamentsarbeit.kommentar_urheber
                        WHERE urheber_art IN ('fraktion', 'haus')
                          AND fraktion_id IS NOT NULL
                          AND {OHNE_18_20})""",
        "lieferung": "plenarkommentare",
        "klasse": None,
        "iri": "reaktionsurheber/{kommentar_id}_{lfd_ereignis}_{lfd_urheber}",
        "geometrie": None,
        "felder": [("fraktion_id", "stkg:hatUrheberFraktion", "ref",
                    "fraktion/{fraktion_id}")],
    },
    {


        "name": "reaktionsurheber_person",
        "tabelle": f"""(SELECT u.kommentar_id, u.lfd_ereignis, u.lfd_urheber, k.person
                         FROM parlamentsarbeit.kommentar_urheber u
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'btv' AND k.kennung = u.urheber_redner_id
                        WHERE u.{OHNE_18_20})""",
        "lieferung": "plenarkommentare",
        "klasse": None,
        "iri": "reaktionsurheber/{kommentar_id}_{lfd_ereignis}_{lfd_urheber}",
        "geometrie": None,
        "felder": [("person", "stkg:hatUrheberPerson", "ref", "person/{person}")],
    },


    {


        "name": "abstimmung",
        "tabelle": """(SELECT datei, wahlperiode, sitzung, datum, titel
                         FROM politiker_innen.abstimmung_bt)""",
        "lieferung": "bt_namentliche_abstimmungen",
        "klasse": "stkg:NamentlicheAbstimmung",
        "iri": "abstimmung/{datei}",
        "geometrie": None,
        "felder": [
            ("datum", "stkg:ereignisDatum",     "datum"),
            ("titel", "stkg:abstimmungstitel",  "text"),
        ],
    },
    {


        "name": "abstimmung_ergebnis",
        "tabelle": """(SELECT datei, amtl_abgegeben, amtl_nicht_abg, amtl_ja,
                              amtl_nein, amtl_enthaltung, amtl_ungueltig,
                              abweichung, titel_pdf, vorlageart
                         FROM politiker_innen.abstimmung_kopf_bt)""",
        "lieferung": "bt_namentliche_abstimmungen",
        "klasse": None,
        "iri": "abstimmung/{datei}",
        "geometrie": None,
        "felder": [
            ("amtl_abgegeben",  "stkg:anzahlAbgegeben",      "int"),
            ("amtl_nicht_abg",  "stkg:anzahlNichtAbgegeben", "int"),
            ("amtl_ja",         "stkg:anzahlJa",             "int"),
            ("amtl_nein",       "stkg:anzahlNein",           "int"),
            ("amtl_enthaltung", "stkg:anzahlEnthaltung",     "int"),
            ("amtl_ungueltig",  "stkg:anzahlUngueltig",      "int"),
            ("abweichung",      "stkg:ergebnisabweichung",   "text"),
            ("titel_pdf",       "stkg:vorlagenbezeichnung",  "text"),
            ("vorlageart",      "stkg:vorlagenart",          "text"),
        ],
    },
    {
        "name": "abstimmung_sitzung",
        "tabelle": """(SELECT a.datei, a.wahlperiode, a.sitzung
                         FROM politiker_innen.abstimmung_bt a
                        WHERE EXISTS (SELECT 1 FROM parlamentsarbeit.rede r
                                       WHERE r.wahlperiode = a.wahlperiode
                                         AND r.sitzung_nr = a.sitzung))""",
        "lieferung": "bt_namentliche_abstimmungen",
        "klasse": None,
        "iri": "abstimmung/{datei}",
        "geometrie": None,
        "felder": [("sitzung", "stkg:hatAbstimmungsSitzung", "ref",
                    "sitzung/{wahlperiode}_{sitzung}")],
    },
    {


        "name": "abstimmung_vorgang",
        "tabelle": """(SELECT datei, vorgang_id
                         FROM politiker_innen.abstimmung_vorgang_bt)""",
        "lieferung": "bt_namentliche_abstimmungen",
        "klasse": None,
        "iri": "abstimmung/{datei}",
        "geometrie": None,
        "felder": [("vorgang_id", "stkg:hatAbstimmungsgegenstand", "ref",
                    "vorgang/{vorgang_id}")],
    },
    {


        "name": "abstimmung_deskriptor",


        "tabelle": """(SELECT datei, deskriptor AS name
                         FROM politiker_innen.abstimmung_deskriptor_bt)""",
        "lieferung": "bt_namentliche_abstimmungen",
        "klasse": None,
        "iri": "abstimmung/{datei}",
        "geometrie": None,
        "felder": [("name", "stkg:hatDeskriptor", "ref", "deskriptor/{name}")],
    },
    {


        "name": "abstimmung_sachgebiet",
        "tabelle": """(SELECT datei, sachgebiet FROM politiker_innen.abstimmung_sachgebiet_bt)""",
        "lieferung": "bt_namentliche_abstimmungen",
        "klasse": None,
        "iri": "abstimmung/{datei}",
        "geometrie": None,
        "felder": [("sachgebiet", "stkg:hatSachgebiet", "code", "sachgebiet")],
    },
    {


        "name": "abstimmung_gremium",
        "tabelle": """(SELECT datei, ausschuss_id FROM politiker_innen.abstimmung_ausschuss)""",
        "lieferung": "bt_namentliche_abstimmungen",
        "klasse": None,
        "iri": "abstimmung/{datei}",
        "geometrie": None,
        "felder": [("ausschuss_id", "stkg:hatAbstimmungsGremium", "ref",
                    "gremium/{ausschuss_id}")],
    },
    {


        "name": "abstimmung_kennung",
        "tabelle": """(SELECT datei, abstimmung_id FROM politiker_innen.abstimmung_bt_aw)""",
        "lieferung": "aw_api_v2",
        "klasse": "stkg:Kennung",
        "iri": "kennung/aw_abstimmung_{abstimmung_id}",
        "geometrie": None,
        "felder": [("abstimmung_id", "stkg:kennungswert", "text")],
    },
    {
        "name": "abstimmung_kennung_kante",
        "tabelle": """(SELECT datei, abstimmung_id FROM politiker_innen.abstimmung_bt_aw)""",
        "lieferung": "aw_api_v2",
        "klasse": None,
        "iri": "abstimmung/{datei}",
        "geometrie": None,
        "felder": [("abstimmung_id", "stkg:hatAbstimmungskennung", "ref",
                    "kennung/aw_abstimmung_{abstimmung_id}")],
    },
    {


        "name": "abstimmung_einleitung",
        "tabelle": """(SELECT datei, einleitung
                         FROM politiker_innen.abstimmung_einleitung
                        WHERE einleitung IS NOT NULL AND btrim(einleitung) <> '')""",
        "lieferung": "aw_api_v2",
        "klasse": None,
        "iri": "abstimmung/{datei}",
        "geometrie": None,
        "felder": [("einleitung", "stkg:abstimmungseinleitung", "text")],
    },
    {


        "name": "stimmabgabe",
        "tabelle": """(SELECT s.datei, s.mdb_id, k.person, s.bemerkung,
                              CASE WHEN s.stimme = 'nicht_abgegeben' THEN 'abwesend'
                                   ELSE s.stimme END AS stimme
                         FROM politiker_innen.stimme_bt s
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'btv' AND k.kennung = s.mdb_id)""",
        "lieferung": "bt_namentliche_abstimmungen",
        "klasse": "stkg:Stimmabgabe",
        "iri": "stimmabgabe/{datei}_{mdb_id}",
        "geometrie": None,
        "felder": [
            ("person",    "stkg:hatAbstimmendePerson",     "ref", "person/{person}"),
            ("datei",     "stkg:hatStimmabgabeAbstimmung", "ref", "abstimmung/{datei}"),
            ("stimme",    "stkg:hatVotum",                 "code", "votum"),
            ("bemerkung", "stkg:entschuldigungsgrund",     "text"),
        ],
    },


    {


        "name": "abwesenheit",
        "tabelle": """(SELECT e.wahlperiode, e.sitzung_nr, e.mdb_id, k.person,
                              e.entschuldigt_bis,
                              CASE WHEN e.grund LIKE '%%Mutterschutz%%'
                                        THEN 'mutterschutz'
                                   WHEN e.grund LIKE '%%Versammlung%%'
                                        THEN 'parlamentarische_versammlung'
                                   END AS grund
                         FROM parlamentsarbeit.entschuldigt e
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'btv' AND k.kennung = e.mdb_id)""",
        "lieferung": "entschuldigte_abgeordnete",
        "klasse": "stkg:EntschuldigteAbwesenheit",
        "iri": "abwesenheit/{wahlperiode}_{sitzung_nr}_{mdb_id}",
        "geometrie": None,
        "felder": [
            ("person",           "stkg:hatAbwesendePerson",   "ref", "person/{person}"),
            ("sitzung_nr",       "stkg:hatAbwesenheitsSitzung", "ref",
             "sitzung/{wahlperiode}_{sitzung_nr}"),
            ("grund",            "stkg:hatAbwesenheitsgrund", "code", "abwesenheitsgrund"),
            ("entschuldigt_bis", "stkg:entschuldigtBis",      "datum"),
        ],
    },
    {


        "name": "ordnungsruf",
        "tabelle": """(SELECT replace(replace(replace(ordnungsruf_id, ':', '_'), '/', '_'), ' ', '_') AS ordnungsruf_id,
                              datum, anzahl_rufe, vorgang_id, empfaenger_person
                         FROM parlamentsarbeit.ordnungsruf)""",
        "lieferung": "dip_dokumente",
        "klasse": "stkg:Ordnungsruf",
        "iri": "ordnungsruf/{ordnungsruf_id}",
        "geometrie": None,
        "felder": [
            ("datum",       "stkg:ereignisDatum", "datum"),
            ("anzahl_rufe", "stkg:anzahlRufe",    "int"),
        ],
    },
    {
        "name": "ordnungsruf_person",
        "tabelle": """(SELECT replace(replace(replace(o.ordnungsruf_id, ':', '_'), '/', '_'), ' ', '_') AS ordnungsruf_id,
                              o.empfaenger_person
                         FROM parlamentsarbeit.ordnungsruf o
                         JOIN parlamentsarbeit.person p
                           ON p.person = o.empfaenger_person)""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "ordnungsruf/{ordnungsruf_id}",
        "geometrie": None,
        "felder": [("empfaenger_person", "stkg:hatGeruegtePerson", "ref",
                    "person/{empfaenger_person}")],
    },
    {
        "name": "ordnungsruf_vorgang",
        "tabelle": """(SELECT replace(replace(replace(o.ordnungsruf_id, ':', '_'), '/', '_'), ' ', '_') AS ordnungsruf_id,
                              o.vorgang_id
                         FROM parlamentsarbeit.ordnungsruf o
                        WHERE EXISTS (SELECT 1 FROM parlamentsarbeit.vorgang v
                                       WHERE v.vorgang_id = o.vorgang_id))""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "ordnungsruf/{ordnungsruf_id}",
        "geometrie": None,
        "felder": [("vorgang_id", "stkg:hatOrdnungsrufVorgang", "ref",
                    "vorgang/{vorgang_id}")],
    },
    {


        "name": "ordnungsruf_erteiler",
        "tabelle": """(SELECT replace(replace(replace(o.ordnungsruf_id, ':', '_'), '/', '_'), ' ', '_') AS ordnungsruf_id,
                              k.person
                         FROM parlamentsarbeit.ordnungsruf o,
                              unnest(string_to_array(o.erteilt_von_person_id, ';'))
                                AS e(id)
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'dip' AND k.kennung = trim(e.id))""",
        "lieferung": "dip_dokumente",
        "klasse": None,
        "iri": "ordnungsruf/{ordnungsruf_id}",
        "geometrie": None,
        "felder": [("person", "stkg:erteiltDurchPerson", "ref", "person/{person}")],
    },
]


DESKRIPTORTYP = {
    "sachbegriffe":       "stkg:deskriptortyp_sachbegriff",
    "institutionen":      "stkg:deskriptortyp_institution",
    "geograph. begriffe": "stkg:deskriptortyp_geographisch",
    "rechtsmaterialien":  "stkg:deskriptortyp_rechtsmaterialie",
    "freier deskriptor":  "stkg:deskriptortyp_frei",
    "personen":           "stkg:deskriptortyp_person",
}


def kopf(lieferung):
    return "\n".join([
        "# Parlamentsarbeit der Lieferung %s" % lieferung,
        "#",
        "# ERZEUGT von 03_load_db/graph/export_parlament.py.",
        "",
    ] + ["@prefix %s: <%s> ." % (pr, u) for pr, u in PRAEFIXE]
      + ["", "%s {" % iri("lieferung/%s" % lieferung), ""])


def tripel(bestand, z):


    z_iri = dict(z)
    for spalte in ("name", "titel", "top_id"):
        if z_iri.get(spalte):
            z_iri[spalte] = slug(z_iri[spalte])
    pfad_teil = bestand["iri"].format(**z_iri)


    if UNGUELTIG.search(pfad_teil):
        KAPUTT.add((bestand["name"], pfad_teil[:70]))
        return None
    kennung = iri(pfad_teil)
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
        elif art == "deskriptortyp":
            objekt = DESKRIPTORTYP.get(str(wert).strip().lower())
            if objekt is None:
                UNBEKANNT.add(("deskriptortyp", str(wert)))
                continue
        elif art == "bool":
            objekt = '"%s"^^xsd:boolean' % (
                "true" if str(wert).strip().lower() in ("true", "t", "1") else "false")
        else:
            objekt = literal(wert, art)
        zeilen.append("        %-28s %s" % (praedikat, objekt))
    if not zeilen:
        return None
    return "    %s\n" % kennung + " ;\n".join(zeilen) + " .\n"


def baue(namen, max_mb, ziel=None):
    global BEKANNT
    BEKANNT = lies_schema_kennungen()
    print("  %d Codelisten-Kennungen aus dem Schema gelesen" % len(BEKANNT))


    ausgabe = Path(ziel).resolve() if ziel else AUSGABE
    if ziel:
        ausgabe.mkdir(parents=True, exist_ok=True)
        print("  Zielordner: %s" % ausgabe)
        if not namen:
            print("  ACHTUNG: --ziel ohne Bestandsnamen schreibt die GANZE " "Lieferung dorthin.\n" "  Zum Anhaengen ist das falsch -- dann steht sie doppelt " "im Graphen.")
    else:
        pfade.pruefe(AUSGABE)
    tmp = ausgabe / "_export.csv"
    grenze = max_mb * 1024 * 1024 if max_mb else 0

    offen = {}
    teile = defaultdict(list)

    def dateiname(lieferung, nr):
        return ausgabe / ("%s.trig" % lieferung if nr == 1
                          else "%s_%02d.trig" % (lieferung, nr))

    def oeffne(lieferung, nr):
        if nr == 1:
            for alt in (list(ausgabe.glob("%s.trig" % lieferung))
                        + list(ausgabe.glob("%s_[0-9][0-9].trig" % lieferung))):
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
    for bestand in BESTAENDE:
        if namen and bestand["name"] not in namen:
            continue
        spalten = spalten_von(bestand)
        run_copy(sql_fuer(bestand, None), tmp)
        import csv as _csv
        with tmp.open(encoding="utf-8", newline="") as fh:
            for z in _csv.DictReader(fh):


                if bestand.get("lieferung_spalte"):
                    lieferung = (z.get(bestand["lieferung_spalte"]) or "").strip()
                    if not lieferung:
                        OHNE_LIEFERUNG.add((bestand["name"], str(z)[:60]))
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

    if OHNE_LIEFERUNG:
        print("\n  ZEILEN OHNE LIEFERUNG -- nicht geschrieben:")
        for name, zeile in sorted(OHNE_LIEFERUNG)[:10]:
            print("    %-28s %s" % (name, zeile))
        print("    %d insgesamt" % len(OHNE_LIEFERUNG))

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
            print("    %s  %.1f MB" % (p.name, p.stat().st_size / 1024 / 1024))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bestand", nargs="*")
    ap.add_argument("--liste", action="store_true")
    ap.add_argument("--max-mb", type=int, default=200)
    ap.add_argument("--ziel", default=None,
                    help="anderer Zielordner. Fuer Teillaeufe, die zu einer " "bereits geladenen Lieferung dazukommen sollen: Der " "regulaere Lauf loescht die Dateien der Lieferung " "vor dem Schreiben, ein Teillauf in einen eigenen " "Ordner nicht.")
    a = ap.parse_args()
    if a.liste:
        for b in BESTAENDE:
            print("  %-22s %s" % (b["name"], b["tabelle"].split("\n")[0][:60]))
        return
    baue(set(a.bestand), a.max_mb, a.ziel)


if __name__ == "__main__":
    main()
