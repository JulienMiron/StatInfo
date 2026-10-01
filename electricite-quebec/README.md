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
│   └── 03_contours_municipalites.py        # limites -> donnees/municipalites.geojson (simplifié, 3 Mo)
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

## Reste à faire

1. Données de température mensuelles (2016 à 2022) par municipalité, pour calculer les degrés-jours.
2. Modèle de consommation résidentielle par logement, estimé sur les unités mesurées, puis
   ajusté aux totaux des MRC.
3. Carte interactive (choroplèthe) avec incertitude.
