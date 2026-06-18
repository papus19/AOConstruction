"""
chiffrage.py — Logique de chiffrage financier
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Responsabilités :
  - Chargement des projets de référence (Supabase)
  - Extraction des prix unitaires depuis projets antérieurs (IA)
  - Extraction des quantités depuis le texte AO (IA)
  - Calcul de la soumission (IA + recalcul Python)
  - Extraction et proposition de prix du bordereau

Règle absolue : aucun import streamlit ici.
Toutes les fonctions retournent des dict ou None.
"""

import json
import re
import database
from llm_manager import LLMManager

llm_manager = LLMManager()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNES
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json(texte: str):
    """Parse un JSON depuis une réponse LLM (gère les backticks markdown)."""
    if not texte:
        return None
    texte = re.sub(r"^```(?:json)?", "", texte.strip()).rstrip("` \n")
    try:
        return json.loads(texte)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", texte)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def _safe_float(val, default=0.0) -> float:
    """Conversion sécurisée en float."""
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# 1. CHARGEMENT DES PROJETS DE RÉFÉRENCE
# ─────────────────────────────────────────────────────────────────────────────

def charger_projets_reference(entreprise_id: str) -> list[dict]:
    """
    Charge les projets antérieurs avec leurs spécifications depuis Supabase.

    Args:
        entreprise_id: UUID de l'entreprise connectée.

    Returns:
        Liste de dicts projets, [] si erreur ou vide.
    """
    try:
        database.apply_supabase_auth()
        result = (
            database.supabase
            .table("projets_antecedents")
            .select("nom_projet, montant, duree_jours, statut, specifications, date_realisation")
            .eq("entreprise_id", entreprise_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        print(f"[chiffrage] Erreur chargement projets : {e}")
        return []


def _formater_references(projets: list[dict]) -> str:
    """
    Formate les projets en texte lisible pour les prompts IA.

    Args:
        projets: Liste de dicts projets de référence.

    Returns:
        Bloc texte formaté pour injection dans un prompt.
    """
    if not projets:
        return "Aucun projet de référence disponible."

    lignes = ["=== BANQUE DE PRIX — PROJETS RÉALISÉS ==="]
    for p in projets:
        lignes.append(
            f"\nProjet : {p['nom_projet']}\n"
            f"Montant total : {float(p.get('montant') or 0):,.0f} $ | "
            f"Durée : {p.get('duree_jours') or 0} jours ouvrés | "
            f"Statut : {p.get('statut', '')} | "
            f"Réalisé le : {p.get('date_realisation') or '—'}"
        )
        if p.get("specifications"):
            lignes.append(f"Détails / prix unitaires :\n{p['specifications']}")
        lignes.append("─" * 50)
    return "\n".join(lignes)


# ─────────────────────────────────────────────────────────────────────────────
# 2. EXTRACTION DES PRIX UNITAIRES (appel IA #1)
# ─────────────────────────────────────────────────────────────────────────────

def extraire_prix_unitaires(
    projets: list[dict],
    specialite: str,
    taux_horaire: float = 65.0
) -> dict | None:
    """
    Analyse les projets réalisés et extrait une banque de prix unitaires.

    Args:
        projets: Projets antérieurs avec leurs spécifications.
        specialite: Ex. "16200 - Électricité".
        taux_horaire: Taux MO à utiliser pour les calculs.

    Returns:
        Dict avec clés : specialite, taux_horaire_moyen, prix_unitaires[], notes.
        None si l'appel IA échoue.
    """
    refs = _formater_references(projets)
    prompt = f"""
Tu es un estimateur spécialisé en {specialite}.
Analyse ces projets réalisés et extrais une BANQUE DE PRIX UNITAIRES.
Le taux horaire à utiliser pour la main-d'œuvre est : {taux_horaire:.2f} $/h

{refs}

INSTRUCTIONS :
- Identifie chaque type de travail avec son prix unitaire RÉEL tiré des projets
- Si le prix unitaire n'est pas explicitement indiqué, calcule-le depuis le montant total et la durée
- Utilise TOUJOURS le taux horaire {taux_horaire:.2f} $/h pour estimer les coûts MO
- N'invente aucun prix — base-toi UNIQUEMENT sur les données ci-dessus
- Si une donnée est absente, indique null

Réponds UNIQUEMENT en JSON valide :
{{
  "specialite": "{specialite}",
  "taux_horaire_moyen": {taux_horaire},
  "prix_unitaires": [
    {{
      "code": "ELEC-001",
      "description": "ex: Pose conduit EMT 25mm",
      "unite": "ex: mètre linéaire",
      "heures_par_unite": 0.5,
      "materiel_par_unite": 15.00,
      "source_projet": "nom du projet de référence"
    }}
  ],
  "notes": "Observations générales sur les prix"
}}
"""
    res = llm_manager.analyze(prompt, max_tokens=2500)
    if not res["success"]:
        return None
    return _parse_json(res["result"])


# ─────────────────────────────────────────────────────────────────────────────
# 3. EXTRACTION DES QUANTITÉS DE L'AO (appel IA #2)
# ─────────────────────────────────────────────────────────────────────────────

def extraire_quantites_appel_offre(analyse: dict, texte_ao: str) -> dict | None:
    """
    Extrait toutes les quantités de travail depuis le texte de l'appel d'offre.

    Args:
        analyse: Dict d'analyse (nom_projet, section, lieu, jours_ouvres).
        texte_ao: Texte brut du document AO (max ~5000 chars utilisés).

    Returns:
        Dict avec clés : travaux[], conditions_particulieres[], exigences_specifiques[].
        None si l'appel IA échoue.
    """
    prompt = f"""
Tu es un estimateur qui lit un appel d'offres.
Extrais TOUTES les quantités de travail décrites.

APPEL D'OFFRE :
Projet : {analyse.get('nom_projet', '')}
Section : {analyse.get('section', '')}
Lieu : {analyse.get('lieu', '')}
Durée : {analyse.get('jours_ouvres', '')} jours

Contenu / description des travaux :
{texte_ao[:5000]}

INSTRUCTIONS :
- Liste chaque type de travail avec sa quantité et unité
- Si la quantité n'est pas précisée, indique "à confirmer" et estime selon le contexte
- Ne calcule pas les prix ici — seulement les quantités

Réponds UNIQUEMENT en JSON valide :
{{
  "travaux": [
    {{
      "description": "ex: Conduit EMT 25mm",
      "quantite": 100,
      "unite": "mètre linéaire",
      "notes": "selon plan électrique section 16200"
    }}
  ],
  "conditions_particulieres": [],
  "exigences_specifiques": []
}}
"""
    res = llm_manager.analyze(prompt, max_tokens=2000)
    if not res["success"]:
        return None
    return _parse_json(res["result"])


# ─────────────────────────────────────────────────────────────────────────────
# 4. CALCUL DE LA SOUMISSION (appel IA #3 + recalcul Python)
# ─────────────────────────────────────────────────────────────────────────────

def calculer_soumission(
    prix_unitaires: dict,
    quantites: dict,
    analyse: dict,
    user: dict,
) -> dict | None:
    """
    Calcule chaque poste budgétaire en multipliant quantité × prix unitaire.
    L'IA propose les correspondances, Python recalcule les totaux.

    Args:
        prix_unitaires: Résultat de extraire_prix_unitaires().
        quantites: Résultat de extraire_quantites_appel_offre().
        analyse: Dict d'analyse du projet.
        user: Profil de l'entreprise (nom_entreprise, licence_rbq).

    Returns:
        Dict avec postes[], sous-totaux, taxes, total_ttc.
        None si l'appel IA échoue.
    """
    taux_h   = prix_unitaires.get("taux_horaire_moyen", 65)
    pu_text  = json.dumps(prix_unitaires.get("prix_unitaires", []), ensure_ascii=False, indent=2)
    qte_text = json.dumps(quantites.get("travaux", []), ensure_ascii=False, indent=2)

    prompt = f"""
Tu es un estimateur spécialisé en {prix_unitaires.get('specialite', 'construction')}.
Tu travailles pour : {user.get('nom_entreprise', '')} | RBQ : {user.get('licence_rbq', '')}

TON RÔLE : Calculer chaque poste budgétaire en multipliant quantité × prix unitaire.

BANQUE DE PRIX UNITAIRES (tirée de tes projets réalisés) :
{pu_text}

QUANTITÉS DE L'APPEL D'OFFRE :
{qte_text}

RÈGLES DE CALCUL STRICTES :
1. Pour chaque travail, cherche le prix unitaire correspondant dans ta banque
2. Calcule : heures_total = heures_par_unite × quantite
3. Calcule : cout_main_oeuvre = heures_total × {taux_h}
4. Calcule : cout_materiel = materiel_par_unite × quantite
5. Calcule : total_poste = cout_main_oeuvre + cout_materiel
6. Si aucun prix unitaire correspondant → extrapole depuis le projet le plus similaire
7. Indique TOUJOURS la source (quel projet de référence)
8. JAMAIS de prix inventé sans source

Réponds UNIQUEMENT en JSON valide :
{{
  "postes": [
    {{
      "code": "ELEC-001",
      "description": "Pose conduit EMT 25mm",
      "quantite": 100,
      "unite": "mètre linéaire",
      "heures_par_unite": 0.5,
      "heures_total": 50,
      "taux_horaire": {taux_h},
      "cout_mo": 3250.00,
      "materiel_par_unite": 15.00,
      "cout_materiel": 1500.00,
      "total_poste": 4750.00,
      "source": "Projet École Émile-Legault 2024"
    }}
  ],
  "sous_total_mo": 0,
  "sous_total_materiel": 0,
  "sous_total_ht": 0,
  "contingence_pct": 10,
  "contingence": 0,
  "total_avant_taxes": 0,
  "tps": 0,
  "tvq": 0,
  "total_ttc": 0,
  "total_heures": 0,
  "taux_horaire": {taux_h},
  "notes_estimateur": "Observations importantes"
}}
"""
    res = llm_manager.analyze(prompt, max_tokens=3500)
    if not res["success"]:
        return None

    data = _parse_json(res["result"])
    if not data:
        return None

    # Recalcul Python — l'IA peut faire des erreurs arithmétiques
    postes = data.get("postes", [])
    for p in postes:
        hpu  = _safe_float(p.get("heures_par_unite"),  0)
        qte  = _safe_float(p.get("quantite"),          0)
        mpu  = _safe_float(p.get("materiel_par_unite"), 0)
        th   = _safe_float(p.get("taux_horaire"),       taux_h) or taux_h
        p["heures_total"]       = round(hpu * qte, 2)
        p["cout_mo"]            = round(p["heures_total"] * th, 2)
        p["cout_materiel"]      = round(mpu * qte, 2)
        p["total_poste"]        = round(p["cout_mo"] + p["cout_materiel"], 2)
        p["taux_horaire"]       = th
        p["heures_par_unite"]   = hpu
        p["materiel_par_unite"] = mpu
        p["quantite"]           = qte

    sous_mo  = sum(p["cout_mo"]       for p in postes)
    sous_mat = sum(p["cout_materiel"] for p in postes)
    sous_ht  = sous_mo + sous_mat
    conting  = sous_ht * (data.get("contingence_pct", 10) / 100)
    avant_tx = sous_ht + conting
    tps      = avant_tx * 0.05
    tvq      = avant_tx * 0.09975
    total    = avant_tx + tps + tvq
    heures   = sum(p["heures_total"] for p in postes)

    data.update({
        "postes":              postes,
        "sous_total_mo":       round(sous_mo,   2),
        "sous_total_materiel": round(sous_mat,  2),
        "sous_total_ht":       round(sous_ht,   2),
        "contingence":         round(conting,   2),
        "total_avant_taxes":   round(avant_tx,  2),
        "tps":                 round(tps,       2),
        "tvq":                 round(tvq,       2),
        "total_ttc":           round(total,     2),
        "total_heures":        round(heures,    2),
        "taux_horaire":        taux_h,
    })
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 5. EXTRACTION DU BORDEREAU AO
# ─────────────────────────────────────────────────────────────────────────────

def extraire_bordereau_ao(
    texte_ao: str,
    analyse: dict,
    projets_references: list[dict] | None = None
) -> dict | None:
    """
    Extrait la structure complète du bordereau depuis le texte AO.
    Tente de pré-remplir les prix depuis les projets de référence.

    Args:
        texte_ao: Texte brut du bordereau (max ~6000 chars utilisés).
        analyse: Dict d'analyse du projet.
        projets_references: Projets antérieurs pour auto-remplissage des prix.

    Returns:
        Dict avec sections[], nb_items_a_saisir, nb_items_auto, totaux.
        None si l'appel IA échoue.
    """
    refs_prix = ""
    if projets_references:
        refs_prix = "\n\nPROJETS ANTÉRIEURS — PRIX DE RÉFÉRENCE DISPONIBLES :\n"
        for p in projets_references:
            specs = p.get("specifications", "") or ""
            if specs:
                refs_prix += (
                    f"\nProjet : {p.get('nom_projet','')} | "
                    f"Montant total : {float(p.get('montant') or 0):,.0f} $\n"
                    f"{specs[:2000]}\n"
                )

    prompt = f"""
Tu es un estimateur professionnel en électricité du bâtiment au Québec.
Tu analyses un appel d'offres pour en extraire le bordereau de prix COMPLET.

RÈGLES STRICTES :
- Extrais CHAQUE ligne du bordereau/formulaire telle qu'elle apparaît dans le document
- Pour chaque item, cherche un prix correspondant dans les projets antérieurs fournis
- Si tu trouves un prix de référence → indique le prix ET la source
- Si aucun prix n'est disponible → laisse prix_unitaire à null et met a_saisir à true
- N'invente AUCUN prix

DOCUMENT AO :
{texte_ao[:6000]}

{refs_prix}

Réponds UNIQUEMENT en JSON valide :
{{
  "sections": [
    {{
      "titre": "SECTION A — TRAVAUX PRÉPARATOIRES",
      "items": [
        {{
          "no": "1",
          "description": "Description exacte du bordereau",
          "unite": "forfait",
          "quantite": 1,
          "prix_unitaire": 8200.00,
          "total": 8200.00,
          "source_prix": "Projet antérieur : École 2023",
          "a_saisir": false,
          "confiance": "haute"
        }}
      ]
    }}
  ],
  "nb_items_a_saisir": 0,
  "nb_items_auto": 0,
  "sous_total_ht": 0,
  "tps": 0,
  "tvq": 0,
  "total_ttc": 0,
  "notes": "Résumé de l'extraction"
}}
"""
    res = llm_manager.analyze(prompt, max_tokens=4000)
    if not res["success"]:
        return None

    data = _parse_json(res["result"])
    if not data:
        return None

    # Comptage auto des items à saisir vs auto-remplis
    nb_saisir = 0
    nb_auto   = 0
    for sec in data.get("sections", []):
        for it in sec.get("items", []):
            if it.get("a_saisir") or it.get("prix_unitaire") is None:
                it["a_saisir"] = True
                nb_saisir += 1
            else:
                it["a_saisir"] = False
                nb_auto += 1

    data["nb_items_a_saisir"] = nb_saisir
    data["nb_items_auto"]     = nb_auto
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 6. PROPOSITION DE PRIX POUR UN BORDEREAU EXISTANT
# ─────────────────────────────────────────────────────────────────────────────

def proposer_prix_bordereau(
    sections: list[dict],
    projets: list[dict],
    taux_h: float,
    analyse: dict,
    user: dict,
    texte_ao: str = "",
) -> dict:
    """
    Pour un bordereau déjà structuré, propose des prix unitaires depuis
    les projets antérieurs ou le taux horaire MO.

    Args:
        sections: Liste de sections du bordereau (format interne).
        projets: Projets antérieurs pour les références de prix.
        taux_h: Taux horaire MO retenu.
        analyse: Dict d'analyse du projet.
        user: Profil de l'entreprise.
        texte_ao: Texte AO optionnel pour contexte supplémentaire.

    Returns:
        Dict avec sections (prix mis à jour), nb_prix_trouves,
        nb_prix_manquants, items_sans_prix[].
    """
    # Construire la liste simplifiée des items pour le prompt
    items_all = []
    for sec in sections:
        for it in sec.get("items", []):
            items_all.append({
                "no":          it["no"],
                "description": it["description"],
                "section":     sec["titre"],
                "unite":       it.get("unite", "forfait"),
            })

    if not items_all:
        return {
            "sections":          sections,
            "nb_prix_trouves":   0,
            "nb_prix_manquants": 0,
            "items_sans_prix":   [],
        }

    # Résumé des projets antérieurs
    resume_projets = ""
    for p in (projets or []):
        specs = p.get("specifications") or p.get("texte_analyse") or ""
        if specs:
            resume_projets += (
                f"\n--- Projet : {p.get('nom_projet','')} "
                f"({float(p.get('montant') or 0):,.0f} $) ---\n"
                f"{str(specs)[:2000]}\n"
            )

    items_json = json.dumps(items_all, ensure_ascii=False, indent=2)

    prompt = f"""
Tu es un estimateur électricien québécois expérimenté.

TAUX HORAIRE MO RETENU : {taux_h:.2f} $/h

ITEMS DU BORDEREAU :
{items_json}

DONNÉES DES PROJETS ANTÉRIEURS :
{resume_projets[:6000] if resume_projets else "Aucun projet antérieur disponible."}

MISSION :
Pour chaque item, propose un prix unitaire en $ basé sur :
1. Les prix réels des projets antérieurs (priorité)
2. Le taux horaire MO × heures estimées + matériel (si pas de référence)
3. Si vraiment impossible → prix_unitaire = null

Réponds UNIQUEMENT en JSON valide :
{{
  "items": [
    {{
      "no": "1",
      "section": "TRAVAUX D'ARCHITECTURE",
      "prix_unitaire": 8200.00,
      "source_prix": "Projet École 2026",
      "confiance": "haute"
    }}
  ]
}}
"""
    res = llm_manager.analyze(prompt, max_tokens=3000)
    prix_ia = {}

    if res["success"]:
        parsed = _parse_json(res["result"])
        if parsed and "items" in parsed:
            for pi in parsed["items"]:
                key = f"{pi.get('section','')}|{pi.get('no','')}"
                prix_ia[key] = pi

    # Application des prix sur les sections
    items_sans_prix = []
    nb_ok = 0

    for sec in sections:
        for it in sec.get("items", []):
            key   = f"{sec['titre']}|{it['no']}"
            match = prix_ia.get(key)
            if match and match.get("prix_unitaire") is not None:
                it["prix_unitaire"] = float(match["prix_unitaire"])
                it["source_prix"]   = match.get("source_prix", "IA")
                it["confiance"]     = match.get("confiance", "moyenne")
                nb_ok += 1
            else:
                it["prix_unitaire"] = None
                it["source_prix"]   = None
                it["confiance"]     = "nulle"
                items_sans_prix.append({
                    "no":          it["no"],
                    "description": it["description"],
                    "section":     sec["titre"],
                    "raison":      (match or {}).get("raison", "Aucune référence trouvée"),
                })

    return {
        "sections":          sections,
        "nb_prix_trouves":   nb_ok,
        "nb_prix_manquants": len(items_sans_prix),
        "items_sans_prix":   items_sans_prix,
    }