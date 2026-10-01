"""Estime la consommation résidentielle 2021 de chaque municipalité du Québec.

Entrées (dossier donnees/) : correspondance_hq_code.csv, recensement_2021_sdr_qc.csv,
  municipalites_points.csv, temperatures_mensuelles.csv, municipalites.geojson (attributs),
  et les deux fichiers d'Hydro-Québec à la racine du dépôt (municipalités et MRC).
Sorties : donnees/modele_coefficients.csv, donnees/estimations_residentiel_2021.csv

Méthode
1. Panel « unité Hydro-Québec x année » (2016-2021, années de 12 mois complets, secteur
   résidentiel) : log(kWh par logement) en fonction des degrés-jours de chauffage (séparés en
   écart annuel à la moyenne de l'unité = effet de la météo, et moyenne de l'unité = niveau
   climatique), de la part de maisons individuelles, de logements mobiles, de locataires, de
   logements d'avant 1980, de la taille des ménages et du revenu médian. Erreurs groupées par unité.
2. Erreur de prédiction honnête : validation croisée par blocs d'unités (10 blocs).
3. Estimation 2021 de chaque code géographique. Les unités mesurées gardent leur valeur observée
   (répartie entre leurs codes selon la prédiction). Pour les autres, la prédiction est ajustée
   par un facteur commun à la MRC pour que mesuré + estimé égale le total résidentiel 2021 de la
   MRC (quand il est complet et cohérent ; sinon aucun ajustement, signalé).
"""
import json
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

RACINE = Path(__file__).resolve().parents[2]
D = RACINE / "electricite-quebec" / "donnees"
HQ_MUNI = RACINE / "2022-10_Historique-consommation-electricite-par-secteur-activite_municipalite.csv"
HQ_MRC = RACINE / "2022-10_Historique-consommation-electricite-par-secteur-activite_MRC.csv"
ANNEE = 2021
FORMULE = "y ~ ldju_c + ldju_m + s_indiv + s_mobile + s_loc + s_av1980 + taille + lrev"
CLES = ["region", "mrc", "muni"]


def norm(s):
    if pd.isna(s):
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"\bsaint(e?)\b", r"st\1", s)


def lire_hq(chemin, colonnes):
    h = pd.read_csv(chemin, sep=";", decimal=",", dtype=str, encoding="utf-8-sig")
    h.columns = colonnes
    h["kwh"] = pd.to_numeric(h.brut.str.replace(",", ".").str.replace(" ", ""), errors="coerce")
    h["an"] = h.mois.str[:4].astype(int)
    return h[h.secteur == "RÉSIDENTIEL"].copy()


def caracteristiques(m):
    """Variables explicatives à partir des totaux du recensement (sommes pour un groupe de codes)."""
    den = m.occupes_type_total
    out = pd.DataFrame(index=m.index)
    out["s_indiv"] = m.type_maison_individuelle / den
    out["s_mobile"] = m.type_logement_mobile / den
    out["s_loc"] = m.locataires / (m.locataires + m.proprietaires)
    out["s_av1980"] = (m.periode_1960_ou_avant + m.periode_1961_1980) / m.periode_total
    out["taille"] = m.personnes_menages / m.logements_occupes
    out["lrev"] = np.log(m.revenu / 1000)
    return out.replace([np.inf, -np.inf], np.nan)


def main():
    corr = pd.read_csv(D / "correspondance_hq_code.csv", dtype={"code_geo": str})
    cen = pd.read_csv(D / "recensement_2021_sdr_qc.csv", dtype={"code_geo": str})
    pts = pd.read_csv(D / "municipalites_points.csv", dtype={"code_geo": str})
    t = pd.read_csv(D / "temperatures_mensuelles.csv")
    t["an"] = t.mois.str[:4].astype(int)
    dju = t.groupby(["point_id", "an"]).dju.sum().rename("dju").reset_index()

    # --- table des codes : recensement + point climatique + degrés-jours par année
    cen = cen.merge(pts, on="code_geo", how="left")
    cen["revenu"] = cen.revenu_median_menage_2020
    dj = cen[["code_geo", "point_id"]].merge(dju, on="point_id")  # code x année
    dj_w = dj.pivot(index="code_geo", columns="an", values="dju")

    # --- unités Hydro-Québec : somme des codes, degrés-jours pondérés par les logements occupés
    lien = corr.dropna(subset=["code_geo"]).merge(cen, on="code_geo", how="left")
    lien["w"] = lien.logements_occupes.fillna(0) + 1e-9
    somm = [c for c in cen.columns if c.startswith(("type_", "periode_")) or c in (
        "locataires", "proprietaires", "personnes_menages", "logements_occupes", "logements_total",
        "occupes_type_total", "population_2021")]
    u = lien.groupby(CLES, dropna=False)[somm].sum()
    u["revenu"] = lien.groupby(CLES, dropna=False).apply(
        lambda g: np.average(g.revenu.fillna(g.revenu.mean()), weights=g.w) if g.revenu.notna().any() else np.nan)
    u = u.join(caracteristiques(u))
    dju_u = {}
    for k, g in lien.groupby(CLES, dropna=False):
        ok = g.code_geo.isin(dj_w.index)
        if ok.any():
            dju_u[k] = (dj_w.loc[g.code_geo[ok]].mul(g.w[ok].values, axis=0).sum() / g.w[ok].sum())
    dju_u = pd.DataFrame(dju_u).T
    dju_u.index = pd.MultiIndex.from_tuples(dju_u.index, names=CLES)
    dju_u = dju_u.stack().rename("dju").reset_index().rename(columns={"level_3": "an"})

    # --- panel
    r = lire_hq(HQ_MUNI, ["region", "mrc", "muni", "mois", "secteur", "brut"])
    a = r.groupby(CLES + ["an"], dropna=False).agg(kwh=("kwh", "sum"), n=("kwh", "count")).reset_index()
    a = a[(a.n == 12) & (a.kwh > 0)]
    p = a.merge(u.reset_index(), on=CLES).merge(dju_u, on=CLES + ["an"])
    p = p[(p.logements_total > 20) & p.an.between(2016, 2021)].copy()
    p["y"] = np.log(p.kwh / p.logements_total)
    p["ldju"] = np.log(p.dju / 1000)
    p = p.dropna(subset=["y", "ldju", "s_indiv", "s_mobile", "s_loc", "s_av1980", "taille", "lrev"]).copy()
    p["unit"] = p.groupby(CLES, dropna=False).ngroup()
    p["ldju_m"] = p.groupby("unit").ldju.transform("mean")
    p["ldju_c"] = p.ldju - p.ldju_m
    ajust = smf.ols(FORMULE, p).fit(cov_type="cluster", cov_kwds={"groups": p.unit})
    sigma = float(np.sqrt(ajust.scale))

    # --- validation croisée par blocs d'unités
    rng = np.random.default_rng(1)
    bloc = pd.Series(rng.integers(0, 10, p.unit.nunique()), index=sorted(p.unit.unique()))
    p["bloc"] = p.unit.map(bloc)
    erreurs = []
    for b in range(10):
        f = smf.ols(FORMULE, p[p.bloc != b]).fit()
        erreurs.append(p.loc[p.bloc == b, "y"] - f.predict(p[p.bloc == b]))
    erreurs = pd.concat(erreurs)
    sigma_cv = float(erreurs.std())
    biais = float(np.exp(sigma_cv**2 / 2))  # correction de retransformation (log -> kWh)
    print(f"Panel : {len(p)} unités-années, {p.unit.nunique()} unités | R2 = {ajust.rsquared:.3f}")
    print(f"Écart-type résiduel {sigma:.3f} ; en validation croisée {sigma_cv:.3f} (échelle log)")
    coef = pd.DataFrame({"coef": ajust.params, "erreur_type": ajust.bse, "p": ajust.pvalues})
    coef.loc["sigma_residuel"] = [sigma, np.nan, np.nan]
    coef.loc["sigma_validation_croisee"] = [sigma_cv, np.nan, np.nan]
    coef.round(4).to_csv(D / "modele_coefficients.csv", encoding="utf-8")
    print(coef.round(3).to_string())

    # --- prédiction 2021 par code
    c = cen.merge(pd.DataFrame({"code_geo": dj_w.index, "dju21": dj_w[ANNEE].values}), on="code_geo", how="left")
    x = c.assign(logements_occupes=c.logements_occupes)
    x = x.join(caracteristiques(x).add_prefix("_")).drop(columns=["s_indiv"], errors="ignore")
    X = pd.DataFrame({
        "ldju_c": 0.0,  # 2021 comparée à la moyenne 2016-2021 du code
        "ldju_m": np.log(dj_w.reindex(c.code_geo).mean(axis=1).values / 1000),
        "s_indiv": x._s_indiv, "s_mobile": x._s_mobile, "s_loc": x._s_loc,
        "s_av1980": x._s_av1980, "taille": x._taille, "lrev": x._lrev,
    }, index=c.index)
    X["ldju_c"] = np.log(c.dju21.values / 1000) - X.ldju_m
    manque = X.isna().any(axis=1) | (c.logements_total.fillna(0) <= 0)
    X = X.fillna(X.median())  # codes sans revenu ou type de logement : médiane (signalés)
    c["pred_kwh"] = np.exp(ajust.predict(X)) * biais * c.logements_total
    c["pred_incomplet"] = manque

    # --- mesures 2021 par unité, répartition entre les codes, MRC
    obs = a[a.an == ANNEE][CLES + ["kwh"]].rename(columns={"kwh": "kwh_obs_unite"})
    lien2 = corr.dropna(subset=["code_geo"]).merge(obs, on=CLES, how="left")[CLES + ["code_geo", "kwh_obs_unite"]]
    c = c.merge(lien2, on="code_geo", how="left")
    c["somme_pred_unite"] = c.groupby(CLES, dropna=False).pred_kwh.transform("sum")
    c["mesure"] = c.kwh_obs_unite.notna()
    c["kwh_mesure"] = np.where(c.mesure, c.kwh_obs_unite * c.pred_kwh / c.somme_pred_unite, np.nan)

    # clé MRC : celle d'Hydro-Québec si le code est associé, sinon celle de la couche des limites
    attr = pd.DataFrame([f["properties"] for f in json.load(open(D / "municipalites.geojson"))["features"]])
    attr = attr.rename(columns={"nom": "nom_couche", "mrc": "mrc_couche", "region": "region_couche"})
    c = c.merge(attr[["code_geo", "nom_couche", "mrc_couche", "region_couche"]], on="code_geo", how="left")
    mrc_hq = lire_hq(HQ_MRC, ["region", "mrc", "mois", "secteur", "brut"])
    mrc_hq = mrc_hq[mrc_hq.an == ANNEE]
    tot = mrc_hq.groupby(["region", "mrc"], dropna=False).agg(
        total=("kwh", "sum"), n=("kwh", "size"), n_ok=("kwh", "count")).reset_index()
    tot["complet"] = tot.n == tot.n_ok
    tot["cle"] = tot.region.map(norm) + "|" + tot.mrc.map(norm)
    cl_ok = set(tot.cle)
    # codes associés à Hydro-Québec : région + MRC d'Hydro-Québec (MRC vide = villes et territoires
    # hors MRC, regroupés par région dans le fichier des MRC) ; autres codes : région + MRC de la couche
    assoc = c.muni.notna()
    c["cle"] = np.where(assoc, c.region.map(norm) + "|" + c.mrc.map(norm),
                        c.region_couche.map(norm) + "|" + c.mrc_couche.map(norm))
    c.loc[assoc & ~c.cle.isin(cl_ok), "cle"] = c.region_couche.map(norm) + "|" + c.mrc_couche.map(norm)
    c["cle_valide"] = c.cle.isin(cl_ok)
    tt = tot.set_index("cle")

    # --- ajustement aux totaux des MRC
    c["kwh_estime"] = np.where(c.mesure, c.kwh_mesure, c.pred_kwh)
    c["facteur_mrc"] = np.nan
    c["statut"] = np.where(c.mesure, "mesure", "estime_non_ajuste")
    bilan = []
    for cle, g in c[c.cle_valide].groupby("cle"):
        total, complet = tt.loc[cle, "total"], bool(tt.loc[cle, "complet"])
        mes = g.kwh_mesure.sum()
        nm = g[~g.mesure]
        if nm.empty or not complet:
            continue
        reste = total - mes
        if reste <= 0:
            bilan.append((cle, "incoherent", total, mes, nm.pred_kwh.sum()))
            continue
        k = reste / nm.pred_kwh.sum()
        c.loc[nm.index, "facteur_mrc"] = k
        c.loc[nm.index, "kwh_estime"] = nm.pred_kwh * k
        c.loc[nm.index, "statut"] = "estime_ajuste_mrc"
        bilan.append((cle, "ok", total, mes, nm.pred_kwh.sum()))
    bilan = pd.DataFrame(bilan, columns=["cle", "etat", "total_mrc", "mesure", "pred"])
    print("\nAjustement MRC :", bilan.etat.value_counts().to_dict())
    k = c.facteur_mrc.dropna()
    print("Facteur d'ajustement : médiane %.2f, 10e-90e centiles %.2f-%.2f" % (k.median(), k.quantile(.1), k.quantile(.9)))
    print("Statuts :", c.statut.value_counts().to_dict())

    # --- sorties
    z = 1.2816  # intervalle à 80 % sur la prédiction par logement (log-normal)
    lo, hi = np.exp(-z * sigma_cv), np.exp(z * sigma_cv)
    c["kwh_bas80"] = np.where(c.mesure, c.kwh_estime, c.kwh_estime * lo)
    c["kwh_haut80"] = np.where(c.mesure, c.kwh_estime, c.kwh_estime * hi)
    c["kwh_par_logement"] = c.kwh_estime / c.logements_total
    c["kwh_par_habitant"] = c.kwh_estime / c.population_2021.replace(0, np.nan)
    sortie = c[[
        "code_geo", "nom", "population_2021", "logements_total", "logements_occupes", "dju21",
        "kwh_estime", "kwh_bas80", "kwh_haut80", "kwh_par_logement", "kwh_par_habitant",
        "statut", "facteur_mrc", "pred_kwh", "pred_incomplet",
    ]].copy()
    for col in ["kwh_estime", "kwh_bas80", "kwh_haut80", "kwh_par_logement", "kwh_par_habitant", "pred_kwh", "dju21"]:
        sortie[col] = sortie[col].round(0)
    sortie["facteur_mrc"] = sortie.facteur_mrc.round(3)
    sortie.to_csv(D / "estimations_residentiel_2021.csv", index=False, encoding="utf-8")
    print(f"\nTotal estimé : {c.kwh_estime.sum()/1e9:.1f} TWh (total MRC 2021 : {tot.total.sum()/1e9:.1f} TWh)")
    print(f"{len(sortie)} codes écrits ; prédiction incomplète pour {int(c.pred_incomplet.sum())}")


if __name__ == "__main__":
    main()
