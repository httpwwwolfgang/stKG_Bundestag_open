import sys
import json
import time
import logging
import os
import re
import hashlib
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

warnings.filterwarnings("ignore")
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from db import run_sql, run_sql_file, query


import lieferung
LIEFERUNG = "destatis_regionaldatenbank"


VERBINDUNGS_TIMEOUT = 5
LESE_TIMEOUT = 1200


VERSUCHE_JE_REQUEST = 25

_wiederholung = Retry(
    total=VERSUCHE_JE_REQUEST,
    connect=VERSUCHE_JE_REQUEST,


    read=VERSUCHE_JE_REQUEST,
    other=VERSUCHE_JE_REQUEST,
    backoff_factor=0.5,
    backoff_max=20,
    status_forcelist=(500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "POST"]),
)
_adapter = HTTPAdapter(max_retries=_wiederholung)

_post_original = requests.post


def _post_geduldig(*args, **kwargs):


    kwargs["timeout"] = (VERBINDUNGS_TIMEOUT, LESE_TIMEOUT)
    with requests.Session() as sitzung:
        sitzung.mount("https://", _adapter)
        sitzung.mount("http://", _adapter)
        return sitzung.post(*args, **kwargs)


requests.post = _post_geduldig


DB_SCHEMA = "strukturdaten_roh"
TABELLE   = "regionalstatistik"


WAHLEN = {2013: ("2013-09-22", 2012),
          2017: ("2017-09-24", 2016),
          2021: ("2021-09-26", 2020)}


TABELLEN = [


    ("11111-01-01-5", "gemeinde", "31.12.",
     "Gebietsflaeche in qkm"),

    ("12411-01-01-5", "gemeinde", "31.12.",
     "Bevoelkerung nach Geschlecht"),
    ("12411-02-03-5", "gemeinde", "31.12.",
     "Bevoelkerung nach Geschlecht und Altersgruppen"),
    ("12411-06-01-5", "gemeinde", "30.06.",
     "Bevoelkerung nach Geschlecht, 30.06."),
    ("12411-07-01-5", "gemeinde", "31.12.",
     "Durchschnittsalter der Bevoelkerung"),
    ("12411-11-01-5", "gemeinde", "31.12.",
     "Bevoelkerung nach Nationalitaet und Geschlecht"),
    ("12612-01-01-5", "gemeinde", "Jahr",
     "Lebendgeborene nach Geschlecht"),
    ("12613-01-01-5", "gemeinde", "Jahr",
     "Gestorbene nach Geschlecht"),
    ("12711-01-03-5", "gemeinde", "Jahr",
     "Zu- und Fortzuege (ueber Gemeindegrenzen) nach Geschlecht und ..."),
    ("12711-91-01-5", "gemeinde", "Jahr",
     "Zu- und Fortzuege ueber Gemeindegrenzen"),

    ("13111-01-03-5", "gemeinde", "30.06.",
     "SV-Beschaeftigte am Arbeitsort"),
    ("13111-02-02-5", "gemeinde", "30.06.",
     "SV-Beschaeftigte am Wohnort"),
    ("13111-08-02-5-B", "gemeinde", "30.06.",
     "Beschaeftigte am Arbeits- und Wohnort, Pendelnde"),
    ("13211-01-03-5", "gemeinde", "Jahr",
     "Arbeitslose nach Personengruppen"),

    ("31111-01-02-5", "gemeinde", "Jahr",
     "Genehmigungen zur Errichtung neuer Wohngebaeude und Wohnungen ..."),
    ("31111-02-02-5", "gemeinde", "Jahr",
     "Genehmigungen zur Errichtung neuer Nichtwohngebaeude"),
    ("31111-03-02-5", "gemeinde", "Jahr",
     "Genehmigungen fuer Wohnungen in Wohn- und Nichtwohngebaeuden ..."),
    ("31121-01-02-5", "gemeinde", "Jahr",
     "Fertigstellungen neuer Wohngebaeude und Wohnungen in ..."),
    ("31121-02-02-5", "gemeinde", "Jahr",
     "Fertigstellungen neuer Nichtwohngebaeude"),
    ("31121-03-02-5", "gemeinde", "Jahr",
     "Fertigstellungen von Wohnungen in Wohn- und ..."),
    ("31231-02-01-5", "gemeinde", "31.12.",
     "Wohngebaeude und Wohnungen"),

    ("32271-01-01-5", "gemeinde", "01.01.",
     "Entgelt fuer die Trinkwasserversorgung privater Haushalte"),

    ("33111-01-01-5", "gemeinde", "31.12.",
     "Bodenflaeche nach Art der tatsaechlichen Nutzung"),
    ("33111-01-02-5", "gemeinde", "31.12.",
     "Bodenflaeche nach Art der tatsaechlichen Nutzung"),
    ("33111-02-01-5", "gemeinde", "31.12.",
     "Siedlungsflaeche nach Art der tatsaechlichen Nutzung"),
    ("33111-03-01-5", "gemeinde", "31.12.",
     "Verkehrsflaeche nach Art der tatsaechlichen Nutzung"),

    ("42111-01-04-5", "gemeinde", "30.09.",
     "Betriebe, taetige Personen, Bruttoentgelte"),

    ("45412-01-02-5", "gemeinde", "Jahr",
     "Beherbergungsbetriebe, Gaestebetten, Gaesteuebernachtungen ..."),
    ("45412-01-03-5", "gemeinde", "Jahr",
     "Beherbergungsbetriebe, Schlafgelegenheiten, Gaesteankuenfte ..."),

    ("46241-01-03-5", "gemeinde", "Jahr",
     "Strassenverkehrsunfaelle, verunglueckte Personen"),
    ("46241-01-04-5", "gemeinde", "Jahr",
     "Strassenverkehrsunfaelle, verunglueckte Personen"),

    ("71231-01-02-5", "gemeinde", "Jahr",
     "Istaufkommen, Grundbetraege, Hebesaetze, Gemeindeanteil an ..."),
    ("71231-01-03-5", "gemeinde", "Jahr",
     "IST-Aufkommen, Grundbetraege, Hebesaetze ..."),
    ("71517-01-03-5", "gemeinde", "Jahr",
     "Bruttoeinnahmen der Gemeinden"),
    ("71517-02-03-5", "gemeinde", "Jahr",
     "Bruttoausgaben der Gemeinden"),

    ("73111-01-01-5", "gemeinde", "Jahr",
     "Lohn- und Einkommensteuerpflichtige"),


    ("12711-01-03-4", "kreis", "Jahr",
     "Zu- und Fortzuege (ueber Gemeindegrenzen) nach Geschlecht und ..."),
    ("12711-02-02-4", "kreis", "Jahr",
     "Zu- und Fortzuege (ueber Gemeindegrenzen und Grenzen des ..."),
    ("12711-03-02-4", "kreis", "Jahr",
     "Zu- und Fortzuege (ueber Gemeindegrenzen und Grenzen des ..."),
    ("12711-04-02-4", "kreis", "Jahr",
     "Zu- und Fortzuege (ueber Kreisgrenzen) nach Geschlecht und ..."),
    ("12711-05-02-4", "kreis", "Jahr",
     "Zu- und Fortzuege (ueber Kreisgrenzen) nach Geschlecht und ..."),
    ("12711-91-01-4", "kreis", "Jahr",
     "Zu- und Fortzuege (ueber Gemeindegrenzen)"),

    ("31111-01-02-4", "kreis", "Jahr",
     "Genehmigungen zur Errichtung neuer Wohngebaeude und Wohnungen ..."),
    ("31111-02-02-4", "kreis", "Jahr",
     "Genehmigungen zur Errichtung neuer Nichtwohngebaeude"),
    ("31111-03-02-4", "kreis", "Jahr",
     "Genehmigungen fuer Wohnungen in Wohn- und Nichtwohngebaeuden ..."),
    ("31111-04-01-4", "kreis", "Jahr",
     "Genehmigungen zur Errichtung neuer Nichtwohngebaeude nach ..."),
    ("31111-05-01-4", "kreis", "Jahr",
     "Genehmigungen zur Errichtung neuer Wohngebaeude und ..."),
    ("31111-06-01-4", "kreis", "Jahr",
     "Genehmigungen zur Errichtung neuer Wohngebaeude und ..."),
    ("31121-01-02-4", "kreis", "Jahr",
     "Fertigstellungen neuer Wohngebaeude und Wohnungen in ..."),
    ("31121-02-02-4", "kreis", "Jahr",
     "Fertigstellungen neuer Nichtwohngebaeude"),
    ("31121-03-02-4", "kreis", "Jahr",
     "Fertigstellungen von Wohnungen in Wohn- und ..."),
    ("31121-04-01-4", "kreis", "Jahr",
     "Fertigstellungen neuer Nichtwohngebaeude nach Gebaeudearten"),
    ("31121-05-01-4", "kreis", "Jahr",
     "Fertigstellungen neuer Wohngebaeude und Nichtwohngebaeude ..."),
    ("31121-06-01-4", "kreis", "Jahr",
     "Fertigstellungen neuer Wohngebaeude und Nichtwohngebaeude ..."),
    ("31231-02-01-4", "kreis", "31.12.",
     "Bestand an Wohngebaeuden und Wohnungen in Wohn- und ..."),

    ("32111-01-02-4", "kreis", "Jahr",
     "Entsorgungs- und Behandlungsanlagen, Abfallmengen (ab 2004)"),
    ("32111-01-03-4", "kreis", "Jahr",
     "Entsorgungs- und Behandlungsanlagen, Abfallmengen (ab 2018)"),
    ("32111-02-03-4", "kreis", "Jahr",
     "Art der Entsorgungs- und Behandlungsanlagen (ab 2007)"),
    ("32121-01-02-4", "kreis", "Jahr",
     "Haushaltsabfaelle - Jahr"),
    ("32151-01-01-4", "kreis", "Jahr",
     "Primaer nachgewiesene Abfallmengen"),
    ("32211-01-01-4", "kreis", "Jahr",
     "Wassergewinnung"),
    ("32211-01-02-4", "kreis", "Jahr",
     "Wassergewinnung"),
    ("32211-02-02-4", "kreis", "Jahr",
     "Anschlussgrad, Wasserabgabe"),
    ("32211-02-03-4", "kreis", "Jahr",
     "Anschlussgrad, Wasserabgabe"),
    ("32212-01-01-4", "kreis", "Jahr",
     "Anschlussgrad an die oeffentliche Kanalisation"),
    ("32212-01-02-4", "kreis", "Jahr",
     "Anschlussgrad an die oeffentliche Kanalisation"),
    ("32213-01-01a-4", "kreis", "Jahr",
     "Laenge des Kanalnetzes, Abwasserbehandlungsanlagen"),
    ("32213-01-01b-4", "kreis", "Jahr",
     "Angeschlossene Einwohnerwerte (EW-Werte)"),
    ("32213-01-01c-4", "kreis", "Jahr",
     "Jahresabwassermenge"),
    ("32213-01-02-4", "kreis", "Jahr",
     "Kanalnetz, Abwasserbehandlungsanlagen"),
    ("32214-01-01-4", "kreis", "Jahr",
     "Klaerschlamm, Entsorgungsarten des Klaerschlamms"),
    ("32214-01-02-4", "kreis", "Jahr",
     "Trockenmasse des entsorgten Klaerschlamms"),
    ("32214-01-03-4", "kreis", "Jahr",
     "Trockenmasse des entsorgten Klaerschlamms"),
    ("32221-01-03-4", "kreis", "Jahr",
     "Wassergewinnung und -bezug - 31.12. / Jahressumme"),
    ("32221-02-01-4", "kreis", "Jahr",
     "Wassereinsatz und ungenutztes Wasser"),
    ("32221-03-01-4", "kreis", "Jahr",
     "Abwasserverbleib"),
    ("32271-01-01-4", "kreis", "01.01.",
     "Entgelt fuer die Trinkwasserversorgung privater Haushalte"),

    ("45412-01-02-4", "kreis", "Jahr",
     "Beherbergungsbetriebe, Gaestebetten, Gaesteuebernachtungen ..."),
    ("45412-01-03-4", "kreis", "Jahr",
     "Beherbergungsbetriebe, Schlafgelegenheiten, Gaesteankuenfte ..."),
    ("45412-02-01-4", "kreis", "Jahr",
     "Beherbergungsbetriebe, Gaestebetten, Gaesteuebernachtungen ..."),
    ("45412-02-02-4", "kreis", "Jahr",
     "Beherbergungsbetriebe, Schlafgelegenheiten, Gaesteankuenfte ..."),
    ("45412-03-01-4", "kreis", "Jahr",
     "Gaesteuebernachtungen, Gaesteankuenfte nach ihrer Herkunft"),
    ("45412-03-02-4", "kreis", "Jahr",
     "Gaesteankuenfte, Gaesteuebernachtungen nach ihrer Herkunft"),

    ("46241-01-03-4", "kreis", "Jahr",
     "Strassenverkehrsunfaelle, verunglueckte Personen"),
    ("46241-01-04-4", "kreis", "Jahr",
     "Strassenverkehrsunfaelle, verunglueckte Personen"),
    ("46251-01-02-4", "kreis", "01.01.",
     "Kraftfahrzeugbestand nach Kraftfahrzeugarten"),
    ("46251-01-03-4", "kreis", "01.01.",
     "Kraftfahrzeugbestand nach Kraftfahrzeugarten"),
    ("46251-02-01-4", "kreis", "01.01.",
     "Personenkraftwagen nach Kraftstoffarten"),
    ("46251-03-01-4", "kreis", "01.01.",
     "Personenkraftwagen nach Emissionsgruppen"),

    ("71231-01-02-4", "kreis", "Jahr",
     "Istaufkommen, Grundbetraege, Hebesaetze, Gemeindeanteil an ..."),
    ("71231-01-03-4", "kreis", "Jahr",
     "IST-Aufkommen, Grundbetraege, Hebesaetze ..."),
    ("71327-01-05-4", "kreis", "31.12.",
     "Schulden der Kernhaushalte der Gemeinden und Gemeindeverbaende"),
    ("71517-01-03-4", "kreis", "Jahr",
     "Bruttoeinnahmen der Gemeinden"),
    ("71517-02-03-4", "kreis", "Jahr",
     "Bruttoausgaben der Gemeinden"),
    ("71517-03-02-4", "kreis", "Jahr",
     "Bruttoeinnahmen der Kreise"),
    ("71517-04-02-4", "kreis", "Jahr",
     "Bruttoausgaben der Kreise"),


    ("12411-03-03-4", "kreis", "31.12.",
     "Bevoelkerung nach Geschlecht, Nationalitaet, Alter"),
    ("12411-08-01-4", "kreis", "31.12.",
     "Jugendquotient, Altenquotient"),
    ("13211-02-05-4", "kreis", "Jahr",
     "Arbeitslose und Arbeitslosenquoten"),
    ("13312-01-05-4", "kreis", "Jahr",
     "Erwerbstaetige nach Wirtschaftszweigen"),
    ("22811-01-01-4", "kreis", "31.12.",
     "Empfaenger sozialer Mindestsicherung"),
    ("52311-01-04-4", "kreis", "Jahr",
     "Gewerbeanmeldungen, -abmeldungen"),
    ("82000-01-01-4", "kreis", "Jahr",
     "Bruttoinlandsprodukt"),
    ("82000-02-01-4", "kreis", "Jahr",
     "Bruttowertschoepfung nach Wirtschaftsbereichen"),
    ("82000-04-01-4", "kreis", "Jahr",
     "Arbeitnehmerentgelt nach Wirtschaftsbereichen"),
    ("82000-07-01-4", "kreis", "Jahr",
     "Verfuegbares Einkommen der privaten Haushalte"),


    ("12521-0040", "kreis", "31.12.",
     "Auslaender nach Geschlecht"),
    ("12521-0041", "kreis", "31.12.",
     "Auslaender nach Geschlecht und Laendergruppierungen"),
    ("12521-0044", "kreis", "Jahr",
     "Auslaender: Registerbewegungen nach Laendergruppierungen"),
    ("12531-0040", "kreis", "31.12.",
     "Schutzsuchende nach Geschlecht"),
    ("12531-0041", "kreis", "31.12.",
     "Schutzsuchende nach Geschlecht und Laendergruppierungen"),
    ("12531-01-01-4", "kreis", "31.12.",
     "Schutzsuchende nach Schutzstatus"),
    ("12531-02-01-4", "kreis", "31.12.",
     "Schutzsuchende nach Herkunft (bis 2021)"),
    ("12531-02-02-4", "kreis", "31.12.",
     "Schutzsuchende nach Herkunft (ab 2022)"),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("regionalstatistik")
logging.getLogger("pystatis").setLevel(logging.WARNING)


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    tabelle      TEXT    NOT NULL,
    ebene        TEXT    NOT NULL,
    jahr         SMALLINT NOT NULL,
    schluessel   TEXT    NOT NULL,
    einheit      TEXT,
    stichtag     DATE,
    merkmale     JSONB   NOT NULL,
    merkmal_hash TEXT    NOT NULL,
    wertname     TEXT    NOT NULL,
    wert         TEXT,
    abrufdatum   DATE    NOT NULL,
    lfd          SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (tabelle, jahr, schluessel, merkmal_hash, wertname, lfd)
);

COMMENT ON TABLE {DB_SCHEMA}.{TABELLE} IS
  'Regionaldatenbank Deutschland, Rohschicht. Anders als INKAR steht jedes '
  'Berichtsjahr im Gebietsstand dieses Jahres - deshalb tragen hier auch '
  'Gemeinden Werte, die spaeter aufgegangen sind.';
COMMENT ON COLUMN {DB_SCHEMA}.{TABELLE}.schluessel IS
  'Wie geliefert: "DG" fuer den Bund, zweistellig Laender, fuenfstellig '
  'Kreise, achtstellig Gemeinden. Aggregate bleiben erhalten.';
COMMENT ON COLUMN {DB_SCHEMA}.{TABELLE}.lfd IS
  'Laufende Nummer, wenn die Schnittstelle dieselbe Einheit mehrfach mit '
  'VERSCHIEDENEN Werten liefert. Im Regelfall 1. Groesser als 1 heisst: Die '
  'Quelle widerspricht sich, und beide Angaben stehen nebeneinander - siehe '
  '.';
"""

INDIZES = f"""
CREATE INDEX IF NOT EXISTS {TABELLE}_zugriff
    ON {DB_SCHEMA}.{TABELLE} (ebene, jahr, schluessel);
CREATE INDEX IF NOT EXISTS {TABELLE}_tabelle
    ON {DB_SCHEMA}.{TABELLE} (tabelle, jahr);
"""


def zerlege(d):
    spalten = list(d.columns)
    dimensionen = sorted({int(m.group(1)) for c in spalten
                          if (m := re.match(r"^(\d+)_variable_code$", c))})
    if not dimensionen:
        raise ValueError("keine N_variable_code-Spalten - prettify=False gesetzt?")

    def schluesselartig(reihe):
        werte = [str(x).strip() for x in reihe.dropna().unique()[:40]]
        if not werte:
            return False
        passend = sum(1 for w in werte if w.upper() == "DG" or w.isdigit())
        return passend >= max(1, int(0.8 * len(werte)))

    regional = next((n for n in dimensionen
                     if schluesselartig(d[f"{n}_variable_attribute_code"])), None)
    if regional is None:
        raise ValueError("keine regionale Dimension erkannt")
    fach = [n for n in dimensionen if n != regional]
    return regional, fach, ("time" if "time" in spalten else None)


def zeilen_aus(d, code, ebene, jahr, heute):
    vorher = len(d)
    d = d.drop_duplicates()
    if len(d) < vorher:
        log.info("    %s Dublettenzeilen entfernt (identisch, kein Widerspruch)",
                 vorher - len(d))

    regional, fach, zeit = zerlege(d)
    raus, leer, gesehen = [], 0, {}
    for _, r in d.iterrows():
        wert = r.get("value")
        if pd.isna(wert):
            leer += 1
            continue
        schluessel = str(r[f"{regional}_variable_attribute_code"]).strip()
        name = r.get(f"{regional}_variable_attribute_label")


        auspraegung = {}
        ebene_geliefert = r.get(f"{regional}_variable_label")
        if not pd.isna(ebene_geliefert):
            auspraegung["_regionalebene"] = str(ebene_geliefert)
        for n in fach:
            label = r.get(f"{n}_variable_label")
            if pd.isna(label):
                continue
            a = r.get(f"{n}_variable_attribute_label")
            auspraegung[str(label)] = None if pd.isna(a) else str(a)

        roh = json.dumps(auspraegung, sort_keys=True, ensure_ascii=False)
        h = hashlib.md5(roh.encode("utf-8")).hexdigest()[:16]


        st = r[zeit] if zeit else None
        st = None if st is None or pd.isna(st) else str(st)[:10]
        if st and not (len(st) == 10 and st[4] == "-" and st[7] == "-"):
            st = None

        gemessen = r.get("value_variable_label")
        einheit = r.get("value_unit")
        wertname = "%s__%s" % ("" if pd.isna(gemessen) else str(gemessen),
                               "" if pd.isna(einheit) else str(einheit))

        gesehen[(schluessel, h, wertname)] = gesehen.get((schluessel, h, wertname), 0) + 1
        raus.append((code, ebene, jahr, schluessel,
                     None if pd.isna(name) else str(name),
                     st, roh, h, wertname, str(wert), heute,
                     gesehen[(schluessel, h, wertname)]))

    mehrfach = {k: n for k, n in gesehen.items() if n > 1}
    if mehrfach:
        log.warning("    %s widerspruechliche Doppellieferungen - beide behalten " "(lfd),", len(mehrfach))
        for (sch, _, wn), n in sorted(mehrfach.items())[:5]:
            log.warning("      %s %s: %dx mit verschiedenen Werten", sch, wn, n)
    if leer:
        log.info("    %s Zeilen ohne Wert uebergangen", f"{leer:,}".replace(",", "."))
    return raus


def slots_freigeben(db_name):
    try:
        from pystatis import http_helper
        r = http_helper.get_data_from_endpoint(
            endpoint="helloworld", method="logincheck", params={}, db_name=db_name)
        log.warning("    Slotlimit erreicht - logincheck: %s",
                    str(getattr(r, "text", r))[:120])
        return True
    except BaseException as e:
        log.warning("    logincheck fehlgeschlagen: %s", str(e)[:100])
        return False


def hole(code, jahr, versuche=3, pause=30):
    from pystatis import Table
    from pystatis import db as _db
    aufgeraeumt = False
    for versuch in range(1, versuche + 1):
        try:
            t = Table(name=code)


            t.get_data(startyear=str(jahr), endyear=str(jahr), prettify=False)
            return t.data
        except BaseException as e:
            art = type(e).__name__


            if not aufgeraeumt and ("parallelen Requests" in str(e)
                                    or "404" in str(e)):
                aufgeraeumt = True
                try:
                    ziel = _db.select_db_by_credentials(_db.identify_db_matches(code))
                except BaseException:
                    ziel = "regio"
                if slots_freigeben(ziel):
                    time.sleep(5)
                    continue
            if versuch < versuche:
                log.warning("    %s %s: %s, Versuch %d von %d - warte %d s",
                            code, jahr, art, versuch, versuche, pause)
                time.sleep(pause)
            else:
                log.warning("    %s %s: %s nach %d Versuchen - %s",
                            code, jahr, art, versuche, str(e)[:90])
    return None


def schreibe(zeilen):
    import csv
    tmp = Path(tempfile.gettempdir()) / f"regiostat_{os.getpid()}.csv"
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(zeilen)
    sql = Path(tempfile.gettempdir()) / f"regiostat_copy_{os.getpid()}.sql"
    sql.write_text(
        f"CREATE TEMP TABLE _neu (LIKE {DB_SCHEMA}.{TABELLE});\n"
        f"\\copy _neu (tabelle, ebene, jahr, schluessel, einheit, stichtag, "
        f"merkmale, merkmal_hash, wertname, wert, abrufdatum, lfd) "
        f"FROM '{tmp.as_posix()}' WITH (FORMAT csv, ENCODING 'UTF8');\n"
        f"DELETE FROM {DB_SCHEMA}.{TABELLE} t USING _neu n "
        f"WHERE t.tabelle = n.tabelle AND t.jahr = n.jahr;\n"
        f"INSERT INTO {DB_SCHEMA}.{TABELLE} SELECT * FROM _neu;\n",
        encoding="utf-8")
    run_sql_file(sql, label="copy regionalstatistik")
    sql.unlink(missing_ok=True)
    tmp.unlink(missing_ok=True)


def main():
    lieferung.merke(LIEFERUNG)
    argumente = [a for a in sys.argv[1:] if not a.startswith("--")]
    jahre = sorted({j for w in WAHLEN for j in (w, WAHLEN[w][1])})
    if "--jahre" in sys.argv:
        jahre = [int(x) for x in sys.argv[sys.argv.index("--jahre") + 1].split(",")]
    auswahl = [t for t in TABELLEN if not argumente or t[0] in argumente]

    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;", "verwerfen")
        log.warning("Tabelle verworfen.")
    run_sql(DDL, "ddl")

    heute = time.strftime("%Y-%m-%d")
    log.info("%d Tabellen x %d Jahrgaenge = %d Abrufe",
             len(auswahl), len(jahre), len(auswahl) * len(jahre))
    fehler = []
    for code, ebene, stichtag, was in auswahl:
        log.info("--- %s (%s, %s) %s ---", code, ebene, stichtag, was)
        for jahr in jahre:
            schon = query(f"""SELECT count(*)::text FROM {DB_SCHEMA}.{TABELLE}
                              WHERE tabelle = '{code}' AND jahr = {jahr};""")[0][0]
            if schon != "0":
                log.info("    %s: %s Zeilen bereits geladen", jahr, schon)
                continue
            t0 = time.time()
            d = hole(code, jahr)
            if d is None or d.empty:
                fehler.append((code, jahr))
                continue
            time.sleep(2)
            zeilen = zeilen_aus(d, code, ebene, jahr, heute)
            schreibe(zeilen)
            log.info("    %s: %s Lieferzeilen -> %s Werte (%.0f s)",
                     jahr, f"{len(d):,}".replace(",", "."),
                     f"{len(zeilen):,}".replace(",", "."), time.time() - t0)
    run_sql(INDIZES, "indizes")

    if fehler:
        log.warning("--- nicht geladen: %d Kombinationen ---", len(fehler))
        for code, jahr in fehler:
            log.warning("    %s %s", code, jahr)
    report()


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    for z in query(f"""
        SELECT tabelle, ebene, string_agg(DISTINCT jahr::text, ',' ORDER BY jahr::text),
               count(*)::text, count(DISTINCT schluessel)::text,
               string_agg(DISTINCT stichtag::text, ',' ORDER BY stichtag::text)
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1, 2 ORDER BY 2, 1;
    """):
        log.info("  %-16s %-9s %-24s %10s Werte, %6s Einheiten, %s",
                 z[0], z[1], z[2][:24], z[3], z[4], (z[5] or "")[:34])

    log.info("--- Deckung der Wahltagsgemeinden ---")
    for jahr, (wt, vor) in WAHLEN.items():
        for z in query(f"""
            WITH w AS (SELECT ags FROM raum.gemeindestand_stichtag
                       WHERE stichtag = DATE '{wt}'),
            hat AS (SELECT DISTINCT schluessel FROM {DB_SCHEMA}.{TABELLE}
                    WHERE ebene = 'gemeinde' AND jahr = {jahr}
                      AND length(schluessel) = 8),
            vorjahr AS (SELECT DISTINCT schluessel FROM {DB_SCHEMA}.{TABELLE}
                        WHERE ebene = 'gemeinde' AND jahr = {vor}
                          AND length(schluessel) = 8)
            SELECT (SELECT count(*)::text FROM w),
                   (SELECT count(*)::text FROM w WHERE ags IN (SELECT schluessel FROM hat)),
                   (SELECT count(*)::text FROM w
                    WHERE ags NOT IN (SELECT schluessel FROM hat)
                      AND ags IN (SELECT schluessel FROM vorjahr)),
                   (SELECT count(*)::text FROM w
                    WHERE ags NOT IN (SELECT schluessel FROM hat)
                      AND ags NOT IN (SELECT schluessel FROM vorjahr));
        """):
            log.info("  Wahl %d: %s Gemeinden am Wahltag | %s aus %d | %s aus %d | " "%s in keinem", jahr, z[0], z[1], jahr, z[2], vor, z[3])


if __name__ == "__main__":
    main()
