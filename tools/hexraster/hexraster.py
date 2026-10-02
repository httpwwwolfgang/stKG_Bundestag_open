import sys
import math
import heapq
import random
import logging
import tempfile
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from shapely import wkt as shapely_wkt
from shapely.geometry import Point


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import DB_SCHEMA, run_sql, run_sql_file, query


BEARB = "hexgitter_bearb"


GRAVITY = True
GRAVITY_UMSCHLOSSEN = 4

GRAVITY_RUNDEN = 400

ZONEN_MAX = 3
W_ZONE    = 3.0

W_KEIM    = 0.1
PUFFER_M  = 20000.0
W_FREMD   = 4.0

W_KOMPAKT = 0.25


W_KANTE     = 20.0


GEWICHT_MIN = 0.5
GEWICHT_MAX = 3.0
W_RICHTUNG  = 1.0
W_LAGE      = 12.0
LAGE_SKALA  = 80000.0

ITERATIONEN = 2000000


T_START     = 60.0
T_ENDE      = 0.5
SEED        = 20260813


ZUG_RADIUS = 3


UMRISS_TOLERANZ = 2000.0


NACHBAR_VEKTOREN = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wk-hex")


DDL = f"""
CREATE TABLE IF NOT EXISTS {BEARB}.hexraster (
    wahljahr     SMALLINT NOT NULL,
    wkr_nr       SMALLINT NOT NULL,
    wkr_name     TEXT,
    land_nr      SMALLINT,
    land_name    TEXT,
    col          INTEGER NOT NULL,
    row          INTEGER NOT NULL,
    versatz_m    DOUBLE PRECISION,
    nachbarn_real     SMALLINT,
    nachbarn_erhalten SMALLINT,
    nachbarn_quote    DOUBLE PRECISION,
    geom         geometry(Polygon, 25832) NOT NULL,
    berechnet_am TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (wahljahr, wkr_nr),
    UNIQUE (wahljahr, col, row),
    FOREIGN KEY (wahljahr, wkr_nr)
        REFERENCES {DB_SCHEMA}.wahlkreis (wahljahr, wkr_nr) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_hexraster_geom ON {BEARB}.hexraster USING GIST (geom);
"""


MIGRATION_DDL = f"""
ALTER TABLE {BEARB}.hexraster ADD COLUMN IF NOT EXISTS wkr_name  TEXT;
ALTER TABLE {BEARB}.hexraster ADD COLUMN IF NOT EXISTS land_nr   SMALLINT;
ALTER TABLE {BEARB}.hexraster ADD COLUMN IF NOT EXISTS land_name TEXT;
ALTER TABLE {BEARB}.hexraster ADD COLUMN IF NOT EXISTS nachbarn_real     SMALLINT;
ALTER TABLE {BEARB}.hexraster ADD COLUMN IF NOT EXISTS nachbarn_erhalten SMALLINT;
ALTER TABLE {BEARB}.hexraster ADD COLUMN IF NOT EXISTS nachbarn_quote    DOUBLE PRECISION;
CREATE INDEX IF NOT EXISTS idx_hexraster_land ON {BEARB}.hexraster (wahljahr, land_nr);
"""


def lade_daten(jahr):
    punkte, land, flaechen = [], [], []
    for nr, x, y, ln, lname, wname, fl in query(f"""
            SELECT wkr_nr, ST_X(ST_PointOnSurface(geom)), ST_Y(ST_PointOnSurface(geom)),
                   land_nr, land_name, wkr_name, flaeche_km2
            FROM {DB_SCHEMA}.wahlkreis WHERE wahljahr = {jahr} ORDER BY wkr_nr;
        """):
        punkte.append((int(nr), float(x), float(y), wname))
        land.append((int(ln), lname))
        flaechen.append(float(fl))

    kanten = [
        (int(a), int(b), float(az))
        for a, b, az in query(f"""
            SELECT wkr_von, wkr_nach, azimut_grad
            FROM {DB_SCHEMA}.nachbarschaft
            WHERE wahljahr = {jahr} AND wkr_von < wkr_nach;
        """)
    ]
    if not kanten:
        raise SystemExit(f"Keine Nachbarschaften fuer {jahr} - erst nachbarschaft.py laufen lassen.")

    landflaeche = {
        int(ln): shapely_wkt.loads(w) for ln, w in query(f"""
            SELECT land_nr,
                   ST_AsText(ST_SimplifyPreserveTopology(ST_Union(geom), {UMRISS_TOLERANZ}))
            FROM {DB_SCHEMA}.wahlkreis WHERE wahljahr = {jahr} GROUP BY land_nr;
        """)
    }


    land_paare = {
        tuple(sorted((int(a), int(b))))
        for a, b in query(f"""
            SELECT DISTINCT wa.land_nr, wb.land_nr
            FROM {DB_SCHEMA}.nachbarschaft n
            JOIN {DB_SCHEMA}.wahlkreis wa
              ON wa.wahljahr = n.wahljahr AND wa.wkr_nr = n.wkr_von
            JOIN {DB_SCHEMA}.wahlkreis wb
              ON wb.wahljahr = n.wahljahr AND wb.wkr_nr = n.wkr_nach
            WHERE n.wahljahr = {jahr} AND wa.land_nr < wb.land_nr;
        """)
    }
    return punkte, land, flaechen, kanten, landflaeche, land_paare


def zellmitte(q, r, size, x0, y0):
    return (x0 + size * math.sqrt(3) * (q + r / 2.0),
            y0 - size * 1.5 * r)


def hexagon(cx, cy, size):
    ecken = [(cx + size * math.cos(math.radians(60 * i - 90)),
              cy + size * math.sin(math.radians(60 * i - 90))) for i in range(6)]
    ecken.append(ecken[0])
    return ecken


def hexdistanz(a, b):
    dq, dr = b[0] - a[0], b[1] - a[1]
    return (abs(dq) + abs(dq + dr) + abs(dr)) // 2


def baue_kandidaten(umriss, anzahl):
    zellflaeche = umriss.area / anzahl
    size = math.sqrt(2.0 * zellflaeche / (3.0 * math.sqrt(3.0)))
    zellbreite = size * math.sqrt(3)
    rand = (ZONEN_MAX + 1) * zellbreite
    xmin, ymin, xmax, ymax = umriss.bounds
    xmin, ymin, xmax, ymax = xmin - rand, ymin - rand, xmax + rand, ymax + rand
    x0, y0 = xmin - 2 * size, ymax + 2 * size

    kandidaten, zonen = [], []
    r = 0
    while True:
        _, cy = zellmitte(0, r, size, x0, y0)
        if cy < ymin:
            break
        q_von = math.floor((xmin - x0) / zellbreite - r / 2.0)
        q_bis = math.ceil((xmax - x0) / zellbreite - r / 2.0)
        for q in range(q_von, q_bis + 1):
            cx, cy = zellmitte(q, r, size, x0, y0)
            d = Point(cx, cy).distance(umriss)
            zone = 0 if d == 0.0 else 1 + int(d / zellbreite)
            if zone <= ZONEN_MAX:
                kandidaten.append((q, r, cx, cy))
                zonen.append(zone)
        r += 1

    if len(kandidaten) < anzahl:
        raise SystemExit(f"Nur {len(kandidaten)} Kandidatenzellen fuer {anzahl} Wahlkreise.")


    q_min = min(q for q, _, _, _ in kandidaten)
    r_min = min(r for _, r, _, _ in kandidaten)
    kandidaten = [(q - q_min + 1, r - r_min + 1, cx, cy)
                  for q, r, cx, cy in kandidaten]

    log.info("Gitter: Zellweite %.0f m, %d Kandidaten (davon %d in Zone 0), " "col 1-%d, row 1-%d",
             size * 2, len(kandidaten), sum(1 for z in zonen if z == 0),
             max(q for q, _, _, _ in kandidaten),
             max(r for _, r, _, _ in kandidaten))
    return kandidaten, zonen, size


def verteile_kontur(kandidaten, zonen, size, landflaeche, quoten,
                    land_paare, mehrteilig_ok):
    zellbreite = size * math.sqrt(3)
    koord = [(q, r) for q, r, _, _ in kandidaten]
    pos = {k: i for i, k in enumerate(koord)}
    nachbarn = [[pos[(q + dq, r + dr)] for dq, dr in NACHBAR_VEKTOREN
                 if (q + dq, r + dr) in pos] for q, r in koord]

    puffer = {ln: geom.buffer(PUFFER_M) for ln, geom in landflaeche.items()}
    zentrum = {ln: geom.centroid for ln, geom in landflaeche.items()}
    je_zelle = []
    for _, _, cx, cy in kandidaten:
        p = Point(cx, cy)
        je_zelle.append((p, frozenset(ln for ln, g in puffer.items()
                                      if g.covers(p))))


    zellflaeche_m = 3.0 * math.sqrt(3.0) / 2.0 * size ** 2
    stadtstaat = {ln for ln in quoten
                  if quoten[ln] * zellflaeche_m > 3.0 * landflaeche[ln].area}
    log.info("  vom Fremd-Puffer befreit (Stadtstaaten): %s",
             ", ".join(str(ln) for ln in sorted(stadtstaat)) or "-")

    def kosten_fn(ln, k):
        p, fremdmenge = je_zelle[k]


        if ln in stadtstaat or ln in fremdmenge:
            fremd = 0
        else:
            fremd = sum(1 for m in fremdmenge if m != ln)
        return (p.distance(landflaeche[ln]) / zellbreite
                + W_ZONE * zonen[k]
                + W_FREMD * fremd
                + W_KOMPAKT * p.distance(zentrum[ln]) / zellbreite)

    plaetze = [ln for ln, anz in sorted(quoten.items()) for _ in range(anz)]
    matrix = np.empty((len(kandidaten), len(plaetze)))
    for k in range(len(kandidaten)):
        einzel = {ln: kosten_fn(ln, k) for ln in quoten}
        for s, ln in enumerate(plaetze):
            matrix[k, s] = einzel[ln]
    zeilen, spalten = linear_sum_assignment(matrix)

    besitzer = {}
    block = {ln: set() for ln in quoten}
    for k, s in zip(zeilen, spalten):
        besitzer[int(k)] = plaetze[s]
        block[plaetze[s]].add(int(k))

    vereinige_bloecke(koord, nachbarn, besitzer, block, land_paare, mehrteilig_ok)
    kompaktiere(koord, pos, zonen, besitzer, block, land_paare)
    verforme_zu_grenzen(koord, zonen, nachbarn, besitzer, block, land_paare)


    kompaktiere(koord, pos, zonen, besitzer, block, land_paare)
    repariere_loecher(kandidaten, zonen, nachbarn, besitzer, block, kosten_fn,
                      koord, land_paare)

    if GRAVITY:
        gravity(koord, pos, zonen, nachbarn, besitzer, block, land_paare)

    gewaehlt = sorted(besitzer)
    return ([kandidaten[k] for k in gewaehlt],
            [besitzer[k] for k in gewaehlt],
            [zonen[k] for k in gewaehlt])


def kompaktiere(koord, pos, zonen, besitzer, block, land_paare):
    def luecke(a, b):
        return min(hexdistanz(koord[ka], koord[kb])
                   for ka in block[a] for kb in block[b])

    luecken = {p: luecke(*p) for p in land_paare}
    zonensumme = {ln: sum(zonen[k] for k in block[ln]) for ln in block}

    def gesamt():
        fehlend = sum(1 for v in luecken.values() if v > 1)
        rest = sum(v - 1 for v in luecken.values() if v > 1)
        return (fehlend, rest, sum(zonensumme.values()))

    start = gesamt()
    for _ in range(60):
        bewegt = 0

        for ln in sorted(block, key=lambda l: len(block[l])):
            weiter = True
            while weiter:
                weiter = False
                for dq, dr in NACHBAR_VEKTOREN:
                    neu = set()
                    ok = True
                    for k in block[ln]:
                        k2 = pos.get((koord[k][0] + dq, koord[k][1] + dr))
                        if k2 is None or (k2 in besitzer and besitzer[k2] != ln):
                            ok = False
                            break
                        neu.add(k2)
                    if not ok:
                        continue
                    vorher = gesamt()
                    alt = block[ln]
                    alt_luecken = {p: luecken[p] for p in land_paare if ln in p}
                    alt_zone = zonensumme[ln]
                    for k in alt - neu:
                        del besitzer[k]
                    for k in neu - alt:
                        besitzer[k] = ln
                    block[ln] = neu
                    for p in alt_luecken:
                        luecken[p] = luecke(*p)
                    zonensumme[ln] = sum(zonen[k] for k in neu)
                    if gesamt() < vorher:
                        bewegt += 1
                        weiter = True
                        break

                    block[ln] = alt
                    for k in neu - alt:
                        del besitzer[k]
                    for k in alt - neu:
                        besitzer[k] = ln
                    luecken.update(alt_luecken)
                    zonensumme[ln] = alt_zone
        if not bewegt:
            break
    ende = gesamt()
    log.info("  Kompaktierung: fehlende Landesgrenzen %d -> %d, Restluecke %d -> %d",
             start[0], ende[0], start[1], ende[1])


def _komponenten(zellen_menge, nachbarn):
    offen = set(zellen_menge)
    teile = []
    while offen:
        start = offen.pop()
        comp, stapel = {start}, [start]
        while stapel:
            k = stapel.pop()
            for k2 in nachbarn[k]:
                if k2 in offen:
                    offen.discard(k2)
                    comp.add(k2)
                    stapel.append(k2)
        teile.append(comp)
    return teile


def vereinige_bloecke(koord, nachbarn, besitzer, block, land_paare,
                      mehrteilig_ok=frozenset()):
    def fehlende_grenzen():
        n = 0
        for a, b in land_paare:
            if min(hexdistanz(koord[ka], koord[kb])
                   for ka in block[a] for kb in block[b]) > 1:
                n += 1
        return n

    for _ in range(200):
        problem = None
        for ln in sorted(block):
            if ln in mehrteilig_ok:
                continue
            teile = _komponenten(block[ln], nachbarn)
            if len(teile) > 1:
                problem = (ln, sorted(teile, key=len))
                break
        if problem is None:
            return
        ln, teile = problem
        klein, haupt = teile[0], teile[-1]

        naechste = lambda k: min(hexdistanz(koord[k], koord[s]) for s in klein)
        rand = sorted({k2 for k in haupt for k2 in nachbarn[k]
                       if k2 in besitzer and besitzer[k2] != ln},
                      key=lambda k: (naechste(k), k))
        getauscht = False
        for f in rand:
            fremd = besitzer[f]
            for s in sorted(klein, key=lambda k: (hexdistanz(koord[k], koord[f]), k)):
                if not any(besitzer.get(k2) == fremd and k2 != f
                           for k2 in nachbarn[s]):
                    continue
                if not _zusammenhaengend((block[fremd] - {f}) | {s}, nachbarn):
                    continue
                vorher = fehlende_grenzen()
                besitzer[f], besitzer[s] = ln, fremd
                block[ln] = (block[ln] - {s}) | {f}
                block[fremd] = (block[fremd] - {f}) | {s}
                if fehlende_grenzen() <= vorher:
                    getauscht = True
                    break
                besitzer[f], besitzer[s] = fremd, ln
                block[ln] = (block[ln] - {f}) | {s}
                block[fremd] = (block[fremd] - {s}) | {f}
            if getauscht:
                break
        if not getauscht:
            log.warning("  Land %d bleibt mehrteilig - kein zulaessiger Tausch gefunden", ln)
            return
    log.warning("  vereinige_bloecke: Rundenlimit erreicht")


def _zusammenhaengend(zellen_menge, nachbarn):
    start = next(iter(zellen_menge))
    gesehen, stapel = {start}, [start]
    while stapel:
        k = stapel.pop()
        for k2 in nachbarn[k]:
            if k2 in zellen_menge and k2 not in gesehen:
                gesehen.add(k2)
                stapel.append(k2)
    return len(gesehen) == len(zellen_menge)


def verforme_zu_grenzen(koord, zonen, nachbarn, besitzer, block, land_paare):
    def luecke(a, b):
        return min(hexdistanz(koord[ka], koord[kb])
                   for ka in block[a] for kb in block[b])

    def bilanz():
        werte = [luecke(*p) for p in land_paare]
        return (sum(1 for v in werte if v > 1),
                sum(v - 1 for v in werte if v > 1),
                sum(zonen[k] for k in besitzer))

    aktuell = bilanz()
    for _ in range(60):
        verbessert = False
        offen = sorted((p for p in land_paare if luecke(*p) > 1),
                       key=lambda p: luecke(*p))
        for paar in offen:
            for a, b in (paar, paar[::-1]):
                ka, kb = min(((x, y) for x in block[a] for y in block[b]),
                             key=lambda xy: hexdistanz(koord[xy[0]], koord[xy[1]]))
                schritt = None
                for k2 in sorted(nachbarn[ka],
                                 key=lambda k: hexdistanz(koord[k], koord[kb])):
                    if (k2 not in besitzer
                            and hexdistanz(koord[k2], koord[kb])
                            < hexdistanz(koord[ka], koord[kb])):
                        schritt = k2
                        break
                if schritt is None:
                    continue
                abgabe = None
                for kd in sorted(block[a],
                                 key=lambda k: -hexdistanz(koord[k], koord[kb])):
                    if kd == ka:
                        continue
                    if _zusammenhaengend((block[a] - {kd}) | {schritt}, nachbarn):
                        abgabe = kd
                        break
                if abgabe is None:
                    continue
                del besitzer[abgabe]
                besitzer[schritt] = a
                block[a] = (block[a] - {abgabe}) | {schritt}
                neu = bilanz()
                if neu < aktuell:
                    aktuell = neu
                    verbessert = True
                    break
                del besitzer[schritt]
                besitzer[abgabe] = a
                block[a] = (block[a] - {schritt}) | {abgabe}
            if verbessert:
                break
        if not verbessert:
            break
    log.info("  Verformung: fehlende Landesgrenzen %d, Restluecke %d",
             aktuell[0], aktuell[1])


def gravity(koord, pos, zonen, nachbarn, besitzer, block, land_paare):
    def offene():
        raus = []
        for k, (q, r) in enumerate(koord):
            if k in besitzer or zonen[k] != 0:
                continue
            um = sum(1 for dq, dr in NACHBAR_VEKTOREN
                     if pos.get((q + dq, r + dr)) in besitzer)
            if um >= GRAVITY_UMSCHLOSSEN:
                raus.append(k)
        return raus

    def fehlende_grenzen():
        n = 0
        for a, b in land_paare:
            if min(hexdistanz(koord[ka], koord[kb])
                   for ka in block[a] for kb in block[b]) > 1:
                n += 1
        return n

    def bilanz():
        return (len(offene()), sum(zonen[k] for k in besitzer))

    aktuell = bilanz()
    start = aktuell
    grenzen_start = fehlende_grenzen()
    gefuellt = 0

    for _ in range(GRAVITY_RUNDEN):
        zug = False
        for loch in offene():
            anrainer = sorted({besitzer[k] for k in nachbarn[loch]
                               if k in besitzer})
            for ln in anrainer:
                if not any(besitzer.get(k) == ln for k in nachbarn[loch]):
                    continue

                for opfer in sorted(block[ln],
                                    key=lambda k: (-zonen[k],
                                                   -hexdistanz(koord[k], koord[loch]))):
                    if opfer == loch:
                        continue
                    neu = (block[ln] - {opfer}) | {loch}
                    if not _zusammenhaengend(neu, nachbarn):
                        continue
                    alt_block = block[ln]
                    del besitzer[opfer]
                    besitzer[loch] = ln
                    block[ln] = neu
                    if bilanz() < aktuell and fehlende_grenzen() <= grenzen_start:
                        aktuell = bilanz()
                        gefuellt += 1
                        zug = True
                        break
                    del besitzer[loch]
                    besitzer[opfer] = ln
                    block[ln] = alt_block
                if zug:
                    break
            if zug:
                break
        if not zug:
            break

    log.info("  Gravity: Binnenluecken %d -> %d, %d Zuege, Zonenkosten %d -> %d",
             start[0], aktuell[0], gefuellt, start[1], aktuell[1])


def repariere_loecher(kandidaten, zonen, nachbarn, besitzer, block, basiskosten,
                      koord, land_paare):
    def zusammenhaengend(zellen_menge):
        return _zusammenhaengend(zellen_menge, nachbarn)

    def fehlende_grenzen():
        n = 0
        for a, b in land_paare:
            if min(hexdistanz(koord[ka], koord[kb])
                   for ka in block[a] for kb in block[b]) > 1:
                n += 1
        return n

    for _ in range(3):
        bewegt = 0
        loecher = [k for k in range(len(kandidaten))
                   if k not in besitzer and zonen[k] == 0
                   and len(nachbarn[k]) == 6
                   and all(k2 in besitzer for k2 in nachbarn[k])]
        for loch in loecher:


            if loch in besitzer or not all(k2 in besitzer for k2 in nachbarn[loch]):
                continue
            for ln in sorted({besitzer[k2] for k2 in nachbarn[loch]}):
                kandidaten_b = sorted(block[ln], key=lambda b: -basiskosten(ln, b))
                getauscht = False
                for b in kandidaten_b:
                    if basiskosten(ln, loch) > basiskosten(ln, b) + 0.5:
                        break

                    if not any(besitzer.get(k2) == ln and k2 != b
                               for k2 in nachbarn[loch]):
                        continue
                    neu = (block[ln] - {b}) | {loch}
                    if not zusammenhaengend(neu):
                        continue
                    vorher = fehlende_grenzen()
                    del besitzer[b]
                    besitzer[loch] = ln
                    block[ln] = neu
                    if fehlende_grenzen() > vorher:

                        del besitzer[loch]
                        besitzer[b] = ln
                        block[ln] = (block[ln] - {loch}) | {b}
                        continue
                    bewegt += 1
                    getauscht = True
                    break
                if getauscht:
                    break
        if not bewegt:
            break
    rest = [k for k in range(len(kandidaten))
            if k not in besitzer and zonen[k] == 0 and len(nachbarn[k]) == 6
            and all(k2 in besitzer for k2 in nachbarn[k])]
    if rest:
        log.warning("  %d Loecher blieben offen", len(rest))


def land_bloecke(zell_land, zellen):
    ergebnis = {}
    for ln in sorted(set(zell_land)):
        offen = {k for k, l in enumerate(zell_land) if l == ln}
        teile = 0
        while offen:
            teile += 1
            stapel = [offen.pop()]
            while stapel:
                k = stapel.pop()
                for k2 in list(offen):
                    if hexdistanz(zellen[k], zellen[k2]) == 1:
                        offen.discard(k2)
                        stapel.append(k2)
        ergebnis[ln] = teile
    return ergebnis


def azimut(dx, dy):
    return math.degrees(math.atan2(dx, dy)) % 360.0


def winkelabstand(a, b):
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d


def kantengewicht(flaeche_i, flaeche_j, median_flaeche):
    mittel = math.sqrt(flaeche_i * flaeche_j)
    return min(GEWICHT_MAX, max(GEWICHT_MIN, math.sqrt(median_flaeche / mittel)))


def kantenkosten(i, j, az_soll, gewicht, zuordnung, zellen):
    qi, ri, xi, yi = zellen[zuordnung[i]]
    qj, rj, xj, yj = zellen[zuordnung[j]]
    kosten = 0.0 if (qj - qi, rj - ri) in NACHBAR_VEKTOREN else W_KANTE * gewicht
    kosten += W_RICHTUNG * winkelabstand(azimut(xj - xi, yj - yi), az_soll) / 180.0
    return kosten


def lagekosten(i, zuordnung, zellen, punkte):
    _, _, cx, cy = zellen[zuordnung[i]]
    _, px, py, _ = punkte[i]
    return W_LAGE * (math.hypot(cx - px, cy - py) / LAGE_SKALA) ** 2


def optimiere(punkte, land, kanten_idx, zellen, zell_land):
    n, m = len(punkte), len(zellen)
    UNMOEGLICH = 1e9
    kosten = np.full((n, m), UNMOEGLICH)
    for i, (_, px, py, _) in enumerate(punkte):
        for k, (_, _, cx, cy) in enumerate(zellen):
            if zell_land[k] == land[i][0]:
                kosten[i, k] = math.hypot(cx - px, cy - py)
    zeilen, spalten = linear_sum_assignment(kosten)
    zuordnung = [0] * n
    for i, k in zip(zeilen, spalten):
        zuordnung[i] = int(k)

    belegt = {k: i for i, k in enumerate(zuordnung)}
    nahe = [[k2 for k2 in range(m)
             if k2 != k and zell_land[k2] == zell_land[k]
             and hexdistanz(zellen[k], zellen[k2]) <= ZUG_RADIUS]
            for k in range(m)]

    inzidenz = [[] for _ in range(n)]
    for e, (i, j, *_) in enumerate(kanten_idx):
        inzidenz[i].append(e)
        inzidenz[j].append(e)

    def teilkosten(knoten):
        betroffen = set()
        for i in knoten:
            betroffen.update(inzidenz[i])
        s = sum(kantenkosten(*kanten_idx[e], zuordnung, zellen) for e in betroffen)
        return s + sum(lagekosten(i, zuordnung, zellen, punkte) for i in knoten)

    def tausche(i, j, ziel, alt):
        zuordnung[i], zuordnung[j] = ziel, alt
        belegt[ziel], belegt[alt] = i, j

    rng = random.Random(SEED)
    abkuehlung = (T_ENDE / T_START) ** (1.0 / ITERATIONEN)
    T = T_START
    for schritt in range(ITERATIONEN):
        i = rng.randrange(n)
        if not nahe[zuordnung[i]]:
            T *= abkuehlung
            continue
        ziel = rng.choice(nahe[zuordnung[i]])
        j = belegt[ziel]
        if i == j:
            T *= abkuehlung
            continue
        alt = zuordnung[i]
        vorher = teilkosten((i, j))
        tausche(i, j, ziel, alt)
        delta = teilkosten((i, j)) - vorher
        if delta > 0 and rng.random() >= math.exp(-delta / T):
            tausche(i, j, alt, ziel)
        T *= abkuehlung
        if (schritt + 1) % 200000 == 0:
            log.info("  ... %d Iterationen, T=%.2f, erhaltene Kanten %d/%d",
                     schritt + 1, T, erhaltene_kanten(zuordnung, kanten_idx, zellen),
                     len(kanten_idx))


    runde = 0
    while True:
        runde += 1
        verbessert = 0
        for i in range(n):
            for ziel in nahe[zuordnung[i]]:
                j = belegt[ziel]
                if i == j:
                    continue
                alt = zuordnung[i]
                vorher = teilkosten((i, j))
                tausche(i, j, ziel, alt)
                if teilkosten((i, j)) < vorher - 1e-9:
                    verbessert += 1
                    break
                tausche(i, j, alt, ziel)
        log.info("  Abstieg Runde %d: %d Verbesserungen, erhaltene Kanten %d/%d",
                 runde, verbessert, erhaltene_kanten(zuordnung, kanten_idx, zellen),
                 len(kanten_idx))
        if verbessert == 0:
            break
    return zuordnung


def erhaltene_kanten(zuordnung, kanten_idx, zellen):
    n = 0
    for i, j, *_ in kanten_idx:
        qi, ri, _, _ = zellen[zuordnung[i]]
        qj, rj, _, _ = zellen[zuordnung[j]]
        if (qj - qi, rj - ri) in NACHBAR_VEKTOREN:
            n += 1
    return n


def _lit(text):
    return "'" + str(text).replace("'", "''") + "'"


def schreibe(jahr, punkte, land, zuordnung, zellen, size, kanten_idx):
    gesamt = [0] * len(punkte)
    erhalten = [0] * len(punkte)
    for i, j, *_ in kanten_idx:
        gesamt[i] += 1
        gesamt[j] += 1
        qi, ri, _, _ = zellen[zuordnung[i]]
        qj, rj, _, _ = zellen[zuordnung[j]]
        if (qj - qi, rj - ri) in NACHBAR_VEKTOREN:
            erhalten[i] += 1
            erhalten[j] += 1

    zeilen = []
    for i, (nr, px, py, wname) in enumerate(punkte):
        q, r, cx, cy = zellen[zuordnung[i]]
        ln, lname = land[i]
        quote = 100.0 * erhalten[i] / gesamt[i] if gesamt[i] else 0.0
        ring = ",".join(f"{x:.2f} {y:.2f}" for x, y in hexagon(cx, cy, size))
        zeilen.append(
            f"({jahr}, {nr}, {_lit(wname)}, {ln}, {_lit(lname)}, {q}, {r}, "
            f"{math.hypot(cx - px, cy - py):.1f}, "
            f"{gesamt[i]}, {erhalten[i]}, {quote:.1f}, "
            f"ST_GeomFromText('POLYGON(({ring}))', 25832))")

    sql = (f"DELETE FROM {BEARB}.hexraster WHERE wahljahr = {jahr};\n"
           f"INSERT INTO {BEARB}.hexraster " "(wahljahr, wkr_nr, wkr_name, land_nr, land_name, col, row, versatz_m, " "nachbarn_real, nachbarn_erhalten, nachbarn_quote, geom)\n" "VALUES\n" + ",\n".join(zeilen) + ";\n")

    tmp = Path(tempfile.gettempdir()) / f"hexraster_{jahr}.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, label=f"hexraster {jahr}")
    tmp.unlink(missing_ok=True)


def main():
    jahre = [int(a) for a in sys.argv[1:]] or [
        int(j) for (j,) in query(
            f"SELECT DISTINCT wahljahr FROM {DB_SCHEMA}.wahlkreis ORDER BY 1;")
    ]
    run_sql(DDL, "hexraster-ddl")
    run_sql(MIGRATION_DDL, "hexraster-migration")


    umriss_gesamt = shapely_wkt.loads(query(f"""
        SELECT ST_AsText(ST_SimplifyPreserveTopology(ST_Union(geom), {UMRISS_TOLERANZ}))
        FROM {DB_SCHEMA}.wahlkreis;
    """)[0][0])
    kandidaten, zonen, size = baue_kandidaten(umriss_gesamt, 299)

    for jahr in jahre:
        punkte, land, flaechen, kanten, landflaeche, land_paare = lade_daten(jahr)
        namen = dict(land)
        quoten = {}
        for ln, _ in land:
            quoten[ln] = quoten.get(ln, 0) + 1
        log.info("[%s] %d Wahlkreise, %d Nachbarschaften, %d echte Landesgrenzen",
                 jahr, len(punkte), len(kanten), len(land_paare))

        index = {nr: i for i, (nr, _, _, _) in enumerate(punkte)}
        median_flaeche = sorted(flaechen)[len(flaechen) // 2]
        kanten_idx = [
            (index[a], index[b], az,
             kantengewicht(flaechen[index[a]], flaechen[index[b]], median_flaeche))
            for a, b, az in kanten
        ]


        mehrteilig_ok = frozenset(
            a for a in quoten for b in quoten
            if a != b and quoten[a] < quoten[b] + 3
            and landflaeche[a].convex_hull.contains(landflaeche[b]))
        if mehrteilig_ok:
            log.info("[%s] mehrteilig zulaessig: %s", jahr,
                     ", ".join(namen[ln] for ln in sorted(mehrteilig_ok)))

        zellen, zell_land, zellzonen = verteile_kontur(
            kandidaten, zonen, size, landflaeche, quoten, land_paare, mehrteilig_ok)

        bloecke = land_bloecke(zell_land, zellen)
        zerrissen = {ln: b for ln, b in bloecke.items()
                     if b > 1 and ln not in mehrteilig_ok}
        geduldet = {ln: b for ln, b in bloecke.items()
                    if b > 1 and ln in mehrteilig_ok}
        log.info("[%s] Laender als ein Block: %d von %d%s%s",
                 jahr, sum(1 for b in bloecke.values() if b == 1), len(bloecke),
                 "" if not geduldet else " - zulaessig mehrteilig: " +
                 ", ".join(f"{namen[ln]} ({b})" for ln, b in sorted(geduldet.items())),
                 "" if not zerrissen else " - UNZULAESSIG zerrissen: " +
                 ", ".join(f"{namen[ln]} ({b})" for ln, b in sorted(zerrissen.items())))

        draussen = {}
        for k, z in enumerate(zellzonen):
            if z > 0:
                draussen.setdefault(zell_land[k], []).append(z)
        if draussen:
            log.info("[%s] Zellen ausserhalb des Umrisses: %d - %s",
                     jahr, sum(len(v) for v in draussen.values()),
                     ", ".join(f"{namen[ln]} {len(v)} (max Zone {max(v)})"
                               for ln, v in sorted(draussen.items())))
        else:
            log.info("[%s] keine Zelle ausserhalb des Umrisses", jahr)

        zuordnung = optimiere(punkte, land, kanten_idx, zellen, zell_land)

        intern = [e for e in kanten_idx if land[e[0]][0] == land[e[1]][0]]
        extern = [e for e in kanten_idx if land[e[0]][0] != land[e[1]][0]]
        e_ges = erhaltene_kanten(zuordnung, kanten_idx, zellen)
        e_int = erhaltene_kanten(zuordnung, intern, zellen)
        e_ext = erhaltene_kanten(zuordnung, extern, zellen)
        log.info("[%s] Nachbarschaften erhalten: %d von %d (%.1f %%) - " "landintern %d/%d (%.1f %%), uebergreifend %d/%d (%.1f %%)",
                 jahr, e_ges, len(kanten_idx), 100.0 * e_ges / len(kanten_idx),
                 e_int, len(intern), 100.0 * e_int / len(intern),
                 e_ext, len(extern), 100.0 * e_ext / len(extern))


        sortiert = sorted(range(len(punkte)), key=lambda i: flaechen[i])
        viertel = len(punkte) // 4
        for label, gruppe in (("Stadt (kleinstes Viertel)", set(sortiert[:viertel])),
                              ("Land (groesstes Viertel)", set(sortiert[-viertel:]))):
            tot = erh = 0
            for i, j, *_ in kanten_idx:
                if i in gruppe or j in gruppe:
                    tot += 1
                    qi, ri, _, _ = zellen[zuordnung[i]]
                    qj, rj, _, _ = zellen[zuordnung[j]]
                    if (qj - qi, rj - ri) in NACHBAR_VEKTOREN:
                        erh += 1
            log.info("[%s] %s: %d/%d Kanten erhalten (%.1f %%)",
                     jahr, label, erh, tot, 100.0 * erh / tot if tot else 0.0)

        versatz = sorted(math.hypot(zellen[zuordnung[i]][2] - px,
                                    zellen[zuordnung[i]][3] - py)
                         for i, (_, px, py, _) in enumerate(punkte))
        log.info("[%s] Lageversatz: Median %.0f km, Maximum %.0f km",
                 jahr, versatz[len(versatz) // 2] / 1000.0, versatz[-1] / 1000.0)

        pos = {(q, r): i for i, (q, r, _, _) in enumerate(zellen)}
        raster_paare = set()
        for i, (q, r, _, _) in enumerate(zellen):
            for dq, dr in NACHBAR_VEKTOREN:
                j = pos.get((q + dq, r + dr))
                if j is not None and zell_land[j] != zell_land[i]:
                    raster_paare.add(tuple(sorted((zell_land[i], zell_land[j]))))
        fehlend = sorted(land_paare - raster_paare)
        log.info("[%s] Landesgrenzen im Raster: %d von %d%s",
                 jahr, len(land_paare) - len(fehlend), len(land_paare),
                 "" if not fehlend else " - fehlend: " +
                 ", ".join(f"{namen[a]}-{namen[b]}" for a, b in fehlend))

        schreibe(jahr, punkte, land, zuordnung, zellen, size, kanten_idx)
        log.info("[%s] geschrieben.", jahr)


if __name__ == "__main__":
    main()
