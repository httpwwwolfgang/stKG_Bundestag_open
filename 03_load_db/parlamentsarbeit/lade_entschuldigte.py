import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from lade_parlamentsarbeit import (
    SCHEMA, ZWISCHEN, lade, neueste, leer_zu_null, run_sql_file, query,
)
import korrekturen

SCHEMA_SQL = f"""
DROP TABLE IF EXISTS {SCHEMA}.entschuldigt;

CREATE TABLE {SCHEMA}.entschuldigt (
    protokoll_nr      text NOT NULL,
    wahlperiode       smallint NOT NULL,
    sitzung_nr        integer NOT NULL,
    sitzung_datum     date,
    lfd               integer NOT NULL,
    titel             text,
    nachname          text NOT NULL,
    vorname           text NOT NULL,
    ortszusatz        text,
    grund             text,
    entschuldigt_bis  date,
    fraktion_roh      text,
    fraktion_id       text,
    mdb_id            text,
    namenslage        text,
    mdb_kandidaten    text,
    anlagen_typ       text,
    PRIMARY KEY (protokoll_nr, lfd)
);

COMMENT ON TABLE {SCHEMA}.entschuldigt IS
 'Entschuldigt fehlende Abgeordnete je Sitzung, aus der Anlage der '
 'Plenarprotokolle ab WP 18. KEINE Anwesenheitsliste: Das Protokoll fuehrt '
 'nur, wer sich entschuldigt hat
 'unentschuldigt fehlte. Aus dem Fehlen einer Zeile folgt keine Anwesenheit. '
 '5 der 697 Sitzungen mit Reden fuehren ueberhaupt keine Liste: 19/154 bis '
 '19/156 ohne Anlage (Beginn der Corona-Pandemie), 18/87 und 19/1 mit leerer '
 'Anlage
COMMENT ON COLUMN {SCHEMA}.entschuldigt.entschuldigt_bis IS
 'Aus der dritten Spalte der Anlage. Sie laeuft bis Sitzung 31 der WP 19 '
 'und entfaellt danach: 7.156 Werte in WP 18, 980 in WP 19, keiner in WP 20. '
 'Wo sie fehlt, ist sie nicht unbekannt, sondern nicht erhoben.';
COMMENT ON COLUMN {SCHEMA}.entschuldigt.grund IS
 'In 431 von 28.173 Zeilen, in vier Schreibweisen fuer zwei Sachverhalte: '
 'gesetzlicher Mutterschutz (329) und Teilnahme an einer Parlamentarischen '
 'Versammlung (102). Unveraendert uebernommen.';
COMMENT ON COLUMN {SCHEMA}.entschuldigt.nachname IS
 'Aus dem Protokolltext geparst. Die Anlage nennt keine Personenkennung; '
 'mdb_id wird nachtraeglich ueber politiker_innen.mdb_namensalias bestimmt.';
COMMENT ON COLUMN {SCHEMA}.entschuldigt.mdb_id IS
 'Nachtraeglich ueber politiker_innen.mdb_namensalias zugeordnet. Der Name '
 'entscheidet; Mandat und Fraktion trennen nur Gleichnamige. Alle 28.173 '
 'Zeilen sind zugeordnet
COMMENT ON COLUMN {SCHEMA}.entschuldigt.namenslage IS
 'Womit entschieden wurde. ueber_namen: genau ein Namenstreffer, Mandat und '
 'Fraktion passen dazu (28.160). Abweichungen der Nebenangaben, die die '
 'Zuordnung nicht aendern: _ohne_fraktionsangabe (6, Regierungsamt oder '
 'Tippfehler in der Fraktionsspalte), _ohne_mandat (3, Zypries als '
 'Ministerin ohne Mandat in WP 19), _nach_schreibfehler (4,'
 'P5). Nicht belegt, aber vorgesehen: ueber_mandat, ueber_fraktion, '
 'ueber_namen_fraktion_widerspricht, mehrdeutig, kein_treffer.';
COMMENT ON COLUMN {SCHEMA}.entschuldigt.mdb_kandidaten IS
 'Bei offener Zuordnung die gefundenen mdb_id, mit ; getrennt. Damit geht '
 'kein Kandidat verloren, nur weil keiner entschieden werden konnte.';
"""


GRADE = {"dr", "prof", "h", "c", "med", "jur", "rer", "nat", "phil", "ing",
         "dipl", "freiherr", "graf", "graefin"}


def namensworte(wert):
    t = unicodedata.normalize("NFKC", str(wert or "")).replace(chr(0xAD), "")
    t = re.sub(r"\s*-\s*", "-", t)
    t = re.sub(r"[^\w\s-]", " ", t)
    return {w for w in t.lower().split() if w not in GRADE and len(w) > 1}


def beurteile(prot, nach, vor, wp, fid, namen, mandat, fraktion):


    fehler = korrekturen.ENTSCHULDIGT_SCHREIBFEHLER.get((prot, nach, vor))
    lage_zusatz = ""
    if fehler:
        nach, vor = fehler[0], fehler[1]
        lage_zusatz = "_nach_schreibfehler"

    w = namensworte(f"{vor} {nach}")
    kand = [m for m, formen in namen.items()
            if any(f <= w or w <= f for f in formen)]
    if not kand:
        return "", "kein_treffer", ""

    if len(kand) == 1:
        mdb = kand[0]


        if wp not in mandat.get(mdb, set()):
            lage = "ueber_namen_ohne_mandat"
        elif not fid:
            lage = "ueber_namen_ohne_fraktionsangabe"
        elif fid in fraktion.get((mdb, wp), set()):
            lage = "ueber_namen"
        else:
            lage = "ueber_namen_fraktion_widerspricht"
        return mdb, lage + lage_zusatz, ""

    in_wp = [m for m in kand if wp in mandat.get(m, set())]
    if len(in_wp) == 1:
        return in_wp[0], "ueber_mandat" + lage_zusatz, ""

    basis = in_wp or kand
    mit_frak = [m for m in basis if fid and fid in fraktion.get((m, wp), set())]
    if len(mit_frak) == 1:
        return mit_frak[0], "ueber_fraktion" + lage_zusatz, ""

    return "", "mehrdeutig" + lage_zusatz, ";".join(sorted(mit_frak or basis))


def loese_personen_auf():
    namen = defaultdict(set)
    for mdb, nach, vor in query("""
            SELECT mdb_id, nachname, vorname
              FROM politiker_innen.mdb_namensalias;"""):
        w = namensworte(f"{vor} {nach}")
        if w:
            namen[mdb].add(frozenset(w))

    mandat, fraktion = defaultdict(set), defaultdict(set)
    for mdb, wp, fid in query("""
            SELECT z.mdb_id, z.wp, al.fraktion_id
              FROM politiker_innen.fraktionszugehoerigkeit z
              LEFT JOIN politiker_innen.fraktion_alias al
                     ON al.quelle =
                        'politiker_innen.fraktionszugehoerigkeit.fraktion'
                    AND al.schreibweise = z.fraktion
             WHERE z.wp >= 18;"""):
        mandat[mdb].add(str(wp))
        if fid:
            fraktion[(mdb, str(wp))].add(fid)

    zeilen, zaehler, merker = [], Counter(), {}
    for prot, lfd, nach, vor, wp, fid in query(f"""
            SELECT protokoll_nr, lfd, nachname, vorname, wahlperiode,
                   coalesce(fraktion_id, '')
              FROM {SCHEMA}.entschuldigt;"""):
        schluessel = (prot, nach, vor, wp, fid)
        if schluessel not in merker:
            merker[schluessel] = beurteile(prot, nach, vor, str(wp), fid,
                                           namen, mandat, fraktion)
        mdb, lage, kandidaten = merker[schluessel]
        zeilen.append({"protokoll_nr": prot, "lfd": lfd, "mdb_id": mdb,
                       "namenslage": lage, "mdb_kandidaten": kandidaten})
        zaehler[lage] += 1

    tmp = ZWISCHEN / "entschuldigt_person.csv"
    pd.DataFrame(zeilen)[["protokoll_nr", "lfd", "mdb_id", "namenslage",
                      "mdb_kandidaten"]].to_csv(
        tmp, index=False, sep="\t", na_rep="", encoding="utf-8")


    kopie = (r"\copy pg_temp.eperson FROM '" + tmp.as_posix()
             + r"' WITH (FORMAT csv, HEADER true, DELIMITER E'\t')")
    sql = ZWISCHEN / "entschuldigt_person.sql"
    sql.write_text(
        "DROP TABLE IF EXISTS pg_temp.eperson;\n" "CREATE TEMP TABLE eperson (protokoll_nr text, lfd integer,\n" "                           mdb_id text, namenslage text,\n" "                           mdb_kandidaten text);\n"
        + kopie + "\n"
        f"UPDATE {SCHEMA}.entschuldigt e\n" "   SET mdb_id = nullif(p.mdb_id, ''), namenslage = p.namenslage,\n" "       mdb_kandidaten = nullif(p.mdb_kandidaten, '')\n" "  FROM eperson p\n" " WHERE p.protokoll_nr = e.protokoll_nr AND p.lfd = e.lfd;\n",
        encoding="utf-8")
    run_sql_file(sql, "Personenzuordnung")
    print("\n  Namenszuordnung der Entschuldigten:")
    for k, v in zaehler.most_common():
        print(f"    {v:>7,}  {k}")


def deutsches_datum(spalten):
    def f(d):
        d = d.copy()
        for s in spalten:
            roh = d[s].str.strip()
            passt = roh.str.match(r"^\d{1,2}\.\d{1,2}\.\d{4}$")
            gewandelt = roh.str.replace(
                r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$",
                lambda m: "%s-%02d-%02d" % (m.group(3), int(m.group(2)),
                                            int(m.group(1))),
                regex=True)
            d[s] = gewandelt.where(passt, "")
        return d
    return f


def pruefe():


    fremd = query(f"""
        SELECT DISTINCT protokoll_nr FROM {SCHEMA}.entschuldigt
         WHERE sitzung_datum IS NULL
           AND protokoll_nr NOT IN ('18/13','18/14','18/15','18/16','18/17',
                                    '18/18');""")
    if fremd:
        raise SystemExit("Zeilen ohne Sitzungsdatum ausserhalb der bekannten " "sechs Protokolle: %s" % [z[0] for z in fremd])
    ohne_datum = query(f"""
        SELECT count(*) FROM {SCHEMA}.entschuldigt
         WHERE sitzung_datum IS NULL;""")[0][0]
    print(f"  ohne Sitzungsdatum: {int(ohne_datum)} (A30, kaputtes XML)")


    for wp, n, m in query(f"""
            SELECT wahlperiode, count(*), max(sitzung_nr)
              FROM {SCHEMA}.entschuldigt WHERE entschuldigt_bis IS NOT NULL
             GROUP BY 1 ORDER BY 1;"""):
        print(f"  entschuldigt_bis in WP {wp}: {int(n):>6,} Zeilen, "
              f"letzte Sitzung {m}")


    ohne = int(query(f"""
        SELECT count(DISTINCT r.protokoll_nr)
          FROM {SCHEMA}.rede r
         WHERE NOT EXISTS (
               SELECT 1 FROM {SCHEMA}.entschuldigt e
                WHERE e.protokoll_nr = replace(r.protokoll_nr, ' (neu)', ''));
        """)[0][0])
    print(f"  Sitzungen ohne Entschuldigtenliste: {ohne} von 697 " "(erwartet: 5 -- 18/87 und 19/1 mit leerer Anlage, " "19/154 bis 19/156 ohne Anlage)")
    if ohne != 5:
        raise SystemExit(
            f"{ohne} Sitzungen ohne Liste, erwartet sind 5. Entweder hat " "der Leser eine Bauform verloren oder es ist eine neue " "Lieferung -- nachsehen, nicht durchwinken.")

    for wp, n in query(f"""
            SELECT wahlperiode, count(*) FROM {SCHEMA}.entschuldigt
             GROUP BY 1 ORDER BY 1;"""):
        print(f"  WP {wp}: {int(n):>7,} Nennungen")

    for g, n in query(f"""
            SELECT coalesce(grund, '(ohne)'), count(*)
              FROM {SCHEMA}.entschuldigt GROUP BY 1 ORDER BY 2 DESC;"""):
        print(f"  {int(n):>7,}  {g}")

    bis = query(f"""
        SELECT wahlperiode, count(entschuldigt_bis)
          FROM {SCHEMA}.entschuldigt GROUP BY 1 ORDER BY 1;""")
    print("  entschuldigt_bis je WP: " +
          ", ".join(f"WP {w}: {int(n):,}" for w, n in bis))


def main():
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False,
                                     encoding="utf-8") as f:
        f.write(SCHEMA_SQL)
        pfad = Path(f.name)
    run_sql_file(pfad, "Tabelle fuer die Entschuldigten")
    pfad.unlink(missing_ok=True)

    lade("entschuldigt", neueste("entschuldigt_2*.csv"),
         ["protokoll_nr", "wahlperiode", "sitzung_nr", "sitzung_datum",
          "lfd", "titel", "nachname", "vorname", "ortszusatz", "grund",
          "entschuldigt_bis", "fraktion_roh", "fraktion_id", "anlagen_typ"],
         wandeln=lambda d: leer_zu_null(
             ["titel", "ortszusatz", "grund", "entschuldigt_bis",
              "fraktion_roh", "fraktion_id", "anlagen_typ"])(
                 deutsches_datum(["sitzung_datum", "entschuldigt_bis"])(d)))

    loese_personen_auf()
    pruefe()


if __name__ == "__main__":
    main()
