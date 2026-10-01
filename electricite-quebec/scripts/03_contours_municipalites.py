"""Prépare les contours des municipalités pour la carte web.

Entrée  : couche munic_s de BDAT(adm)_SHP.zip (MRNF, découpages administratifs)
Sortie  : electricite-quebec/donnees/municipalites.geojson
          (un polygone par code géographique, simplifié, en WGS84)

Étapes : lecture, projection en mètres (NAD83 / MTM Québec Lambert, EPSG:32198), fusion des
morceaux d'une même municipalité, simplification par polygone,
reprojection en WGS84 et écriture avec 5 décimales.
"""
import sys
from pathlib import Path

import geopandas as gpd
import shapely

RACINE = Path(__file__).resolve().parents[2]
ARCHIVE_SHP = RACINE / "BDAT(adm)_SHP.zip"
SORTIE = RACINE / "electricite-quebec" / "donnees" / "municipalites.geojson"
TOLERANCE_M = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0


def main():
    g = gpd.read_file(f"zip://{ARCHIVE_SHP}!Bdat/SHP/munic_s.shp")
    g = g.to_crs(32198)
    attr = (
        g.drop_duplicates("MUS_CO_GEO")
        .set_index("MUS_CO_GEO")[["MUS_NM_MUN", "MUS_NM_MRC", "MUS_NM_REG", "MUS_CO_DES"]]
        .rename(columns={"MUS_NM_MUN": "nom", "MUS_NM_MRC": "mrc", "MUS_NM_REG": "region", "MUS_CO_DES": "designation"})
    )
    fusion = g.dissolve(by="MUS_CO_GEO")[["geometry"]]
    fusion = fusion.join(attr).reset_index().rename(columns={"MUS_CO_GEO": "code_geo"})
    fusion["geometry"] = fusion.geometry.make_valid()

    # Simplification polygone par polygone (la simplification « coverage » laisse intacts
    # les très gros polygones du Nord, qui compteraient à eux seuls plus de 300 000 sommets).
    # Les frontières communes peuvent donc différer de quelques dizaines de mètres : sans
    # effet visible à l'échelle d'une carte du Québec. Les polygones restés très détaillés
    # (côtes du Nord) sont simplifiés plus fortement.
    simple = fusion.geometry.simplify(TOLERANCE_M, preserve_topology=True)
    trop_detailles = simple.map(lambda x: shapely.get_num_coordinates(x)) > 15_000
    simple[trop_detailles] = fusion.geometry[trop_detailles].simplify(TOLERANCE_M * 8, preserve_topology=True)
    methode = "simplify par polygone"
    fusion["geometry"] = simple
    fusion = fusion[~fusion.geometry.is_empty]
    fusion = fusion.to_crs(4326)
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    fusion.to_file(SORTIE, driver="GeoJSON", COORDINATE_PRECISION=5)
    taille = SORTIE.stat().st_size / 1e6
    print(f"{len(fusion)} polygones | tolérance {TOLERANCE_M:.0f} m | {methode} | {taille:.1f} Mo")


if __name__ == "__main__":
    main()
