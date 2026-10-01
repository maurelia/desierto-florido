"""Construye species.json (catálogo de la app) a partir de catalogo.sqlite.

Agrega a cada especie un bloque `traits` normalizado para el identificador:
  - rasgos extraídos del texto de la ficha (procedencia "libro"),
  - color verificado en las fotografías del libro (procedencia "libro_foto", data/colores_libro.csv),
  - color por nombre común (procedencia "nombre"),
  - rasgos borrador de data/rasgos_por_verificar.csv (procedencia "por_verificar"),
  - rango latitudinal derivado de las regiones citadas en la distribución,
  - perfil mensual de floración desde iNaturalist (data/floracion_inat.csv).
También escribe esos campos de vuelta en catalogo.sqlite.

Uso:  python tools/build_catalog.py
"""
import csv
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "catalogo.sqlite"
OUT = ROOT / "species.json"
DRAFT = ROOT / "data" / "rasgos_por_verificar.csv"
PHENO = ROOT / "data" / "floracion_inat.csv"
VERIFIED = ROOT / "data" / "colores_libro.csv"
VERIFIED_TRAITS = ROOT / "data" / "rasgos_libro.csv"  # rasgos verificados en fotos/íconos del libro cuando el texto no los dice  # colores verificados en las fotos del libro (prioridad máxima)  # generado por tools/fetch_phenology.py

# Registros que no son una especie o duplican otro (se muestran, pero no compiten en la identificación)
EXCLUDED = {105: "Encabezado de sección, no es especie", 66: "Duplicado de id 35 (Aristolochia vaginans)"}

# Rango latitudinal aproximado de cada región (sur, norte), grados decimales
REGIONS = {
    "arica y parinacota": (-19.2, -17.5), "tarapaca": (-21.6, -19.0), "antofagasta": (-26.1, -21.4),
    "atacama": (-29.5, -25.3), "coquimbo": (-32.3, -29.0), "valparaiso": (-33.9, -32.0),
    "metropolitana": (-34.3, -32.9), "o'higgins": (-35.0, -33.8), "maule": (-36.5, -34.7),
    "nuble": (-37.2, -36.0), "biobio": (-38.5, -36.4), "araucania": (-39.6, -37.6),
    "los rios": (-40.7, -39.3), "los lagos": (-44.1, -40.2), "aysen": (-49.2, -43.6),
    "magallanes": (-56.0, -48.6),
}

COLOR_WORDS = [
    (r"blanc", "blanco"), (r"amarill", "amarillo"), (r"anaranjad|naranj", "naranjo"),
    (r"roj", "rojo"), (r"rosad|fucsia|magenta", "rosado"), (r"purpur|morad|lila|violet", "morado"),
    (r"azul|celest", "azul"),
]
# Nombres comunes cuyo color no se refiere a la flor
NAME_COLOR_SKIP = {"Adesmia argentea"}

VALID = {
    "colors": {"blanco", "amarillo", "naranjo", "rojo", "rosado", "morado", "azul", "verde"},
    "growth": {"hierba", "arbusto", "cactus", "parasita"},
    "habit": {"rastrera", "erecta", "trepadora"},
    "flower_type": {"trimera", "cruz4", "libres5", "muchos", "tubo", "cabezuela", "irregular"},
    "geophyte": {"si", "no"},
    "cycle": {"anual", "perenne"},
}


def norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower().replace("’", "'"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def colors_in(text):
    return sorted({c for pat, c in COLOR_WORDS if re.search(pat, text)})


def book_colors(sp):
    """Colores mencionados junto a 'flor'/'tépalo' en la ficha (no espinas ni hojas)."""
    found = set()
    for field in (sp["flower_shape"], sp["description_source"]):
        for clause in re.split(r"[;.]", norm(field)):
            m = re.search(r"(flor|tepalo|petalo)", clause)
            if m:
                found |= set(colors_in(clause[m.start():]))
    return sorted(found)


def name_colors(sp):
    if sp["scientific_name"] in NAME_COLOR_SKIP:
        return []
    n = norm(sp["common_names"])
    return colors_in(n) + (["azul"] if "azulillo" in n and "azul" not in colors_in(n) else [])


def lat_range(text):
    t = norm(text)
    hits = [REGIONS[r] for r in REGIONS if r in t]
    if not hits:
        return None, None
    return min(h[0] for h in hits), max(h[1] for h in hits)


def book_traits(sp):
    desc, shape = norm(sp["description_source"]), norm(sp["flower_shape"])
    growth, under = norm(sp["growth_form"]), norm(sp["underground_structure"])
    where = " ".join(norm(sp[k]) for k in ("habitat", "description_source", "distribution_text"))
    t = {}
    if sp["group_name"] == "Cactácea" or growth == "cactacea":
        t["growth"] = "cactus"
    elif "parasit" in growth:
        t["growth"] = "parasita"
    elif "arbusto" in growth:  # incluye subarbusto
        t["growth"] = "arbusto"
    elif growth == "hierba":
        t["growth"] = "hierba"
    if re.search(r"trepador", desc):
        t["habit"] = "trepadora"
    elif re.search(r"rastrer|postrad|tendid|procumbente", desc):
        t["habit"] = "rastrera"
    elif re.search(r"erect|derecho|ascendente|ascendient|tallos rectos", desc):
        t["habit"] = "erecta"
    if "cabezuela" in shape:
        t["flower_type"] = "cabezuela"
    elif re.search(r"amariposada|irregular", shape):
        t["flower_type"] = "irregular"
    elif "tetramera" in shape:
        t["flower_type"] = "cruz4"
    elif "trimera" in shape:
        t["flower_type"] = "trimera"
    elif re.search(r"pentamera|unidos solo en su base", shape):
        t["flower_type"] = "libres5"
    elif re.search(r"acampanada|tubular|tubo|embudo", shape):
        t["flower_type"] = "tubo"
    elif t.get("growth") == "cactus":
        t["flower_type"] = "muchos"
    # Leyenda del libro: bulbo, rizoma y cormo son órganos subterráneos de resistencia (rebrota cada año)
    if "geofita" in desc or "bulbo" in under or (t.get("growth") == "hierba" and re.search(r"rizoma|cormo", under)):
        t["geophyte"] = "si"
    elif under.startswith("raiz pivotante") or under.startswith("raiz fasciculada"):
        t["geophyte"] = "no"
    if norm(sp["life_cycle"]) in ("anual", "perenne"):
        t["cycle"] = norm(sp["life_cycle"])
    if re.search(r"suculent|carnos", desc) or t.get("growth") == "cactus":
        t["succulent"] = "si"
    if re.search(r"espin", desc) or t.get("growth") == "cactus":
        t["spiny"] = "si"
    coast = bool(re.search(r"costa|litoral|duna", where))
    inland = bool(re.search(r"interior", where))
    if coast or inland:
        t["zone"] = "ambos" if coast and inland else ("costa" if coast else "interior")
    return t


def load_draft():
    rows = {}
    with open(DRAFT, encoding="utf-8") as f:
        lines = [l for l in f if l.strip() and not l.startswith("#")]
    for r in csv.DictReader(lines, delimiter=";"):
        rec = {}
        for k in VALID:
            v = (r.get(k) or "").strip()
            if not v:
                continue
            vals = v.split("|") if k == "colors" else [v]
            bad = [x for x in vals if x not in VALID[k]]
            if bad:
                raise ValueError(f"{r['scientific_name']}: valor inválido {bad} en {k}")
            rec[k] = vals if k == "colors" else v
        rows[r["scientific_name"].strip()] = rec
    return rows


def load_verified(rows_by_id):
    out = {}
    with open(VERIFIED, encoding="utf-8") as f:
        lines = [l for l in f if l.strip() and not l.startswith("#")]
    for r in csv.DictReader(lines, delimiter=";"):
        sid = int(r["id"])
        if sid not in rows_by_id or rows_by_id[sid]["scientific_name"] != r["scientific_name"]:
            raise ValueError(f"colores_libro.csv: id {sid} no coincide con {r['scientific_name']}")
        cols = [c for c in r["colors"].split("|") if c]
        bad = [c for c in cols if c not in VALID["colors"]]
        if bad:
            raise ValueError(f"colores_libro.csv: color inválido {bad} en {r['scientific_name']}")
        out[sid] = cols
    return out


def load_verified_traits(rows_by_id):
    out = {}
    with open(VERIFIED_TRAITS, encoding="utf-8") as f:
        lines = [l for l in f if l.strip() and not l.startswith("#")]
    for r in csv.DictReader(lines, delimiter=";"):
        sid, key, val = int(r["id"]), r["trait"].strip(), r["value"].strip()
        if sid not in rows_by_id or rows_by_id[sid]["scientific_name"] != r["scientific_name"]:
            raise ValueError(f"rasgos_libro.csv: id {sid} no coincide con {r['scientific_name']}")
        if key not in VALID or key == "colors" or val not in VALID[key]:
            raise ValueError(f"rasgos_libro.csv: {key}={val} inválido ({r['scientific_name']})")
        out.setdefault(sid, {})[key] = val
    return out


def load_phenology():
    if not PHENO.exists():
        return {}
    with open(PHENO, encoding="utf-8") as f:
        return {r["scientific_name"]: r for r in csv.DictReader(f, delimiter=";") if r.get("profile")}


def flowering_window(profile, threshold=.3):
    """Meses consecutivos (circulares) alrededor del máximo con floración ≥ umbral del máximo."""
    if min(profile) >= threshold:
        return 1, 12  # todo el año
    peak = max(range(12), key=lambda m: profile[m])
    start = end = peak
    while profile[(start - 1) % 12] >= threshold and (start - 1) % 12 != peak:
        start = (start - 1) % 12
    while profile[(end + 1) % 12] >= threshold and (end + 1) % 12 != start:
        end = (end + 1) % 12
    return start + 1, end + 1


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    draft = load_draft()
    pheno = load_phenology()
    cols = ["id", "scientific_name", "common_names", "group_name", "book_page", "pdf_page", "distribution_text",
            "origin_status", "description_source", "conservation_status", "flower_color", "flower_shape",
            "growth_form", "life_cycle", "underground_structure", "habitat", "sensitive_location", "data_quality"]
    rows = [dict(r) for r in con.execute(f"select {', '.join(cols)} from species order by scientific_name, id")]
    verified = load_verified({r["id"]: r for r in rows})
    verified_traits = load_verified_traits({r["id"]: r for r in rows})
    unused = set(draft) - {r["scientific_name"] for r in rows}
    if unused:
        raise ValueError(f"Especies del CSV que no están en el catálogo: {sorted(unused)}")

    out = []
    for sp in rows:
        traits, src = {}, {}
        for k, v in book_traits(sp).items():
            traits[k], src[k] = v, "libro"
        bc = book_colors(sp)
        if bc:
            traits["colors"], src["colors"] = bc, "libro"
        elif name_colors(sp):
            traits["colors"], src["colors"] = name_colors(sp), "nombre"
        if sp["id"] in verified:
            traits["colors"], src["colors"] = verified[sp["id"]], "libro_foto"
        for k, v in verified_traits.get(sp["id"], {}).items():
            if k not in traits:  # el texto de la ficha manda
                traits[k], src[k] = v, "libro_foto"
        for k, v in draft.get(sp["scientific_name"], {}).items():
            if k not in traits:
                traits[k], src[k] = v, "por_verificar"
        lat_min, lat_max = lat_range(sp["distribution_text"])
        # Especie amenazada o marcada: coordenadas protegidas al exportar públicamente
        cons = norm(sp["conservation_status"])
        sensitive = bool(sp["sensitive_location"]) or bool(re.search(r"en peligro|vulnerable", cons))
        ph = pheno.get(sp["scientific_name"])
        if ph:
            prof = [float(v) for v in ph["profile"].split()]
            sp["flowering_start_month"], sp["flowering_end_month"] = flowering_window(prof)
            sp.update(flowering_profile=prof, flowering_source=ph["source"], flowering_n=int(ph["n"]), flowering_place=ph["place"])
        else:
            sp.update(flowering_start_month=None, flowering_end_month=None, flowering_profile=None,
                      flowering_source=None, flowering_n=None, flowering_place=None)
        sp.update(traits=traits, trait_sources=src, lat_min=lat_min, lat_max=lat_max,
                  sensitive_location=int(sensitive), excluded_reason=EXCLUDED.get(sp["id"]))
        out.append(sp)

    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    existing = {r[1] for r in con.execute("pragma table_info(species)")}
    for col, typ in [("flowering_profile_json", "TEXT"), ("flowering_source", "TEXT"), ("flowering_n", "INTEGER"), ("traits_json", "TEXT"), ("trait_sources_json", "TEXT"), ("lat_min", "REAL"),
                     ("lat_max", "REAL"), ("excluded_reason", "TEXT")]:
        if col not in existing:
            con.execute(f"alter table species add column {col} {typ}")
    obs_cols = {r[1] for r in con.execute("pragma table_info(observations)")}
    for col in ("observer", "validation_status", "identification_method", "altitude_accuracy_m"):
        if col not in obs_cols:
            con.execute(f"alter table observations add column {col} TEXT")
    for sp in out:
        con.execute("update species set flowering_start_month=?, flowering_end_month=?, flowering_profile_json=?, "
                    "flowering_source=?, flowering_n=? where id=?",
                    (sp["flowering_start_month"], sp["flowering_end_month"],
                     json.dumps(sp["flowering_profile"]) if sp["flowering_profile"] else None, sp["flowering_source"],
                     sp["flowering_n"], sp["id"]))
        con.execute("update species set traits_json=?, trait_sources_json=?, lat_min=?, lat_max=?, excluded_reason=?, "
                    "sensitive_location=?, flower_color=? where id=?",
                    (json.dumps(sp["traits"], ensure_ascii=False), json.dumps(sp["trait_sources"]), sp["lat_min"],
                     sp["lat_max"], sp["excluded_reason"], sp["sensitive_location"],
                     "|".join(sp["traits"].get("colors", [])) or None, sp["id"]))
    con.execute("insert or replace into app_metadata values ('catalog_version', '0.6.0')")
    con.commit()

    n = len(out)
    cover = {k: sum(k in s["traits"] for s in out) for k in list(VALID) + ["succulent", "spiny", "zone"]}
    by_src = {s: sum(v == s for sp in out for v in sp["trait_sources"].values()) for s in ("libro", "libro_foto", "nombre", "por_verificar")}
    print(f"{n} registros → {OUT.name}")
    print("cobertura por rasgo:", cover)
    print("con rango latitudinal:", sum(s["lat_min"] is not None for s in out), "| sensibles:",
          [s["scientific_name"] for s in out if s["sensitive_location"]])
    print("rasgos por procedencia:", by_src)
    print("con perfil de floración:", sum(s["flowering_profile"] is not None for s in out))


if __name__ == "__main__":
    main()
