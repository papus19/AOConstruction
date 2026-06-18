"""
offre_technique.py — Génération du contenu textuel de l'offre
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Responsabilités :
  - Génération du mémoire technique (IA)
  - Validation de conformité de l'offre (IA)

Règle absolue : aucun import streamlit ici.
Toutes les fonctions retournent des dict ou None.
"""

import json
import re
from llm_manager import LLMManager

llm_manager = LLMManager()


# ─────────────────────────────────────────────────────────────────────────────
# HELPER
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


# ─────────────────────────────────────────────────────────────────────────────
# 1. GÉNÉRATION DU MÉMOIRE TECHNIQUE
# ─────────────────────────────────────────────────────────────────────────────

def generer_offre_technique(
    analyse: dict,
    soumission: dict,
    prix_unitaires: dict,
    user: dict,
    projets_choisis: list[dict] | None = None,
    texte_ao: str = "",
) -> dict | None:
    """
    Rédige le mémoire technique officiel de la soumission.

    Toutes les informations sont tirées du document AO et des projets
    antérieurs fournis — aucune invention de faits.

    Args:
        analyse: Dict d'analyse du projet (nom, lieu, section, jours_ouvres).
        soumission: Résultat de calculer_soumission() avec les postes chiffrés.
        prix_unitaires: Banque de prix avec la spécialité.
        user: Profil entreprise (nom_entreprise, licence_rbq, contact_nom).
        projets_choisis: Projets antérieurs similaires à valoriser.
        texte_ao: Texte complet du document AO pour contextualisation.

    Returns:
        Dict structuré du mémoire technique.
        None si l'appel IA échoue.
    """
    specialite = prix_unitaires.get("specialite", "électricité")

    postes_txt = "\n".join(
        f"- {p['description']} : {p.get('quantite',0)} {p.get('unite','')} "
        f"({p.get('heures_total',0)}h MO + {p.get('cout_materiel',0):,.0f}$ mat.) "
        f"→ {p.get('total_poste',0):,.0f}$"
        for p in soumission.get("postes", [])
    )

    refs_valorisees = ""
    if projets_choisis:
        refs_valorisees = "\n\nPROJETS ANTÉRIEURS SIMILAIRES À VALORISER :\n"
        for p in projets_choisis:
            refs_valorisees += (
                f"- {p.get('nom_projet', '')} : {float(p.get('montant') or 0):,.0f} $ "
                f"({p.get('duree_jours', '')} jours)\n"
            )
            if p.get("specifications"):
                refs_valorisees += f"  Détails : {str(p['specifications'])[:300]}\n"

    ao_context = ""
    if texte_ao and texte_ao.strip():
        ao_context = f"\nDOCUMENT APPEL D'OFFRE COMPLET (source de vérité) :\n{texte_ao[:7000]}"

    prompt = f"""
Tu es à la fois :
  • ESTIMATEUR PROFESSIONNEL senior de {user.get('nom_entreprise', '')} (Licence RBQ {user.get('licence_rbq', '')})
  • COMPTABLE INTERNE qui vérifie chaque chiffre avant de le soumettre
  • RÉDACTEUR TECHNIQUE spécialiste {specialite} au Québec

RÈGLES ABSOLUES — ZÉRO HALLUCINATION :
- Chaque fait doit provenir du DOCUMENT AO ou des PROJETS ANTÉRIEURS fournis
- Si une information n'est pas dans ces sources → indique «À confirmer avec le client»
- Toutes les normes citées doivent être réelles et applicables au Québec
- Langue : français professionnel canadien québécois

════════════════════════════════════════
CONTEXTE DU PROJET (source : document AO)
════════════════════════════════════════
Projet  : {analyse.get('nom_projet', '')}
Lieu    : {analyse.get('lieu', '')}
Section : {analyse.get('section', '')}
Durée   : {analyse.get('jours_ouvres', '')} jours ouvrés
{ao_context}

════════════════════════════════════════
CHIFFRAGE RETENU (source : estimateur interne)
════════════════════════════════════════
{postes_txt}
{refs_valorisees}

Réponds UNIQUEMENT en JSON valide :
{{
  "titre": "Mémoire technique — {analyse.get('nom_projet', '')}",
  "titre_offre": "Offre de services — {analyse.get('nom_projet', '')}",
  "introduction": "Présentation ciblée sur CE projet",
  "comprehension_projet": "Résumé précis des travaux demandés dans l'AO",
  "comprehension_mandat": "Résumé précis des travaux demandés dans l'AO",
  "contraintes_chantier": ["Contrainte 1 tirée de l'AO"],
  "approche_methodologique": {{
    "description": "Vue d'ensemble de la méthode",
    "phases": [
      {{
        "nom": "Phase 1 — Préparation et coordination",
        "phase": "Phase 1 — Préparation et coordination",
        "description": "Actions concrètes tirées du chiffrage",
        "duree": "X jours"
      }}
    ]
  }},
  "methodologie": [
    {{
      "phase": "Phase 1",
      "description": "Description détaillée",
      "duree": "X jours"
    }}
  ],
  "postes_techniques": [
    {{
      "titre": "Nom exact du poste",
      "approche": "Méthode d'exécution spécifique",
      "normes_applicables": ["CSA C22.1-21", "CCÉ art.10"]
    }}
  ],
  "equipe_proposee": [
    {{
      "role": "Chargé de projet",
      "nom": "{user.get('contact_nom', '')}",
      "experience": "Maître électricien — Licence RBQ {user.get('licence_rbq', '')}",
      "responsabilites": ["Coordination des travaux", "Respect des délais et des normes"]
    }}
  ],
  "equipe": [
    {{
      "role": "Chargé de projet",
      "nom": "{user.get('contact_nom', '')}",
      "qualification": "Maître électricien — Licence RBQ {user.get('licence_rbq', '')}"
    }}
  ],
  "livrables": [
    {{
      "nom": "Plans as-built",
      "description": "Plans électriques finaux signés",
      "format": "PDF + DWG AutoCAD 2022"
    }}
  ],
  "normes_applicables": ["CSA C22.1-21 — Code canadien de l'électricité"],
  "garanties_qualite": ["Garantie main-d'œuvre et matériaux : 2 ans"],
  "garanties": ["Garantie main-d'œuvre et matériaux : 2 ans"],
  "references_projets": ["Projet similaire réalisé : NOM — montant $"],
  "avantages_concurrentiels": ["Avantage 1 concret"],
  "calendrier_execution": "Description du calendrier proposé",
  "conclusion": "Engagement ferme de l'entreprise pour CE projet"
}}
"""
    res = llm_manager.analyze(prompt, max_tokens=4000)
    if not res["success"]:
        return None
    return _parse_json(res["result"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. VALIDATION DE CONFORMITÉ
# ─────────────────────────────────────────────────────────────────────────────

def valider_conformite_offre(offre_complete: dict, exigences: dict) -> dict:
    """
    Compare point par point la soumission préparée avec le bordereau officiel AO.

    Args:
        offre_complete: Dict contenant offre_technique et offre_financiere.
        exigences: Dict d'analyse (structure_bordereau, nom_projet, etc.).

    Returns:
        Dict avec score_conformite, points_conformes[], points_manquants[],
        items_manquants[], recommandations[], pret_a_envoyer, raison_blocage.
        Retourne un dict d'erreur si l'appel IA échoue (jamais None).
    """
    bordereau_ao         = exigences.get("structure_bordereau", {}) or {}
    bordereau_ao_sections = bordereau_ao.get("categories", []) or []
    soum_financiere       = offre_complete.get("offre_financiere", {})
    soum_sections         = soum_financiere.get("sections", []) or soum_financiere.get("postes", [])

    # Formatage du bordereau officiel
    items_ao_txt = ""
    if bordereau_ao_sections:
        for cat in bordereau_ao_sections:
            items_ao_txt += f"\nSection : {cat.get('nom', '')}\n"
            for it in cat.get("items", []):
                items_ao_txt += (
                    f"  [{it.get('numero','')}] {it.get('description','')} "
                    f"— type: {it.get('type','')}\n"
                )
    else:
        items_ao_txt = "(Structure bordereau non extraite — analyse sur texte AO)"

    # Formatage de la soumission préparée
    items_soum_txt = ""
    for sec in soum_sections:
        items_soum_txt += f"\nSection soumission : {sec.get('titre', sec.get('description',''))}\n"
        for it in sec.get("items", sec.get("postes", [])):
            pu = it.get("prix_unitaire") or it.get("cout_unitaire") or it.get("total_poste")
            items_soum_txt += (
                f"  [{it.get('no', it.get('numero',''))}] "
                f"{it.get('description','')} → {pu or 'PRIX MANQUANT'}\n"
            )

    prompt = f"""
Tu es un vérificateur de conformité des soumissions en électricité du bâtiment au Québec.

MISSION : Comparer point par point la soumission préparée avec le bordereau officiel de l'AO.

BORDEREAU OFFICIEL DE L'AO :
{items_ao_txt[:3000]}

SOUMISSION PRÉPARÉE :
{items_soum_txt[:2000]}

OFFRE TECHNIQUE :
{json.dumps(offre_complete.get('offre_technique', {}), ensure_ascii=False)[:1500]}

EXIGENCES GÉNÉRALES :
{json.dumps(exigences, ensure_ascii=False)[:1500]}

Réponds UNIQUEMENT en JSON valide :
{{
  "score_conformite": 85,
  "items_ao_total": 12,
  "items_couverts": 10,
  "items_manquants": [
    {{
      "no": "3",
      "description": "Description exacte du bordereau AO",
      "probleme": "Prix non saisi — à compléter avant envoi",
      "priorite": "critique"
    }}
  ],
  "points_conformes": ["✅ Description conforme 1"],
  "points_manquants": ["⚠️ Item 3 : Prix manquant"],
  "recommandations": ["💡 Recommandation concrète 1"],
  "pret_a_envoyer": false,
  "raison_blocage": "2 items sans prix dans le bordereau"
}}
"""
    res = llm_manager.analyze(prompt, max_tokens=2000)

    # Valeur de retour par défaut si l'IA échoue — jamais None
    fallback = {
        "score_conformite":  0,
        "points_conformes":  [],
        "points_manquants":  ["Validation impossible — LLM indisponible"],
        "recommandations":   [],
        "pret_a_envoyer":    False,
        "raison_blocage":    "Erreur LLM",
    }

    if not res["success"]:
        return fallback

    data = _parse_json(res["result"])
    return data if data else fallback