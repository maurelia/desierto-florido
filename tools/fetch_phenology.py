"""Perfil mensual de floración por especie a partir de iNaturalist → data/floracion_inat.csv

Fuente preferida: observaciones de grado de investigación anotadas "Flowering" (term 12 = 13).
Si hay pocas, se usan todas las observaciones (en el desierto florido casi siempre se fotografía la planta en flor).
Corrección por esfuerzo: los conteos de cada mes se dividen por el total de observaciones de plantas de ese mes
en el mismo lugar (septiembre-octubre concentran ~8 veces más observaciones que otoño).
Lugar: regiones de Atacama + Coquimbo; si hay pocas observaciones, todo Chile.

Uso:  python tools/fetch_phenology.py               (luego python tools/build_catalog.py)
      python tools/fetch_phenology.py --reprofile   recalcula perfiles con los conteos guardados (solo descarga el esfuerzo)
"""
import csv
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "floracion_inat.csv"
API = "https://api.inaturalist.org/v1"
PLACES = {"atacama_coquimbo": "12680,12682", "chile": "7182"}
FLOWERING = {"term_id": 12, "term_value_id": 13}
PLANTAE = 47126
MIN_FLOWERING, MIN_ANY = 15, 12
S = requests.Session()
S.headers["User-Agent"] = "desierto-florido-fieldguide/0.6 (personal research)"


def get(path, **params):
    for i in range(6):
        time.sleep(1.1)  # límite recomendado por iNaturalist: ~1 solicitud por segundo
        try:
            r = S.get(f"{API}/{path}", params=params, timeout=40)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"iNaturalist no responde: {path} {params}")


def histogram(taxon, place, flowering):
    p = {"taxon_id": taxon, "place_id": place, "interval": "month_of_year", "date_field": "observed", "quality_grade": "research"}
    if flowering:
        p.update(FLOWERING)
    h = get("observations/histogram", **p)["results"]["month_of_year"]
    return [h[str(m)] for m in range(1, 13)]


def taxon_id(name):
    q = name.replace(" var. ", " ").replace(" subsp. ", " ")
    for t in get("taxa", q=q, is_active="true")["results"]:
        names = {t["name"], t.get("matched_term", "")}
        base = " ".join(q.split()[:2])
        if q in names or (t["rank"] == "species" and base in names):
            return t["id"], t["name"]
    return None, None


PSEUDO = 4  # observaciones ficticias repartidas según el esfuerzo: acercan las muestras pequeñas a "sin información"


def profile(counts, effort):
    tot = sum(effort)
    rate = [(c + PSEUDO * e / tot) / e if e else 0 for c, e in zip(counts, effort)]
    # suavizado circular: el mes vecino aporta (floración que cruza el límite de mes, muestras pequeñas)
    sm = [.6 * rate[m] + .2 * (rate[m - 1] + rate[(m + 1) % 12]) for m in range(12)]
    top = max(sm) or 1
    return [round(v / top, 2) for v in sm]


def reprofile():
    with open(OUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    effort = {(pl, fl): histogram(PLANTAE, pid, fl) for pl, pid in PLACES.items() for fl in (True, False)}
    for r in rows:
        if r.get("counts"):
            counts = [int(v) for v in r["counts"].split()]
            r["profile"] = " ".join(map(str, profile(counts, effort[(r["place"], r["source"] == "inat_floracion")])))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    print(f"Perfiles recalculados: {sum(bool(r.get('counts')) for r in rows)}")


def main():
    if "--reprofile" in __import__("sys").argv:
        return reprofile()
    species = json.loads((ROOT / "species.json").read_text(encoding="utf-8"))
    names = sorted({s["scientific_name"] for s in species if not s.get("excluded_reason") and " sp." not in s["scientific_name"]})
    effort = {(pl, fl): histogram(PLANTAE, pid, fl) for pl, pid in PLACES.items() for fl in (True, False)}
    rows = []
    for name in names:
        tid, inat_name = taxon_id(name)
        row = {"scientific_name": name, "inat_taxon_id": tid or "", "inat_name": inat_name or ""}
        if tid:
            for place, pid in PLACES.items():
                fl = histogram(tid, pid, True)
                counts, kind = (fl, "floracion") if sum(fl) >= MIN_FLOWERING else (histogram(tid, pid, False), "observaciones")
                if sum(counts) >= (MIN_FLOWERING if kind == "floracion" else MIN_ANY) or place == "chile":
                    break
            if sum(counts) >= 5:
                row.update(source=f"inat_{kind}", place=place, n=sum(counts),
                           counts=" ".join(map(str, counts)), profile=" ".join(map(str, profile(counts, effort[(place, kind == 'floracion')]))))
        rows.append(row)
        print(f"{row.get('n', 0):5}  {name}  {row.get('source', 'sin datos')}  {row.get('profile', '')}", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["scientific_name", "inat_taxon_id", "inat_name", "source", "place", "n", "counts", "profile"], delimiter=";")
        w.writeheader()
        w.writerows(rows)
    print(f"\n{sum('profile' in r for r in rows)}/{len(rows)} especies con perfil → {OUT}")


if __name__ == "__main__":
    main()
