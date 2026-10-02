import csv
import logging
import sys
from collections import defaultdict
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

ABZUEGE = (Path(__file__).resolve().parents[2] / "01_fetch" / "dip"
           / "export")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dsn
DSN = dsn()
AW = "politiker_innen"
LIEFERUNG = "dip_dokumente"
WAHLPERIODEN = (18, 19, 20)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("abstimmung-sachgebiet")


DDL = f"""
SET client_min_messages TO WARNING;
DROP TABLE IF EXISTS {AW}.abstimmung_deskriptor_bt;
DROP TABLE IF EXISTS {AW}.abstimmung_sachgebiet_bt;
DROP TABLE IF EXISTS {AW}.abstimmung_vorgang_bt;

CREATE TABLE {AW}.abstimmung_vorgang_bt (
    datei             TEXT NOT NULL,
    vorgang_id        TEXT NOT NULL,
    ueber_drucksachen TEXT[] NOT NULL,
    vorgangstyp       TEXT,
    titel             TEXT,
    abstract          TEXT,
    beratungsstand    TEXT,
    herkunft          TEXT NOT NULL DEFAULT '{LIEFERUNG}',
    PRIMARY KEY (datei, vorgang_id)
);
CREATE INDEX ON {AW}.abstimmung_vorgang_bt (vorgang_id);

CREATE TABLE {AW}.abstimmung_sachgebiet_bt (
    datei       TEXT NOT NULL,
    sachgebiet  TEXT NOT NULL,
    grund       TEXT,
    herkunft    TEXT NOT NULL DEFAULT '{LIEFERUNG}',
    PRIMARY KEY (datei, sachgebiet)
);
CREATE INDEX ON {AW}.abstimmung_sachgebiet_bt (sachgebiet);

CREATE TABLE {AW}.abstimmung_deskriptor_bt (
    datei       TEXT NOT NULL,
    deskriptor  TEXT NOT NULL,
    typ         TEXT NOT NULL,
    herkunft    TEXT NOT NULL DEFAULT '{LIEFERUNG}',
    PRIMARY KEY (datei, deskriptor, typ)
);
CREATE INDEX ON {AW}.abstimmung_deskriptor_bt (deskriptor);

COMMENT ON TABLE {AW}.abstimmung_vorgang_bt IS
 'Welche Vorgaenge des DIP eine namentliche Abstimmung beruehrt, ueber ihre '
 'Drucksachennummern verbunden. n:m in beide Richtungen: ein Vorgang buendelt '
 'Antrag, Beschlussempfehlung und Bericht, und eine Abstimmung nennt mehrere '
 'Drucksachen. Lieferung {LIEFERUNG}.';
COMMENT ON COLUMN {AW}.abstimmung_vorgang_bt.ueber_drucksachen IS
 'Die Drucksachennummer(n) dieser Abstimmung, die den Bezug hergestellt '
 'haben. Wichtig, weil nicht jede gedruckte Nummer die abgestimmte Vorlage '
 'ist - manche nennen nur den Zusammenhang, auf den sich der Antrag bezieht.';
COMMENT ON TABLE {AW}.abstimmung_sachgebiet_bt IS
 'Sachgebiet je namentlicher Abstimmung, aus dem Vokabular des DIP (28 '
 'Begriffe) - nicht selbst vergeben und nicht zusammengefasst. Ersetzt fuer '
 'die Bundestagslieferung, was abstimmung_thema nur fuer die 459 '
 'abgeordnetenwatch-Abstimmungen leistete. Jede der 642 Abstimmungen hat eine '
 'Zeile; wo kein Sachgebiet zu holen war, steht der Wert unbekannt.';
COMMENT ON COLUMN {AW}.abstimmung_sachgebiet_bt.sachgebiet IS
 'Einer der 28 DIP-Begriffe ODER der Wert `unbekannt`. WER DIE BEGRIFFE '
 'AUSZAEHLT, MUSS AUF herkunft = ''{LIEFERUNG}'' FILTERN - sonst zaehlt '
 '`unbekannt` als 29. Sachgebiet mit. Betrifft 4 von 642 Abstimmungen.';
COMMENT ON COLUMN {AW}.abstimmung_sachgebiet_bt.grund IS
 'Nur bei sachgebiet = unbekannt gefuellt: warum keines zu holen war. '
 'Maschinell aus dem Befund erzeugt, nicht formuliert.';
COMMENT ON COLUMN {AW}.abstimmung_sachgebiet_bt.herkunft IS
 '{LIEFERUNG} fuer ein echtes Sachgebiet, `ohne Angabe` fuer die Zeilen mit '
 'dem Wert unbekannt. Daran, und nur daran, sind beide zu trennen.';
COMMENT ON TABLE {AW}.abstimmung_deskriptor_bt IS
 'Deskriptoren des DIP je Abstimmung, mit ihrem Typ (Sachbegriffe, '
 'Geographische Begriffe, Institutionen, Personen, Rechtsmaterialien). Viel '
 'feiner als das Sachgebiet: im Median 13 je Abstimmung, in der Spitze '
 'ueber 300 bei Haushaltsabstimmungen.';
"""


def neuester_abzug():
    ordner = sorted(p for p in ABZUEGE.glob("dokumente_*") if p.is_dir())
    if not ordner:
        raise SystemExit(f"Kein Abzug unter {ABZUEGE} - erst herunterladen.")


    for p in reversed(ordner):
        if all((p / f"vorgangsposition_wp{wp}.csv").exists() for wp in WAHLPERIODEN):
            return p
    raise SystemExit("Kein Abzug enthaelt alle drei Wahlperioden.")


def lies_dip(ordner):
    ds2vg = defaultdict(set)
    sachgebiet = defaultdict(set)
    deskriptor = defaultdict(set)
    kopf = {}
    for wp in WAHLPERIODEN:
        with open(ordner / f"vorgangsposition_wp{wp}.csv", encoding="utf-8",
                  newline="") as f:
            for r in csv.DictReader(f):
                if r["dokumentart"] == "Drucksache" and r["dokumentnummer"]:
                    ds2vg[r["dokumentnummer"]].add(r["vorgang_id"])
        with open(ordner / f"vorgang_sachgebiet_wp{wp}.csv", encoding="utf-8",
                  newline="") as f:
            for r in csv.DictReader(f):
                sachgebiet[r["vorgang_id"]].add(r["sachgebiet"])
        with open(ordner / f"vorgang_deskriptor_wp{wp}.csv", encoding="utf-8",
                  newline="") as f:
            for r in csv.DictReader(f):
                deskriptor[r["vorgang_id"]].add((r["name"], r["typ"]))
        with open(ordner / f"vorgang_wp{wp}.csv", encoding="utf-8",
                  newline="") as f:
            for r in csv.DictReader(f):
                kopf[r["vorgang_id"]] = (r["vorgangstyp"], r["titel"],
                                         r["abstract"], r["beratungsstand"])
    log.info("   %d Drucksachennummern mit Vorgangsbezug, %d Vorgaenge mit " "Sachgebiet, %d mit Deskriptoren, %d Vorgangskoepfe",
             len(ds2vg), len(sachgebiet), len(deskriptor), len(kopf))
    return ds2vg, sachgebiet, deskriptor, kopf


def main():
    ordner = neuester_abzug()
    log.info("--- DIP-Abzug: %s ---", ordner.name)
    ds2vg, sachgebiet, deskriptor, kopf = lies_dip(ordner)

    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(f"""SELECT datei, drucksachen FROM {AW}.abstimmung_kopf_bt
                        ORDER BY datei;""")
        abst = cur.fetchall()

    vorgaenge, sg_zeilen, de_zeilen = [], [], []
    ohne_drucksache, ohne_vorgang, ohne_sachgebiet = [], [], []
    unbekannte_ds = defaultdict(list)
    for datei, ds in abst:
        if not ds:
            ohne_drucksache.append(datei)
            sg_zeilen.append((datei, "unbekannt",
                              "keine Drucksachennummer - ueber diesen Weg " "ist kein Vorgang erreichbar", "ohne Angabe"))
            continue

        ueber = defaultdict(list)
        for d in ds:
            if d not in ds2vg:
                unbekannte_ds[d].append(datei)
                continue
            for v in ds2vg[d]:
                ueber[v].append(d)
        if not ueber:
            ohne_vorgang.append(datei)
            sg_zeilen.append((datei, "unbekannt",
                              "die Drucksachennummern stehen in keiner " "Vorgangsposition des DIP-Abzugs", "ohne Angabe"))
            continue
        for v, nummern in ueber.items():
            typ, titel, abstract, stand = kopf.get(v, (None, None, None, None))
            vorgaenge.append((datei, v, sorted(set(nummern)), typ, titel,
                              abstract or None, stand or None))
        sg = {s for v in ueber for s in sachgebiet.get(v, ())}
        if not sg:


            typen = sorted({kopf.get(v, ("?",))[0] for v in ueber})
            ohne_sachgebiet.append(datei)
            sg_zeilen.append((datei, "unbekannt",
                              f"erreicht {len(ueber)} Vorgang/Vorgaenge "
                              f"({', '.join(typen)}), keiner fuehrt im DIP ein "
                              f"Sachgebiet", "ohne Angabe"))
        sg_zeilen += [(datei, s, None, LIEFERUNG) for s in sorted(sg)]
        de_zeilen += [(datei, n, t) for n, t in
                      sorted({x for v in ueber for x in deskriptor.get(v, ())})]

    with conn.cursor() as cur:
        cur.execute(DDL)
        execute_values(cur, f"""INSERT INTO {AW}.abstimmung_vorgang_bt
            (datei, vorgang_id, ueber_drucksachen, vorgangstyp, titel,
             abstract, beratungsstand) VALUES %s;""", vorgaenge)
        execute_values(cur, f"""INSERT INTO {AW}.abstimmung_sachgebiet_bt
            (datei, sachgebiet, grund, herkunft) VALUES %s;""", sg_zeilen)
        execute_values(cur, f"""INSERT INTO {AW}.abstimmung_deskriptor_bt
            (datei, deskriptor, typ) VALUES %s;""", de_zeilen)
    conn.commit()
    log.info("   %d Abstimmung-Vorgang-Kanten, %d Sachgebietszeilen, " "%d Deskriptorzeilen geschrieben",
             len(vorgaenge), len(sg_zeilen), len(de_zeilen))

    log.info("--- Was nicht durchkam ---")
    log.info("   %d Abstimmungen ohne Drucksachennummer (belegte Abwesenheit, " "siehe abstimmung_kopf_bt.vermerk)", len(ohne_drucksache))
    for d in ohne_drucksache:
        log.info("      %s", d)
    if unbekannte_ds:
        log.warning("   %d Drucksachennummern stehen in keiner " "Vorgangsposition des Abzugs:", len(unbekannte_ds))
        for nr, dateien in sorted(unbekannte_ds.items()):
            log.warning("      %-12s in %s", nr, ", ".join(d[:26] for d in dateien))
    if ohne_vorgang:
        log.warning("   %d Abstimmungen erreichen keinen Vorgang:", len(ohne_vorgang))
        for d in ohne_vorgang:
            log.warning("      %s", d)
    if ohne_sachgebiet:
        log.warning("   %d Abstimmungen erreichen Vorgaenge, die im DIP KEIN " "Sachgebiet fuehren - nicht gefuellt:", len(ohne_sachgebiet))
        for d in ohne_sachgebiet:
            log.warning("      %s", d)

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT count(DISTINCT datei), count(*), count(DISTINCT sachgebiet),
                   round(count(*)::numeric / nullif(count(DISTINCT datei), 0), 2)
              FROM {AW}.abstimmung_sachgebiet_bt
             WHERE herkunft = '{LIEFERUNG}';""")
        n_abst, n_zeil, n_sg, je = cur.fetchone()
        log.info("--- Sachgebiete ---")
        log.info("   %d von 642 Abstimmungen haben ein Sachgebiet, " "%d Zeilen, %d verschiedene Begriffe, %s je Abstimmung",
                 n_abst, n_zeil, n_sg, je)
        cur.execute(f"""SELECT sachgebiet, count(*) FROM {AW}.abstimmung_sachgebiet_bt
                         WHERE herkunft = '{LIEFERUNG}'
                         GROUP BY 1 ORDER BY 2 DESC;""")
        for s, n in cur.fetchall():
            log.info("   %-46s %4d", s[:44], n)

        cur.execute(f"""SELECT typ, count(*), count(DISTINCT deskriptor)
                          FROM {AW}.abstimmung_deskriptor_bt
                         GROUP BY 1 ORDER BY 2 DESC;""")
        log.info("--- Deskriptoren nach Typ ---")
        for t, n, v in cur.fetchall():
            log.info("   %-32s %6d Zeilen, %5d verschiedene", t[:30], n, v)


        cur.execute(f"""
            SELECT count(*) FILTER (WHERE herkunft = '{LIEFERUNG}'),
                   count(*) FILTER (WHERE herkunft <> '{LIEFERUNG}'),
                   (SELECT count(DISTINCT v.datei)
                      FROM {AW}.abstimmung_bt_aw v
                      JOIN {AW}.abstimmung a ON a.aw_id = v.abstimmung_id
                     WHERE coalesce(a.einleitung, '') <> ''),
                   (SELECT count(DISTINCT datei) FROM {AW}.abstimmung_vorgang_bt
                     WHERE coalesce(abstract, '') <> '')
              FROM (SELECT DISTINCT datei, herkunft
                      FROM {AW}.abstimmung_sachgebiet_bt) q;""")
        mit_sg, ohne_sg, mit_einl, mit_abstract = cur.fetchone()
        log.info("--- Abdeckung ueber alle 642 ---")
        log.info("   %d mit Sachgebiet, %d mit dem Wert unbekannt", mit_sg, ohne_sg)
        log.info("   %d mit Einleitungstext von abgeordnetenwatch (beschreibt " "das Ergebnis)", mit_einl)
        log.info("   %d mit Abstract aus dem DIP (beschreibt die Vorlage)",
                 mit_abstract)
    conn.close()


if __name__ == "__main__":
    main()
