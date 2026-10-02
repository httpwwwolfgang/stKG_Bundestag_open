import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import (run_sql, run_sql_file, query,
                             _psql_args, _pg_env)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEMA = "parlamentsarbeit"
EXPORT = (Path(__file__).resolve().parents[2] / "02_clean"
          / "plenarprotokolle" / "export")
import zwischenstand


import lieferung
LIEFERUNG = "cpp_bt_fobbe"
ZWISCHEN = zwischenstand.fuer(__file__, "zwischen")
ARCHIV = zwischenstand.ordner("01_fetch", "dip",
                              "aktivitaeten_20260828")

DDL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};


CREATE TABLE IF NOT EXISTS {SCHEMA}.redner (
    redner_id            text PRIMARY KEY,
    kennungsart          text,
    titel                text,
    vorname              text,
    nachname             text,
    namenszusatz         text,
    ortszusatz           text,
    schreibweisen_anzahl integer,
    merkmale_anzahl      integer
);
COMMENT ON TABLE {SCHEMA}.redner IS
  'Sprecher-Kennungen des Protokolls. NICHT eindeutig pro Person: Wer als '
  'Abgeordnete und als Ministerin spricht, hat zwei Kennungen.';

CREATE TABLE IF NOT EXISTS {SCHEMA}.redner_merkmal (
    redner_id   text REFERENCES {SCHEMA}.redner(redner_id),
    art         text,
    wert        text,
    reden       integer,
    erste_rede  date,
    letzte_rede date,
    wahlperioden text
);
COMMENT ON COLUMN {SCHEMA}.redner_merkmal.erste_rede IS
  'Belegzeitraum im Protokoll — KEINE Amtszeit.';

CREATE TABLE IF NOT EXISTS {SCHEMA}.rede (
    rede_id          text PRIMARY KEY,
    redner_id        text REFERENCES {SCHEMA}.redner(redner_id),
    wahlperiode      integer NOT NULL,
    sitzung_nr       integer,
    sitzung_datum    date,
    protokoll_nr     text,
    fraktion         text,
    rolle_kurz       text,
    rolle_lang       text,
    redeart          text,
    redeart_quelle   text,
    seite            integer,
    quadrant         char(1),
    zeichen          integer,
    tokens           integer,
    saetze           integer,
    kommentare_anzahl integer
);
COMMENT ON COLUMN {SCHEMA}.rede.seite IS
  'Aus dem Inhaltsverzeichnis. Leer bei vier Protokollen (sonderfaelle PA16).';

CREATE TABLE IF NOT EXISTS {SCHEMA}.rede_text (
    rede_id text PRIMARY KEY REFERENCES {SCHEMA}.rede(rede_id),
    text    text
);
COMMENT ON TABLE {SCHEMA}.rede_text IS
  'Der Wortlaut, 290 Mio Zeichen. Eigene Tabelle, damit Abfragen auf '
  'Metadaten ihn nicht mitschleppen.';

CREATE TABLE IF NOT EXISTS {SCHEMA}.tagesordnungspunkt (
    protokoll_nr   text,
    top_id         text,
    lfd            integer,
    wahlperiode    integer,
    titel          text,
    titel_quelle   text,
    zusatztitel    text,
    drucksachen    text,
    reden          integer,
    PRIMARY KEY (protokoll_nr, top_id, lfd)
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.rede_tagesordnungspunkt (
    rede_id      text PRIMARY KEY REFERENCES {SCHEMA}.rede(rede_id),
    protokoll_nr text,
    top_id       text,
    lfd          integer,
    herkunft     text,
    FOREIGN KEY (protokoll_nr, top_id, lfd)
        REFERENCES {SCHEMA}.tagesordnungspunkt(protokoll_nr, top_id, lfd)
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.tagesordnungspunkt_sachgebiet (
    protokoll_nr text,
    top_id       text,
    lfd          integer,
    sachgebiet   text,
    drucksache   text,
    vorgang_id   text,
    vorgangstyp  text,
    FOREIGN KEY (protokoll_nr, top_id, lfd)
        REFERENCES {SCHEMA}.tagesordnungspunkt(protokoll_nr, top_id, lfd)
);
CREATE TABLE IF NOT EXISTS {SCHEMA}.tagesordnungspunkt_deskriptor (
    protokoll_nr text,
    top_id       text,
    lfd          integer,
    deskriptor   text,
    typ          text,
    vorgang_id   text,
    FOREIGN KEY (protokoll_nr, top_id, lfd)
        REFERENCES {SCHEMA}.tagesordnungspunkt(protokoll_nr, top_id, lfd)
);
COMMENT ON TABLE {SCHEMA}.tagesordnungspunkt_deskriptor IS
  'Deskriptoren der Vorlage, ueber die Drucksache des Punktes. Beschreiben '
  'die Vorlage, nicht den Beitrag — dafuer rede_deskriptor. Deutlich weniger '
  'Geographische Begriffe (4.489 gegen 21.678).';

COMMENT ON TABLE {SCHEMA}.tagesordnungspunkt_sachgebiet IS
  'Sachgebiet der Debatte, nicht der einzelnen Rede. Ein Punkt fasst bei '
  'verbundener Beratung mehrere Vorlagen zusammen und traegt dann mehrere '
  'Sachgebiete — 2.221 Punkte haben zwei, 536 mehr als sechs.';


CREATE TABLE IF NOT EXISTS {SCHEMA}.aktivitaet (
    aktivitaet_id   text PRIMARY KEY,
    person_id       text,
    titel           text,
    aktivitaetsart  text,
    wahlperiode     integer,
    datum           date,
    protokoll_nr    text,
    seite           integer,
    quadrant        char(1),
    anfangsseite    integer,
    endseite        integer,
    vorgang_ids     text,
    vorgangsbezug_anzahl integer
);
COMMENT ON COLUMN {SCHEMA}.aktivitaet.vorgangsbezug_anzahl IS
  'Bei 4.965 Aktivitaeten groesser als die Zahl der Ids: Das DIP liefert nur '
  'eine Vorschau mit Deckel 4 (Kurzdoku 2.3).';

CREATE TABLE IF NOT EXISTS {SCHEMA}.aktivitaet_deskriptor (
    aktivitaet_id text REFERENCES {SCHEMA}.aktivitaet(aktivitaet_id),
    lfd           integer,
    name          text,
    typ           text,
    PRIMARY KEY (aktivitaet_id, lfd)
);


CREATE TABLE IF NOT EXISTS {SCHEMA}.personenbruecke (
    person_id      text,
    redner_id      text,
    dip_titel      text,
    protokoll_name text,
    aktivitaeten   integer,
    reden          integer,
    lage           text
);
COMMENT ON TABLE {SCHEMA}.personenbruecke IS
  '1:n — dieselbe Person hat als Abgeordnete eine andere Kennung als als '
  'Ministerin. Gebildet ueber den Namen, siehe baue_personenbruecke.py.';

DROP TABLE IF EXISTS {SCHEMA}.rede_aktivitaet;
CREATE TABLE {SCHEMA}.rede_aktivitaet (
    rede_id       text NOT NULL REFERENCES {SCHEMA}.rede(rede_id),
    aktivitaet_id text REFERENCES {SCHEMA}.aktivitaet(aktivitaet_id),
    zuordnung     text NOT NULL,
    kandidaten    integer,
    UNIQUE NULLS NOT DISTINCT (rede_id, aktivitaet_id)
);
COMMENT ON COLUMN {SCHEMA}.rede_aktivitaet.zuordnung IS
  'fundstelle_und_person | nur_person | im_bereich | dip_namensfehler = '
  'zugeordnet. person_passt_nicht | offen = geprueft und verworfen. '
  'unbekannt = geprueft, das DIP fuehrt nichts dazu; dann ist '
  'aktivitaet_id leer. Regeln in.';
COMMENT ON COLUMN {SCHEMA}.rede_aktivitaet.aktivitaet_id IS
  'NULL nur bei zuordnung = unbekannt. Jede Rede hat mindestens eine Zeile: '
  'entweder eine Aktivitaet oder den ausdruecklichen Vermerk, dass keine '
  'gefunden wurde. Eine fehlende Zeile gibt es nicht.';


CREATE TABLE IF NOT EXISTS {SCHEMA}.rede_deskriptor (
    rede_id    text REFERENCES {SCHEMA}.rede(rede_id),
    deskriptor text,
    typ        text,
    belege     integer,
    PRIMARY KEY (rede_id, deskriptor, typ)
);

CREATE INDEX IF NOT EXISTS rede_protokoll_idx
    ON {SCHEMA}.rede (protokoll_nr, seite, quadrant);
CREATE INDEX IF NOT EXISTS rede_redner_idx   ON {SCHEMA}.rede (redner_id);
CREATE INDEX IF NOT EXISTS akt_person_idx    ON {SCHEMA}.aktivitaet (person_id);
CREATE INDEX IF NOT EXISTS desk_typ_idx      ON {SCHEMA}.rede_deskriptor (typ);
"""


def ohne_leere_kennung(d):
    return d[d["redner_id"].astype(str).str.strip() != ""].copy()


def rede_anreichern(d):
    art = pd.read_csv(neueste("redeart_2*.csv"), sep=";", dtype=str,
                      keep_default_na=False)
    fund = pd.read_csv(neueste("fundstelle_2*.csv"), sep=";", dtype=str,
                       keep_default_na=False)
    d = d.merge(art[["rede_id", "redeart", "redeart_quelle"]],
                on="rede_id", how="left")
    d = d.merge(fund[["rede_id", "seite", "quadrant"]].drop_duplicates("rede_id"),
                on="rede_id", how="left")
    for s in ["seite", "quadrant", "redeart_quelle"]:
        d[s] = d[s].replace({"": None})


    d.loc[~d["quadrant"].isin(list("ABCD")), "quadrant"] = None

    d["redner_id"] = d["redner_id"].replace({"": None, "nan": None,
                                             "None": None})
    return ganzzahl(["tokens", "saetze", "zeichen", "sitzung_nr",
                     "kommentare_anzahl"])(d)


def top_zuordnung(d):
    d = d.copy()
    d["herkunft"] = "struktur"
    dazu = pd.read_csv(neueste("anlage_rede_tagesordnungspunkt_*.csv"),
                       sep=";", dtype=str, keep_default_na=False)
    print(f"  {len(dazu):,} Anlagen-Reden aus dem Anlagenkopf ergaenzt")
    return pd.concat([d, dazu], ignore_index=True).drop_duplicates("rede_id")


def aktivitaet_aufbereiten(d):
    teile = d["seite"].astype(str).str.extract(r"^(\d+)\s*([A-D])$")
    d["seite"] = teile[0]
    d["quadrant"] = teile[1]
    for s in ["wahlperiode", "datum", "anfangsseite", "endseite",
              "vorgangsbezug_anzahl", "seite"]:
        d[s] = d[s].replace({"": None})
    return d


def bericht():
    print(f"\n{'=' * 66}")
    zeilen = query(f"""
        SELECT relname, n_live_tup FROM pg_stat_user_tables
        WHERE schemaname = '{SCHEMA}' ORDER BY relname;""")
    for name, n in zeilen:
        print(f"  {int(n):>9,}  {SCHEMA}.{name}")

    print("\n  Zuordnung Rede <-> Aktivitaet:")
    for art, n in query(f"""
            SELECT zuordnung, count(*) FROM {SCHEMA}.rede_aktivitaet
            GROUP BY zuordnung ORDER BY count(*) DESC;"""):
        print(f"    {int(n):>8,}  {art}")

    n = query(f"""
        SELECT count(DISTINCT rede_id) FROM {SCHEMA}.rede_aktivitaet
        WHERE zuordnung IN ('fundstelle_und_person','nur_person',
                            'im_bereich','dip_namensfehler');""")[0][0]
    ges = query(f"SELECT count(*) FROM {SCHEMA}.rede;")[0][0]
    print(f"\n  {int(n):,} von {int(ges):,} Reden haben eine Aktivitaet")

    n = query(f"SELECT count(DISTINCT rede_id) FROM {SCHEMA}.rede_deskriptor;")[0][0]
    print(f"  {int(n):,} Reden haben mindestens einen Deskriptor")


def neueste(muster, ordner=None):
    treffer = sorted((ordner or EXPORT).glob(muster))
    if not treffer:
        raise SystemExit(f"Keine Datei zu {muster}")
    return treffer[-1]


def lade(tabelle, quelle, spalten, umbenennen=None, wandeln=None,
         trenner=";"):
    if quelle.suffix == ".parquet":
        d = pd.read_parquet(quelle)
    else:
        d = pd.read_csv(quelle, sep=trenner, dtype=str, keep_default_na=False)
    if umbenennen:
        d = d.rename(columns=umbenennen)
    if wandeln:
        d = wandeln(d)

    fehlend = [s for s in spalten if s not in d.columns]
    if fehlend:
        raise SystemExit(f"{tabelle}: Spalten fehlen in {quelle.name}: {fehlend}")

    tmp = ZWISCHEN / f"{tabelle}.csv"
    d[spalten].to_csv(tmp, index=False, sep="\t", na_rep="",
                      quoting=csv.QUOTE_MINIMAL, encoding="utf-8")

    run_sql(f"TRUNCATE {SCHEMA}.{tabelle} CASCADE;", tabelle)
    befehl = (fr"\copy {SCHEMA}.{tabelle} ({', '.join(spalten)}) "
              fr"FROM '{tmp.as_posix()}' WITH (FORMAT csv, HEADER true, "
              fr"DELIMITER E'\t')")
    proc = subprocess.run(_psql_args() + ["-c", befehl], env=_pg_env(),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"{tabelle} laden fehlgeschlagen:\n{proc.stderr}")
    n = query(f"SELECT count(*) FROM {SCHEMA}.{tabelle};")[0][0]
    print(f"  {int(n):>9,}  {tabelle:<26} aus {quelle.name}")
    return int(n)


def leer_zu_null(spalten):
    def f(d):
        d = d.copy()
        for s in spalten:
            if s in d.columns:
                d[s] = d[s].replace({"": None, "nan": None, "None": None})
        return d
    return f


def ganzzahl(spalten):
    def f(d):
        d = d.copy()
        for s in spalten:
            if s in d.columns:
                d[s] = (pd.to_numeric(d[s], errors="coerce")
                        .astype("Int64").astype(object)
                        .where(lambda x: x.notna(), None))
        return d
    return f


def main():
    lieferung.merke(LIEFERUNG)
    ZWISCHEN.mkdir(parents=True, exist_ok=True)
    print(f"Schema {SCHEMA} anlegen")


    ddl = ZWISCHEN / "schema.sql"
    ddl.write_text(DDL, encoding="utf-8")
    run_sql_file(ddl, "Schema")
    print("  Tabellen stehen.\n")
    print("Laden — Reihenfolge folgt den Fremdschluesseln:\n")


    lade("redner", neueste("redner_2*.csv"),
         ["redner_id", "kennungsart", "titel", "vorname", "nachname",
          "namenszusatz", "ortszusatz", "schreibweisen_anzahl",
          "merkmale_anzahl"],
         wandeln=lambda d: leer_zu_null(["schreibweisen_anzahl",
                                         "merkmale_anzahl"])(
             ohne_leere_kennung(d)))

    lade("redner_merkmal", neueste("redner_merkmal_*.csv"),
         ["redner_id", "art", "wert", "reden", "erste_rede", "letzte_rede",
          "wahlperioden"],
         wandeln=leer_zu_null(["reden", "erste_rede", "letzte_rede"]))

    lade("rede", neueste("rede_2*.parquet"),
         ["rede_id", "redner_id", "wahlperiode", "sitzung_nr",
          "sitzung_datum", "protokoll_nr", "fraktion", "rolle_kurz",
          "rolle_lang", "redeart", "redeart_quelle", "seite", "quadrant",
          "zeichen", "tokens", "saetze", "kommentare_anzahl"],
         wandeln=rede_anreichern)

    lade("rede_text", neueste("rede_2*.parquet"), ["rede_id", "text"])

    lade("tagesordnungspunkt", neueste("tagesordnungspunkt_2*.csv"),
         ["protokoll_nr", "top_id", "lfd", "wahlperiode", "titel",
          "titel_quelle", "zusatztitel", "drucksachen", "reden"],
         wandeln=leer_zu_null(["lfd", "wahlperiode", "reden"]))

    lade("rede_tagesordnungspunkt", neueste("rede_tagesordnungspunkt_2*.csv"),
         ["rede_id", "protokoll_nr", "top_id", "lfd", "herkunft"],
         wandeln=top_zuordnung)

    lade("tagesordnungspunkt_sachgebiet", neueste("top_sachgebiet_2*.csv"),
         ["protokoll_nr", "top_id", "lfd", "sachgebiet", "drucksache",
          "vorgang_id", "vorgangstyp"])

    lade("tagesordnungspunkt_deskriptor", neueste("top_deskriptor_2*.csv"),
         ["protokoll_nr", "top_id", "lfd", "deskriptor", "typ",
          "vorgang_id"])


    lade("aktivitaet", ARCHIV / "aktivitaet_20260828_011252.csv",
         ["aktivitaet_id", "person_id", "titel", "aktivitaetsart",
          "wahlperiode", "datum", "protokoll_nr", "seite", "quadrant",
          "anfangsseite", "endseite", "vorgang_ids", "vorgangsbezug_anzahl"],
         wandeln=aktivitaet_aufbereiten)

    lade("aktivitaet_deskriptor",
         ARCHIV / "aktivitaet_deskriptor_20260828_011252.csv",
         ["aktivitaet_id", "lfd", "name", "typ"])


    lade("personenbruecke", neueste("personenbruecke_2*.csv"),
         ["person_id", "redner_id", "dip_titel", "protokoll_name",
          "aktivitaeten", "reden", "lage"],
         wandeln=leer_zu_null(["redner_id", "aktivitaeten", "reden"]))

    lade("rede_aktivitaet", neueste("rede_aktivitaet_2*.csv"),
         ["rede_id", "aktivitaet_id", "zuordnung", "kandidaten"],
         wandeln=leer_zu_null(["kandidaten", "aktivitaet_id"]))


    lade("rede_deskriptor", neueste("rede_deskriptor_2*.csv"),
         ["rede_id", "deskriptor", "typ", "belege"],
         wandeln=leer_zu_null(["belege"]))

    bericht()


if __name__ == "__main__":
    main()
