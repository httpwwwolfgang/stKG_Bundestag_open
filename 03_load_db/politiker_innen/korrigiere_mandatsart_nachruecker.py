import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SCHEMA = "politiker_innen"

BETROFFEN = f"""
    SELECT aw_id, politician_label, mandatsart_amtlich
      FROM {SCHEMA}.candidacy_mandate
     WHERE type = 'mandate' AND mandatsart = 'moved_up'
"""


def pruefe_vorher():
    zeilen = query(BETROFFEN)
    if not zeilen:
        log.info("Kein Mandat mit 'moved_up' - nichts zu tun.")
        return []

    ohne = [z for z in zeilen if z[2] is None]
    if ohne:
        for aw_id, label, _ in ohne:
            log.error("ohne amtliche Mandatsart: %s (aw_id %s)", label, aw_id)
        raise SystemExit(f"{len(ohne)} Mandate ohne amtlichen Wert - Abbruch, " "der Fall gehoert vorgelegt.")

    fremd = sorted({z[2] for z in zeilen} - {"Landesliste", "Direktwahl"})
    if fremd:
        raise SystemExit(f"unerwartete amtliche Werte: {fremd} - Abbruch.")

    direkt = [z for z in zeilen if z[2] == "Direktwahl"]
    if direkt:
        for aw_id, label, _ in direkt:
            log.warning("Nachruecker mit amtlicher Direktwahl: %s", label)
        raise SystemExit(f"{len(direkt)} Nachruecker mit Direktwahl - " "Abbruch, das ist zu klaeren.")

    log.info("%s Mandate mit 'moved_up', alle amtlich 'Landesliste'.",
             len(zeilen))
    return zeilen


def setze():
    run_sql(f"""
        UPDATE {SCHEMA}.candidacy_mandate
           SET mandatsart = CASE mandatsart_amtlich
                              WHEN 'Landesliste' THEN 'list'
                              WHEN 'Direktwahl'  THEN 'constituency'
                            END,
               mandatsart_herkunft = 'amtlich_ersetzt'
         WHERE type = 'mandate'
           AND mandatsart = 'moved_up'
           AND mandatsart_amtlich IS NOT NULL;
    """, "Mandatsart der Nachruecker auf den amtlichen Wert setzen")


def bericht():


    log.info("--- Mandatsart nach dem Eingriff ---")
    for art, herkunft, roh, n in query(f"""
            SELECT mandatsart, mandatsart_herkunft, mandate_won, count(*)
              FROM {SCHEMA}.candidacy_mandate WHERE type = 'mandate'
             GROUP BY 1, 2, 3 ORDER BY 4 DESC;"""):
        log.info("%-14s %-18s geliefert=%-14s %s",
                 art, herkunft, roh or "(leer)", n)

    rest = query(f"SELECT count(*) FROM {SCHEMA}.candidacy_mandate " "WHERE type = 'mandate' AND mandatsart = 'moved_up';")[0][0]
    log.info("verbliebene 'moved_up' in mandatsart: %s", rest)

    erhalten = query(f"SELECT count(*) FROM {SCHEMA}.candidacy_mandate " "WHERE type = 'mandate' AND mandate_won = 'moved_up';")[0][0]
    log.info("gelieferter Wert 'moved_up' weiterhin in mandate_won: %s",
             erhalten)

    log.info("--- Nachruecken steht in %s.nachfolge ---", SCHEMA)
    for wp, n in query(f"SELECT wp, count(*) FROM {SCHEMA}.nachfolge " "GROUP BY wp ORDER BY wp;"):
        log.info("  WP %s: %s Uebergaenge", wp, n)


def main():


    if pruefe_vorher():
        setze()
    bericht()


if __name__ == "__main__":
    main()
