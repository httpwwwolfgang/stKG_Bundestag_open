import json
import logging
import re
import sys
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

import lieferung


LIEFERUNG        = "bt_ausgeschiedene"


SCHEMA = "roh_bundestag"
BASIS = "https://www.bundestag.de"

QUELLE = (Path(__file__).resolve().parents[4] / "Daten" / "politiker_innen"
          / "bundestag_ausgeschiedene")


KOPF_AUSGESCHIEDEN = "ausgeschieden"
KOPF_NACHFOLGER = "nachfolger"
KOPF_NAMEN = ["zuvor", "jetzt", "fraktion", "datum"]

BERLIN_KATEGORIEN = ["Direktmandate", "Listenmandate",
                     "Mandatsverluste", "Mandatsgewinne"]

TODESZEICHEN = "†"
DATUM = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})(.*)$", re.S)
WK_NUMMER = re.compile(r"\(WK\s*(\d+)\)")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("nachfolge")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};

CREATE TABLE IF NOT EXISTS {SCHEMA}.nachfolge (
    wp                   SMALLINT NOT NULL,
    lfd                  SMALLINT NOT NULL,
    ausgeschieden_am     DATE,
    ausgeschieden_roh    TEXT,
    verstorben           BOOLEAN NOT NULL,
    vorgaenger_roh       TEXT,
    vorgaenger_name      TEXT,
    vorgaenger_fraktion  TEXT,
    vorgaenger_url       TEXT,
    vorgaenger_link_anzahl SMALLINT,
    nachfolger_benannt   BOOLEAN NOT NULL,
    nachfolger_roh       TEXT,
    nachfolger_name      TEXT,
    nachfolger_fraktion  TEXT,
    nachfolger_url       TEXT,
    nachfolger_link_anzahl SMALLINT,
    eingetreten_am       DATE,
    eingetreten_roh      TEXT,
    hinweis              TEXT,
    quelle_url           TEXT NOT NULL,
    abgerufen_am         DATE NOT NULL,
    PRIMARY KEY (wp, lfd)
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.namensaenderung (
    wp             SMALLINT NOT NULL,
    lfd            SMALLINT NOT NULL,
    zuvor          TEXT,
    jetzt          TEXT,
    jetzt_url      TEXT,
    fraktion       TEXT,
    geaendert_am   DATE,
    geaendert_roh  TEXT,
    quelle_url     TEXT NOT NULL,
    abgerufen_am   DATE NOT NULL,
    PRIMARY KEY (wp, lfd)
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.wiederholungswahl_berlin (
    lfd           SMALLINT PRIMARY KEY,
    kategorie     TEXT NOT NULL,
    person_roh    TEXT,
    person_url    TEXT,
    partei        TEXT,
    gebiet_art    TEXT,
    gebiet_roh    TEXT,
    wkr_nr        SMALLINT,
    status        TEXT,
    quelle_url    TEXT NOT NULL,
    abgerufen_am  DATE NOT NULL
);

ALTER TABLE {SCHEMA}.nachfolge
    ADD COLUMN IF NOT EXISTS vorgaenger_link_anzahl SMALLINT;
ALTER TABLE {SCHEMA}.nachfolge
    ADD COLUMN IF NOT EXISTS nachfolger_link_anzahl SMALLINT;

COMMENT ON COLUMN {SCHEMA}.nachfolge.nachfolger_link_anzahl IS
 'Zahl der Links in der Zelle. Bei mehr als einem bleibt die URL NULL - '
 'welcher gemeint ist, geht aus der Seite nicht hervor. Kommt vor, weil ein '
 'Name mitten im Wort zerschnitten und die erste Haelfte falsch verlinkt ist '
 '(WP 19 Zeile 41, Carola Reimann).';

COMMENT ON TABLE {SCHEMA}.nachfolge IS
 'Ausgeschiedene Abgeordnete und deren Nachfolger, Deutscher Bundestag, je '
 'Wahlperiode eine Seite. Enthaelt KEINEN Personenschluessel - die IDs in den '
 'Links sind Redaktionssystem-IDs und wechseln je Wahlperiode.';
COMMENT ON COLUMN {SCHEMA}.nachfolge.nachfolger_benannt IS
 'FALSE, wenn die Zelle keine Person nennt (Sitz unbesetzt, kein '
 'Listennachfolger, Mandat durch Wiederholungswahl entfallen). Erkannt am '
 'fehlenden Link, nicht am Wortlaut.';
COMMENT ON COLUMN {SCHEMA}.nachfolge.verstorben IS
 'Kreuzzeichen in der Ausscheidenszelle: der Bundestag markiert damit, dass '
 'das Mandat durch Tod endete.';
COMMENT ON COLUMN {SCHEMA}.namensaenderung.jetzt IS
 'Der Name, unter dem die Person spaeter gefuehrt wird. Noetig fuer jeden '
 'Namensabgleich: die Quellen nennen sie mal so, mal so.';
"""


def sql_wert(wert):
    if wert is None:
        return "NULL"
    if isinstance(wert, bool):
        return "TRUE" if wert else "FALSE"
    if isinstance(wert, int):
        return str(wert)
    return "'" + str(wert).replace("'", "''") + "'"


def datum(roh, wo):
    inhalt = (roh or "").replace("\xa0", " ").strip()
    if not inhalt:
        return None
    treffer = DATUM.match(inhalt)
    if not treffer:
        raise SystemExit(f"Unlesbares Datum '{roh}' bei {wo} - Lauf abgebrochen.")
    return f"{treffer[3]}-{treffer[2]}-{treffer[1]}"


def text(zelle):
    roh = zelle.get_text("").replace("\xa0", " ")
    return re.sub(r"\s+", " ", roh).strip() or None


def link(zelle):
    anker = zelle.find_all("a")
    if len(anker) != 1:
        return None, len(anker)
    url = anker[0].get("href") or None
    if url and url.startswith("/"):
        url = BASIS + url
    return url, 1


def name_und_fraktion(roh):
    name, komma, fraktion = (roh or "").rpartition(", ")
    return (name, fraktion) if komma else (roh, None)


def person(zelle):
    roh = text(zelle)
    url, anzahl = link(zelle)
    if anzahl == 0:
        return roh, None, None, None, 0
    name, fraktion = name_und_fraktion(roh)
    return roh, name, fraktion, url, anzahl


def suppe(datei):
    baum = BeautifulSoup(datei.read_text(encoding="utf-8"), "html.parser")
    for span in baum.find_all("span"):
        if "--hidden" in (span.get("class") or []):
            span.decompose()
    return baum


def kopf(tabelle):
    erste = tabelle.find("tr")
    if erste is None:
        return []
    return [(z.get_text(" ", strip=True) or "").lower()
            for z in erste.find_all(["th", "td"])]


def lies_wahlperiode(datei, wp, quelle_url, abgerufen_am):
    baum = suppe(datei)
    nachfolge, namen, uebergangen = [], [], []

    for tabelle in baum.find_all("table"):
        spalten_kopf = kopf(tabelle)
        zeilen = tabelle.find_all("tr")[1:]

        if (len(spalten_kopf) == 4
                and spalten_kopf[0].startswith(KOPF_AUSGESCHIEDEN)
                and KOPF_NACHFOLGER in spalten_kopf[2]):
            for lfd, zeile in enumerate(zeilen, 1):
                zellen = zeile.find_all("td")
                wo = f"WP {wp} Zeile {lfd}"
                if len(zellen) == 4:
                    v_roh, v_name, v_frak, v_url, v_links = person(zellen[1])
                    n_roh, n_name, n_frak, n_url, n_links = person(zellen[2])
                    aus_roh = text(zellen[0])
                    ein_roh = text(zellen[3])
                    hinweis = None
                elif len(zellen) == 3:


                    v_roh, v_name, v_frak, v_url, v_links = person(zellen[1])
                    n_roh = n_name = n_frak = n_url = None
                    n_links = 0
                    aus_roh = text(zellen[0])
                    ein_roh = None
                    hinweis = text(zellen[2])
                else:
                    raise SystemExit(
                        f"{wo}: {len(zellen)} Spalten statt 3 oder 4 - "
                        f"Seitenaufbau geaendert, Lauf abgebrochen.")

                nachfolge.append((
                    wp, lfd,
                    datum(aus_roh, f"{wo} ausgeschieden"), aus_roh,
                    TODESZEICHEN in (aus_roh or ""),
                    v_roh, v_name, v_frak, v_url, v_links,
                    n_links > 0, n_roh, n_name, n_frak, n_url, n_links,
                    datum(ein_roh, f"{wo} eingetreten"), ein_roh,
                    hinweis, quelle_url, abgerufen_am,
                ))

        elif spalten_kopf[:4] == KOPF_NAMEN:
            for lfd, zeile in enumerate(zeilen, 1):
                zellen = zeile.find_all("td")
                wo = f"WP {wp} Namensaenderung Zeile {lfd}"
                if len(zellen) != 4:
                    raise SystemExit(
                        f"{wo}: {len(zellen)} Spalten statt 4 - Lauf abgebrochen.")


                j_url, _ = link(zellen[1])
                roh = text(zellen[3])
                namen.append((
                    wp, lfd, text(zellen[0]), text(zellen[1]), j_url,
                    text(zellen[2]),
                    datum(roh, wo), roh, quelle_url, abgerufen_am,
                ))

        else:
            uebergangen.append(spalten_kopf[:4])

    for spalten_kopf in uebergangen:
        log.info("WP %s: Tabelle uebergangen, Kopfzeile %s", wp, spalten_kopf)
    return nachfolge, namen


def lies_berlin(datei, quelle_url, abgerufen_am):
    baum = suppe(datei)
    zeilen, gefunden = [], []
    lfd = 0

    for tabelle in baum.find_all("table"):
        beschriftung = tabelle.find("caption")
        if beschriftung is None:
            continue
        kategorie = beschriftung.get_text(" ", strip=True)
        if kategorie not in BERLIN_KATEGORIEN:
            continue
        gefunden.append(kategorie)

        spalten_kopf = kopf(tabelle)
        gebiet_art = spalten_kopf[2].capitalize() if len(spalten_kopf) > 2 else None

        for zeile in tabelle.find_all("tr")[1:]:
            zellen = zeile.find_all("td")
            if len(zellen) != 3:
                raise SystemExit(
                    f"Berlin/{kategorie}: {len(zellen)} Spalten statt 3 - "
                    f"Seitenaufbau geaendert, Lauf abgebrochen.")


            if not text(zellen[0]):
                if not zeilen:
                    raise SystemExit(
                        f"Berlin/{kategorie}: Statuszeile ohne vorangehende "
                        f"Personenzeile - Lauf abgebrochen.")
                letzte = list(zeilen[-1])
                letzte[8] = text(zellen[2])
                zeilen[-1] = tuple(letzte)
                continue

            lfd += 1

            p_url, _ = link(zellen[0])
            gebiet = text(zellen[2])
            treffer = WK_NUMMER.search(gebiet or "")
            zeilen.append((
                lfd, kategorie, text(zellen[0]), p_url, text(zellen[1]),
                gebiet_art, gebiet, int(treffer[1]) if treffer else None,
                None, quelle_url, abgerufen_am,
            ))

    fehlend = [k for k in BERLIN_KATEGORIEN if k not in gefunden]
    if fehlend:
        raise SystemExit(f"Berlin: Teiltabellen fehlen: {fehlend} - "
                         f"Seitenaufbau geaendert, Lauf abgebrochen.")
    return zeilen


def schreibe_insert(datei, tabelle, spalten, zeilen, schluessel):
    if not zeilen:
        return
    setzen = ",\n    ".join(f"{s} = EXCLUDED.{s}"
                            for s in spalten if s not in schluessel)
    datei.write(f"INSERT INTO {SCHEMA}.{tabelle} ({', '.join(spalten)}) VALUES\n")
    datei.write(",\n".join("(" + ", ".join(sql_wert(w) for w in z) + ")"
                           for z in zeilen))
    datei.write(f"\nON CONFLICT ({', '.join(schluessel)}) DO UPDATE SET\n    "
                f"{setzen};\n\n")


def bericht():
    log.info("--- Ergebnis ---")
    for wp, n, benannt, verstorben in query(f"""
            SELECT wp, count(*), count(*) FILTER (WHERE nachfolger_benannt),
                   count(*) FILTER (WHERE verstorben)
              FROM {SCHEMA}.nachfolge GROUP BY wp ORDER BY wp;"""):
        log.info("WP %s: %s Ausscheiden, davon %s mit benanntem Nachfolger, " "%s durch Tod", wp, n, benannt, verstorben)

    log.info("Ohne benannten Nachfolger:")
    for wp, lfd, vor, aus, nach, hin in query(f"""
            SELECT wp, lfd, vorgaenger_name, ausgeschieden_am,
                   coalesce(nachfolger_roh, '-'), coalesce(hinweis, '-')
              FROM {SCHEMA}.nachfolge WHERE NOT nachfolger_benannt
             ORDER BY wp, lfd;"""):
        log.info("   WP %s/%s  %s, %s  ->  %s | %s", wp, lfd, vor, aus, nach, hin)

    log.info("Zellen mit mehr als einem Link (URL bleibt NULL):")
    mehrfach = query(f"""
        SELECT wp, lfd, coalesce(vorgaenger_name, '-'),
               coalesce(nachfolger_name, '-'),
               vorgaenger_link_anzahl, nachfolger_link_anzahl
          FROM {SCHEMA}.nachfolge
         WHERE vorgaenger_link_anzahl > 1 OR nachfolger_link_anzahl > 1
         ORDER BY wp, lfd;""")
    if mehrfach:
        for wp, lfd, vor, nach, vl, nl in mehrfach:
            log.info("   WP %s Zeile %s: %s (%s Links) -> %s (%s Links)",
                     wp, lfd, vor, vl, nach, nl)
    else:
        log.info("   keine")

    for wp, n in query(f"""SELECT wp, count(*) FROM {SCHEMA}.namensaenderung
                            GROUP BY wp ORDER BY wp;"""):
        log.info("WP %s: %s Namensaenderungen", wp, n)

    for kat, n, mit_wk in query(f"""
            SELECT kategorie, count(*), count(wkr_nr)
              FROM {SCHEMA}.wiederholungswahl_berlin
             GROUP BY kategorie ORDER BY kategorie;"""):
        log.info("Berlin/%s: %s Zeilen, %s mit Wahlkreisnummer", kat, n, mit_wk)


def main():
    lieferung.merke(LIEFERUNG)
    manifest_pfad = QUELLE / "abruf.json"
    if not manifest_pfad.exists():
        raise SystemExit(f"Kein Abruf-Manifest: {manifest_pfad}. Zuerst "
                         f"01_fetch/bundestag/hole_ausgeschiedene.py.")
    manifest = json.loads(manifest_pfad.read_text(encoding="utf-8"))

    nachfolge, namen, berlin = [], [], []
    for eintrag in manifest.values():
        datei = QUELLE / eintrag["datei"]
        if not datei.exists():
            raise SystemExit(f"Datei aus dem Manifest fehlt: {datei}")
        log.info("Lese %s (Abruf %s, sha256 %s)", datei.name,
                 eintrag["abgerufen_am"], eintrag["sha256"][:16])

        if eintrag["wahlperiode"] is None:
            berlin = lies_berlin(datei, eintrag["url"], eintrag["abgerufen_am"])
        else:
            a, b = lies_wahlperiode(datei, eintrag["wahlperiode"],
                                    eintrag["url"], eintrag["abgerufen_am"])
            nachfolge += a
            namen += b

    log.info("Gelesen: %d Nachfolgezeilen, %d Namensaenderungen, %d Zeilen " "Berlin", len(nachfolge), len(namen), len(berlin))

    run_sql(DDL, "roh_bundestag.nachfolge anlegen")

    tmp = Path(tempfile.gettempdir()) / "bundestag_nachfolge.sql"
    with tmp.open("w", encoding="utf-8") as f:
        schreibe_insert(f, "nachfolge",
                        ["wp", "lfd", "ausgeschieden_am", "ausgeschieden_roh",
                         "verstorben", "vorgaenger_roh", "vorgaenger_name",
                         "vorgaenger_fraktion", "vorgaenger_url",
                         "vorgaenger_link_anzahl",
                         "nachfolger_benannt", "nachfolger_roh",
                         "nachfolger_name", "nachfolger_fraktion",
                         "nachfolger_url", "nachfolger_link_anzahl",
                         "eingetreten_am", "eingetreten_roh",
                         "hinweis", "quelle_url", "abgerufen_am"],
                        nachfolge, ["wp", "lfd"])
        schreibe_insert(f, "namensaenderung",
                        ["wp", "lfd", "zuvor", "jetzt", "jetzt_url",
                         "fraktion", "geaendert_am", "geaendert_roh",
                         "quelle_url", "abgerufen_am"], namen, ["wp", "lfd"])
        schreibe_insert(f, "wiederholungswahl_berlin",
                        ["lfd", "kategorie", "person_roh", "person_url",
                         "partei", "gebiet_art", "gebiet_roh", "wkr_nr",
                         "status", "quelle_url", "abgerufen_am"],
                        berlin, ["lfd"])
    log.info("SQL geschrieben: %s (%.1f kB)", tmp, tmp.stat().st_size / 1e3)

    run_sql_file(tmp, "bundestag-nachfolge")
    bericht()


if __name__ == "__main__":
    main()
