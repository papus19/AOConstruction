"""
courriel.py — Génération du courriel de soumission
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Responsabilités :
  - Génération du courriel d'envoi de soumission (IA)

Règle absolue : aucun import streamlit ici.
"""

import re
import json
from llm_manager import LLMManager

llm_manager = LLMManager()


def _parse_json(texte: str):
    """Parse un JSON depuis une réponse LLM."""
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


def generer_email_soumission(exigences: dict, offre_tech: dict, user: dict) -> dict:
    """
    Rédige un courriel de soumission professionnel et distinctif.

    Le courriel s'ouvre sur une référence spécifique au projet, démontre
    la compréhension du mandat, met en valeur 2-3 avantages concrets
    et cite une référence similaire réalisée.

    Args:
        exigences: Dict d'analyse (nom_projet, lieu, section, client,
                   contact_email, responsable, jours_ouvres).
        offre_tech: Mémoire technique généré (avantages_concurrentiels,
                    references_projets).
        user: Profil entreprise (nom_entreprise, licence_rbq,
              contact_nom, contact_telephone, contact_email).

    Returns:
        Dict avec clés : sujet, destinataire_nom, destinataire_email,
        corps, note_interne.
        Retourne un courriel générique si l'appel IA échoue (jamais None).
    """
    nom_projet    = exigences.get("nom_projet", "")
    lieu          = exigences.get("lieu", "")
    section       = exigences.get("section", "")
    jours         = exigences.get("jours_ouvres", "")
    client        = exigences.get("client", "")
    email_contact = exigences.get("contact_email", "")
    resp_contact  = exigences.get("responsable", "")

    avantages = offre_tech.get("avantages_concurrentiels", [])
    refs      = offre_tech.get("references_projets", [])
    avantages_txt = "\n".join(f"- {a}" for a in avantages[:4]) if avantages else ""
    refs_txt      = "\n".join(f"- {r}" for r in refs[:3])      if refs      else ""

    prompt = f"""
Tu es le directeur des opérations de {user.get('nom_entreprise', '')} (Licence RBQ {user.get('licence_rbq', '')}).
Tu rédiges le courriel de soumission officiel pour cet appel d'offres.

OBJECTIF : Rédiger un courriel PROFESSIONNEL et DISTINCTIF.

INFORMATIONS DU PROJET :
- Projet : {nom_projet}
- Lieu : {lieu}
- Section : {section}
- Durée : {jours} jours ouvrés
- Donneur d'ouvrage : {client}
- Contact : {resp_contact}

NOS POINTS FORTS :
{avantages_txt or "(à adapter selon le projet)"}

NOS RÉFÉRENCES SIMILAIRES :
{refs_txt or "(à adapter selon les projets antérieurs)"}

RÈGLES :
1. Ouvrir avec une référence SPÉCIFIQUE au projet
2. Démontrer la compréhension du mandat en 1-2 phrases précises
3. 2-3 avantages CONCRETS et MESURABLES
4. 1 référence similaire réalisée
5. Longueur : 200 à 280 mots
6. AUCUNE formule passe-partout

Réponds en JSON :
{{
  "sujet": "Objet précis et distinctif incluant le nom du projet",
  "destinataire_nom": "{resp_contact or 'Madame, Monsieur'}",
  "destinataire_email": "{email_contact}",
  "corps": "Corps complet du courriel — 200 à 280 mots",
  "note_interne": "Note pour l'expéditeur : point à vérifier avant envoi (optionnel)"
}}
"""
    res = llm_manager.analyze(prompt, max_tokens=1500)

    # Courriel générique de secours
    fallback = {
        "sujet": (
            f"Soumission — {nom_projet} | "
            f"{user.get('nom_entreprise','')} | "
            f"RBQ {user.get('licence_rbq','')}"
        ),
        "destinataire_nom":   resp_contact or "Madame, Monsieur",
        "destinataire_email": email_contact,
        "corps": (
            f"{resp_contact or 'Madame, Monsieur'},\n\n"
            f"Nous soumettons par la présente notre offre pour les travaux d'électricité "
            f"relatifs au projet «{nom_projet}», situé au {lieu}.\n\n"
            f"{user.get('nom_entreprise','')} (RBQ {user.get('licence_rbq','')}) réalise "
            f"ce type de travaux depuis plusieurs années dans le secteur institutionnel "
            f"au Québec.\n\n"
            f"Cordialement,\n{user.get('contact_nom','')}\n"
            f"{user.get('nom_entreprise','')}\n"
            f"{user.get('contact_telephone','')}"
        ),
        "note_interne": "",
    }

    if not res["success"]:
        return fallback

    data = _parse_json(res["result"])
    return data if data else fallback