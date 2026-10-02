import glob
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber
import psycopg2
from psycopg2.extras import execute_values

QUELLE = (Path(__file__).resolve().parents[4] / "Daten" / "politiker_innen"
          / "bundestag_namentliche_abstimmungen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dsn
DSN = dsn()
AW = "politiker_innen"
LIEFERUNG = "bt_namentliche_abstimmungen"
KORREKTUREN = (Path(__file__).resolve().parents[2] / "01_fetch"
               / "bundestag" / "korrekturen_abstimmung_kopf.csv")


VORLAGEARTEN = (
    "Beschlussempfehlung", "Gesetzentwurf", "Gesetzentwürfe",
    "Entschließungsantrag", "Entschließungsanträge",
    "Änderungsantrag", "Änderungsanträge",
    "Geschäftsordnungsantrag", "Antrag", "Anträge", "Einspruch",
    "Bericht", "Wahlvorschlag", "Unterrichtung", "Verordnung",
    "Zusatztagesordnungspunkt",
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("abstimmung-kopf")


DDL = f"""
SET client_min_messages TO WARNING;
DROP TABLE IF EXISTS {AW}.abstimmung_kopf_bt;

CREATE TABLE {AW}.abstimmung_kopf_bt (
    datei            TEXT PRIMARY KEY,
    pdf_datei        TEXT NOT NULL,
    sitzung_pdf      SMALLINT,
    abstimmung_pdf   SMALLINT,
    vorlageart       TEXT,
    titel_pdf        TEXT,
    drucksachen      TEXT[],
    drucksachen_zeile TEXT,
    amtl_abgegeben   SMALLINT,
    amtl_nicht_abg   SMALLINT,
    amtl_ja          SMALLINT,
    amtl_nein        SMALLINT,
    amtl_enthaltung  SMALLINT,
    amtl_ungueltig   SMALLINT,
    beginn           TIME,
    ende             TIME,
    abweichung       TEXT,
    vermerk          TEXT,
    herkunft         TEXT NOT NULL DEFAULT '{LIEFERUNG}',
    korrigierte_felder TEXT[],
    korrektur_herkunft TEXT,
    korrektur_beleg    TEXT
);
CREATE INDEX ON {AW}.abstimmung_kopf_bt USING gin (drucksachen);

COMMENT ON TABLE {AW}.abstimmung_kopf_bt IS
 'Kopfangaben aus dem PDF je namentlicher Abstimmung, Lieferung '
 '{LIEFERUNG}. Getrennt von abstimmung_bt, weil diese von '
 'load_namentliche_abstimmungen.py bei jedem Lauf neu aufgebaut wird - eine '
 'Spalte, ein Besitzer. Verbunden ueber datei.';
COMMENT ON COLUMN {AW}.abstimmung_kopf_bt.drucksachen IS
 'Alle im Kopf genannten Drucksachennummern (WP/Nummer), in der Reihenfolge '
 'des Drucks. Mehrfach, weil eine Abstimmung ueber Antrag UND '
 'Beschlussempfehlung dazu gehen kann. Einziger Schluessel, der eine '
 'Abstimmung mit einem Vorgang im DIP verbindet - in der Excel und im '
 'Listentitel steht er nicht.';
COMMENT ON COLUMN {AW}.abstimmung_kopf_bt.drucksachen_zeile IS
 'Die Drucksachenzeile im Wortlaut, unveraendert. Steht daneben, weil die '
 'zerlegte Liste Zusaetze verliert - "18/1336 (neu)" wird zu 18/1336 - und '
 'weil zwei Schreibfehler des Herausgebers ("Dr. 18/982", "Druckensachen") '
 'nur hier noch zu sehen sind.';
COMMENT ON COLUMN {AW}.abstimmung_kopf_bt.titel_pdf IS
 'Voller amtlicher Vorlagentitel, mehrzeilig zusammengefuehrt. Nicht zu '
 'verwechseln mit abstimmung_bt.titel, dem gekuerzten Titel der Trefferliste.';
COMMENT ON COLUMN {AW}.abstimmung_kopf_bt.vorlageart IS
 'Erste Kopfzeile, sofern sie mit einem amtlichen Begriff beginnt '
 '(Gesetzentwurf, Antrag, Beschlussempfehlung, ...). Sonst NULL - es wird '
 'nicht geraten.';
COMMENT ON COLUMN {AW}.abstimmung_kopf_bt.vermerk IS
 'Erlaeuterung aus korrekturen_abstimmung_kopf.csv - getrennt von abweichung, '
 'weil hier nichts widerspruechlich ist: der Vermerk haelt fest, dass eine '
 'fehlende Angabe BELEGT fehlt. Drei Abstimmungen nennen keine Drucksache, '
 'weil auch das Plenarprotokoll keine nennt - eine Geschaeftsordnungsfrage '
 'und zwei Einsprueche nach Paragraf 39 GO-BT.';
COMMENT ON COLUMN {AW}.abstimmung_kopf_bt.korrigierte_felder IS
 'Die Felder dieser Zeile, deren Wert NICHT aus dem Abstimmungs-PDF stammt, '
 'sondern aus korrekturen_abstimmung_kopf.csv. Steht ein Feldname hier, gilt '
 'fuer diesen einen Wert korrektur_herkunft statt herkunft. Betrifft 5 der '
 '642 Abstimmungen: zwei eingescannte PDF ohne Textebene, zwei unlesbar '
 'gedruckte Drucksachennummern und eines, unter dem der Bundestag das PDF '
 'einer anderen Sitzung verlinkt.';
COMMENT ON COLUMN {AW}.abstimmung_kopf_bt.korrektur_beleg IS
 'Die Plenarprotokolldatei, in der die korrigierten Werte im Wortlaut stehen. '
 'Der Wortlaut selbst steht in korrekturen_abstimmung_kopf.csv.';
COMMENT ON COLUMN {AW}.abstimmung_kopf_bt.abweichung IS
 'NULL, wenn PDF und Excel dieselbe Abstimmung beschreiben und die '
 'amtlichen Summen mit den gezaehlten Stimmen uebereinstimmen. Sonst der '
 'Befund im Wortlaut. WER HIER ETWAS STEHEN HAT, DARF drucksachen NICHT '
 'ungeprueft verwenden: am 31.01.2024 verlinkt der Bundestag unter '
 'Abstimmung Nr. 1 das PDF einer anderen Sitzung, byte-gleich mit dem vom '
 '19.01.2024 - die Drucksachennummern dort gehoeren zu einer anderen '
 'Abstimmung.';
COMMENT ON COLUMN {AW}.abstimmung_kopf_bt.amtl_ja IS
 'Amtliche Summe aus dem PDF. Gegen die gezaehlten Zeilen in stimme_bt '
 'geprueft; Abweichungen stehen im Lauflog.';
"""

ENDE_KOPF = "Abgegebene Stimmen insgesamt"
DS_NUMMER = re.compile(r"\b(\d{2})/(\d{1,5})\b")


DS_WORT = re.compile(r"(?<![A-Za-zÄÖÜäöü])(?:BT-)?(?:Druck\w*|Dr\.?s)\.?:?"
                     r"(?![a-zäöü])", re.I)


DS_TIPPFEHLER = re.compile(r"\bDr\.\s*\d{2}/\d{1,5}")


NUR_NUMMERN = re.compile(
    r"^[-–\s]*(?:(?:und|sowie|,|;)\s*)*"
    r"(?:\d{2}/\d{1,5}(?:\s*\(neu\))?\s*(?:(?:und|sowie|,|;)\s*)*)+[-–\s]*$",
    re.I)


def ist_drucksachenzeile(z):
    if not DS_NUMMER.search(z):
        return False
    return bool(DS_WORT.search(z) or DS_TIPPFEHLER.search(z)
                or NUR_NUMMERN.match(z))


def zahl(text, muster):
    m = re.search(muster, text)
    return int(m.group(1)) if m else None


def uhrzeit(text, wort):
    m = re.search(wort + r":\s*(\d{1,2})[:.](\d{2})", text)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def lies_kopf(pfad):
    with pdfplumber.open(pfad) as pdf:
        text = pdf.pages[0].extract_text() or ""
    zeilen = [z.strip() for z in text.splitlines()]

    d = {"sitzung_pdf": zahl(text, r"(\d+)\.\s*Sitzung des Deutschen Bundestages"),
         "abstimmung_pdf": zahl(text, r"Abstimmung\s+Nr\.\s*(\d+)"),
         "amtl_abgegeben": zahl(text, r"Abgegebene Stimmen insgesamt:\s*(\d+)"),
         "amtl_nicht_abg": zahl(text, r"Nicht abgegebene(?: Stimmen)?:\s*(\d+)"),
         "amtl_ja": zahl(text, r"Ja-Stimmen:\s*(\d+)"),
         "amtl_nein": zahl(text, r"Nein-Stimmen:\s*(\d+)"),
         "amtl_enthaltung": zahl(text, r"Enthaltungen:\s*(\d+)"),
         "amtl_ungueltig": zahl(text, r"Ung(?:ü|ue)ltige:\s*(\d+)"),
         "beginn": uhrzeit(text, "Beginn"),
         "ende": uhrzeit(text, "Ende")}


    oben = next((i for i, z in enumerate(zeilen)
                 if re.search(r"Ergebnis der Namentlichen Abstimmung", z)), None)
    unten = next((i for i, z in enumerate(zeilen) if z.startswith(ENDE_KOPF)), None)
    block = zeilen[oben + 1:unten] if oben is not None and unten is not None else []
    block = [z for z in block if z]


    ds_zeilen, rest = [], []
    for z in block:
        if not ist_drucksachenzeile(z):
            rest.append(z)
            continue
        w = DS_WORT.search(z)
        vorn = z[:w.start()].strip() if w else ""
        if len(re.sub(r"[-–(\s]", "", vorn)) > 2:
            rest.append(vorn)
            ds_zeilen.append(z[w.start():])
        else:
            ds_zeilen.append(z)

    nummern, gesehen = [], set()
    for z in ds_zeilen:
        for wp, nr in DS_NUMMER.findall(z):
            s = f"{wp}/{nr}"
            if s not in gesehen:
                gesehen.add(s)
                nummern.append(s)
    d["drucksachen"] = nummern or None
    d["drucksachen_zeile"] = " ".join(ds_zeilen) or None


    d["ds_unvollstaendig"] = [z for z in block
                              if DS_WORT.search(z) and not DS_NUMMER.search(z)]

    d["titel_pdf"] = " ".join(rest) or None
    d["vorlageart"] = next((v for v in VORLAGEARTEN
                            if rest and rest[0].startswith(v)), None)
    return d


GANZZAHLIG = {"sitzung_pdf", "abstimmung_pdf", "amtl_abgegeben",
              "amtl_nicht_abg", "amtl_ja", "amtl_nein", "amtl_enthaltung",
              "amtl_ungueltig"}


def lies_korrekturen():
    if not KORREKTUREN.exists():
        log.warning("%s fehlt - es wird nichts korrigiert.", KORREKTUREN)
        return [], []
    werte, vermerke = [], []
    for zeile in KORREKTUREN.read_text(encoding="utf-8").splitlines():
        if not zeile.strip() or zeile.startswith("#") or zeile.startswith("datei;"):
            continue
        t = zeile.split(";", 6)
        if len(t) < 6:
            log.warning("   Korrekturzeile unvollstaendig: %s", zeile[:70])
            continue
        datei, feld, wert, herkunft, beleg, datum = t[:6]
        if feld == "vermerk":
            vermerke.append((datei, wert, herkunft, beleg))
        else:
            werte.append((datei, feld, wert, herkunft, beleg))
    return werte, vermerke


def wende_korrekturen_an(conn, werte, vermerke):
    if not werte and not vermerke:
        return
    je_datei = {}
    with conn.cursor() as cur:
        for datei, feld, wert, herkunft, beleg in werte:
            if wert == "NULL":


                gesetzt = None
            elif feld == "drucksachen":
                gesetzt = [w.strip() for w in wert.split("|") if w.strip()]
            elif feld in GANZZAHLIG:
                gesetzt = int(wert)
            else:
                gesetzt = wert
            cur.execute(f"UPDATE {AW}.abstimmung_kopf_bt SET {feld} = %s "
                        f"WHERE datei = %s;", (gesetzt, datei))
            if cur.rowcount != 1:
                log.warning("   Korrektur ohne Ziel: %s / %s", datei[:34], feld)
                continue
            je_datei.setdefault(datei, [set(), herkunft, beleg])[0].add(feld)

        for datei, (felder, herkunft, beleg) in je_datei.items():
            cur.execute(f"""UPDATE {AW}.abstimmung_kopf_bt
                               SET korrigierte_felder = %s,
                                   korrektur_herkunft = %s,
                                   korrektur_beleg = %s
                             WHERE datei = %s;""",
                        (sorted(felder), herkunft, beleg, datei))


        for datei, _, herkunft, beleg in vermerke:
            if datei not in je_datei:
                cur.execute(f"""UPDATE {AW}.abstimmung_kopf_bt
                                   SET korrektur_herkunft = %s,
                                       korrektur_beleg = %s
                                 WHERE datei = %s;""", (herkunft, beleg, datei))
    conn.commit()

    log.info("--- Korrekturen aus %s ---", KORREKTUREN.name)
    for datei, (felder, herkunft, beleg) in sorted(je_datei.items()):
        log.info("   %-32s %-22s aus %s", datei[:32],
                 ", ".join(sorted(felder))[:22], beleg)
    log.info("   %d Werte in %d Abstimmungen gesetzt, %d Vermerke",
             len(werte), len(je_datei), len(vermerke))


def doppelte_pdf(protokoll):
    nach_summe = {}
    for e in json.loads(protokoll.read_text(encoding="utf-8")).values():
        if e.get("pdf_sha256"):
            nach_summe.setdefault(e["pdf_sha256"], []).append(e["datei"])
    treffer = {}
    for dateien in nach_summe.values():
        if len(dateien) > 1:
            for d in sorted(dateien):
                treffer[d] = ", ".join(x for x in sorted(dateien) if x != d)
    return treffer


def setze_abweichung(conn, doppelt, vermerke=()):
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH g AS (
              SELECT datei,
                     count(*) FILTER (WHERE stimme = 'ja')              AS ja,
                     count(*) FILTER (WHERE stimme = 'nein')            AS nein,
                     count(*) FILTER (WHERE stimme = 'enthaltung')      AS enth,
                     count(*) FILTER (WHERE stimme = 'ungueltig')       AS ung,
                     count(*) FILTER (WHERE stimme = 'nicht_abgegeben') AS na
                FROM {AW}.stimme_bt GROUP BY datei)
            SELECT k.datei, a.sitzung, k.sitzung_pdf, a.abstimmung,
                   k.abstimmung_pdf,
                   g.ja, k.amtl_ja, g.nein, k.amtl_nein, g.enth,
                   k.amtl_enthaltung, g.ung, k.amtl_ungueltig,
                   g.na, k.amtl_nicht_abg
              FROM {AW}.abstimmung_kopf_bt k
              JOIN {AW}.abstimmung_bt a USING (datei)
              LEFT JOIN g USING (datei);""")
        zeilen = cur.fetchall()

    befunde = []
    for (datei, sz, szp, ab, abp, *paare) in zeilen:
        teile = []
        if szp is not None and szp != sz:
            teile.append(f"Sitzung laut PDF {szp}, laut Excel {sz}")
        if abp is not None and abp != ab:
            teile.append(f"Abstimmungsnummer laut PDF {abp}, laut Excel {ab}")
        for name, (gez, amtl) in zip(
                ("ja", "nein", "enthaltung", "ungueltig", "nicht abgegeben"),
                zip(paare[0::2], paare[1::2])):
            if gez is not None and amtl is not None and gez != amtl:
                teile.append(f"{name}: gezaehlt {gez}, amtlich {amtl}")
        if datei in doppelt:
            teile.append(f"PDF byte-gleich mit dem von {doppelt[datei]}")
        if teile:
            befunde.append((datei, "; ".join(teile)))

    with conn.cursor() as cur:
        if befunde:
            execute_values(cur, f"""
                UPDATE {AW}.abstimmung_kopf_bt k SET abweichung = v.text
                  FROM (VALUES %s) AS v (datei, text)
                 WHERE k.datei = v.datei;""", befunde)


        if vermerke:
            execute_values(cur, f"""
                UPDATE {AW}.abstimmung_kopf_bt k SET vermerk = v.text
                  FROM (VALUES %s) AS v (datei, text)
                 WHERE k.datei = v.datei;""",
                [(d, v) for d, v, _, _ in vermerke])
    conn.commit()

    log.info("--- Abweichungen zwischen PDF und Excel ---")
    log.info("   %d von %d Abstimmungen ohne jeden Befund",
             len(zeilen) - len(befunde), len(zeilen))
    for datei, text in befunde:
        log.warning("   %-32s %s", datei[:32], text)
    if vermerke:
        log.info("   dazu %d Vermerke (keine Abweichung, sondern eine belegte " "Abwesenheit):", len(vermerke))
        for datei, text, _, _ in vermerke:
            log.info("   %-32s %s", datei[:32], text[:110])


def main():
    protokoll = QUELLE / "abruf.json"
    if not protokoll.exists():
        raise SystemExit(f"{protokoll} fehlt - erst herunterladen.")
    eintraege = json.loads(protokoll.read_text(encoding="utf-8")).values()

    paare = [(e["datei"], e["pdf_datei"]) for e in eintraege if e.get("pdf_datei")]
    ohne_pdf = sorted(e["datei"] for e in eintraege if not e.get("pdf_datei"))
    log.info("%d Abstimmungen im Protokoll, %d davon mit PDF",
             len(eintraege), len(paare))
    if ohne_pdf:
        log.warning("--- %d Abstimmungen ohne PDF: keine Drucksachennummer, " "nichts ersatzweise abgeleitet ---", len(ohne_pdf))
        for n in ohne_pdf:
            log.warning("      %s", n)

    fehlt_datei = [p for _, p in paare if not (QUELLE / p).exists()]
    if fehlt_datei:
        log.warning("%d PDF im Protokoll, aber nicht auf der Platte", len(fehlt_datei))

    log.info("--- %d PDF werden gelesen ---", len(paare))
    zeilen, mangel, unvollstaendig = [], Counter(), []
    for i, (xlsx, pdf) in enumerate(sorted(paare), 1):
        if not (QUELLE / pdf).exists():
            continue
        try:
            k = lies_kopf(QUELLE / pdf)
        except Exception as e:
            log.warning("   %s nicht lesbar: %s", pdf, str(e)[:70])
            mangel["nicht lesbar"] += 1
            continue
        for feld in ("drucksachen", "titel_pdf", "vorlageart", "amtl_ja",
                     "beginn", "ende"):
            if k[feld] is None:
                mangel["ohne " + feld] += 1
        for z in k["ds_unvollstaendig"]:
            unvollstaendig.append((pdf, z))
        zeilen.append((xlsx, pdf, k["sitzung_pdf"], k["abstimmung_pdf"],
                       k["vorlageart"], k["titel_pdf"], k["drucksachen"],
                       k["drucksachen_zeile"], k["amtl_abgegeben"], k["amtl_nicht_abg"], k["amtl_ja"],
                       k["amtl_nein"], k["amtl_enthaltung"], k["amtl_ungueltig"],
                       k["beginn"], k["ende"]))
        if i % 100 == 0:
            log.info("   %d/%d gelesen", i, len(paare))

    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
        execute_values(cur, f"""
            INSERT INTO {AW}.abstimmung_kopf_bt
                (datei, pdf_datei, sitzung_pdf, abstimmung_pdf, vorlageart,
                 titel_pdf, drucksachen, drucksachen_zeile,
                 amtl_abgegeben, amtl_nicht_abg,
                 amtl_ja, amtl_nein, amtl_enthaltung, amtl_ungueltig,
                 beginn, ende)
            VALUES %s;""", zeilen)
    conn.commit()
    log.info("   %d Zeilen geschrieben", len(zeilen))

    if unvollstaendig:
        log.warning("--- %d Drucksachenangaben ohne Wahlperiode oder ohne " "lesbare Nummer ---", len(unvollstaendig))
        log.warning("    Nicht ergaenzt: welche Wahlperiode gemeint ist, steht " "nicht da. Der Wortlaut bleibt in drucksachen_zeile.")
        for pdf, z in unvollstaendig:
            log.warning("      %-30s %s", pdf[:30], z[:80])

    log.info("--- Was im Kopf gefehlt hat (wie geliefert, vor den Korrekturen) ---")
    if not mangel:
        log.info("   nichts: jedes PDF nennt Drucksache, Titel, Art, Zahlen " "und Uhrzeiten")
    for k, v in mangel.most_common():
        log.info("   %-24s %4d", k, v)

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT count(*) FILTER (WHERE a.datei IS NULL),
                   count(*) FILTER (WHERE k.datei IS NULL)
              FROM {AW}.abstimmung_kopf_bt k
              FULL JOIN {AW}.abstimmung_bt a USING (datei);""")
        verwaist, ohne_kopf = cur.fetchone()
        log.info("--- Verbindung zu abstimmung_bt ---")
        log.info("   %d Kopfzeilen ohne Abstimmung, %d Abstimmungen ohne Kopf",
                 verwaist, ohne_kopf)

        cur.execute(f"""
            SELECT count(*) FROM {AW}.abstimmung_kopf_bt k
              JOIN {AW}.abstimmung_bt a USING (datei)
             WHERE k.sitzung_pdf IS DISTINCT FROM a.sitzung
                OR k.abstimmung_pdf IS DISTINCT FROM a.abstimmung;""")
        log.info("   %d mal weichen Sitzungs-/Abstimmungsnummer zwischen PDF " "und Excel ab (Stand der Lieferung, vor den Korrekturen)",
                 cur.fetchone()[0])

    werte, vermerke = lies_korrekturen()
    wende_korrekturen_an(conn, werte, vermerke)
    setze_abweichung(conn, doppelte_pdf(protokoll), vermerke)

    with conn.cursor() as cur:

        cur.execute(f"""
            SELECT count(*) FILTER (WHERE abweichung IS NULL),
                   count(*)
              FROM {AW}.abstimmung_kopf_bt;""")
        sauber, alle = cur.fetchone()
        log.info("--- Probe: amtliches Ergebnis gegen gezaehlte Stimmen ---")
        log.info("   bei %d von %d Abstimmungen stimmen Ja, Nein, Enthaltung, " "Ungueltig und Nicht abgegeben genau ueberein", sauber, alle)

        cur.execute(f"""
            SELECT count(DISTINCT datei) AS mit,
                   count(DISTINCT datei) FILTER
                        (WHERE cardinality(drucksachen) > 1) AS mehrere,
                   count(DISTINCT d)     AS verschiedene
              FROM {AW}.abstimmung_kopf_bt
              LEFT JOIN LATERAL unnest(drucksachen) d ON true
             WHERE drucksachen IS NOT NULL;""")
        mit, mehrere, versch = cur.fetchone()
        cur.execute(f"SELECT count(*) FROM {AW}.abstimmung_kopf_bt "
                    f"WHERE drucksachen IS NULL;")
        log.info("--- Drucksachen ---")
        log.info("   %d Abstimmungen nennen mindestens eine Drucksache, " "%d nennen keine", mit, cur.fetchone()[0])
        log.info("   %d Nennungen mit mehr als einer Nummer, " "%d verschiedene Drucksachen insgesamt", mehrere, versch)

        cur.execute(f"""
            SELECT coalesce(vorlageart, '(ohne)'), count(*)
              FROM {AW}.abstimmung_kopf_bt GROUP BY 1 ORDER BY 2 DESC;""")
        log.info("--- Vorlageart ---")
        for art, n in cur.fetchall():
            log.info("   %-28s %4d", art[:26], n)
    conn.close()


if __name__ == "__main__":
    main()
