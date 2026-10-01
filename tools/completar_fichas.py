"""Aplica data/fichas_completadas.csv a catalogo.sqlite (fichas transcritas del libro).

Solo escribe los campos no vacíos del CSV y marca la ficha como estructurada.
Uso:  python tools/completar_fichas.py     (luego python tools/build_catalog.py)
"""
import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ["distribution_text", "origin_status", "description_source", "growth_form", "life_cycle",
          "underground_structure", "flower_shape", "conservation_status"]
NOTE = {"texto": "Ficha transcrita del texto del libro (revisión 2026-09-30).",
        "iconos": "Ficha sin texto descriptivo: rasgos leídos de los íconos del libro (revisión 2026-09-30)."}


def main():
    con = sqlite3.connect(ROOT / "catalogo.sqlite")
    with open(ROOT / "data" / "fichas_completadas.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader([l for l in f if l.strip() and not l.startswith("#")], delimiter=";"))
    for r in rows:
        name = con.execute("select scientific_name from species where id=?", (int(r["id"]),)).fetchone()
        if not name or name[0] != r["scientific_name"]:
            raise ValueError(f"id {r['id']} no coincide con {r['scientific_name']}")
        sets = {k: r[k].strip() for k in FIELDS if r[k].strip()}
        sets.update(data_quality="source_extracted", source_note=NOTE[r["fuente"]])
        con.execute(f"update species set {', '.join(f'{k}=?' for k in sets)} where id=?", (*sets.values(), int(r["id"])))
    con.commit()
    print(f"{len(rows)} fichas completadas")


if __name__ == "__main__":
    main()
