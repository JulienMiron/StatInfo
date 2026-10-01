"""Télécharge les températures quotidiennes et calcule les degrés-jours de chauffage mensuels.

Source : réanalyse ERA5 (Copernicus / ECMWF), servie par l'API gratuite d'Open-Meteo
         (https://open-meteo.com, aucun compte requis, usage non commercial, données CC-BY 4.0).
         Les derniers jours, pas encore dans l'archive, viennent de l'API de prévision
         d'Open-Meteo (paramètre past_days) et sont remplacés par l'archive aux exécutions suivantes.

Principe : chaque municipalité (centre de son polygone) est associée à un point d'une grille
régulière (0,5° par défaut) ; on télécharge un point par cellule habitée, pas un point par
municipalité. Le script est INCRÉMENTAL : il garde ce qu'il a déjà téléchargé et ne demande
que les jours manquants (plus un recouvrement de 30 jours, car les valeurs récentes d'ERA5
peuvent être révisées). On peut donc le relancer à volonté, et plus tard le planifier tel quel.

Fichiers produits dans electricite-quebec/donnees/ :
  points_temperature.csv         un point de grille par ligne (point_id, lat, lon, n_municipalites)
  municipalites_points.csv       code_geo -> point_id
  temperatures_quotidiennes.csv  point_id, date, tmoy (°C), source (archive ou recent)
  temperatures_mensuelles.csv    point_id, mois, tmoy, dju (degrés-jours sous la base), n_jours, complet

Utilisation (depuis la racine du dépôt) :
  python electricite-quebec/scripts/04_temperatures.py --essai   # 2 appels, ne modifie rien
  python electricite-quebec/scripts/04_temperatures.py           # téléchargement complet / mise à jour
  python electricite-quebec/scripts/04_temperatures.py --fin 2022-12-31   # seulement la période du calage

Si la limite quotidienne gratuite d'Open-Meteo est atteinte, le script s'arrête proprement :
il suffit de le relancer le lendemain, il reprend où il s'est arrêté.
Dépendances : pandas, numpy.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[2]
DONNEES = RACINE / "electricite-quebec" / "donnees"
URL_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
URL_RECENT = "https://api.open-meteo.com/v1/forecast"
FUSEAU = "America/Toronto"
DELAI_ARCHIVE_JOURS = 7  # l'archive a quelques jours de retard
VARIABLE = "temperature_2m_mean"


class LimiteJournaliere(Exception):
    """La limite quotidienne gratuite de l'API est atteinte."""


# --------------------------------------------------------------------------- appels réseau
def appeler(url, params, essais=6):
    """GET JSON avec reprises. Lève LimiteJournaliere si le quota du jour est épuisé."""
    adresse = url + "?" + urllib.parse.urlencode(params)
    attente = 5
    for _ in range(essais):
        try:
            requete = urllib.request.Request(adresse, headers={"User-Agent": "StatInfo-electricite-quebec/1.0"})
            with urllib.request.urlopen(requete, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            corps = e.read().decode("utf-8", "replace")
            try:
                raison = json.loads(corps).get("reason", corps)
            except Exception:
                raison = corps[:200]
            if e.code == 429:
                bas = raison.lower()
                if "daily" in bas:
                    raise LimiteJournaliere(raison)
                pause = 65 if "minut" in bas else 600 if "hour" in bas else attente
                print(f"  Limite de débit atteinte ({raison}) ; pause de {pause} s")
                time.sleep(pause)
            elif e.code >= 500:
                print(f"  Erreur serveur {e.code} ; nouvel essai dans {attente} s")
                time.sleep(attente)
            else:
                raise RuntimeError(f"Erreur {e.code} : {raison}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"  Problème réseau ({e}) ; nouvel essai dans {attente} s")
            time.sleep(attente)
        attente = min(attente * 2, 120)
    raise RuntimeError("Trop d'échecs consécutifs : réessaie plus tard (le script reprendra où il s'est arrêté).")


def lire_reponse(rep, ids):
    """Réponse Open-Meteo -> liste de (point_id, date, tmoy). Un objet si 1 point, une liste sinon."""
    blocs = rep if isinstance(rep, list) else [rep]
    if len(blocs) != len(ids):
        raise RuntimeError(f"Réponse inattendue : {len(blocs)} blocs pour {len(ids)} points")
    lignes = []
    for pid, bloc in zip(ids, blocs):
        quotidien = bloc["daily"]
        for jour, t in zip(quotidien["time"], quotidien[VARIABLE]):
            if t is not None:
                lignes.append((pid, jour, float(t)))
    return lignes


def telecharger_archive(points, debut, fin):
    ids = list(points.point_id)
    rep = appeler(
        URL_ARCHIVE,
        {
            "latitude": ",".join(f"{x:.4f}" for x in points.lat),
            "longitude": ",".join(f"{x:.4f}" for x in points.lon),
            "start_date": debut.isoformat(),
            "end_date": fin.isoformat(),
            "daily": VARIABLE,
            "timezone": FUSEAU,
        },
    )
    return lire_reponse(rep, ids)


def telecharger_recent(points, jours):
    ids = list(points.point_id)
    rep = appeler(
        URL_RECENT,
        {
            "latitude": ",".join(f"{x:.4f}" for x in points.lat),
            "longitude": ",".join(f"{x:.4f}" for x in points.lon),
            "daily": VARIABLE,
            "past_days": jours,
            "forecast_days": 1,
            "timezone": FUSEAU,
        },
    )
    return lire_reponse(rep, ids)


# --------------------------------------------------------------------------- points de grille
def construire_points(resolution, tous):
    centres = pd.read_csv(DONNEES / "centres_municipalites.csv", dtype={"code_geo": str})
    centres["la"] = ((centres.lat / resolution).round() * resolution).round(4)
    centres["lo"] = ((centres.lon / resolution).round() * resolution).round(4)
    centres["point_id"] = centres.la.map("{:.3f}".format) + "_" + centres.lo.map("{:.3f}".format)

    # Cellules utiles : habitées au recensement de 2021 ou contenant une municipalité d'Hydro-Québec
    utiles = set()
    f_rec, f_cor = DONNEES / "recensement_2021_sdr_qc.csv", DONNEES / "correspondance_hq_code.csv"
    if f_rec.exists():
        rec = pd.read_csv(f_rec, dtype={"code_geo": str})
        utiles |= set(rec.code_geo[rec.population_2021 > 0])
    if f_cor.exists():
        utiles |= set(pd.read_csv(f_cor, dtype={"code_geo": str}).code_geo.dropna())
    centres["utile"] = True if (tous or not utiles) else centres.code_geo.isin(utiles)

    points = (
        centres[centres.utile]
        .groupby("point_id")
        .agg(lat=("la", "first"), lon=("lo", "first"), n_municipalites=("code_geo", "size"))
        .reset_index()
    )
    # Municipalités dont la cellule n'est pas téléchargée : point téléchargé le plus proche
    xy = points[["lat", "lon"]].to_numpy()
    liens = []
    for r in centres.itertuples():
        if r.point_id in set(points.point_id):
            liens.append((r.code_geo, r.point_id))
        else:
            d = (xy[:, 0] - r.lat) ** 2 + ((xy[:, 1] - r.lon) * np.cos(np.radians(r.lat))) ** 2
            liens.append((r.code_geo, points.point_id.iloc[int(d.argmin())]))
    return points, pd.DataFrame(liens, columns=["code_geo", "point_id"])


# --------------------------------------------------------------------------- stockage
def charger_quotidien(dossier):
    f = dossier / "temperatures_quotidiennes.csv"
    if not f.exists():
        return pd.DataFrame(columns=["point_id", "date", "tmoy", "source"])
    return pd.read_csv(f, dtype={"point_id": str})


def ajouter(dossier, lignes, source):
    if not lignes:
        return
    f = dossier / "temperatures_quotidiennes.csv"
    df = pd.DataFrame(lignes, columns=["point_id", "date", "tmoy"]).assign(source=source)
    df.to_csv(f, mode="a", header=not f.exists(), index=False)


def consolider(dossier):
    """Un seul enregistrement par point et par jour (l'archive l'emporte), trié."""
    q = charger_quotidien(dossier)
    if q.empty:
        return q
    q["priorite"] = (q.source != "archive").astype(int)
    q = (
        q.sort_values(["point_id", "date", "priorite"])
        .drop_duplicates(["point_id", "date"], keep="first")
        .drop(columns="priorite")
    )
    q.to_csv(dossier / "temperatures_quotidiennes.csv", index=False)
    return q


def mensuel(quotidien, base):
    q = quotidien.copy()
    q["mois"] = q.date.str[:7]
    q["dju"] = (base - q.tmoy).clip(lower=0)
    m = q.groupby(["point_id", "mois"]).agg(tmoy=("tmoy", "mean"), dju=("dju", "sum"), n_jours=("tmoy", "size")).reset_index()
    m["complet"] = m.n_jours == pd.PeriodIndex(m.mois, freq="M").days_in_month
    m[["tmoy", "dju"]] = m[["tmoy", "dju"]].round(2)
    return m


# --------------------------------------------------------------------------- programme
def lire_arguments(argv=None):
    p = argparse.ArgumentParser(description="Températures quotidiennes ERA5 (Open-Meteo) et degrés-jours mensuels")
    p.add_argument("--essai", action="store_true", help="2 appels de vérification, sans rien écrire")
    p.add_argument("--debut", default="2016-01-01", help="premier jour à télécharger (défaut : 2016-01-01)")
    p.add_argument("--fin", default=None, help="dernier jour à télécharger (défaut : il y a 7 jours, plus les derniers jours via l'API récente)")
    p.add_argument("--resolution", type=float, default=0.5, help="pas de la grille en degrés (défaut : 0,5)")
    p.add_argument("--lot", type=int, default=10, help="points par appel (défaut : 10)")
    p.add_argument("--pause", type=float, default=1.0, help="secondes entre deux appels (défaut : 1)")
    p.add_argument("--recouvrement", type=int, default=30, help="jours re-téléchargés avant le dernier jour connu")
    p.add_argument("--base", type=float, default=18.0, help="base des degrés-jours en °C (défaut : 18)")
    p.add_argument("--sans-recent", action="store_true", help="ne pas compléter avec les tout derniers jours")
    p.add_argument("--tous-les-points", action="store_true", help="inclure aussi les cellules inhabitées")
    p.add_argument("--dossier", default=str(DONNEES), help="dossier de sortie (défaut : electricite-quebec/donnees)")
    return p.parse_args(argv)


def essai():
    """Deux appels réels (archive et récent) pour Québec, sans rien écrire."""
    pt = pd.DataFrame({"point_id": ["essai"], "lat": [46.81], "lon": [-71.21]})
    print("1) Archive, janvier 2021, point de Québec …")
    lignes = telecharger_archive(pt, date(2021, 1, 1), date(2021, 1, 31))
    t = [x[2] for x in lignes]
    print(f"   {len(lignes)} jours reçus ; moyenne {np.mean(t):.1f} °C ; premiers jours : {t[:3]}")
    print("2) Derniers jours (API de prévision, past_days = 3) …")
    lignes = telecharger_recent(pt, 3)
    print(f"   {len(lignes)} jours reçus ; dates : {[x[1] for x in lignes]}")
    print("Tout fonctionne. Lance le script sans --essai pour le téléchargement complet.")


def main(argv=None):
    a = lire_arguments(argv)
    if a.essai:
        essai()
        return
    dossier = Path(a.dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    points, liens = construire_points(a.resolution, a.tous_les_points)
    points.to_csv(dossier / "points_temperature.csv", index=False)
    liens.to_csv(dossier / "municipalites_points.csv", index=False)
    print(f"{len(points)} points de grille ({a.resolution}°) pour {len(liens)} municipalités")

    aujourdhui = date.today()
    fin_archive = aujourdhui - timedelta(days=DELAI_ARCHIVE_JOURS)
    if a.fin:
        fin_archive = min(fin_archive, date.fromisoformat(a.fin))
    debut_global = date.fromisoformat(a.debut)
    quotidien = charger_quotidien(dossier)
    derniers = quotidien[quotidien.source == "archive"].groupby("point_id").date.max()

    # Point par point : début = dernier jour d'archive connu moins le recouvrement
    groupes = {}
    for r in points.itertuples():
        if r.point_id in derniers.index:
            debut = max(debut_global, date.fromisoformat(derniers[r.point_id]) - timedelta(days=a.recouvrement) + timedelta(days=1))
        else:
            debut = debut_global
        if debut <= fin_archive:
            groupes.setdefault(debut, []).append(r.point_id)

    taches = []  # (debut, fin, lot de points)
    for debut, ids in sorted(groupes.items()):
        courant = debut
        while courant <= fin_archive:
            fin = min(date(courant.year, 12, 31), fin_archive)
            for i in range(0, len(ids), a.lot):
                taches.append((courant, fin, ids[i : i + a.lot]))
            courant = fin + timedelta(days=1)

    arret = False
    try:
        for k, (debut, fin, ids) in enumerate(taches, 1):
            print(f"[{k}/{len(taches)}] archive {debut} -> {fin}, {len(ids)} points")
            lot = points[points.point_id.isin(ids)]
            ajouter(dossier, telecharger_archive(lot, debut, fin), "archive")
            time.sleep(a.pause)
        if not a.sans_recent and not a.fin and (aujourdhui - fin_archive).days > 1:
            jours = (aujourdhui - fin_archive).days
            ids_tous = list(points.point_id)
            for i in range(0, len(ids_tous), a.lot):
                lot = points[points.point_id.isin(ids_tous[i : i + a.lot])]
                print(f"[récent] {jours} derniers jours, points {i + 1} à {i + len(lot)}")
                lignes = [x for x in telecharger_recent(lot, jours) if fin_archive < date.fromisoformat(x[1]) < aujourdhui]
                ajouter(dossier, lignes, "recent")
                time.sleep(a.pause)
    except LimiteJournaliere as e:
        arret = True
        print(f"\nLimite quotidienne atteinte ({e}).\nRelance le script demain : il reprend où il s'est arrêté.")

    q = consolider(dossier)
    if q.empty:
        print("Aucune donnée téléchargée.")
        return
    m = mensuel(q, a.base)
    m.to_csv(dossier / "temperatures_mensuelles.csv", index=False)
    complets = m.groupby("point_id").complet.sum()
    print(f"\n{q.point_id.nunique()} points, du {q.date.min()} au {q.date.max()} ; {len(m)} mois-points écrits")
    print(f"Mois complets par point : min {int(complets.min())}, médiane {int(complets.median())}, max {int(complets.max())}")
    if arret:
        sys.exit(0)


if __name__ == "__main__":
    main()
