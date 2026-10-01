"""Assemble la carte interactive : carte/index.html (page autonome, sans serveur).

Entrées : donnees/municipalites.geojson, donnees/estimations_residentiel_2021.csv
Le modèle HTML est dans carte/modele.html ; ce script y injecte les données.
"""
import json
from pathlib import Path

import pandas as pd
import shapely
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.geometry.polygon import orient

RACINE = Path(__file__).resolve().parents[1]
D = RACINE / "donnees"
C = RACINE / "carte"


def arrondir(coords, n=3):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], n), round(coords[1], n)]
    return [arrondir(c, n) for c in coords]


def main():
    est = pd.read_csv(D / "estimations_residentiel_2021.csv", dtype={"code_geo": str}).set_index("code_geo")
    gj = json.load(open(D / "municipalites.geojson", encoding="utf-8"))
    feats = []
    for f in gj["features"]:
        p = f["properties"]
        code = p["code_geo"]
        e = est.loc[code] if code in est.index else None
        def v(col, r=0):
            if e is None or pd.isna(e[col]):
                return None
            return round(float(e[col]), r)
        props = {
            "c": code, "n": p["nom"], "m": p["mrc"], "r": p["region"],
            "k": v("kwh_estime"), "lo": v("kwh_bas80"), "hi": v("kwh_haut80"),
            "l": v("kwh_par_logement"), "h": v("kwh_par_habitant"),
            "p": v("population_2021"), "lg": v("logements_total"), "d": v("dju21"),
            "s": None if e is None else {"mesure": 0, "estime_ajuste_mrc": 1, "estime_non_ajuste": 2}[e["statut"]],
        }
        # coordonnées arrondies (1 décimale de précision ~ 100 m), géométrie revalidée,
        # puis anneaux extérieurs horaires, comme l'exige d3
        g = shapely.set_precision(shape(f["geometry"]), 0.001)
        if not g.is_valid:
            g = g.buffer(0)
        polys = [x for x in (g.geoms if hasattr(g, "geoms") else [g]) if x.geom_type == "Polygon" and not x.is_empty]
        if not polys:
            continue
        polys = [orient(x, sign=-1.0) for x in polys]
        m = mapping(polys[0] if len(polys) == 1 else MultiPolygon(polys))
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": m["type"], "coordinates": m["coordinates"]}})
    donnees = json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":"))
    html = (C / "modele.html").read_text(encoding="utf-8").replace("__DONNEES__", donnees)
    (C / "index.html").write_text(html, encoding="utf-8")
    print(f"carte/index.html : {len(html)/1e6:.1f} Mo, {len(feats)} municipalités")


if __name__ == "__main__":
    main()
