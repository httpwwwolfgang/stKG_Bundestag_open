import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import (run_sql, run_sql_file, query,
                             _psql_args, _pg_env)
import fraktionen as fr
import korrekturen

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEMA = "politiker_innen"
HIER = Path(__file__).resolve().parent
import zwischenstand
ZWISCHEN = zwischenstand.fuer(__file__, "zwischen")
ZIEL = zwischenstand.fuer(__file__)
KOMMENTARE = (HIER.parents[1] / "02_clean" / "plenarprotokolle"
              / "export")
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"


QUELLEN = [
    ("parlamentsarbeit.rede.fraktion",
     "select fraktion, count(*) from parlamentsarbeit.rede " "where fraktion is not null and fraktion <> '' group by 1"),
    ("politiker_innen.fraktionszugehoerigkeit.fraktion",
     "select fraktion, count(*) from politiker_innen.fraktionszugehoerigkeit " "where wp >= 18 group by 1"),
    ("politiker_innen.fraktion.kurzname",
     "select kurzname, count(*) from politiker_innen.fraktion group by 1"),
    ("politiker_innen.mandat.fraction_label",
     "select fraction_label, count(*) from politiker_innen.mandat " "where fraction_label is not null group by 1"),


    ("politiker_innen.stimme_bt.fraktion_roh",
     "select fraktion_roh, count(*) from politiker_innen.stimme_bt " "where fraktion_roh is not null group by 1"),
]

DDL = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.fraktion_kanonisch (
    fraktion_id text PRIMARY KEY,
    name        text NOT NULL,
    partei      text
);
COMMENT ON TABLE {SCHEMA}.fraktion_kanonisch IS
  'Fraktionen und Gruppen als Knoten. name ist der Name im Graphen. '
  'Ob und wann sie bestanden, steht in fraktion_zeitraum.';
COMMENT ON COLUMN {SCHEMA}.fraktion_kanonisch.partei IS
  'Traegende Partei. Bei fraktionslos leer, weil es keine gibt.';

CREATE TABLE IF NOT EXISTS {SCHEMA}.fraktion_zeitraum (
    fraktion_id  text NOT NULL REFERENCES {SCHEMA}.fraktion_kanonisch,
    wahlperiode  smallint NOT NULL,
    art          text NOT NULL,
    von          date NOT NULL,
    bis          date,
    bis_herkunft text NOT NULL,
    mitglieder   integer NOT NULL,
    amtliche_bezeichnung text NOT NULL,
    PRIMARY KEY (fraktion_id, wahlperiode, art)
);
COMMENT ON TABLE {SCHEMA}.fraktion_zeitraum IS
  'Bestand je Fraktion/Gruppe und Wahlperiode aus den amtlichen '
  'Stammdaten des Bundestages. Die Linke steht in WP 20 zweimal: als '
  'Fraktion bis 05.12.2023 und als Gruppe ab 02.02.2024.';
COMMENT ON COLUMN {SCHEMA}.fraktion_zeitraum.art IS
  'fraktion | gruppe | fraktionslos — aus dem amtlichen Namen gelesen.';
COMMENT ON COLUMN {SCHEMA}.fraktion_zeitraum.bis IS
  'Nur gesetzt, wenn JEDE Mitgliedschaft ein Enddatum hat. Sonst NULL. '
  'Siehe bis_herkunft — der Wert ist abgeleitet, nicht geliefert.';

CREATE TABLE IF NOT EXISTS {SCHEMA}.fraktion_alias (
    quelle       text NOT NULL,
    schreibweise text NOT NULL,
    fraktion_id  text REFERENCES {SCHEMA}.fraktion_kanonisch,
    wahlperiode  smallint,
    treffer      bigint NOT NULL,
    PRIMARY KEY (quelle, schreibweise)
);
COMMENT ON TABLE {SCHEMA}.fraktion_alias IS
  'Jede Schreibweise, die irgendeine Quelle liefert, mit dem Knoten, den '
  'sie meint. Die rohe Form bleibt erhalten: Wer nur die CSU-Rufe will, '
  'filtert auf schreibweise = CSU.';
COMMENT ON COLUMN {SCHEMA}.fraktion_alias.wahlperiode IS
  'Nur gesetzt, wenn die Schreibweise die Legislatur mitfuehrt '
  '(Abgeordnetenwatch: SPD (Bundestag 2021 - 2025)).';

DROP TABLE IF EXISTS parlamentsarbeit.redner_mdb;
CREATE TABLE parlamentsarbeit.redner_mdb (
    redner_id text PRIMARY KEY REFERENCES parlamentsarbeit.redner,
    mdb_id    text,
    herkunft  text NOT NULL,
    beleg     text
);
COMMENT ON TABLE parlamentsarbeit.redner_mdb IS
  'Verbindet die Sprecherkennung des Protokolls mit der Kennung der '
  'Bundestagsverwaltung. Ueber diese Tabelle laeuft der Weg zu den '
  'amtlichen Stammdaten und weiter zu Abgeordnetenwatch, Mandat und '
  'Wahlkreis (TODO E).';
COMMENT ON COLUMN parlamentsarbeit.redner_mdb.mdb_id IS
  'NULL, wenn die Zuordnung offen ist — Gaeste, Bundesratsmitglieder und '
  'Behelfskennungen ohne Beleg. Es wird nichts geraten (Regel 8).';
COMMENT ON COLUMN parlamentsarbeit.redner_mdb.herkunft IS
  'kennung_des_bundestages: die Protokollkennung ist bereits die richtige. '
  'behelfskennung_aufgeloest: aus korrekturen.BEHELFSKENNUNG, mit Beleg. '
  'behelfskennung_regierung_aufgeloest: aus '
  'korrekturen.BEHELFSKENNUNG_REGIERUNG, anderer Beleg (siehe dort). '
  'offen: keine Zuordnung.';

DROP TABLE IF EXISTS parlamentsarbeit.rede_fraktion;
CREATE TABLE parlamentsarbeit.rede_fraktion (
    rede_id           text PRIMARY KEY REFERENCES parlamentsarbeit.rede,
    fraktion_roh      text,
    fraktion_roh_id   text REFERENCES {SCHEMA}.fraktion_kanonisch,
    fraktion_id       text REFERENCES {SCHEMA}.fraktion_kanonisch,
    fraktion_herkunft text NOT NULL,
    belegt            boolean NOT NULL,
    mehrdeutig        boolean NOT NULL,
    amtliche_fraktion text
);
COMMENT ON COLUMN parlamentsarbeit.rede_fraktion.fraktion_herkunft IS
  'stammdaten: genau eine belegte Zugehoerigkeit am Sitzungstag. '
  'protokoll_entscheidet: die Stammdaten fuehren zwei, und das Protokoll '
  'nennt eine davon (5 Reden am 02.02.2024, dem Gruendungstag der Gruppen). '
  'offen: keine Zuordnung, fraktion_id bleibt leer.';
COMMENT ON TABLE parlamentsarbeit.rede_fraktion IS
  'Trennt zwei Dinge, die das Protokoll in einer Spalte fuehrt: was dort '
  'steht (fraktion_roh) und welche Fraktionszugehoerigkeit die amtlichen '
  'Stammdaten am Sitzungstag belegen (fraktion_id, amtliche_fraktion).';
COMMENT ON COLUMN parlamentsarbeit.rede_fraktion.fraktion_roh IS
  'Der Eintrag des Protokolls, unveraendert. Bei Rednern ohne Mandat ist '
  'das die Partei, nicht die Fraktion.';
COMMENT ON COLUMN parlamentsarbeit.rede_fraktion.fraktion_roh_id IS
  'Derselbe Eintrag auf einen Knoten normiert — nur eine Schreibweisen-'
  'Frage, keine Aussage darueber, ob die Fraktion bestand.';
COMMENT ON COLUMN parlamentsarbeit.rede_fraktion.fraktion_id IS
  'Die Fraktion, der die Rede zugeordnet wird. Gesetzt nur, wenn die '
  'Stammdaten fuer den Sitzungstag GENAU EINE Zugehoerigkeit belegen. '
  'Wer nicht im Bundestag sass, bekommt hier NULL — Westerwelle und '
  'Koenigshaus stehen im Protokoll als FDP, gehoerten aber keiner '
  'FDP-Fraktion an (in WP 18 gab es keine). Ihr Eintrag bleibt in '
  'fraktion_roh erhalten.';
COMMENT ON COLUMN parlamentsarbeit.rede_fraktion.belegt IS
  'Wahr, wenn die Person am Sitzungstag laut amtlichen Stammdaten einer '
  'Fraktion angehoerte.';
COMMENT ON COLUMN parlamentsarbeit.rede_fraktion.mehrdeutig IS
  'Wahr, wenn die Stammdaten fuer den Sitzungstag mehr als eine '
  'Zugehoerigkeit fuehren. Dann bleibt fraktion_id leer und in '
  'amtliche_fraktion stehen alle, getrennt durch | — es wird keine '
  'ausgewaehlt (Regel 8).';
"""

REDE_FRAKTION = """
INSERT INTO parlamentsarbeit.rede_fraktion
     (rede_id, fraktion_roh, fraktion_roh_id, fraktion_id, fraktion_herkunft,
      belegt, mehrdeutig, amtliche_fraktion)
SELECT r.rede_id,
       nullif(r.fraktion, ''),
       roh.fraktion_id,
       CASE

         WHEN f.n = 1 THEN f.ids[1]






         WHEN f.n > 1 AND roh.fraktion_id = ANY(f.ids) THEN roh.fraktion_id
       END,
       CASE
         WHEN f.n = 1 THEN 'stammdaten'
         WHEN f.n > 1 AND roh.fraktion_id = ANY(f.ids)
              THEN 'protokoll_entscheidet'
         ELSE 'offen'
       END,
       coalesce(f.n, 0) > 0,
       coalesce(f.n, 0) > 1,
       f.namen
  FROM parlamentsarbeit.rede r
  LEFT JOIN parlamentsarbeit.redner_mdb m ON m.redner_id = r.redner_id
  LEFT JOIN politiker_innen.fraktion_alias roh
         ON roh.quelle = 'parlamentsarbeit.rede.fraktion'
        AND roh.schreibweise = r.fraktion
  LEFT JOIN LATERAL (




        SELECT count(DISTINCT z.fraktion) AS n,
               string_agg(DISTINCT z.fraktion, ' | ') AS namen,
               array_agg(DISTINCT al.fraktion_id) AS ids
          FROM politiker_innen.fraktionszugehoerigkeit z
          JOIN politiker_innen.fraktion_alias al
            ON al.quelle = 'politiker_innen.fraktionszugehoerigkeit.fraktion'
           AND al.schreibweise = z.fraktion
         WHERE z.mdb_id = m.mdb_id
           AND z.wp    = r.wahlperiode
           AND z.von  <= r.sitzung_datum
           AND (z.bis IS NULL OR z.bis >= r.sitzung_datum)
       ) f ON true;
"""


def art_aus_name(amtlich):
    if amtlich.startswith("Fraktion "):
        return "fraktion"
    if amtlich.startswith("Gruppe "):
        return "gruppe"
    if amtlich == "Fraktionslos":
        return "fraktionslos"
    raise SystemExit(f"Art nicht erkennbar: {amtlich!r}")


def zeitraeume():
    roh = query("""
        select wp, fraktion, min(von), max(bis), count(*),
               count(*) filter (where bis is null)
          from politiker_innen.fraktionszugehoerigkeit
         where wp >= 18
         group by wp, fraktion
         order by wp, min(von), fraktion
    """)
    zeilen = []
    for wp, amtlich, von, letztes_ende, anzahl, ohne_ende in roh:
        fid = fr.zu_id(amtlich)
        if fid is None:
            raise SystemExit(f"Schreibweise unbekannt: {amtlich!r}")
        offen = int(ohne_ende) > 0
        zeilen.append({
            "fraktion_id": fid,
            "wahlperiode": int(wp),
            "art": art_aus_name(amtlich),
            "von": von,
            "bis": "" if offen else letztes_ende,
            "bis_herkunft": ("offen: mindestens eine Mitgliedschaft ohne " "Enddatum" if offen else
                             "abgeleitet: alle Mitgliedschaften beendet"),
            "mitglieder": int(anzahl),
            "amtliche_bezeichnung": amtlich,
        })
    return zeilen


def schreibweisen_aus_kommentaren():
    treffer = sorted(KOMMENTARE.glob("kommentar_urheber_*.csv"))
    if not treffer:
        return None
    d = pd.read_csv(treffer[-1], sep=";", dtype=str, keep_default_na=False)
    if "schreibweise" not in d.columns:
        return None


    d = d[(d["schreibweise"] != "") & (~d["umfang"].str.startswith("haus"))]
    return d.groupby("schreibweise").size().to_dict()


def aliasse():
    zeilen, unbekannt = [], []

    def aufnehmen(quelle, werte):
        for wert, n in werte.items():
            fid = fr.zu_id(wert)
            _, wp = fr.normiere(wert)
            if fid is None:
                unbekannt.append((quelle, wert))
            zeilen.append({"quelle": quelle, "schreibweise": wert,
                           "fraktion_id": fid or "", "wahlperiode": wp or "",
                           "treffer": int(n)})

    for quelle, sql in QUELLEN:


        schema, tabelle = quelle.split(".")[:2]
        da = query(f"""select count(*) from information_schema.tables
                        where table_schema = '{schema}'
                          and table_name = '{tabelle}'""")[0][0]
        if not int(da):
            print(f"  ! Quelltabelle {schema}.{tabelle} existiert nicht — "
                  f"ihre Schreibweisen fehlen im Verzeichnis.")
            continue
        aufnehmen(quelle, {w: n for w, n in query(sql) if w})

    aus_text = schreibweisen_aus_kommentaren()
    if aus_text is None:
        print("  ! Kommentar-Schreibweisen fehlen: klassifiziere_kommentare.py")
        print("    hat die Spalte `schreibweise` noch nicht geschrieben.")
        print("    Die Alias-Tabelle bleibt fuer diese Quelle leer.")
    else:
        aufnehmen("kommentar_urheber.schreibweise", aus_text)

    if unbekannt:
        print("\nSchreibweisen ohne Eintrag in fraktionen.ALIAS:")
        for quelle, wert in unbekannt:
            print(f"    {quelle}: {wert!r}")
        raise SystemExit("Abbruch: erst in fraktionen.py eintragen (Regel 6).")
    return zeilen


def redner_mdb():
    zeilen = []
    for (rid,) in query("select redner_id from parlamentsarbeit.redner"):
        mdb = korrekturen.mdb_kennung(rid)
        if rid.startswith("11"):
            herkunft, beleg = "kennung_des_bundestages", ""
        elif rid in korrekturen.BEHELFSKENNUNG:
            person, reden, fraktion = korrekturen.BEHELFSKENNUNG[rid][1:]
            herkunft = "behelfskennung_aufgeloest"
            beleg = (f"{person}, {reden} Reden; Name im MdB-Verzeichnis "
                     f"eindeutig, Wahlperiode belegt, Fraktion {fraktion} "
                     f"in Protokoll und Stammdaten gleich")
        elif rid in korrekturen.BEHELFSKENNUNG_REGIERUNG:
            person, reden, amt, grund = \
                korrekturen.BEHELFSKENNUNG_REGIERUNG[rid][1:]
            herkunft = "behelfskennung_regierung_aufgeloest"
            beleg = f"{person}, {reden} Reden, {amt}; {grund}"
        else:
            herkunft, beleg = "offen", ""
        zeilen.append({"redner_id": rid, "mdb_id": mdb or "",
                       "herkunft": herkunft, "beleg": beleg})
    return zeilen


def lade(tabelle, zeilen, spalten, schema=SCHEMA):
    tmp = ZWISCHEN / f"{tabelle}.csv"
    pd.DataFrame(zeilen)[spalten].to_csv(
        tmp, index=False, sep="\t", na_rep="",
        quoting=csv.QUOTE_MINIMAL, encoding="utf-8")
    run_sql(f"TRUNCATE {schema}.{tabelle} CASCADE;", tabelle)
    befehl = (fr"\copy {schema}.{tabelle} ({', '.join(spalten)}) "
              fr"FROM '{tmp.as_posix()}' WITH (FORMAT csv, HEADER true, "
              fr"DELIMITER E'\t')")
    proc = subprocess.run(_psql_args() + ["-c", befehl], env=_pg_env(),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"{tabelle} laden fehlgeschlagen:\n{proc.stderr}")
    n = query(f"SELECT count(*) FROM {schema}.{tabelle};")[0][0]
    print(f"  {int(n):>7,}  {schema}.{tabelle}")
    return zeilen


def bericht():
    print("\n" + "=" * 68)
    print("Bestand je Wahlperiode — aus den amtlichen Stammdaten:")
    for wp, fid, art, von, bis, herkunft, n in query("""
            select wahlperiode, fraktion_id, art, von, bis, bis_herkunft,
                   mitglieder
              from politiker_innen.fraktion_zeitraum
             order by wahlperiode, von, fraktion_id"""):
        ende = bis if bis else herkunft.split(":")[0]
        print(f"  WP {wp}  {fid:<13} {art:<12} {von} bis {ende:<12}"
              f" {int(n):>4} Mitglieder")

    print("\nSchreibweisen je Quelle:")
    for quelle, n, offen in query("""
            select quelle, count(*), count(*) filter (where fraktion_id is null)
              from politiker_innen.fraktion_alias group by 1 order by 1"""):
        rest = f", davon {offen} ohne Zuordnung" if int(offen) else ""
        print(f"  {int(n):>3}  {quelle}{rest}")

    print("\nFraktion je Rede — was das Protokoll sagt gegen die Stammdaten:")
    for roh, belegt, n in query("""
            select fraktion_roh is not null, belegt, count(*)
              from parlamentsarbeit.rede_fraktion group by 1, 2 order by 1, 2"""):

        schl = (str(roh).lower().startswith("t"),
                str(belegt).lower().startswith("t"))
        wort = {(True, True): "Protokoll nennt eine Fraktion, Stammdaten " "belegen eine Zugehoerigkeit",
                (True, False): "Protokoll nennt eine Fraktion, Stammdaten " "belegen keine (Redner ohne Mandat)",
                (False, True): "Protokoll nennt keine, Stammdaten belegen " "eine (Ministerin mit Mandat)",
                (False, False): "weder noch (Gast, Bundesrat, " "Behelfskennung)"}[schl]
        print(f"  {int(n):>7,}  {wort}")
    for n, in query("""select count(*) from parlamentsarbeit.rede_fraktion
                        where mehrdeutig"""):
        print(f"  {int(n):>7,}  mehrdeutig: mehr als eine Zugehoerigkeit am "
              f"Sitzungstag")
    print("\nWie die fraktion_id zustande kommt:")
    for h, n in query("""select fraktion_herkunft, count(*)
              from parlamentsarbeit.rede_fraktion group by 1 order by 2 desc"""):
        print(f"  {int(n):>7,}  {h}")

    print("\nProtokollkennung -> Kennung der Bundestagsverwaltung:")
    for h, n in query("""select herkunft, count(*) from parlamentsarbeit.redner_mdb
              group by 1 order by 2 desc"""):
        print(f"  {int(n):>7,}  {h}")

    print("\nReden ohne jede Sprecherkennung, also ohne Zeile in redner_mdb:")
    for wp, n in query("""select wahlperiode, count(*) from parlamentsarbeit.rede
             where redner_id is null or redner_id = '' group by 1 order by 1"""):
        print(f"  {int(n):>7,}  Wahlperiode {wp}")

    print("\nReden, die das Protokoll einer Fraktion zuordnet, ohne dass die")
    print("Stammdaten eine Zugehoerigkeit belegen — fraktion_id bleibt leer:")
    for roh, wp, n in query("""
            select f.fraktion_roh, r.wahlperiode, count(*)
              from parlamentsarbeit.rede_fraktion f
              join parlamentsarbeit.rede r using (rede_id)
             where f.fraktion_roh is not null and not f.belegt
             group by 1, 2 order by 3 desc limit 10"""):
        print(f"  {int(n):>7,}  WP {wp}  {roh}")

    print("\nProtokoll und Stammdaten nennen verschiedene Fraktionen:")
    treffer = query("""
            select f.fraktion_roh, f.amtliche_fraktion, count(*)
              from parlamentsarbeit.rede_fraktion f
             where f.fraktion_roh_id is not null and f.fraktion_id is not null
               and f.fraktion_roh_id <> f.fraktion_id
             group by 1, 2 order by 3 desc limit 10""")
    if not treffer:
        print("  keine")
    for roh, amt, n in treffer:
        print(f"  {int(n):>7,}  Protokoll {roh}  <->  Stammdaten {amt}")


def main():
    ZWISCHEN.mkdir(parents=True, exist_ok=True)
    ZIEL.mkdir(parents=True, exist_ok=True)

    print(f"Tabellen in {SCHEMA} und parlamentsarbeit anlegen")


    ddl = ZWISCHEN / "schema.sql"
    ddl.write_text(DDL, encoding="utf-8")
    run_sql_file(ddl, "Schema")
    print("  Tabellen stehen.\n")

    print("Laden:")
    knoten = [{"fraktion_id": i, "name": n, "partei": p or ""}
              for i, n, p in fr.KANON]
    lade("fraktion_kanonisch", knoten, ["fraktion_id", "name", "partei"])

    zr = zeitraeume()
    lade("fraktion_zeitraum", zr,
         ["fraktion_id", "wahlperiode", "art", "von", "bis", "bis_herkunft",
          "mitglieder", "amtliche_bezeichnung"])

    al = aliasse()
    lade("fraktion_alias", al,
         ["quelle", "schreibweise", "fraktion_id", "wahlperiode", "treffer"])

    lade("redner_mdb", redner_mdb(),
         ["redner_id", "mdb_id", "herkunft", "beleg"],
         schema="parlamentsarbeit")


    sql = ZWISCHEN / "rede_fraktion.sql"
    sql.write_text("TRUNCATE parlamentsarbeit.rede_fraktion;\n"
                   + REDE_FRAKTION, encoding="utf-8")
    run_sql_file(sql, "rede_fraktion")
    n = query("SELECT count(*) FROM parlamentsarbeit.rede_fraktion;")[0][0]
    print(f"  {int(n):>7,}  parlamentsarbeit.rede_fraktion")


    for name, zeilen in (("fraktion_kanonisch", knoten),
                         ("fraktion_zeitraum", zr),
                         ("fraktion_alias", al)):
        pfad = ZIEL / f"{name}_{STEMPEL}.csv"
        pd.DataFrame(zeilen).to_csv(pfad, index=False, sep=";",
                                    encoding="utf-8")
        print(f"  {len(zeilen):>7,}  -> {pfad.name}")

    bericht()


if __name__ == "__main__":
    main()
