import sys
import logging
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

DB_SCHEMA   = "raum"
ERG_SCHEMA  = "wahlergebnisse"
TABELLE    = "einheitsuebergang"
MV_GEMEIND = "kleinst_100_amtlich"
MV_STADT   = "kleinst_100_geteilt"

UEBERGAENGE = [(2013, 2017), (2017, 2021)]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("einheit-uebergang")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    von_wahljahr         SMALLINT NOT NULL,
    von_einheit_id       TEXT,
    von_typ              TEXT,
    nach_wahljahr        SMALLINT NOT NULL,
    nach_einheit_id      TEXT,
    nach_typ             TEXT,
    kontinuitaet         TEXT     NOT NULL,
    beziehung            TEXT     NOT NULL,
    typ_geaendert        BOOLEAN,
    wkr_geaendert        BOOLEAN,
    name_geaendert       BOOLEAN,
    mitglieder_ab        INTEGER,
    mitglieder_zu        INTEGER,
    mitglieder_gemeinsam INTEGER,
    fusion_bereinigt     BOOLEAN,
    herkunft             TEXT     NOT NULL,
    CHECK (von_einheit_id IS NOT NULL OR nach_einheit_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS {TABELLE}_key
    ON {DB_SCHEMA}.{TABELLE}
       (von_wahljahr, nach_wahljahr,
        coalesce(von_einheit_id, ''), coalesce(nach_einheit_id, ''));
CREATE INDEX IF NOT EXISTS {TABELLE}_von_idx
    ON {DB_SCHEMA}.{TABELLE} (von_wahljahr, von_einheit_id);
CREATE INDEX IF NOT EXISTS {TABELLE}_nach_idx
    ON {DB_SCHEMA}.{TABELLE} (nach_wahljahr, nach_einheit_id);
"""


MITGLIED_CTE = f"""
bezirk AS (
    SELECT w.wahljahr, w.wkr_nr, w.kreis, w.bwbez,
           raum.gemeinde_ags(w.ags) AS gem_ags
    FROM {ERG_SCHEMA}.wahlbezirk w
),
geteilt AS (
    SELECT wahljahr, gem_ags
    FROM (SELECT DISTINCT wahljahr, gem_ags, wkr_nr FROM bezirk) d
    WHERE NOT raum.ist_sammelposten(gem_ags)
    GROUP BY 1, 2 HAVING count(*) > 1
),
zuordnung AS (
    SELECT DISTINCT b.wahljahr, b.gem_ags,
           CASE WHEN b.bwbez = '00' THEN b.gem_ags
                ELSE 'V-' || b.kreis || '-' || b.bwbez
                     || '-' || lpad(b.wkr_nr::text, 3, '0') END AS einheit_id
    FROM bezirk b
    WHERE NOT EXISTS (SELECT 1 FROM geteilt g
                      WHERE (g.wahljahr, g.gem_ags) = (b.wahljahr, b.gem_ags))
      AND NOT raum.ist_sammelposten(b.gem_ags)
),
einheit AS (
    SELECT wahljahr, einheit_id, typ, wkr_nr, gemeindename
      FROM {DB_SCHEMA}.{MV_GEMEIND}
    UNION ALL
    SELECT wahljahr, einheit_id, 'grossstadt_wahlkreis', wkr_nr, gemeindename
      FROM {DB_SCHEMA}.{MV_STADT}
),
mitglied AS (

    SELECT z.wahljahr, z.einheit_id, z.gem_ags AS ags, NULL::SMALLINT AS wkr
    FROM zuordnung z
    JOIN {DB_SCHEMA}.{MV_GEMEIND} e
      ON (e.wahljahr, e.einheit_id) = (z.wahljahr, z.einheit_id)
    UNION ALL

    SELECT g.wahljahr, g.einheit_id, g.ags, g.wkr_nr
    FROM {DB_SCHEMA}.{MV_STADT} g
)
"""


def sql_ueber_datei(sql, label):
    pfad = Path(tempfile.gettempdir()) / f"einheitsueb_{abs(hash(label))}.sql"
    pfad.write_text("SET client_encoding TO 'UTF8';\n" + sql, encoding="utf-8")
    try:
        run_sql_file(pfad, label=label)
    finally:
        pfad.unlink(missing_ok=True)


def wahltag(jahr):
    zeilen = query(f"""
        SELECT datum FROM zeit.stichtag
        WHERE art = 'wahltag' AND bezug = 'Wahl {jahr}';
    """)
    if not zeilen:
        raise SystemExit(f"Kein Wahltag fuer Wahl {jahr} in zeit.stichtag")
    return zeilen[0][0]


def lade(von, nach):
    tag_von, tag_nach = wahltag(von), wahltag(nach)

    sql_ueber_datei(f"""
        DELETE FROM {DB_SCHEMA}.{TABELLE}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach};

        WITH RECURSIVE
        {MITGLIED_CTE},


        wechsel AS (
            SELECT DISTINCT ags_alt, ags_neu
            FROM raum.gebietsuebergang
            WHERE wirksam > DATE '{tag_von}' AND wirksam <= DATE '{tag_nach}'
              AND ags_alt <> ags_neu
              AND art IN ('eingliederung', 'zusammenschluss', 'schluesselaenderung')
        ),
        kette (ags_alt, ags_neu, tiefe) AS (
            SELECT ags_alt, ags_neu, 1 FROM wechsel
            UNION
            SELECT k.ags_alt, w.ags_neu, k.tiefe + 1
            FROM kette k JOIN wechsel w ON w.ags_alt = k.ags_neu
            WHERE k.tiefe < 5
        ),
        endziel AS (
            SELECT DISTINCT ON (ags_alt) ags_alt, ags_neu
            FROM kette ORDER BY ags_alt, tiefe DESC
        ),


        wkr_neu AS (
            SELECT DISTINCT ON (von_wkr_nr) von_wkr_nr, nach_wkr_nr
            FROM raum.wahlkreisuebergang
            WHERE von_wahljahr = {von} AND nach_wahljahr = {nach}
              AND von_wkr_nr IS NOT NULL AND nach_wkr_nr IS NOT NULL
            ORDER BY von_wkr_nr, nach_wkr_nr
        ),


        mitglied_alt AS (
            SELECT m.einheit_id,
                   coalesce(e.ags_neu, m.ags)
                   || coalesce('|' || lpad(coalesce(t.nach_wkr_nr, m.wkr)::text,
                                           3, '0'), '')          AS schluessel,
                   (e.ags_neu IS NOT NULL)                       AS uebersetzt
            FROM mitglied m
            LEFT JOIN endziel e ON e.ags_alt = m.ags
            LEFT JOIN wkr_neu t ON t.von_wkr_nr = m.wkr
            WHERE m.wahljahr = {von}
        ),
        mitglied_neu AS (
            SELECT m.einheit_id,
                   m.ags || coalesce('|' || lpad(m.wkr::text, 3, '0'), '')
                       AS schluessel
            FROM mitglied m WHERE m.wahljahr = {nach}
        ),
        ueberschneidung AS (
            SELECT a.einheit_id AS id_alt, b.einheit_id AS id_neu,
                   count(*) AS gemeinsam
            FROM mitglied_alt a JOIN mitglied_neu b USING (schluessel)
            GROUP BY 1, 2
        ),


        rangiert AS (
            SELECT u.*,
                   row_number() OVER (PARTITION BY id_alt
                                      ORDER BY gemeinsam DESC, id_neu) AS r_alt,
                   row_number() OVER (PARTITION BY id_neu
                                      ORDER BY gemeinsam DESC, id_alt) AS r_neu
            FROM ueberschneidung u
        ),
        paar AS (
            SELECT r.id_alt, r.id_neu, r.gemeinsam,
                   count(*) OVER (PARTITION BY r.id_alt) AS nachfolger,
                   count(*) OVER (PARTITION BY r.id_neu) AS vorgaenger
            FROM rangiert r WHERE r.r_alt = 1 OR r.r_neu = 1
        ),



        groesse_alt AS (
            SELECT einheit_id, count(*) AS n, bool_or(uebersetzt) AS fusion
            FROM mitglied_alt GROUP BY 1
        ),
        groesse_neu AS (
            SELECT einheit_id, count(*) AS n FROM mitglied_neu GROUP BY 1
        ),
        bilanz AS (
            SELECT p.*, ga.n AS n_alt, gn.n AS n_neu, ga.fusion
            FROM paar p
            JOIN groesse_alt ga ON ga.einheit_id = p.id_alt
            JOIN groesse_neu gn ON gn.einheit_id = p.id_neu
        ),
        ohne_nachfolger AS (
            SELECT ga.einheit_id, ga.n
            FROM groesse_alt ga
            WHERE NOT EXISTS (SELECT 1 FROM paar p WHERE p.id_alt = ga.einheit_id)
        ),
        ohne_vorgaenger AS (
            SELECT gn.einheit_id, gn.n
            FROM groesse_neu gn
            WHERE NOT EXISTS (SELECT 1 FROM paar p WHERE p.id_neu = gn.einheit_id)
        )
        INSERT INTO {DB_SCHEMA}.{TABELLE}
            (von_wahljahr, von_einheit_id, von_typ,
             nach_wahljahr, nach_einheit_id, nach_typ,
             kontinuitaet, beziehung, typ_geaendert, wkr_geaendert,
             name_geaendert,
             mitglieder_ab, mitglieder_zu, mitglieder_gemeinsam,
             fusion_bereinigt, herkunft)
        SELECT {von}, b.id_alt, ea.typ, {nach}, b.id_neu, en.typ,
               CASE WHEN b.n_alt = b.gemeinsam AND b.n_neu = b.gemeinsam
                         THEN 'identisch'
                    WHEN b.n_alt = b.gemeinsam THEN 'nur_zugang'
                    WHEN b.n_neu = b.gemeinsam THEN 'nur_abgang'
                    ELSE                            'austausch' END,
               CASE WHEN b.nachfolger > 1 AND b.vorgaenger > 1 THEN 'verflochten'
                    WHEN b.nachfolger > 1 THEN 'aufgeteilt'
                    WHEN b.vorgaenger > 1 THEN 'zusammengefuehrt'
                    ELSE                       'eindeutig' END,
               ea.typ IS DISTINCT FROM en.typ,
               coalesce(w.nach_wkr_nr, ea.wkr_nr) IS DISTINCT FROM en.wkr_nr,



               ea.gemeindename IS DISTINCT FROM en.gemeindename,
               b.n_alt - b.gemeinsam, b.n_neu - b.gemeinsam, b.gemeinsam,
               b.fusion,
               CASE WHEN ea.typ = 'grossstadt_wahlkreis'
                      OR en.typ = 'grossstadt_wahlkreis'
                    THEN 'mengenvergleich der Stadtteile je Wahlkreis'
                    ELSE 'mengenvergleich der Mitgliedsgemeinden' END
        FROM bilanz b
        JOIN einheit ea ON (ea.wahljahr, ea.einheit_id) = ({von},  b.id_alt)
        JOIN einheit en ON (en.wahljahr, en.einheit_id) = ({nach}, b.id_neu)
        LEFT JOIN wkr_neu w ON w.von_wkr_nr = ea.wkr_nr

        UNION ALL

        SELECT {von}, o.einheit_id, ea.typ, {nach}, NULL::TEXT, NULL::TEXT,
               'aufgeloest', 'ohne_partner', NULL::BOOLEAN, NULL::BOOLEAN,
               NULL::BOOLEAN,
               o.n::INTEGER, 0, 0, NULL::BOOLEAN,
               'kein Nachfolger mit gemeinsamem Mitglied'
        FROM ohne_nachfolger o
        JOIN einheit ea ON (ea.wahljahr, ea.einheit_id) = ({von}, o.einheit_id)

        UNION ALL

        SELECT {von}, NULL::TEXT, NULL::TEXT, {nach}, o.einheit_id, en.typ,
               'neu', 'ohne_partner', NULL::BOOLEAN, NULL::BOOLEAN,
               NULL::BOOLEAN,
               0, o.n::INTEGER, 0, NULL::BOOLEAN,
               'kein Vorgaenger mit gemeinsamem Mitglied'
        FROM ohne_vorgaenger o
        JOIN einheit en ON (en.wahljahr, en.einheit_id) = ({nach}, o.einheit_id);
    """, f"einheitsuebergang {von}->{nach}")


def report(von, nach):
    log.info("--- %s -> %s ---", von, nach)
    for zeile in query(f"""
        SELECT kontinuitaet, beziehung, count(*)
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach}
        GROUP BY 1, 2 ORDER BY 3 DESC;
    """):
        log.info("  %-14s %-18s %6s", *zeile)

    log.info("  Typwechsel:")
    for zeile in query(f"""
        SELECT coalesce(von_typ, '-'), coalesce(nach_typ, '-'), count(*)
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach}
          AND (von_typ IS DISTINCT FROM nach_typ)
        GROUP BY 1, 2 ORDER BY 3 DESC;
    """):
        log.info("    %-22s -> %-22s %6s", *zeile)


    for seite, jahr in (("von", von), ("nach", nach)):


        zeilen = query(f"""
            SELECT count(*) AS einheiten,
                   count(*) FILTER (WHERE u.n IS NULL)  AS ohne_zeile,
                   count(*) FILTER (WHERE u.n > 1)      AS mehrfach
            FROM (SELECT einheit_id FROM {DB_SCHEMA}.{MV_GEMEIND}
                   WHERE wahljahr = {jahr}
                  UNION ALL
                  SELECT einheit_id FROM {DB_SCHEMA}.{MV_STADT}
                   WHERE wahljahr = {jahr}) e
            LEFT JOIN (SELECT {seite}_einheit_id AS id, count(*) AS n
                       FROM {DB_SCHEMA}.{TABELLE}
                       WHERE von_wahljahr = {von} AND nach_wahljahr = {nach}
                         AND {seite}_einheit_id IS NOT NULL
                       GROUP BY 1) u ON u.id = e.einheit_id;
        """)
        if zeilen:
            log.info("  %s-Seite %s: %s Einheiten, %s ohne Zeile, %s mehrfach",
                     seite, jahr, *zeilen[0])


    zeilen = query(f"""
        SELECT count(*) FILTER (WHERE von_einheit_id = nach_einheit_id),
               count(*) FILTER (WHERE von_einheit_id <> nach_einheit_id),
               count(*) FILTER (WHERE von_einheit_id = nach_einheit_id
                                  AND kontinuitaet <> 'identisch')
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach}
          AND von_einheit_id IS NOT NULL AND nach_einheit_id IS NOT NULL;
    """)
    if zeilen:
        log.info("  Kennung: %s Paare gleich, %s verschieden, davon %s gleich " "benannt aber nicht identisch", *zeilen[0])


    zeilen = query(f"""
        SELECT count(*) FILTER (WHERE fusion_bereinigt),
               count(*) FILTER (WHERE fusion_bereinigt AND kontinuitaet = 'identisch')
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach};
    """)
    if zeilen:
        log.info("  Fusion vorgeschaltet bei %s Einheiten, davon %s dadurch " "identisch", *zeilen[0])


    zeilen = query(f"""
        SELECT count(*),
               count(*) FILTER (WHERE name_geaendert),
               count(*) FILTER (WHERE name_geaendert AND kontinuitaet = 'identisch')
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach}
          AND von_einheit_id IS NOT NULL AND nach_einheit_id IS NOT NULL;
    """)
    if zeilen:
        log.info("  %s Paare, davon %s umbenannt, davon %s bei sonst " "identischer Einheit", *zeilen[0])


    for zeile in query(f"""
        SELECT von_einheit_id, nach_einheit_id, mitglieder_gemeinsam,
               mitglieder_ab, mitglieder_zu
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach}
          AND mitglieder_gemeinsam > 0
          AND mitglieder_gemeinsam * 2
              < greatest(mitglieder_gemeinsam + mitglieder_ab,
                         mitglieder_gemeinsam + mitglieder_zu)
        ORDER BY mitglieder_gemeinsam LIMIT 15;
    """):
        log.info("    schwach: %s -> %s (%s gemeinsam, %s ab, %s zu)", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;",
                "tabelle verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    run_sql(DDL, "ddl")

    for von, nach in UEBERGAENGE:
        lade(von, nach)
        report(von, nach)


if __name__ == "__main__":
    main()
