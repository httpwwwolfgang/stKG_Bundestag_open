import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lade_parlamentsarbeit import (
    SCHEMA, lade, neueste, leer_zu_null,
)
from lade_parlamentsarbeit import run_sql, run_sql_file, query

import tempfile


SCHEMA_SQL = f"""
DROP TABLE IF EXISTS {SCHEMA}.kommentar_urheber;
DROP TABLE IF EXISTS {SCHEMA}.kommentar_art;
DROP TABLE IF EXISTS {SCHEMA}.kommentar;

CREATE TABLE {SCHEMA}.kommentar (
    kommentar_id     text PRIMARY KEY,
    protokoll_nr     text NOT NULL,
    wahlperiode      smallint NOT NULL,
    kontext          text NOT NULL,
    rede_id          text,
    top_id           text,
    lfd              integer,
    nach_absatz      integer,
    absaetze_gesamt  integer,
    ereignisse       smallint NOT NULL,
    text             text NOT NULL,
    doppelt          boolean NOT NULL DEFAULT false
);

CREATE TABLE {SCHEMA}.kommentar_art (
    kommentar_id    text NOT NULL,
    lfd_ereignis    smallint NOT NULL,
    rede_id         text,
    art             text NOT NULL,
    urheber_anzahl  smallint NOT NULL,
    text            text NOT NULL,
    PRIMARY KEY (kommentar_id, lfd_ereignis)
);

CREATE TABLE {SCHEMA}.kommentar_urheber (
    kommentar_id        text NOT NULL,
    lfd_ereignis        smallint NOT NULL,
    lfd_urheber         smallint NOT NULL,
    urheber_art         text NOT NULL,
    fraktion_id         text,
    urheber_name        text,
    urheber_redner_id   text,
    namenslage          text,
    schreibweise        text,
    umfang              text,
    fundstelle_im_text  integer,
    PRIMARY KEY (kommentar_id, lfd_ereignis, lfd_urheber)
);

COMMENT ON TABLE {SCHEMA}.kommentar IS
 'Klammerbloecke der Plenarprotokolle ab WP 18
 'geschieht. Ein Block kann mehrere Ereignisse enthalten; die stehen in '
 'kommentar_art. kontext sagt, woran der Block haengt: rede, '
 'tagesordnungspunkt, sitzungsbeginn oder anlage. Bei den letzten drei ist '
 'rede_id leer (15.892 Bloecke).';
COMMENT ON COLUMN {SCHEMA}.kommentar.doppelt IS
 'Derselbe Klammertext erscheint im Protokoll zweimal an derselben Stelle '
 '(436 Bloecke). Nicht entfernt, damit die Zaehlung dem Protokoll folgt.';
COMMENT ON TABLE {SCHEMA}.kommentar_art IS
 'Einzelereignisse je Klammerblock mit ihrer Art. Einteilung nach Open '
 'Discourse (Richter/Koch/Franke 2020), Muster neu geschrieben fuer die '
 'annotierten XML. person_wortlaut ist die Aeusserung einer einzelnen '
 'Person mit wiedergegebenem Wortlaut und nicht mit zuruf zu vermengen.';
COMMENT ON COLUMN {SCHEMA}.kommentar_urheber.urheber_redner_id IS
 'Die Sprecherkennung des Zwischenrufers
 'rede.redner_id. Damit haengen Rede und Zwischenruf am selben Menschen. '
 'Leer, wo der Name nicht eindeutig aufloesbar war; namenslage sagt warum.';
COMMENT ON COLUMN {SCHEMA}.kommentar_urheber.namenslage IS
 'eindeutig = Name und Fraktion stimmen (283.153). nur_name = Name '
 'eindeutig, die Fraktion in der eckigen Klammer widerspricht (15, noch '
 'nicht geprueft)
 'und kein_treffer (74) sind nicht aufgeloest, redner_id bleibt leer.';
COMMENT ON COLUMN {SCHEMA}.kommentar_urheber.urheber_name IS
 'Der Name, wie ihn das Protokoll vor der eckigen Klammer nennt
 'unaufgeloest, nicht auf parlamentsarbeit.redner abgebildet. Gesetzt bei '
 'umfang = person, sonst leer.';
COMMENT ON TABLE {SCHEMA}.kommentar_urheber IS
 'Wer das Ereignis ausgeloest hat. umfang unterscheidet, ob eine ganze '
 'Fraktion, einzelne Abgeordnete, eine benannte Person oder das ganze Haus '
 'gemeint sind. '
 'fraktion_id verweist auf politiker_innen.fraktion_kanonisch, ohne '
 'Fremdschluessel
"""

ARTEN_ERWARTET = {
    "beifall", "person_wortlaut", "zuruf", "heiterkeit", "lachen",
    "widerspruch", "abgeordneter", "handlung", "unruhe", "sonstiges",
    "unterbrechung", "zustimmung", "glocke",
}

ART_ERWARTET = {"person", "fraktion", "haus"}

UMFANG_ERWARTET = {"ganz", "teilweise", ""}

NAMENSLAGE_ERWARTET = {"eindeutig", "nur_name", "mehrdeutig",
                       "kein_treffer", ""}


def ja_zu_boolean(spalten):
    def f(d):
        d = d.copy()
        for s in spalten:
            d[s] = d[s].str.strip().str.lower().eq("ja").map(
                {True: "true", False: "false"})
        return d
    return f


def pruefe_zusammenhang():


    verwaist = int(query(f"""
        SELECT count(*) FROM {SCHEMA}.kommentar_art a
         WHERE NOT EXISTS (SELECT 1 FROM {SCHEMA}.kommentar k
                            WHERE k.kommentar_id = a.kommentar_id);""")[0][0])
    if verwaist:
        raise SystemExit(
            f"{verwaist} Ereignisse zeigen auf einen Block, den es nicht " "gibt. Die Exportdateien stammen aus verschiedenen Laeufen -- " "erst neu erzeugen, dann laden.")

    verwaist = int(query(f"""
        SELECT count(*) FROM {SCHEMA}.kommentar_urheber u
         WHERE NOT EXISTS (SELECT 1 FROM {SCHEMA}.kommentar_art a
                            WHERE a.kommentar_id = u.kommentar_id
                              AND a.lfd_ereignis = u.lfd_ereignis);""")[0][0])
    if verwaist:
        raise SystemExit(f"{verwaist} Urheber ohne zugehoeriges Ereignis.")

    print("  jede Kennung zeigt auf einen vorhandenen Block")


def pruefe_wertebereiche():
    for tabelle, spalte, erwartet in [
            ("kommentar_art", "art", ARTEN_ERWARTET),
            ("kommentar_urheber", "urheber_art", ART_ERWARTET),
            ("kommentar_urheber", "umfang", UMFANG_ERWARTET),
            ("kommentar_urheber", "namenslage", NAMENSLAGE_ERWARTET)]:
        ist = {z[0] or "" for z in query(
            f"SELECT DISTINCT {spalte} FROM {SCHEMA}.{tabelle};")}
        neu = sorted(ist - erwartet)
        if neu:
            raise SystemExit(
                f"{tabelle}.{spalte} bringt unbekannte Werte mit: {neu}. " "Die Codeliste im Schema kennt sie nicht -- vorlegen, " "nicht stillschweigend aufnehmen.")
    print("  keine unbekannten Arten oder Umfaenge")


def bericht():
    print("--- Kommentare nach Kontext ---")
    for kontext, n, ohne_rede in query(f"""
            SELECT kontext, count(*), count(*) FILTER (WHERE rede_id IS NULL)
              FROM {SCHEMA}.kommentar GROUP BY 1 ORDER BY 2 DESC;"""):
        print(f"  {int(n):>9,}  {kontext:<20} davon ohne Rede: "
              f"{int(ohne_rede):,}")

    print("--- Ereignisse nach Art ---")
    for art, n in query(f"""
            SELECT art, count(*) FROM {SCHEMA}.kommentar_art
             GROUP BY 1 ORDER BY 2 DESC;"""):
        print(f"  {int(n):>9,}  {art}")

    print("--- Urheber nach Art, Fraktionen ganz oder teilweise ---")
    for art, umfang, n in query(f"""
            SELECT urheber_art, coalesce(umfang,'-'), count(*)
              FROM {SCHEMA}.kommentar_urheber
             GROUP BY 1, 2 ORDER BY 3 DESC;"""):
        print(f"  {int(n):>9,}  {art:<10} {umfang}")

    print("--- Haengen die Bloecke an bekannten Reden? ---")
    for lage, n in query(f"""
            SELECT CASE WHEN k.rede_id IS NULL THEN 'ohne rede_id'
                        WHEN r.rede_id IS NULL THEN 'rede_id unbekannt'
                        ELSE 'Rede vorhanden' END, count(*)
              FROM {SCHEMA}.kommentar k
              LEFT JOIN {SCHEMA}.rede r ON r.rede_id = k.rede_id
             GROUP BY 1 ORDER BY 2 DESC;"""):
        print(f"  {int(n):>9,}  {lage}")

    print("--- Sind die Fraktionskennungen bekannt? ---")
    for lage, n in query(f"""
            SELECT CASE WHEN u.fraktion_id IS NULL THEN 'ohne Kennung'
                        WHEN f.fraktion_id IS NULL THEN 'KENNUNG UNBEKANNT'
                        ELSE 'bekannt' END, count(*)
              FROM {SCHEMA}.kommentar_urheber u
              LEFT JOIN politiker_innen.fraktion_kanonisch f
                     ON f.fraktion_id = u.fraktion_id
             GROUP BY 1 ORDER BY 2 DESC;"""):
        print(f"  {int(n):>9,}  {lage}")


def main():
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False,
                                     encoding="utf-8") as f:
        f.write(SCHEMA_SQL)
        pfad = Path(f.name)
    run_sql_file(pfad, "Tabellen fuer die Kommentare")
    pfad.unlink(missing_ok=True)

    lade("kommentar", neueste("kommentar_2*.csv"),
         ["kommentar_id", "protokoll_nr", "wahlperiode", "kontext",
          "rede_id", "top_id", "lfd", "nach_absatz", "absaetze_gesamt",
          "ereignisse", "text", "doppelt"],
         wandeln=lambda d: ja_zu_boolean(["doppelt"])(
             leer_zu_null(["rede_id", "top_id", "lfd", "nach_absatz",
                           "absaetze_gesamt"])(d)))

    lade("kommentar_art", neueste("kommentar_art_*.csv"),
         ["kommentar_id", "lfd_ereignis", "rede_id", "art",
          "urheber_anzahl", "text"],
         wandeln=leer_zu_null(["rede_id"]))

    lade("kommentar_urheber", neueste("kommentar_urheber_*.csv"),
         ["kommentar_id", "lfd_ereignis", "lfd_urheber", "fraktion_id",
          "urheber_art", "urheber_name", "urheber_redner_id",
          "namenslage", "schreibweise", "umfang", "fundstelle_im_text"],
         wandeln=leer_zu_null(["fraktion_id", "urheber_name",
                               "urheber_redner_id", "namenslage",
                               "schreibweise", "umfang",
                               "fundstelle_im_text"]))

    pruefe_zusammenhang()
    pruefe_wertebereiche()
    bericht()


if __name__ == "__main__":
    main()
