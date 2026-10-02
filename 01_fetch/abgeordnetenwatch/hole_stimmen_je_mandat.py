import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg2
from abgeordnetenwatch import (
    AbgeordnetenwatchAPI, RateLimiter, START_CALLS_PER_MIN, DB_DSN,
    upsert_raw, DB_SCHEMA,
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("stimmen-je-mandat")


def main():
    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{DB_SCHEMA}", public;')
        cur.execute("SELECT count(*) FROM raw_votes;")
        vorher = cur.fetchone()[0]
        cur.execute("""SELECT aw_id, politician_label, parliament_period_label
                         FROM candidacy_mandate WHERE type = 'mandate'
                        ORDER BY parliament_period_label, aw_id;""")
        mandate = cur.fetchall()

    log.info("%d Stimmen im Bestand, %d Mandate abzufragen", vorher, len(mandate))

    limiter = RateLimiter(START_CALLS_PER_MIN)
    api = AbgeordnetenwatchAPI(limiter)

    neu_gesamt = 0
    ohne_stimmen = []
    for i, (mid, name, periode) in enumerate(mandate, 1):
        stimmen = list(api.fetch_all("votes", {"mandate": mid}))
        if stimmen:
            upsert_raw(conn, "raw_votes", stimmen)
        else:
            ohne_stimmen.append((mid, name, periode))
        neu_gesamt += len(stimmen)
        if i % 100 == 0 or i == len(mandate):
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{DB_SCHEMA}", public;')
                cur.execute("SELECT count(*) FROM raw_votes;")
                stand = cur.fetchone()[0]
            log.info("  %d/%d Mandate, %d Stimmen abgerufen, Bestand jetzt %d (+%d)",
                     i, len(mandate), neu_gesamt, stand, stand - vorher)

    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{DB_SCHEMA}", public;')
        cur.execute("SELECT count(*) FROM raw_votes;")
        nachher = cur.fetchone()[0]

    log.info("--- Ergebnis ---")
    log.info("   vorher %d, nachher %d, neu %d Stimmen", vorher, nachher, nachher - vorher)
    if ohne_stimmen:
        log.info("   %d Mandate ohne jede Stimme:", len(ohne_stimmen))
        for mid, name, periode in ohne_stimmen[:10]:
            log.info("      %s %s (%s)", mid, name, periode)

    log.info("--- Abstimmungen, die nur in den Stimmen vorkommen ---")
    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{DB_SCHEMA}", public;')
        cur.execute("""
            SELECT DISTINCT (v.data->'poll'->>'id')::int AS poll_id,
                            v.data->'poll'->>'label'     AS titel
              FROM raw_votes v
             WHERE NOT EXISTS (SELECT 1 FROM raw_polls p
                                WHERE (p.data->>'id')::int
                                      = (v.data->'poll'->>'id')::int)
             ORDER BY 1;""")
        fehlend = cur.fetchall()
    log.info("   %d Abstimmungen ohne Eintrag in raw_polls", len(fehlend))
    for pid, titel in fehlend:
        log.info("      poll %-7s %s", pid, (titel or "")[:66])

    log.info("--- Wie viele Abstimmungen sind es jetzt je Wahlperiode? ---")
    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{DB_SCHEMA}", public;')
        cur.execute("""
            SELECT m.parliament_period_label,
                   count(DISTINCT (v.data->'poll'->>'id')::int)
              FROM raw_votes v
              JOIN candidacy_mandate m
                ON m.aw_id = (v.data->'mandate'->>'id')::int
             GROUP BY 1 ORDER BY 1;""")
        for periode, n in cur.fetchall():
            log.info("   %-24s %s Abstimmungen", periode, n)

    conn.close()


if __name__ == "__main__":
    main()
