import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import log, query, run_sql

QUELLE = "gerda_seit_1990.gemeinde_harm21"


def wahltage():
    zeilen = query("""SELECT wahljahr, wahltag, count(*)
                        FROM %s
                       GROUP BY 1, 2 ORDER BY 1""" % QUELLE)
    aus = {}
    for r in zeilen:
        jahr = int(str(r[0]).strip())
        tag = str(r[1]).strip()
        if jahr in aus:
            raise SystemExit(
                "Wahljahr %d nennt mehr als einen Wahltag (%s und %s) -- " "die Quelle ist uneindeutig, hier wird nicht gewaehlt."
                % (jahr, aus[jahr], tag))
        aus[jahr] = tag
    return aus


def main():
    neu = wahltage()
    log.info("GERDA nennt %d Wahlen: %s", len(neu),
             ", ".join(str(j) for j in sorted(neu)))

    vorhanden = {int(str(r[0]).strip()): str(r[1]).strip()
                 for r in query("SELECT wahljahr, wahltag FROM wahlergebnisse.wahl")}
    log.info("wahlergebnisse.wahl fuehrt bisher %d: %s", len(vorhanden),
             ", ".join(str(j) for j in sorted(vorhanden)))


    for jahr, tag in sorted(vorhanden.items()):
        if jahr in neu and neu[jahr] != tag:
            log.warning("  %d: bisher %s, GERDA nennt %s -- NICHT geaendert",
                        jahr, tag, neu[jahr])

    fehlend = {j: t for j, t in neu.items() if j not in vorhanden}
    if not fehlend:
        log.info("Nichts zu ergaenzen.")
        return

    werte = ", ".join("(%d, DATE '%s')" % (j, t) for j, t in sorted(fehlend.items()))
    run_sql("INSERT INTO wahlergebnisse.wahl (wahljahr, wahltag) VALUES %s " "ON CONFLICT (wahljahr) DO NOTHING;" % werte)
    log.info("%d Wahlen ergaenzt: %s", len(fehlend),
             ", ".join("%d (%s)" % (j, t) for j, t in sorted(fehlend.items())))

    for r in query("SELECT wahljahr, wahltag FROM wahlergebnisse.wahl ORDER BY 1"):
        log.info("  %s  %s", str(r[0]).strip(), str(r[1]).strip())


if __name__ == "__main__":
    main()
