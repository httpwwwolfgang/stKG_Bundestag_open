import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import query

ROH = "roh_bundestag"
AW = "politiker_innen"


LABEL = {18: "2013", 19: "2017", 20: "2021"}

WORT = re.compile(r"[^\W\d_]+", re.UNICODE)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("zuordnung")


def woerter(name):
    return set(w.casefold() for w in WORT.findall(name or ""))


def abschnitt(titel):
    log.info("\n%s\n%s", titel, "-" * len(titel))


def lies_nachfolge():
    zeilen = []
    for wp, lfd, rolle, name, datum in query(f"""
            SELECT wp, lfd, 'ausgeschieden', vorgaenger_name,
                   coalesce(ausgeschieden_am::text, '')
              FROM {ROH}.nachfolge WHERE vorgaenger_name IS NOT NULL
            UNION ALL
            SELECT wp, lfd, 'nachgerueckt', nachfolger_name,
                   coalesce(eingetreten_am::text, '')
              FROM {ROH}.nachfolge WHERE nachfolger_name IS NOT NULL
            ORDER BY 1, 2, 3;"""):
        zeilen.append((int(wp), int(lfd), rolle, name, datum or None))
    return zeilen


def lies_stammdaten():
    bestand = defaultdict(list)
    for wp, mdb_id, vorname, nachname, von, bis in query(f"""
            SELECT w.wp, w.id, n.vorname, n.nachname,
                   coalesce(w.mdbwp_von::text, ''), coalesce(w.mdbwp_bis::text, '')
              FROM {ROH}.stammdaten_mdb_wahlperiode w
              JOIN {ROH}.stammdaten_mdb_name n ON n.id = w.id
             WHERE w.wp IN (18, 19, 20);"""):
        bestand[int(wp)].append((mdb_id, vorname, nachname, von or None, bis or None))
    return bestand


def lies_abgeordnetenwatch():
    bestand = defaultdict(list)
    for label, aw_id, vorname, nachname in query(f"""
            SELECT DISTINCT m.parliament_period_label, p.aw_id,
                            p.first_name, p.last_name
              FROM {AW}.candidacy_mandate m
              JOIN {AW}.politician p ON p.aw_id = m.politician_id;"""):
        for wp, teil in LABEL.items():
            if label.startswith("Bundestag") and teil in label.split("-")[0]:
                bestand[wp].append((aw_id, vorname, nachname))
    return bestand


def treffer(name, kandidaten):
    gesucht = woerter(name)
    gefunden = {}
    for eintrag in kandidaten:
        vorname, nachname = eintrag[1], eintrag[2]
        if not vorname or not nachname:
            continue
        if woerter(vorname) <= gesucht and woerter(nachname) <= gesucht:
            gefunden.setdefault(eintrag[0], eintrag)
    return list(gefunden.values())


def pruefe(bezeichnung, nennungen, bestand, mit_datum):
    abschnitt(f"{bezeichnung}")
    zaehler = defaultdict(int)
    mehrdeutig, ohne, datum_weicht = [], [], []

    for wp, lfd, rolle, name, datum in nennungen:
        gefunden = treffer(name, bestand.get(wp, []))
        if len(gefunden) == 1:
            zaehler["eindeutig"] += 1
            if mit_datum and datum:
                eintrag = gefunden[0]
                soll = eintrag[3] if rolle == "nachgerueckt" else eintrag[4]
                if soll != datum:
                    datum_weicht.append((wp, lfd, rolle, name, datum, soll))
        elif len(gefunden) > 1:
            zaehler["mehrdeutig"] += 1
            mehrdeutig.append((wp, lfd, rolle, name,
                               [f"{e[0]} {e[1]} {e[2]}" for e in gefunden]))
        else:
            zaehler["ohne Treffer"] += 1
            ohne.append((wp, lfd, rolle, name))

    gesamt = sum(zaehler.values())
    log.info("Von %d Nennungen sind %d eindeutig einer Person zuzuordnen, " "%d passen auf mehrere, %d auf keine.",
             gesamt, zaehler["eindeutig"], zaehler["mehrdeutig"],
             zaehler["ohne Treffer"])

    if mehrdeutig:
        log.info("\nMehrdeutig - hier muss die ID von Hand nachgetragen werden:")
        for wp, lfd, rolle, name, kandidaten in mehrdeutig:
            log.info("   WP %d Zeile %-3d %-12s %-30s -> %s",
                     wp, lfd, rolle, name, " | ".join(kandidaten))

    if ohne:
        log.info("\nOhne Treffer - warum steht diese Person nicht im Bestand?")
        for wp, lfd, rolle, name in ohne:
            log.info("   WP %d Zeile %-3d %-12s %s", wp, lfd, rolle, name)

    if datum_weicht:
        log.info("\nEindeutig, aber das Mandatsdatum weicht ab " "(Seite <-> Bestand) - Zuordnung nicht bestaetigt:")
        for wp, lfd, rolle, name, seite, soll in datum_weicht:
            log.info("   WP %d Zeile %-3d %-12s %-30s Seite %s, Bestand %s",
                     wp, lfd, rolle, name, seite, soll or "keins")

    return mehrdeutig, ohne


def main():


    abschnitt("0 · Kommen die Umlaute richtig in der Tabelle an?")
    for wp, lfd, name in query(f"""
            SELECT wp, lfd, vorgaenger_name FROM {ROH}.nachfolge
             WHERE vorgaenger_name !~ '^[[:ascii:]]*$' ORDER BY wp, lfd LIMIT 5;"""):
        log.info("   WP %s Zeile %-3s %s", wp, lfd, name)

    nennungen = lies_nachfolge()
    abschnitt("1 · Wie viele Personen sind ueberhaupt zu verknuepfen?")
    je_wp = defaultdict(int)
    for wp, _, _, _, _ in nennungen:
        je_wp[wp] += 1
    for wp in sorted(je_wp):
        log.info("   WP %d: %d Nennungen (Ausgeschiedene und Nachrueckende " "zusammen)", wp, je_wp[wp])
    log.info("   insgesamt: %d", len(nennungen))

    abschnitt("2 · Steht derselbe Name mehrfach auf einer Seite?")
    doppelt = defaultdict(list)
    for wp, lfd, rolle, name, _ in nennungen:
        doppelt[(wp, name)].append((lfd, rolle))
    mehrfach = {k: v for k, v in doppelt.items() if len(v) > 1}
    if mehrfach:
        for (wp, name), stellen in sorted(mehrfach.items()):
            log.info("   WP %d  %-30s %d Nennungen: %s", wp, name,
                     len(stellen), stellen)
        log.info("   Das ist nicht zwingend ein Fehler: wer ausscheidet, kann " "vorher nachgerueckt sein.")
    else:
        log.info("   Nein - jeder Name kommt je Wahlperiode nur einmal vor.")

    pruefe("3 · Abgleich gegen die amtlichen MdB-Stammdaten",
           nennungen, lies_stammdaten(), mit_datum=True)
    pruefe("4 · Abgleich gegen Abgeordnetenwatch",
           nennungen, lies_abgeordnetenwatch(), mit_datum=False)


if __name__ == "__main__":
    main()
