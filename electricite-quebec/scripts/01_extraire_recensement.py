"""Extrait du Profil du recensement 2021 (SDR, Québec) les caractéristiques utiles.

Entrée  : 98-401-X2021020_fra_CSV.zip (à la racine du dépôt, non modifié)
Sortie  : electricite-quebec/donnees/recensement_2021_sdr_qc.csv
          (une ligne par subdivision de recensement, une colonne par caractéristique)

Le fichier de données fait environ 650 Mo décompressé : il est lu par blocs,
directement depuis l'archive, sans extraction sur le disque.
"""
import zipfile
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
ARCHIVE = RACINE / "98-401-X2021020_fra_CSV.zip"
MEMBRE = "98-401-X2021020_Francais_CSV_data.csv"
SORTIE = RACINE / "electricite-quebec" / "donnees" / "recensement_2021_sdr_qc.csv"

# ID_CARACTÉRISTIQUE -> nom de colonne
CARACTERISTIQUES = {
    1: "population_2021",
    4: "logements_total",
    5: "logements_occupes",
    7: "superficie_km2",
    41: "occupes_type_total",
    42: "type_maison_individuelle",
    43: "type_maison_jumelee",
    44: "type_maison_rangee",
    45: "type_appart_duplex",
    46: "type_appart_moins_5_etages",
    47: "type_appart_5_etages_plus",
    48: "type_autre_attenante",
    49: "type_logement_mobile",
    56: "personnes_menages",
    57: "taille_moyenne_menage",
    243: "revenu_median_menage_2020",
    1415: "proprietaires",
    1416: "locataires",
    1440: "periode_total",
    1441: "periode_1960_ou_avant",
    1442: "periode_1961_1980",
    1443: "periode_1981_1990",
    1444: "periode_1991_2000",
    1445: "periode_2001_2005",
    1446: "periode_2006_2010",
    1447: "periode_2011_2015",
    1448: "periode_2016_2021",
}

# Colonnes du fichier source (encodage latin-1) : IDUGD, CODE_GÉO_ALT, NIVEAU_GÉO,
# NOM_GÉO, ID_CARACTÉRISTIQUE, C1_CHIFFRE_TOTAL
COLONNES = [1, 2, 3, 4, 8, 11]
NOMS = ["idugd", "code_alt", "niveau", "nom", "id_car", "valeur"]


def main() -> None:
    morceaux = []
    with zipfile.ZipFile(ARCHIVE) as z, z.open(MEMBRE) as f:
        lecteur = pd.read_csv(
            f,
            encoding="latin-1",
            usecols=COLONNES,
            header=0,
            names=NOMS,
            dtype={"code_alt": str},
            chunksize=500_000,
        )
        for bloc in lecteur:
            bloc = bloc[bloc.id_car.isin(CARACTERISTIQUES)]
            morceaux.append(bloc)

    long = pd.concat(morceaux, ignore_index=True)
    long["colonne"] = long.id_car.map(CARACTERISTIQUES)
    large = long.pivot_table(
        index=["code_alt", "nom", "niveau"], columns="colonne", values="valeur", aggfunc="first"
    ).reset_index()
    # Code géographique municipal à 5 chiffres : les 5 derniers chiffres du code SDR
    # (24 = Québec). C'est la clé de jointure avec les limites administratives (MUS_CO_GEO).
    large.insert(0, "code_geo", large.code_alt.str[-5:])
    large = large.drop(columns=["code_alt"])
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    large.to_csv(SORTIE, index=False, encoding="utf-8")
    print(f"{len(large)} subdivisions écrites dans {SORTIE.relative_to(RACINE)}")


if __name__ == "__main__":
    main()
