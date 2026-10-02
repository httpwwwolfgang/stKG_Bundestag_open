import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade


csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

REPO = Path(__file__).resolve().parents[1]
from db import run_copy

BASIS = "https://skg-bundestag.de/"
CRS   = "http://www.opengis.net/def/crs/EPSG/0/25832"

AUSGABE = pfade.RAUM


UNBEKANNT = set()


OHNE_LIEFERUNG = set()

PRAEFIXE = [
    ("stkg", "https://skg-bundestag.de/schema#"),
    ("geo",  "http://www.opengis.net/ont/geosparql#"),
    ("xsd",  "http://www.w3.org/2001/XMLSchema#"),
]


CODE = {
    "filiationsart": {
        "identisch":          "stkg:filiation_fortsetzung",
        "aufgegangen_in":     "stkg:filiation_ableitung",
        "hervorgegangen_aus": "stkg:filiation_ableitung",
        "flaechenwechsel":    "stkg:filiation_flaechenwechsel",
    },
    "filiationsgrund": {

        "namensaenderung":      "stkg:grund_namensaenderung",
        "schluesselaenderung":  "stkg:grund_schluesselaenderung",
        "eingliederung":        "stkg:grund_eingliederung",
        "zusammenschluss":      "stkg:grund_zusammenschluss",
        "teilausgliederung":    "stkg:grund_teilausgliederung",

        "identisch":   "stkg:grund_identisch",
        "nur_zugang":  "stkg:grund_nur_zugang",
        "nur_abgang":  "stkg:grund_nur_abgang",
        "austausch":   "stkg:grund_austausch",
    },
    "einheitsart": {
        "gemeinde":             "stkg:einheitsart_gemeinde",
        "briefwahleinheit":     "stkg:einheitsart_briefwahlverbund",
        "grossstadt_wahlkreis": "stkg:einheitsart_wahlkreisteil",
    },
    "gebietsart": {
        "gemeinde":                                        "stkg:gebietsart_gemeinde",
        "stadt":                                           "stkg:gebietsart_stadt",
        "gemeinde (gemeinschaftsangehörig)":               "stkg:gebietsart_gemeinde_verband",
        "stadt (gemeinschaftsangehörig)":                  "stkg:gebietsart_stadt_verband",
        "stadt (kreisfrei)":                               "stkg:gebietsart_stadt_kreisfrei",
        "gemeindefreies gebiet":                           "stkg:gebietsart_gemeindefrei",
        "gemeindefreies gebiet (gemeinschaftsangehörig)":  "stkg:gebietsart_gemeindefrei_verband",

        "land":                                            "stkg:gebietsart_land",
        "freistaat":                                       "stkg:gebietsart_freistaat",
        "freie hansestadt":                                "stkg:gebietsart_freie_hansestadt",
        "freie und hansestadt":                            "stkg:gebietsart_freie_und_hansestadt",
        "landkreis":                                       "stkg:gebietsart_landkreis",
        "kreis":                                           "stkg:gebietsart_kreis",
        "kreisfreie stadt":                                "stkg:gebietsart_kreisfreie_stadt",
        "stadtkreis":                                      "stkg:gebietsart_stadtkreis",
        "städteregion":                                    "stkg:gebietsart_staedteregion",
        "region":                                          "stkg:gebietsart_region",
        "regionalverband":                                 "stkg:gebietsart_regionalverband",
    },
    "zugehoerigkeitsart": {
        "true":  "stkg:zugehoerigkeit_teilweise",
        "false": "stkg:zugehoerigkeit_ganz",
    },
}


MERKMALE = {
    "einwohnerzahl": ("Einwohnerzahl",
                      "Einwohnerzahl der Einheit zum Gebietsstand, wie die " "Geometrielieferung sie mitfuehrt."),
    "flaeche":       ("Fläche",
                      "Fläche der Einheit in Quadratkilometern, aus der " "gelieferten Geometrie berechnet."),
}


def mit_gueltigkeit(tabellen, schluessel, zusatz=""):
    union = " UNION ".join(
        f"SELECT {schluessel} AS k, stichtag FROM {t}" for t in tabellen)
    return f"""(
        SELECT q.*,
               (SELECT min(a.stichtag) - 1
                  FROM ({union}) a
                 WHERE a.k = q.{schluessel}
                   AND a.stichtag > q.stichtag) AS gueltig_bis{zusatz}
          FROM %s q
    ) AS mit_ende"""


NUTS3 = """,
               (SELECT r.typ_id
                  FROM strukturdaten.kreis_raumgliederung r
                 WHERE r.gliederung = 'N3D'
                   AND r.kreis = q.ags
                   AND r.gebietsstand = q.stichtag) AS nuts3"""


GEMEINDE_STAENDE = ("raum.gemeindestand", "raum.gemeindestand_stichtag")
KREIS_STAENDE    = ("raum.kreisstand", "raum.kreisstand_stichtag")
LAND_STAENDE     = ("raum.landstand", "raum.landstand_stichtag")


BESTAENDE = [


    {
        "name": "gemeindestand", "tabelle": mit_gueltigkeit(GEMEINDE_STAENDE, "ags") % "raum.gemeindestand",
        "lieferung": "bkg_vg250", "klasse": "stkg:Gemeindestand",
        "iri": "gemeindestand/{ags}_{stichtag}",
        "felder": [("ags", "stkg:amtlicherGemeindeschluessel", "text"),
                   ("ars", "stkg:regionalschluessel", "text"),
                   ("gen", "stkg:gemeindename", "text"),
                   ("stichtag", "stkg:gueltigVon", "datum"),
                   ("gueltig_bis", "stkg:gueltigBis", "datum"),
                   ("bez", "stkg:hatGebietsart", "code", "gebietsart")],
        "geometrie": "geom",
        "beobachtung": [("ewz", "einwohnerzahl"), ("flaeche_km2", "flaeche")],
    },
    {
        "name": "gemeindestand_stichtag", "tabelle": mit_gueltigkeit(GEMEINDE_STAENDE, "ags") % "(SELECT * FROM raum.gemeindestand_stichtag WHERE stichtag IN (SELECT datum FROM zeit.stichtag WHERE art = 'wahltag'))",
        "lieferung": "bkg_vg250", "klasse": "stkg:Gemeindestand",
        "iri": "gemeindestand/{ags}_{stichtag}",
        "felder": [("ags", "stkg:amtlicherGemeindeschluessel", "text"),
                   ("ars", "stkg:regionalschluessel", "text"),
                   ("gen", "stkg:gemeindename", "text"),
                   ("stichtag", "stkg:gueltigVon", "datum"),
                   ("gueltig_bis", "stkg:gueltigBis", "datum"),
                   ("bez", "stkg:hatGebietsart", "code", "gebietsart")],
        "geometrie": "geom",
        "beobachtung": [("ewz", "einwohnerzahl"), ("flaeche_km2", "flaeche")],
    },
    {
        "name": "kreisstand", "tabelle": mit_gueltigkeit(KREIS_STAENDE, "ags", NUTS3) % "raum.kreisstand",
        "lieferung": "bkg_vg250", "klasse": "stkg:Kreisstand",
        "iri": "kreisstand/{ags}_{stichtag}",
        "felder": [("ags", "stkg:kreisschluessel", "text"),
                   ("gen", "stkg:kreisname", "text"),
                   ("nuts3", "stkg:nuts3schluessel", "text"),
                   ("stichtag", "stkg:gueltigVon", "datum"),
                   ("gueltig_bis", "stkg:gueltigBis", "datum"),
                   ("bez", "stkg:hatGebietsart", "code", "gebietsart")],
        "geometrie": "geom",
        "beobachtung": [("ewz", "einwohnerzahl"), ("flaeche_km2", "flaeche")],
    },
    {
        "name": "kreisstand_stichtag", "tabelle": mit_gueltigkeit(KREIS_STAENDE, "ags", NUTS3) % "(SELECT * FROM raum.kreisstand_stichtag WHERE stichtag IN (SELECT datum FROM zeit.stichtag WHERE art = 'wahltag'))",
        "lieferung": "bkg_vg250", "klasse": "stkg:Kreisstand",
        "iri": "kreisstand/{ags}_{stichtag}",
        "felder": [("ags", "stkg:kreisschluessel", "text"),
                   ("gen", "stkg:kreisname", "text"),
                   ("nuts3", "stkg:nuts3schluessel", "text"),
                   ("stichtag", "stkg:gueltigVon", "datum"),
                   ("gueltig_bis", "stkg:gueltigBis", "datum"),
                   ("bez", "stkg:hatGebietsart", "code", "gebietsart")],
        "geometrie": "geom",
        "beobachtung": [("ewz", "einwohnerzahl"), ("flaeche_km2", "flaeche")],
    },
    {
        "name": "landstand", "tabelle": mit_gueltigkeit(LAND_STAENDE, "ags") % "raum.landstand",
        "lieferung": "bkg_vg250", "klasse": "stkg:Bundesland",
        "iri": "bundesland/{ags}_{stichtag}",
        "felder": [("gen", "stkg:bundeslandname", "text"),
                   ("stichtag", "stkg:gueltigVon", "datum"),
                   ("gueltig_bis", "stkg:gueltigBis", "datum"),
                   ("bez", "stkg:hatGebietsart", "code", "gebietsart")],
        "geometrie": "geom",
        "beobachtung": [("ewz", "einwohnerzahl"), ("flaeche_km2", "flaeche")],
    },
    {
        "name": "landstand_stichtag", "tabelle": mit_gueltigkeit(LAND_STAENDE, "ags") % "(SELECT * FROM raum.landstand_stichtag WHERE stichtag IN (SELECT datum FROM zeit.stichtag WHERE art = 'wahltag'))",
        "lieferung": "bkg_vg250", "klasse": "stkg:Bundesland",
        "iri": "bundesland/{ags}_{stichtag}",
        "felder": [("gen", "stkg:bundeslandname", "text"),
                   ("stichtag", "stkg:gueltigVon", "datum"),
                   ("gueltig_bis", "stkg:gueltigBis", "datum"),
                   ("bez", "stkg:hatGebietsart", "code", "gebietsart")],
        "geometrie": "geom",
        "beobachtung": [("ewz", "einwohnerzahl"), ("flaeche_km2", "flaeche")],
    },


    {
        "name": "wahlkreisstand", "tabelle": "raum.wahlkreis",
        "lieferung": "bwl_wahlkreisgeometrie", "klasse": "stkg:Wahlkreisstand",
        "iri": "wahlkreisstand/{wahljahr}_{wkr_nr}",
        "felder": [("wkr_nr", "stkg:wahlkreisnummer", "int"),
                   ("wkr_name", "stkg:wahlkreisname", "text"),
                   ("wahljahr", "stkg:giltFuerWahl", "ref", "wahl/{wahljahr}")],
        "geometrie": "geom",
        "beobachtung": [("flaeche_km2", "flaeche")],
    },


    {
        "name": "auszaehleinheit_amtlich", "tabelle": "raum.kleinst_100_amtlich",
        "lieferung": None, "lieferung_spalte": "lieferung_id",
        "klasse": "stkg:Auszaehleinheit",
        "iri": "auszaehleinheit/{wahljahr}_{einheit_id}",
        "felder": [("gemeindename", "stkg:raumbezeichnung", "text"),
                   ("typ", "stkg:hatEinheitsart", "code", "einheitsart")],
        "geometrie": "geom",
        "beobachtung": [("flaeche_km2", "flaeche")],
    },
    {
        "name": "auszaehleinheit_geteilt",


        "tabelle": "(SELECT *, 'grossstadt_wahlkreis' AS typ " " FROM raum.kleinst_100_geteilt)",
        "lieferung": None, "lieferung_spalte": "lieferung_id",
        "klasse": "stkg:Auszaehleinheit",
        "iri": "auszaehleinheit/{wahljahr}_{einheit_id}",
        "felder": [("gemeindename", "stkg:raumbezeichnung", "text"),
                   ("typ", "stkg:hatEinheitsart", "code", "einheitsart")],
        "geometrie": "geom",
        "beobachtung": [("flaeche_km2", "flaeche")],
    },
    {
        "name": "kreis_wahlkreis", "tabelle": "raum.kreis_wahlkreis",
        "lieferung": "kreis_wahlkreis_zuschnitt",
        "klasse": "stkg:KreisWahlkreisZuschnitt",
        "iri": "kreiswahlkreis/{wahljahr}_{kreis}_{wkr_nr}",
        "felder": [("kreisname", "stkg:raumbezeichnung", "text")],
        "geometrie": "geom",
        "beobachtung": [("flaeche_km2", "flaeche")],
    },


    {
        "name": "hexkarte", "tabelle": "raum.hexkarte",
        "lieferung": "hexkarte_wahlkreis", "klasse": "stkg:KartogrammGeometrie",
        "iri": "kartogramm/{wahljahr}_{wkr_nr}",
        "felder": [],
        "geometrie": "geom", "geometrie_eigenstaendig": True,
        "haengt_an": ("wahlkreisstand/{wahljahr}_{wkr_nr}", "geo:hasGeometry"),
    },


    {
        "name": "gemeinde_wahlkreis", "tabelle": "raum.gemeinde_wahlkreis_wahltag",


        "lieferung": None, "lieferung_spalte": None,
        "lieferung_je_herkunft": {


            "bezirk":            "bwl_wahlbezirke_{wahljahr}",


            "aufnahme":          "bwl_wahlbezirke_{wahljahr}",


            "gebietsuebergang":  "bwl_wahlbezirke_{wahljahr}",


            "geometrie":         "gemeindefrei_wahlkreis",


            "eingriff_vg1000":   "gemeindefrei_wahlkreis",
        },
        "klasse": "stkg:Zugehoerigkeit",
        "iri": "zugehoerigkeit/gemeinde_wahlkreis/{wahljahr}_{ags}_{wkr_nr}",
        "felder": [("ags", "stkg:hatMitglied", "ref",
                    "gemeindestand/{ags}_{wahltag}"),
                   ("wkr_nr", "stkg:gehoertZu", "ref",
                    "wahlkreisstand/{wahljahr}_{wkr_nr}"),


                   ("anteilig", "stkg:hatZugehoerigkeitsart", "code",
                    "zugehoerigkeitsart")],
        "geometrie": None,
    },
    {
        "name": "gemeinde_kreis", "tabelle": "raum.gemeinde_kreis",
        "lieferung": "bkg_vg250", "klasse": "stkg:Zugehoerigkeit",
        "iri": "zugehoerigkeit/gemeinde_kreis/{wahljahr}_{ags}",
        "felder": [("ags", "stkg:hatMitglied", "ref",
                    "gemeindestand/{ags}_{stichtag}"),
                   ("kreis", "stkg:gehoertZu", "ref",
                    "kreisstand/{kreis}_{stichtag}")],
        "geometrie": None,
    },
    {
        "name": "gemeinde_land", "tabelle": "raum.gemeinde_land",
        "lieferung": "bkg_vg250", "klasse": "stkg:Zugehoerigkeit",
        "iri": "zugehoerigkeit/gemeinde_land/{wahljahr}_{ags}",
        "felder": [("ags", "stkg:hatMitglied", "ref",
                    "gemeindestand/{ags}_{wahltag}"),
                   ("land", "stkg:gehoertZu", "ref",
                    "bundesland/{land}_{wahltag}")],
        "wahltag_join": True,
        "geometrie": None,
    },
    {
        "name": "kreis_land", "tabelle": "raum.kreis_land",
        "lieferung": "bkg_vg250", "klasse": "stkg:Zugehoerigkeit",
        "iri": "zugehoerigkeit/kreis_land/{wahljahr}_{kreis}",
        "felder": [("kreis", "stkg:hatMitglied", "ref",
                    "kreisstand/{kreis}_{wahltag}"),
                   ("land", "stkg:gehoertZu", "ref",
                    "bundesland/{land}_{wahltag}")],
        "wahltag_join": True,
        "geometrie": None,
    },
    {
        "name": "wahlkreis_land", "tabelle": "raum.wahlkreis_land",
        "lieferung": "bwl_wahlkreisgeometrie", "klasse": "stkg:Zugehoerigkeit",
        "iri": "zugehoerigkeit/wahlkreis_land/{wahljahr}_{wkr_nr}",
        "felder": [("wkr_nr", "stkg:hatMitglied", "ref",
                    "wahlkreisstand/{wahljahr}_{wkr_nr}"),
                   ("land", "stkg:gehoertZu", "ref",
                    "bundesland/{land}_{wahltag}")],
        "wahltag_join": True,
        "geometrie": None,
    },
    {
        "name": "gemeinde_auszaehleinheit", "tabelle": "raum.gemeinde_kleinst_100",
        "lieferung": None, "lieferung_spalte": "lieferung_id",
        "klasse": "stkg:Zugehoerigkeit",
        "iri": "zugehoerigkeit/gemeinde_auszaehleinheit/{wahljahr}_{ags}_{einheit_id}",
        "felder": [("ags", "stkg:hatMitglied", "ref",
                    "gemeindestand/{ags}_{wahltag}"),
                   ("einheit_id", "stkg:gehoertZu", "ref",
                    "auszaehleinheit/{wahljahr}_{einheit_id}")],
        "wahltag_join": True,
        "geometrie": None,
    },


    {
        "name": "gebietsuebergang_gemeinde", "tabelle": "raum.gebietsuebergang",
        "wo": "ebene = 'Gemeinde'",
        "lieferung": "destatis_gebietsaenderungen", "klasse": "stkg:Filiation",
        "iri": "filiation/gebiet/{jahrgang}_{zeile}_{teil}",
        "felder": [("ags_alt", "stkg:hatVorgaenger", "ref",
                    "gemeindestand/{ags_alt}_{stand_davor}"),
                   ("ags_neu", "stkg:hatNachfolger", "ref",
                    "gemeindestand/{ags_neu}_{stand_danach}"),
                   ("wirksam", "stkg:filiationWirksam", "datum"),
                   ("art", "stkg:hatFiliationsgrund", "code", "filiationsgrund"),
                   ("kontinuitaet", "stkg:hatFiliationsart", "code",
                    "filiationsart"),
                   ("flaeche_qm", "stkg:uebergangFlaeche", "dez"),
                   ("einwohner", "stkg:uebergangEinwohner", "int")],
        "geometrie": None,
    },
    {
        "name": "gebietsuebergang_kreis", "tabelle": "raum.gebietsuebergang",
        "wo": "ebene = 'Kreis'",
        "lieferung": "destatis_gebietsaenderungen", "klasse": "stkg:Filiation",
        "iri": "filiation/gebiet/{jahrgang}_{zeile}_{teil}",
        "felder": [("ags_alt", "stkg:hatVorgaenger", "ref",
                    "kreisstand/{ags_alt}_{stand_davor}"),
                   ("ags_neu", "stkg:hatNachfolger", "ref",
                    "kreisstand/{ags_neu}_{stand_danach}"),
                   ("wirksam", "stkg:filiationWirksam", "datum"),
                   ("art", "stkg:hatFiliationsgrund", "code", "filiationsgrund"),
                   ("kontinuitaet", "stkg:hatFiliationsart", "code",
                    "filiationsart"),
                   ("flaeche_qm", "stkg:uebergangFlaeche", "dez"),
                   ("einwohner", "stkg:uebergangEinwohner", "int")],
        "geometrie": None,
    },
    {


        "name": "wahlkreisuebergang_ab",
        "tabelle": """(SELECT g.von_wahljahr, g.von_wkr_nr, g.nach_wahljahr,
                              g.nach_wkr_nr, g.ags, s.datum AS wahltag
                         FROM raum.wahlkreisuebergang_gemeinde g
                         JOIN zeit.stichtag s ON s.art = 'wahltag'
                          AND extract(year from s.datum)::int = g.von_wahljahr
                        WHERE g.richtung = 'ab')""",
        "lieferung": "wahlkreisuebergang", "klasse": None,
        "iri": "filiation/wahlkreis/{von_wahljahr}_{von_wkr_nr}_{nach_wahljahr}_{nach_wkr_nr}",
        "felder": [("ags", "stkg:hatAbgegebeneGemeinde", "ref",
                    "gemeindestand/{ags}_{wahltag}")],
        "geometrie": None,
    },
    {
        "name": "wahlkreisuebergang_zu",
        "tabelle": """(SELECT g.von_wahljahr, g.von_wkr_nr, g.nach_wahljahr,
                              g.nach_wkr_nr, g.ags, s.datum AS wahltag
                         FROM raum.wahlkreisuebergang_gemeinde g
                         JOIN zeit.stichtag s ON s.art = 'wahltag'
                          AND extract(year from s.datum)::int = g.nach_wahljahr
                        WHERE g.richtung = 'zu')""",
        "lieferung": "wahlkreisuebergang", "klasse": None,
        "iri": "filiation/wahlkreis/{von_wahljahr}_{von_wkr_nr}_{nach_wahljahr}_{nach_wkr_nr}",
        "felder": [("ags", "stkg:hatAufgenommeneGemeinde", "ref",
                    "gemeindestand/{ags}_{wahltag}")],
        "geometrie": None,
    },
    {


        "name": "gemeinde_aufnahme",
        "tabelle": """(SELECT a.wahljahr, a.ags, a.ags_aufnehmend,
                              s.datum AS wahltag,
                              'bwl_wahlbezirke_' || a.wahljahr AS lieferung_id
                         FROM raum.gemeinde_aufnahme a
                         JOIN zeit.stichtag s ON s.art = 'wahltag'
                          AND extract(year from s.datum)::int = a.wahljahr)""",
        "lieferung": None, "lieferung_spalte": "lieferung_id",
        "klasse": None,
        "iri": "gemeindestand/{ags}_{wahltag}",
        "felder": [("ags_aufnehmend", "stkg:wirdAufgenommenVon", "ref",
                    "gemeindestand/{ags_aufnehmend}_{wahltag}")],
        "geometrie": None,
    },
    {
        "name": "wahlkreisuebergang", "tabelle": "raum.wahlkreisuebergang",
        "lieferung": "wahlkreisuebergang", "klasse": "stkg:Filiation",
        "iri": "filiation/wahlkreis/{von_wahljahr}_{von_wkr_nr}_{nach_wahljahr}_{nach_wkr_nr}",
        "felder": [("von_wkr_nr", "stkg:hatVorgaenger", "ref",
                    "wahlkreisstand/{von_wahljahr}_{von_wkr_nr}"),
                   ("nach_wkr_nr", "stkg:hatNachfolger", "ref",
                    "wahlkreisstand/{nach_wahljahr}_{nach_wkr_nr}"),


                   ("kontinuitaet", "stkg:hatFiliationsgrund", "code",
                    "filiationsgrund")],
        "geometrie": None,
    },
    {
        "name": "einheitsuebergang", "tabelle": "raum.einheitsuebergang",
        "lieferung": "einheitsuebergang", "klasse": "stkg:Filiation",
        "iri": "filiation/auszaehleinheit/{von_wahljahr}_{von_einheit_id}_{nach_wahljahr}_{nach_einheit_id}",
        "felder": [("von_einheit_id", "stkg:hatVorgaenger", "ref",
                    "auszaehleinheit/{von_wahljahr}_{von_einheit_id}"),
                   ("nach_einheit_id", "stkg:hatNachfolger", "ref",
                    "auszaehleinheit/{nach_wahljahr}_{nach_einheit_id}")],
        "geometrie": None,
    },


    {
        "name": "gemeindestand_crosswalk", "tabelle": "raum.gemeindestand_crosswalk",
        "lieferung": "bbsr_ags_crosswalk", "klasse": "stkg:Umrechnung",
        "iri": "umrechnung/gemeinde/{stichtag}_{ags}_{ags_21}",
        "felder": [("ags", "stkg:umrechnungVon", "ref",
                    "gemeindestand/{ags}_{stichtag}"),
                   ("ags_21", "stkg:umrechnungNach", "ref",
                    "gemeindestand/{ags_21}_2021-12-31"),
                   ("pop_cw", "stkg:gewichtBevoelkerung", "dez"),
                   ("area_cw", "stkg:gewichtFlaeche", "dez"),
                   ("emp_cw", "stkg:gewichtBeschaeftigte", "dez")],
        "geometrie": None,
    },
    {
        "name": "kreisstand_crosswalk", "tabelle": "raum.kreisstand_crosswalk",
        "lieferung": "bbsr_cty_crosswalk", "klasse": "stkg:Umrechnung",
        "iri": "umrechnung/kreis/{stichtag}_{kreis}_{kreis_21}",
        "felder": [("kreis", "stkg:umrechnungVon", "ref",
                    "kreisstand/{kreis}_{stichtag}"),
                   ("kreis_21", "stkg:umrechnungNach", "ref",
                    "kreisstand/{kreis_21}_2021-12-31"),
                   ("pop_cw", "stkg:gewichtBevoelkerung", "dez"),
                   ("area_cw", "stkg:gewichtFlaeche", "dez"),
                   ("emp_cw", "stkg:gewichtBeschaeftigte", "dez")],
        "geometrie": None,
    },


    {
        "name": "nachbarschaft", "tabelle": "raum.nachbarschaft",
        "wo": "wkr_von < wkr_nach",
        "lieferung": "nachbarschaft_wahlkreis", "klasse": "stkg:Nachbarschaft",
        "iri": "nachbarschaft/{wahljahr}_{wkr_von}_{wkr_nach}",
        "felder": [("wkr_von", "stkg:beteiligteEinheit", "ref",
                    "wahlkreisstand/{wahljahr}_{wkr_von}"),
                   ("wkr_nach", "stkg:beteiligteEinheit", "ref",
                    "wahlkreisstand/{wahljahr}_{wkr_nach}"),
                   ("grenzlaenge_m", "stkg:grenzlaenge", "dez")],
        "geometrie": None,
        "zusatz": [("wahlkreisstand/{wahljahr}_{wkr_von}", "stkg:benachbartMit",
                    "wahlkreisstand/{wahljahr}_{wkr_nach}"),
                   ("wahlkreisstand/{wahljahr}_{wkr_nach}", "stkg:benachbartMit",
                    "wahlkreisstand/{wahljahr}_{wkr_von}")],
    },


    {
        "name": "gemeinde_gerda",
        "tabelle": "(SELECT * FROM raum.gemeinde_gerda WHERE variante <> 'raw')",
        "lieferung": "gemeinde_gerda_zuordnung", "klasse": "stkg:Zugehoerigkeit",
        "iri": "zugehoerigkeit/gemeinde_gerda/{wahljahr}_{variante}_{gerda_ags}",
        "felder": [("ags", "stkg:gehoertZu", "ref",
                    "gemeindestand/{ags}_{wahltag}")],
        "wahltag_join": True,
        "geometrie": None,
    },


    {
        "name": "ort_gn250",
        "tabelle": """(SELECT nnid, name, oba, geom
                         FROM roh_gn250.name_punkt
                        WHERE oba NOT IN ('AX_Gemeinde',
                                          'AX_Verwaltungsgemeinschaft',
                                          'AX_KreisRegion',
                                          'AX_Regierungsbezirk',
                                          'AX_Bundesland',
                                          'AX_Raumeinheit',
                                          'AX_Nationalstaat'))""",
        "lieferung": "bkg_gn250", "klasse": "stkg:Ort",
        "iri": "ort/gn250/{nnid}",
        "felder": [("name", "stkg:ortsbezeichnung", "text"),
                   ("oba",  "stkg:ortsart",         "text")],
        "geometrie": "geom",
    },
]


def txt(wert):
    s = str(wert)
    for such, ersatz in (("\\", "\\\\"), ('"', '\\"'), ("\n", "\\n"),
                         ("\r", ""), ("\t", "\\t")):
        s = s.replace(such, ersatz)
    return f'"{s}"'


def iri(pfad):
    return f"<{BASIS}{pfad}>"


def literal(wert, art):
    if art == "text":
        return txt(wert)
    if art == "int":
        return f'"{wert}"^^xsd:integer'
    if art == "dez":
        return f'"{wert}"^^xsd:decimal'
    if art == "datum":
        return f'"{wert}"^^xsd:date'
    return txt(wert)


def spalten_von(bestand):
    noetig = set()
    import re
    for muster in [bestand["iri"]] + [f[3] for f in bestand["felder"]
                                      if len(f) > 3]:
        noetig |= set(re.findall(r"\{(\w+)\}", muster))
    for f in bestand["felder"]:
        noetig.add(f[0])
    for s, _ in bestand.get("beobachtung", []):
        noetig.add(s)
    if bestand.get("lieferung_spalte"):
        noetig.add(bestand["lieferung_spalte"])
    if bestand.get("lieferung_je_herkunft"):
        noetig.add("herkunft")
    if bestand.get("haengt_an"):
        noetig |= set(re.findall(r"\{(\w+)\}", bestand["haengt_an"][0]))
    for a, _, b in bestand.get("zusatz", []):
        noetig |= set(re.findall(r"\{(\w+)\}", a + b))


    if bestand.get("wahltag_join"):
        noetig.discard("wahltag")
    return sorted(noetig)


def pruefe_wahltagsbezug():
    FUEHRT_SELBST = {"raum.gemeinde_wahlkreis_wahltag"}
    fehler = []
    for b in BESTAENDE:
        muster = [b["iri"]] + [f[3] for f in b["felder"] if len(f) > 3]
        muster += [x for a, _, c in b.get("zusatz", []) for x in (a, c)]
        if not any("{wahltag}" in m for m in muster):
            continue
        if b.get("wahltag_join"):
            continue
        if b["tabelle"] in FUEHRT_SELBST:
            continue


        if "AS wahltag" in b["tabelle"]:
            continue
        fehler.append(b["name"])
    if fehler:
        raise SystemExit(
            "Diese Bestaende nennen {wahltag} im Muster, haben aber weder " "wahltag_join noch eine eigene Spalte: "
            + ", ".join(fehler))


def sql_fuer(bestand, stellen):
    spalten = list(spalten_von(bestand))


    if not bestand.get("wahltag_join"):
        auswahl = [f"{s}::text AS {s}" for s in spalten]
        if bestand["geometrie"]:
            auswahl.append(
                f"ST_AsText({bestand['geometrie']}, {stellen}) AS wkt")
        wo = f"WHERE {bestand['wo']}" if bestand.get("wo") else ""
        return (f"SELECT {', '.join(auswahl)} "
                f"FROM {bestand['tabelle']} {wo}")

    auswahl = [f"q.{s}::text AS {s}" for s in spalten]
    if bestand["geometrie"]:
        auswahl.append(f"ST_AsText(q.{bestand['geometrie']}, {stellen}) AS wkt")
    auswahl.append("wt.datum::text AS wahltag")
    von = (f"{bestand['tabelle']} q" " JOIN (SELECT substring(bezug from '[0-9]+')::smallint AS jahr," "              datum FROM zeit.stichtag WHERE art = 'wahltag') wt" "   ON wt.jahr = q.wahljahr")
    wo = f"WHERE {bestand['wo']}" if bestand.get("wo") else ""
    return f"SELECT {', '.join(auswahl)} FROM {von} {wo}"


def merkmal_bloecke(lieferung, gebraucht):
    aus = []
    for schluessel in sorted(gebraucht):
        bez, definition = MERKMALE[schluessel]
        aus.append("\n".join([
            f"    {iri(f'merkmal/{lieferung}/{schluessel}')}",
            "        a                        stkg:Merkmal ;",
            f"        stkg:merkmalsbezeichnung {txt(bez)} ;",
            f"        stkg:merkmalsdefinition  {txt(definition)} .",
            "",
        ]))
    return aus


def tripel(bestand, z, stellen):
    kennung = iri(bestand["iri"].format(**z))
    t = []

    if bestand.get("geometrie_eigenstaendig"):


        ziel, kante = bestand["haengt_an"]
        t += [f"    {iri(ziel.format(**z))} {kante} {kennung} .",
              "",
              f"    {kennung}",
              f"        a          {bestand['klasse']} ;",
              f'        geo:asWKT  "<{CRS}> {z["wkt"]}"^^geo:wktLiteral .',
              ""]
        return "\n".join(t)


    zeilen = ([f"        a  {bestand['klasse']}"]
              if bestand.get("klasse") else [])
    for feld in bestand["felder"]:
        spalte, praedikat, art = feld[0], feld[1], feld[2]
        wert = z.get(spalte)
        if wert in (None, ""):
            continue
        if art == "ref":
            objekt = iri(feld[3].format(**z))
        elif art == "code":


            objekt = CODE[feld[3]].get(str(wert).lower())
            if objekt is None:
                UNBEKANNT.add((bestand["name"], spalte, wert))
                continue
        else:
            objekt = literal(wert, art)
        zeilen.append(f"        {praedikat}  {objekt}")

    if bestand["geometrie"]:
        geo = iri("geometrie/" + bestand["iri"].format(**z))
        zeilen += [f"        geo:hasDefaultGeometry  {geo}",
                   f"        geo:hasGeometry         {geo}"]
    t.append(f"    {kennung}\n" + " ;\n".join(zeilen) + " .")
    t.append("")

    if bestand["geometrie"]:
        t += [f"    {geo}",
              "        a          stkg:Geometrie ;",
              f'        geo:asWKT  "<{CRS}> {z["wkt"]}"^^geo:wktLiteral .',
              ""]

    for spalte, merkmal in bestand.get("beobachtung", []):
        wert = z.get(spalte)
        if wert in (None, ""):
            continue
        lieferung = (z.get(bestand["lieferung_spalte"])
                     if bestand.get("lieferung_spalte") else bestand["lieferung"])
        beob = iri(f"beobachtung/{merkmal}/" + bestand["iri"].format(**z))
        t += [f"    {beob}",
              "        a                  stkg:Beobachtung ;",
              f"        stkg:hatMerkmal    {iri(f'merkmal/{lieferung}/{merkmal}')} ;",
              f"        stkg:hatRaumbezug  {kennung} ;",
              f"        stkg:wert          {literal(wert, 'dez')} .",
              ""]

    for subj, praedikat, obj in bestand.get("zusatz", []):
        t.append(f"    {iri(subj.format(**z))} {praedikat} "
                 f"{iri(obj.format(**z))} .")
    if bestand.get("zusatz"):
        t.append("")

    return "\n".join(t)


def lieferung_von(bestand, z):
    if bestand.get("lieferung_spalte"):
        return z.get(bestand["lieferung_spalte"])
    if bestand.get("lieferung_je_herkunft"):
        wahl = bestand["lieferung_je_herkunft"].get(z.get("herkunft"))
        if isinstance(wahl, dict):
            return wahl.get(int(z["wahljahr"]))
        if wahl:
            return wahl.format(**z)
        OHNE_LIEFERUNG.add((bestand["name"], z.get("herkunft")))
        return None
    return bestand["lieferung"]


def kopfzeilen(lieferung, stellen):
    return "\n".join([
        f"# Raumbestand der Lieferung {lieferung}",
        "#",
        "# ERZEUGT von 03_load_db/graph/export_raum.py.",
        f"# Koordinaten in EPSG:25832, {stellen} Nachkommastelle(n).",
        "",
    ] + [f"@prefix {p}: <{u}> ." for p, u in PRAEFIXE]
      + ["", f"{iri(f'lieferung/{lieferung}')} {{", ""])


def baue(namen, stellen, max_mb):
    pfade.pruefe(AUSGABE)
    pruefe_wahltagsbezug()
    tmp = AUSGABE / "_export.csv"


    if namen:
        betroffen = {b["lieferung"] for b in BESTAENDE
                     if b["name"] in namen and b.get("lieferung")}
        fehlend = sorted(b["name"] for b in BESTAENDE
                         if b.get("lieferung") in betroffen
                         and b["name"] not in namen)
        if fehlend:
            print("ACHTUNG: Teillauf. Diese Bestaende teilen sich eine " "Lieferung mit den gewaehlten,")
            print("         werden aber NICHT geschrieben und gehen in " "der Datei verloren:")
            for name in fehlend:
                print(f"           {name}")
            print("         Ohne Argumente aufrufen, um alles zu " "schreiben.\n")

    offen = {}
    merkmale = defaultdict(set)
    teile = defaultdict(list)
    grenze = max_mb * 1024 * 1024

    def dateiname(lieferung, nr):
        return AUSGABE / (f"{lieferung}.trig" if nr == 1
                          else f"{lieferung}_{nr:02d}.trig")

    def oeffne(lieferung, nr):
        pfad = dateiname(lieferung, nr)
        if nr == 1:


            for alt in AUSGABE.glob(f"{lieferung}.trig"):
                alt.unlink()
            for alt in AUSGABE.glob(f"{lieferung}_[0-9][0-9].trig"):
                alt.unlink()
        fh = pfad.open("w", encoding="utf-8")
        fh.write(kopfzeilen(lieferung, stellen))
        teile[lieferung].append(pfad)
        return fh

    def schliesse(lieferung, fh):
        for block in merkmal_bloecke(lieferung, merkmale[lieferung]):
            fh.write(block)
        fh.write("}\n")
        fh.close()

    def schreibe(lieferung, text):
        if lieferung not in offen:
            offen[lieferung] = [oeffne(lieferung, 1), 1, 0]
        eintrag = offen[lieferung]
        if grenze and eintrag[2] + len(text) > grenze:
            schliesse(lieferung, eintrag[0])
            if eintrag[1] == 1:


                erst = teile[lieferung][0]
                neu = dateiname(lieferung, 1).with_name(f"{lieferung}_01.trig")


                erst.replace(neu)
                teile[lieferung][0] = neu
            eintrag[1] += 1
            eintrag[0] = oeffne(lieferung, eintrag[1])
            eintrag[2] = 0
        eintrag[0].write(text)
        eintrag[2] += len(text)

    try:
        for bestand in BESTAENDE:
            if namen and bestand["name"] not in namen:
                continue
            run_copy(sql_fuer(bestand, stellen), tmp, bestand["name"])
            anzahl = 0
            with tmp.open(encoding="utf-8", newline="") as fh:
                for z in csv.DictReader(fh):
                    lieferung = lieferung_von(bestand, z)
                    if not lieferung:
                        continue
                    schreibe(lieferung, tripel(bestand, z, stellen))
                    for spalte, merkmal in bestand.get("beobachtung", []):
                        if z.get(spalte):
                            merkmale[lieferung].add(merkmal)
                    anzahl += 1
            print(f"  {bestand['name']:<28} {anzahl:>8} Zeilen")
    finally:
        for lieferung, eintrag in sorted(offen.items()):
            schliesse(lieferung, eintrag[0])
        gesamt = anzahl_dateien = 0
        for lieferung in sorted(teile):
            for pfad in teile[lieferung]:
                gross = pfad.stat().st_size
                gesamt += gross
                anzahl_dateien += 1
                print(f"  -> {pfad.name:<34} {gross/1024/1024:>8.1f} MB")
        tmp.unlink(missing_ok=True)
        print(f"\n{anzahl_dateien} Dateien in {len(teile)} Named Graphs, "
              f"{gesamt/1024/1024:.1f} MB gesamt")
        mehrteilig = {k: v for k, v in teile.items() if len(v) > 1}
        if mehrteilig:
            print("\nMehrteilig - beim Laden erst den Graphen leeren, dann " "alle Teile OHNE 'Replacement' laden:")


            for lieferung, pfadliste in sorted(mehrteilig.items()):
                print(f"    {lieferung}: {len(pfadliste)} Teile")
                print(f"      DROP GRAPH <{BASIS}lieferung/{lieferung}>")
        if OHNE_LIEFERUNG:
            print("\nZeilen ohne Lieferung - nicht geschrieben:")
            for bestand, wert in sorted(OHNE_LIEFERUNG):
                print(f"    {bestand}: herkunft = {wert!r}")
        if UNBEKANNT:
            print(f"\n{len(UNBEKANNT)} Codewerte ohne Eintrag in CODE - " "die Kante fehlt bei diesen Zeilen:")
            for bestand, spalte, wert in sorted(UNBEKANNT):
                print(f"    {bestand}.{spalte} = {wert!r}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("bestand", nargs="*", help="nur diese Bestaende")
    p.add_argument("--stellen", type=int, default=1)
    p.add_argument("--max-mb", type=int, default=200,
                   help="Umbruch in Teildateien ab dieser Groesse; 0 = nie")
    p.add_argument("--liste", action="store_true")
    a = p.parse_args()
    if a.liste:
        for b in BESTAENDE:
            print(f"  {b['name']:<28} {b['tabelle']:<34} "
                  f"{b['lieferung'] or '(aus den Daten)'}")
    else:
        baue(set(a.bestand), a.stellen, a.max_mb)
