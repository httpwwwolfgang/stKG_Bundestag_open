import csv
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wahlergebnisse"))

from db import run_sql_file, query
from load_partei_mapping import normalise_party, lit

META = "meta"
TABELLE = "partei_mapping"
AW = "politiker_innen"
LIEFERUNG = "aw_api_v2"


KEINE_PARTEI = {"Einzelbewerbung"}


ALIAS = (Path(__file__).resolve().parents[2] / "01_fetch"
         / "abgeordnetenwatch" / "korrekturen_partei_alias.csv")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("partei-mapping-aw")


def lies_alias():
    if not ALIAS.exists():
        raise SystemExit(f"Aliasliste fehlt: {ALIAS}")
    with ALIAS.open(encoding="utf-8", newline="") as f:
        return {z["aw_label"]: z for z in csv.DictReader(f, delimiter=";")}


def main():
    alias = lies_alias()
    log.info("%d Aliase aus %s", len(alias), ALIAS.name)
    for a in alias.values():
        log.info("   %-34s -> %-22s (%s, %s)", a["aw_label"][:32],
                 a["ziel_schluessel"], a["amtlicher_name"], a["wahl"])

    roh = query(f"""
        SELECT label FROM {AW}.partei
         WHERE EXISTS (SELECT 1 FROM {AW}.candidacy_mandate c
                        WHERE c.party_id = {AW}.partei.aw_id)
         ORDER BY label;""")
    log.info("%d Parteibezeichnungen mit mindestens einer Kandidatur", len(roh))

    werte = []
    for (name,) in roh:
        if name in KEINE_PARTEI:
            schluessel, verfahren = name.lower(), "keine_partei"
        elif name in alias:
            schluessel, verfahren = alias[name]["ziel_schluessel"], "alias"
        else:
            schluessel, verfahren = normalise_party(name)
        werte.append(f"({lit(name)}, {lit(schluessel)}, {lit(verfahren)}, "
                     f"ARRAY[{lit(LIEFERUNG)}])")


    sql = (f"INSERT INTO {META}.{TABELLE} "
           f"(partei_roh, partei, verfahren, lieferung_ids)\nVALUES\n"
           + ",\n".join(werte) + "\n"
           f"ON CONFLICT (partei_roh) DO UPDATE SET\n"


           f"    partei    = EXCLUDED.partei,\n"
           f"    verfahren = EXCLUDED.verfahren,\n"
           f"    lieferung_ids = (SELECT array_agg(DISTINCT x ORDER BY x)\n"
           f"                       FROM unnest({TABELLE}.lieferung_ids\n"
           f"                                   || EXCLUDED.lieferung_ids) x);\n")
    tmp = Path(tempfile.gettempdir()) / "partei_mapping_aw.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, label="partei_mapping_aw")
    tmp.unlink(missing_ok=True)

    log.info("--- Die Tabelle nach Lieferung ---")
    for zeile in query(f"""
            SELECT CASE
                     WHEN lieferung_ids @> ARRAY['{LIEFERUNG}']
                          AND array_length(lieferung_ids, 1) > 1
                       THEN 'beide'
                     WHEN lieferung_ids @> ARRAY['{LIEFERUNG}'] THEN 'nur aw'
                     ELSE 'nur amtlich' END AS woher,
                   count(*)::text
              FROM {META}.{TABELLE} GROUP BY 1 ORDER BY 2 DESC;"""):
        log.info("   %-14s %s Rohnamen", *zeile)

    log.info("--- Was jetzt anschliessbar ist ---")
    for offen, gesamt in query(f"""
            SELECT count(*) FILTER (WHERE NOT EXISTS (
                     SELECT 1 FROM {META}.{TABELLE} m
                      WHERE m.partei_roh = k.party_label))::text,
                   count(*)::text
              FROM {AW}.kandidatur k WHERE k.party_label IS NOT NULL;"""):
        log.info("   Kandidaturen ohne Mapping: %s von %s (vorher 1.406)",
                 offen, gesamt)

    log.info("--- Gegenprobe: treffen aw und amtlich denselben Schluessel? ---")
    for zeile in query(f"""
            SELECT a.partei_roh, b.partei_roh, a.partei
              FROM {META}.{TABELLE} a
              JOIN {META}.{TABELLE} b
                ON b.partei = a.partei AND b.partei_roh <> a.partei_roh
             WHERE a.lieferung_ids @> ARRAY['{LIEFERUNG}']
               AND NOT b.lieferung_ids @> ARRAY['{LIEFERUNG}']
             ORDER BY a.partei LIMIT 12;"""):
        log.info("   %-34s %-24s -> %s", zeile[0][:32], zeile[1][:22], zeile[2])

    log.info("--- Und was das oeffnet: Kandidat gegen amtliches Ergebnis ---")
    for zeile in query(f"""
            SELECT k.politician_label, k.wkr_nr::text, m.partei,
                   e.stimmen::text, k.erststimmen_anteil::text
              FROM {AW}.kandidatur k
              JOIN {META}.{TABELLE} m ON m.partei_roh = k.party_label
              JOIN {META}.{TABELLE} m2 ON m2.partei = m.partei
               AND NOT m2.lieferung_ids @> ARRAY['{LIEFERUNG}']
              JOIN wahlergebnisse.wahlkreis_ergebnis e
                ON e.wahljahr = 2021 AND e.wkr_nr = k.wkr_nr
               AND e.stimme = 'erststimme' AND e.partei = m2.partei_roh
             WHERE k.wahl LIKE '%2021' AND k.wkr_nr = 218
             ORDER BY e.stimmen DESC LIMIT 6;"""):
        log.info("   WK %s  %-26s %-14s %8s Erststimmen (%s %%)",
                 zeile[1], zeile[0][:24], zeile[2], zeile[3], zeile[4])

    log.info("--- Rohnamen ohne Parteischluessel ---")
    for name, n in query(f"""
            SELECT partei_roh, count(*)::text FROM {META}.{TABELLE}
             WHERE verfahren = 'keine_partei' GROUP BY 1;"""):
        log.info("   %s (verfahren = keine_partei)", name)


if __name__ == "__main__":
    main()
