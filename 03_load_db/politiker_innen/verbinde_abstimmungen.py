import logging
import sys
from collections import Counter, defaultdict

import psycopg2
from psycopg2.extras import execute_values
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dsn

DSN = dsn()
AW = "politiker_innen"


UEBERSETZUNG = {"yes": "ja", "no": "nein", "abstain": "enthaltung",
                "no_show": "nicht_abgegeben"}

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("abstimmungen-verbinden")


DDL = f"""
SET client_min_messages TO WARNING;
DROP TABLE IF EXISTS {AW}.abstimmung_bt_aw;
CREATE TABLE {AW}.abstimmung_bt_aw (
    datei          TEXT PRIMARY KEY REFERENCES {AW}.abstimmung_bt (datei),
    abstimmung_id  INTEGER NOT NULL,
    gemeinsam      INTEGER NOT NULL,
    gleich         INTEGER NOT NULL,
    verschieden    INTEGER NOT NULL,
    verfahren      TEXT NOT NULL
);
CREATE UNIQUE INDEX ON {AW}.abstimmung_bt_aw (abstimmung_id);

DROP TABLE IF EXISTS {AW}.abstimmung_einleitung;
CREATE TABLE {AW}.abstimmung_einleitung (
    datei       TEXT PRIMARY KEY REFERENCES {AW}.abstimmung_bt (datei),
    einleitung  TEXT NOT NULL,
    aw_id       INTEGER NOT NULL,
    aw_url      TEXT,
    herkunft    TEXT NOT NULL DEFAULT 'aw_api_v2'
);
COMMENT ON TABLE {AW}.abstimmung_einleitung IS
 'Das EINZIGE, was von der Lieferung abgeordnetenwatch bei den namentlichen '
 'Abstimmungen noch in den Bestand eingeht: der redaktionelle Einleitungstext, '
 'direkt an der Bundestagsabstimmung. Er beschreibt das ERGEBNIS ("Mit grosser '
 'Mehrheit hat der Bundestag ... beschlossen") - das DIP-Abstract in '
 'abstimmung_vorgang_bt beschreibt dagegen den INHALT der Vorlage. Zwei '
 'verschiedene Aussagen, keine Dopplung.';
DROP TABLE IF EXISTS {AW}.abstimmung_ausschuss;
CREATE TABLE {AW}.abstimmung_ausschuss (
    datei        TEXT NOT NULL REFERENCES {AW}.abstimmung_bt (datei),
    ausschuss    TEXT NOT NULL,
    ausschuss_id INTEGER,
    herkunft     TEXT NOT NULL,
    PRIMARY KEY (datei, ausschuss)
);
COMMENT ON TABLE {AW}.abstimmung_ausschuss IS
 'Welcher Ausschuss die Vorlage behandelt hat, je namentlicher Abstimmung. '
 'Kommt von abgeordnetenwatch - der Bundestag liefert zu den Abstimmungen '
 'KEINEN Ausschussbezug, und im DIP steckt er nur im Vorlagentitel, nicht als '
 'Feld. Jede der 642 Abstimmungen hat eine Zeile; wo keiner zu holen war, '
 'steht `unbekannt`.';
COMMENT ON COLUMN {AW}.abstimmung_ausschuss.ausschuss IS
 'Name des Ausschusses ODER der Wert `unbekannt`. WER AUSSCHUESSE AUSZAEHLT, '
 'MUSS AUF herkunft = ''aw_api_v2'' FILTERN - sonst zaehlt `unbekannt` als '
 'Ausschuss mit.';
COMMENT ON COLUMN {AW}.abstimmung_ausschuss.herkunft IS
 'aw_api_v2 fuer einen echten Ausschuss, `ohne Angabe` fuer die Zeilen mit dem '
 'Wert unbekannt. Daran, und nur daran, sind beide zu trennen.';
COMMENT ON COLUMN {AW}.abstimmung_einleitung.aw_id IS
 'Die Abstimmung bei abgeordnetenwatch, aus der der Text stammt - Herkunfts'
 'nachweis, kein Fremdschluessel: die Clean-Tabelle dazu gibt es nicht mehr. '
 'Der Rohsatz steht in raw_polls.';

COMMENT ON TABLE {AW}.abstimmung_bt_aw IS
 'Kante zwischen der Abstimmung des Bundestages (abstimmung_bt) und derselben '
 'Abstimmung bei abgeordnetenwatch (abstimmung). Verbunden ueber Datum und '
 'STIMMVERHALTEN, nicht ueber den Titel: Beide Bestaende haengen an denselben '
 'mandat_id, und bei 630 bis 736 Mitgliedern je Abstimmung ist eine zufaellige '
 'Uebereinstimmung ausgeschlossen. Zweck: die Sachgebiete, Einleitungstexte '
 'und Drucksachenverweise von abgeordnetenwatch erreichbar machen, ohne sie '
 'in die Bundestagslieferung hineinzuschreiben - es gibt sie nur fuer 459 der '
 '642 Abstimmungen.';
COMMENT ON COLUMN {AW}.abstimmung_bt_aw.gemeinsam IS
 'Mandate, fuer die BEIDE Lieferungen eine Stimme fuehren.';
COMMENT ON COLUMN {AW}.abstimmung_bt_aw.verschieden IS
 'Davon mit abweichendem Wert. Wird nicht geglaettet: wo es nicht null ist, '
 'widersprechen sich die Lieferungen und das gehoert sichtbar.';
"""


def main():
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(f"""SELECT datei, datum FROM {AW}.abstimmung_bt;""")
        bt_datum = dict(cur.fetchall())


        cur.execute(f"""SELECT (data->>'id')::int,
                               (data->>'field_poll_date')::date
                          FROM {AW}.raw_polls;""")
        aw_datum = dict(cur.fetchall())

        cur.execute(f"""SELECT datei, mandat_id, stimme FROM {AW}.stimme_bt
                         WHERE mandat_id IS NOT NULL;""")
        bt = defaultdict(dict)
        for datei, mandat, wert in cur.fetchall():
            bt[datei][mandat] = wert


        cur.execute(f"""SELECT (data->'poll'->>'id')::int,
                               (data->'mandate'->>'id')::int,
                                data->>'vote'
                          FROM {AW}.raw_votes;""")
        aw = defaultdict(dict)
        for aid, mandat, wert in cur.fetchall():
            aw[aid][mandat] = UEBERSETZUNG.get(wert, wert)

    log.info("%d Abstimmungen des Bundestages, %d bei abgeordnetenwatch",
             len(bt_datum), len(aw_datum))


    je_tag = defaultdict(list)
    for aid, d in aw_datum.items():
        je_tag[d].append(aid)

    treffer, verteilung, ohne = [], Counter(), []
    for datei, d in sorted(bt_datum.items()):
        beste = None
        for aid in je_tag.get(d, []):
            gemeinsam = set(bt[datei]) & set(aw[aid])
            if not gemeinsam:
                continue
            gleich = sum(1 for m in gemeinsam if bt[datei][m] == aw[aid][m])
            anteil = gleich / len(gemeinsam)
            if beste is None or anteil > beste[3]:
                beste = (aid, len(gemeinsam), gleich, anteil)
        if beste is None:
            ohne.append((datei, d))
            continue
        aid, gemeinsam, gleich, anteil = beste
        verteilung[round(anteil, 2)] += 1
        treffer.append((datei, aid, gemeinsam, gleich, gemeinsam - gleich, anteil))

    log.info("--- Wie gut passt der beste Kandidat je Tag? ---")
    for anteil in sorted(verteilung, reverse=True)[:12]:
        log.info("   Uebereinstimmung %5.0f %%: %3d Abstimmungen",
                 anteil * 100, verteilung[anteil])
    log.info("   ohne Kandidaten am selben Tag: %d", len(ohne))


    sicher = [t for t in treffer if t[5] >= 0.99]
    unsicher = [t for t in treffer if t[5] < 0.99]


    je_aw = defaultdict(list)
    for t in sicher:
        je_aw[t[1]].append(t)
    eindeutig, umstritten = [], []
    for aid, kandidaten in je_aw.items():
        if len(kandidaten) == 1:
            eindeutig.append(kandidaten[0])
            continue
        beste = max(k[5] for k in kandidaten)
        spitze = [k for k in kandidaten if k[5] == beste]
        if len(spitze) == 1:
            eindeutig.append(spitze[0])
            umstritten += [k for k in kandidaten if k is not spitze[0]]
        else:
            umstritten += kandidaten

    with conn.cursor() as cur:
        execute_values(cur, f"""INSERT INTO {AW}.abstimmung_bt_aw
            (datei, abstimmung_id, gemeinsam, gleich, verschieden, verfahren)
            VALUES %s""",
            [(t[0], t[1], t[2], t[3], t[4], "stimmuster") for t in eindeutig])


        cur.execute(f"""
            INSERT INTO {AW}.abstimmung_einleitung
                (datei, einleitung, aw_id, aw_url)
            SELECT v.datei,
                   p.data->>'field_intro',
                   (p.data->>'id')::int,
                   p.data->>'abgeordnetenwatch_url'
              FROM {AW}.abstimmung_bt_aw v
              JOIN {AW}.raw_polls p ON (p.data->>'id')::int = v.abstimmung_id
             WHERE coalesce(p.data->>'field_intro', '') <> '';""")
        log.info("   %d Einleitungstexte an die Abstimmung gehaengt", cur.rowcount)


        cur.execute(f"""
            INSERT INTO {AW}.abstimmung_ausschuss
                (datei, ausschuss, ausschuss_id, herkunft)
            SELECT DISTINCT v.datei, a->>'label', (a->>'id')::int, 'aw_api_v2'
              FROM {AW}.abstimmung_bt_aw v
              JOIN {AW}.raw_polls p ON (p.data->>'id')::int = v.abstimmung_id,
                   jsonb_array_elements(CASE
                       WHEN jsonb_typeof(p.data->'field_committees') = 'array'
                       THEN p.data->'field_committees' ELSE '[]'::jsonb END) a
             WHERE a->>'label' IS NOT NULL;""")
        mit = cur.rowcount


        cur.execute(f"""
            INSERT INTO {AW}.abstimmung_ausschuss
                (datei, ausschuss, ausschuss_id, herkunft)
            SELECT b.datei, 'unbekannt', NULL, 'ohne Angabe'
              FROM {AW}.abstimmung_bt b
             WHERE NOT EXISTS (SELECT 1 FROM {AW}.abstimmung_ausschuss x
                                WHERE x.datei = b.datei);""")
        log.info("   %d Ausschusszeilen, dazu %d mal `unbekannt`", mit, cur.rowcount)
    conn.commit()

    log.info("--- Ergebnis ---")
    log.info("   %d Abstimmungen verbunden", len(eindeutig))
    log.info("   %d unsicher (unter 99 %% Uebereinstimmung)", len(unsicher))
    log.info("   %d umstritten (zwei Dateien auf dieselbe aw-Abstimmung)",
             len(umstritten))
    log.info("   %d ohne Kandidaten am selben Tag", len(ohne))

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT count(*) FILTER (WHERE verschieden = 0),
                   count(*) FILTER (WHERE verschieden > 0),
                   sum(verschieden)
              FROM {AW}.abstimmung_bt_aw;""")
        null, mit, summe = cur.fetchone()
        log.info("   davon %d ohne jeden Widerspruch, %d mit (zusammen %s Stimmen)",
                 null, mit, summe)

        log.info("--- Was dadurch erreichbar wird ---")
        cur.execute(f"""
            SELECT a.wahlperiode,
                   count(*) AS abstimmungen,
                   count(v.datei) AS mit_aw,
                   count(*) FILTER (WHERE t.n > 0) AS mit_sachgebiet
              FROM {AW}.abstimmung_bt a
              LEFT JOIN {AW}.abstimmung_bt_aw v ON v.datei = a.datei
              LEFT JOIN (SELECT datei, count(*) AS n
                           FROM {AW}.abstimmung_sachgebiet_bt
                          WHERE herkunft = 'dip_dokumente' GROUP BY 1) t
                     ON t.datei = a.datei
             GROUP BY 1 ORDER BY 1;""")
        for wp, n, mit_aw, mit_sg in cur.fetchall():
            log.info("   WP %d: %3d Abstimmungen, %3d mit Beschreibung, %3d mit Sachgebiet",
                     wp, n, mit_aw, mit_sg)

    log.info("--- Und welche abgeordnetenwatch-Abstimmungen bleiben ohne Partner? ---")
    with conn.cursor() as cur:


        cur.execute(f"""
            SELECT extract(year FROM (p.data->>'field_poll_date')::date)::int AS jahr,
                   count(*) AS gesamt,
                   count(v.abstimmung_id) AS verbunden,
                   count(*) - count(v.abstimmung_id) AS offen
              FROM {AW}.raw_polls p
              LEFT JOIN {AW}.abstimmung_bt_aw v
                     ON v.abstimmung_id = (p.data->>'id')::int
             GROUP BY 1 ORDER BY 1;""")
        for jahr, n, verb, offen in cur.fetchall():
            log.info("   %d: %3d Abstimmungen, %3d verbunden, %3d offen",
                     jahr, n, verb, offen)
        cur.execute(f"""
            SELECT (p.data->>'field_poll_date'), (p.data->>'id')::int,
                   (p.data->>'label'),
                   (SELECT count(*) FROM {AW}.abstimmung_bt b
                     WHERE b.datum = (p.data->>'field_poll_date')::date)
              FROM {AW}.raw_polls p
             WHERE NOT EXISTS (SELECT 1 FROM {AW}.abstimmung_bt_aw v
                                WHERE v.abstimmung_id = (p.data->>'id')::int)
             ORDER BY 1 LIMIT 15;""")
        for d, aid, titel, am_tag in cur.fetchall():
            log.info("   %s  %5d  %-48s  %d BT-Abstimmungen am selben Tag",
                     d, aid, str(titel)[:46], am_tag)

    if unsicher:
        log.info("--- Unsichere Paare ---")
        for datei, aid, gem, gl, versch, anteil in sorted(unsicher, key=lambda x: x[5])[:15]:
            log.info("   %-38s -> %5d  %5.1f %% (%d von %d)",
                     datei[:36], aid, anteil * 100, gl, gem)
    if umstritten:
        log.info("--- Umstrittene Paare ---")
        for datei, aid, gem, gl, versch, anteil in sorted(umstritten, key=lambda x: x[1]):
            log.info("   %-38s -> %5d  %5.1f %%", datei[:36], aid, anteil * 100)

    conn.close()


if __name__ == "__main__":
    main()
