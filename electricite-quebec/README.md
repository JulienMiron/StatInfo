# Électricité au Québec : carte par municipalité

Première étape du projet de site de statistiques sur le Québec : estimer la consommation
d'électricité par municipalité en croisant la population, le parc de logements et la
température.

## Sources et licences

| Données | Source | Licence |
|---|---|---|
| Consommation d'électricité par secteur, par municipalité et par MRC (mensuelle, janvier 2016 à septembre 2022) | Hydro-Québec, [Données Québec](https://www.donneesquebec.ca/recherche/dataset/historique-consommation-electricite-secteur-activite) | CC-BY-NC 4.0 (attribution, **usage non commercial**) |
| Découpages administratifs (limites des municipalités) | Ministère des Ressources naturelles et des Forêts, [Données Québec](https://www.donneesquebec.ca/recherche/dataset/decoupages-administratifs) | CC-BY 4.0 |
| Profil du recensement de 2021, subdivisions de recensement du Québec | [Statistique Canada](https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/details/download-telecharger.cfm?Lang=F) | À vérifier sur le site de Statistique Canada |
| Températures quotidiennes (réanalyse ERA5) | [Open-Meteo](https://open-meteo.com), à partir de données Copernicus / ECMWF | CC-BY 4.0 ; API gratuite pour usage non commercial |

À cause de la licence CC-BY-NC, le site qui affichera ces données doit rester non commercial
(pas de publicité ni de monétisation) et citer Hydro-Québec.

## Ce que contiennent les données d'Hydro-Québec

- **Fichier municipal** : 1 152 « unités » (municipalités et territoires), 5 secteurs
  (agricole, commercial, industriel, institutionnel, résidentiel), 81 mois.
  **70 % des valeurs sont vides** : 57 % des unités n'ont aucune valeur résidentielle, et
  seules 286 ont une année 2021 complète. Les réseaux municipaux (Saguenay, Sherbrooke,
  Alma, Magog, Joliette, Westmount) sont entièrement vides. La cause n'est pas documentée
  dans le fichier ; une règle de confidentialité pour les petits groupes de clients est
  l'hypothèse la plus probable, à confirmer.
- **Fichier MRC** : beaucoup plus complet (environ 166 TWh par an, dont 60 TWh d'industriel en
  2021), mais 5,6 % des cases sont vides, surtout dans une catégorie « sans MRC » de six régions.
- Les deux fichiers ne sont pas parfaitement cohérents : dans 3,4 % des cases où le total MRC
  est connu, la somme des municipalités le dépasse.
- Intensité résidentielle 2021 : médiane de 19,4 MWh par logement occupé dans les 286 unités
  mesurées (5e à 95e centile : 14,2 à 31,5), contre 19,7 MWh pour le total des MRC. Le reste
  implicite des MRC (total MRC moins les unités mesurées) donne 20,0 MWh par logement, contre
  19,8 pour les unités mesurées : l'ajustement des estimations sur les totaux des MRC est cohérent.
  Les unités mesurées sont toutefois plus grandes (médiane de 754 logements occupés contre 480).

Conséquence : une carte de consommation **mesurée** par municipalité n'est pas possible.
La carte reposera sur un modèle (ménages, type de logement, degrés-jours) calé sur les valeurs
observées et ajusté aux totaux des MRC, avec l'incertitude affichée et la distinction entre
unités mesurées et estimées.

## Contenu du dossier

```
electricite-quebec/
├── scripts/
│   ├── 01_extraire_recensement.py          # recensement 2021 -> donnees/recensement_2021_sdr_qc.csv
│   ├── 02_correspondance_municipalites.py  # noms Hydro-Québec -> codes -> donnees/correspondance_hq_code.csv
│   ├── 03_contours_municipalites.py        # limites -> donnees/municipalites.geojson (simplifié, 3 Mo) et centres_municipalites.csv
│   └── 04_temperatures.py                  # températures ERA5 (Open-Meteo) -> degrés-jours mensuels, incrémental
└── donnees/
```

Les fichiers sources (archives et CSV à la racine du dépôt) ne sont pas modifiés. Dépendances
Python : pandas, geopandas, pyogrio, shapely.

### Correspondance des noms

Hydro-Québec ne publie que des noms. La jointure avec les codes géographiques officiels (clé
commune avec le recensement) se fait par région + MRC + nom, puis par région + nom, puis par nom
unique. Elle associe 1 127 des 1 152 unités, soit **99,8 % de la consommation observée**. Quand
plusieurs codes portent le même nom dans une même MRC (par exemple une ville et un canton),
l'unité reçoit tous ces codes. Les 25 unités restantes n'ont pas été retrouvées dans la couche
(noms différents, fusions ou renommages possibles, non vérifié) ; elles pèsent 0,2 % de la
consommation observée. Les plus importantes sont Saint-Côme--Linière,
Métabetchouan--Lac-à-la-Croix, Betsiamites et Saint-Bruno.

Les contours datent de 2026, le recensement de 2021 et les données d'Hydro-Québec s'arrêtent en
2022 : sept codes associés à Hydro-Québec n'existent pas au recensement (Amos, La Pocatière,
Cacouna, Lac-des-Aigles, Plessisville, Notre-Dame-de-la-Salette, Hébertville), probablement à la
suite de changements de municipalités ; ces unités n'auront pas de caractéristiques de logement
tant que la correspondance n'est pas corrigée à la main.

### Températures

`04_temperatures.py` associe chaque municipalité (centre de son polygone) à un point d'une grille
de 0,5° et télécharge un point par cellule utile (207 points). Il produit les températures
quotidiennes, puis les degrés-jours de chauffage mensuels (base 18 °C) par point, et le lien
municipalité -> point (`municipalites_points.csv`).

```
python electricite-quebec/scripts/04_temperatures.py --essai            # 2 appels de vérification, ne modifie rien
python electricite-quebec/scripts/04_temperatures.py --fin 2022-12-31   # période du calage (données d'Hydro-Québec jusqu'en 2022)
python electricite-quebec/scripts/04_temperatures.py                    # jusqu'à aujourd'hui, puis mises à jour
```

Le script est incrémental : il garde ce qui est déjà téléchargé et ne demande que les jours
manquants, avec un recouvrement de 30 jours parce que les valeurs récentes d'ERA5 peuvent être
révisées. Les derniers jours, absents de l'archive, viennent de l'API de prévision d'Open-Meteo
et sont remplacés par l'archive aux exécutions suivantes. C'est ce qui permettra de le planifier
plus tard (par exemple une exécution quotidienne) sans le réécrire.

**Limites à connaître**

- L'API gratuite d'Open-Meteo plafonne le nombre d'appels par jour, et un appel qui couvre de
  nombreux jours compte pour plusieurs. Le premier téléchargement complet pourrait donc
  s'étaler sur plusieurs jours : à la limite quotidienne, le script s'arrête proprement et
  reprend où il s'est arrêté à la relance. Les mises à jour suivantes sont minimes.
  Les conditions exactes sont à vérifier sur la page de tarification d'Open-Meteo.
- Le script a été testé hors ligne avec de fausses réponses de l'API (reprise incrémentale, arrêt
  à la limite quotidienne, calcul des degrés-jours), mais **l'appel réel à l'API n'a pas pu être
  testé** depuis l'environnement où il a été écrit. Commence par `--essai`.
- Une cellule de 0,5° (environ 55 km sur 38 km) ignore les écarts locaux de température,
  notamment l'altitude.
- Ces données sont publiées sous licence CC-BY 4.0 : à citer (Open-Meteo, données ERA5 de
  Copernicus / ECMWF).

## Reste à faire

1. Lancer `04_temperatures.py` (voir ci-dessus), puis calculer les degrés-jours par municipalité.
2. Modèle de consommation résidentielle par logement, estimé sur les unités mesurées, puis
   ajusté aux totaux des MRC.
3. Carte interactive (choroplèthe) avec incertitude.
