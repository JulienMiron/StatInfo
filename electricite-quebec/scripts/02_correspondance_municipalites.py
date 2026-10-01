"""Associe chaque municipalité d'Hydro-Québec à son ou ses codes géographiques officiels.

Hydro-Québec ne publie que des noms (région, MRC, municipalité), sans code. La jointure
se fait donc avec la couche des municipalités du MRNF (munic_s), qui contient le nom, la MRC,
la région et le code géographique (MUS_CO_GEO, clé commune avec le recensement).

Niveaux de correspondance, du plus strict au plus souple :
  1. région + MRC + nom
  2. région + nom        (cas où la MRC est vide chez Hydro-Québec : villes-MRC, etc.)
  3. nom seul, s'il est unique dans toute la province

Passe 1 : un niveau qui donne exactement un code l'emporte.
Passe 2 : si une « unité » Hydro-Québec correspond à plusieurs codes de même nom (ex. ville
          et canton qui portent le même nom, regroupés par Hydro-Québec), on retire les codes
          déjà pris par une autre unité ; s'il en reste un, on l'attribue ; s'il en reste
          plusieurs (niveaux 1 et 2 seulement), l'unité couvre tout le groupe de codes.
Passe 3 : un code ne peut appartenir qu'à une seule unité. En cas de conflit, la méthode la
          plus stricte gagne ; à égalité, les unités concernées restent sans code (ambiguës).

Entrées : 2022-10_Historique-...municipalite.csv (racine du dépôt) et la couche munic_s
          lue directement dans BDAT(adm)_SHP.zip.
Sortie  : electricite-quebec/donnees/correspondance_hq_code.csv
          (une ligne par couple unité Hydro-Québec / code ; code_geo vide si non associée)
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd
import pyogrio

RACINE = Path(__file__).resolve().parents[2]
HQ = RACINE / "2022-10_Historique-consommation-electricite-par-secteur-activite_municipalite.csv"
ARCHIVE_SHP = RACINE / "BDAT(adm)_SHP.zip"
SORTIE = RACINE / "electricite-quebec" / "donnees" / "correspondance_hq_code.csv"

PRIORITE = {"region+mrc+nom": 1, "region+nom": 2, "nom": 3}


def norm(s):
    """Minuscules, sans accents ni ponctuation ; « saint(e) » abrégé en « st(e) »."""
    if pd.isna(s):
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"\bsaint(e?)\b", r"st\1", s)
    return s


def charger_couche():
    chemin = f"zip://{ARCHIVE_SHP}!Bdat/SHP/munic_s.shp"
    g = pyogrio.read_dataframe(chemin, read_geometry=False)
    g = g.drop_duplicates("MUS_CO_GEO")[
        ["MUS_CO_GEO", "MUS_NM_MUN", "MUS_NM_MRC", "MUS_NM_REG", "MUS_CO_DES"]
    ].copy()
    g["n_nom"] = g.MUS_NM_MUN.map(norm)
    g["n_mrc"] = g.MUS_NM_MRC.map(norm)
    g["n_reg"] = g.MUS_NM_REG.map(norm)
    return g


def main():
    couche = charger_couche()
    hq = pd.read_csv(HQ, sep=";", decimal=",", dtype={"Total (kWh)": str})
    hq.columns = ["region", "mrc", "muni", "mois", "secteur", "brut"]
    hq["kwh"] = pd.to_numeric(hq.brut.str.replace(",", "."), errors="coerce")
    unites = (
        hq.groupby(["region", "mrc", "muni"], dropna=False)
        .kwh.sum()
        .rename("kwh_observe")
        .reset_index()
    )
    unites["n_nom"] = unites.muni.map(norm)
    unites["n_mrc"] = unites.mrc.map(norm)
    unites["n_reg"] = unites.region.map(norm)

    def candidats(colonnes):
        return couche.groupby(colonnes).MUS_CO_GEO.agg(list).to_dict()

    c1 = candidats(["n_reg", "n_mrc", "n_nom"])
    c2 = candidats(["n_reg", "n_nom"])
    c3 = candidats(["n_nom"])

    def listes(u):
        """Listes de codes candidats par niveau pour une unité."""
        out = []
        if u.n_mrc:
            out.append(("region+mrc+nom", c1.get((u.n_reg, u.n_mrc, u.n_nom), [])))
        out.append(("region+nom", c2.get((u.n_reg, u.n_nom), [])))
        out.append(("nom", c3.get(u.n_nom, [])))
        return out

    # Passe 1 : niveau donnant exactement un code
    attrib = {}  # index de l'unité -> (méthode, [codes])
    for i, u in unites.iterrows():
        for meth, cs in listes(u):
            if len(cs) == 1:
                attrib[i] = (meth, list(cs))
                break

    # Passe 2 : unités restantes, en retirant les codes déjà pris par d'autres unités
    pris = {c for _, cs in attrib.values() for c in cs}
    for i, u in unites.iterrows():
        if i in attrib:
            continue
        for meth, cs in listes(u):
            restants = [c for c in cs if c not in pris]
            if len(restants) == 1:
                attrib[i] = (meth, restants)
                break
            if len(restants) > 1 and meth != "nom":
                attrib[i] = (meth + "+groupe", restants)
                break
        if i in attrib:
            pris.update(attrib[i][1])

    # Passe 3 : un code, une seule unité
    par_code = {}
    for i, (meth, cs) in attrib.items():
        for c in cs:
            par_code.setdefault(c, []).append((PRIORITE[meth.split("+groupe")[0]], i))
    ambigus = set()
    for c, lst in par_code.items():
        if len(lst) > 1:
            lst.sort()
            if lst[0][0] < lst[1][0]:
                ambigus.update(i for _, i in lst[1:])
            else:
                ambigus.update(i for _, i in lst)
    for i in ambigus:
        attrib.pop(i, None)

    lignes = []
    for i, u in unites.iterrows():
        meth, cs = attrib.get(i, ("aucune" if i not in ambigus else "ambigue", [None]))
        for c in cs:
            lignes.append(
                {
                    "region": u.region,
                    "mrc": u.mrc,
                    "muni": u.muni,
                    "kwh_observe": u.kwh_observe,
                    "code_geo": c,
                    "methode": meth,
                    "n_codes_unite": len([x for x in cs if x]),
                }
            )
    res = pd.DataFrame(lignes)
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(SORTIE, index=False, encoding="utf-8")

    u = res.drop_duplicates(["region", "mrc", "muni"])
    ok = u.code_geo.notna()
    print(f"{len(u)} unités Hydro-Québec | associées : {ok.sum()} | groupes de plusieurs codes : {(u.n_codes_unite > 1).sum()}")
    print(u.methode.value_counts().to_string())
    print(f"Part de la consommation observée associée : {u.loc[ok, 'kwh_observe'].sum() / u.kwh_observe.sum():.3%}")
    print(f"Codes attribués à plus d'une unité : {res[res.code_geo.notna()].code_geo.duplicated().sum()}")
    non = u[~ok].sort_values("kwh_observe", ascending=False)
    print("\nNon associées :")
    print(non[["region", "mrc", "muni", "kwh_observe", "methode"]].head(30).to_string(index=False))


if __name__ == "__main__":
    main()
