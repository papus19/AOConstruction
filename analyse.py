"""
Analyse des appels d'offres
v4.2 — Modifications :
  - Sauvegarde du provider LLM réellement utilisé dans st.session_state["llm_dernier_provider"]
    après chaque étape → affiché dynamiquement dans la sidebar de app_modular.py
"""
import streamlit as st
from datetime import datetime, timedelta
import re
import json
import database
from llm_manager import LLMManager


# ─────────────────────────────────────────────────────────────────────────────
# UTILITAIRE DATES — JOURS OUVRABLES
# ─────────────────────────────────────────────────────────────────────────────

def _jours_ouvrables_depuis_auj(date_cible_str: str) -> int | None:
    formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d",
               "%d %B %Y", "%d %b %Y", "%B %d, %Y"]
    cible = None
    for fmt in formats:
        try:
            cible = datetime.strptime(date_cible_str.strip(), fmt)
            break
        except Exception:
            pass
    if cible is None:
        return None

    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    cible = cible.replace(hour=0, minute=0, second=0, microsecond=0)

    if cible <= today:
        return 0

    jours = 0
    courant = today
    while courant < cible:
        courant += timedelta(days=1)
        if courant.weekday() < 5:
            jours += 1
    return jours


def _verifier_dates_ao(texte_ao: str, today_str: str) -> dict:
    alertes = []
    details = {}

    patterns_cloture = [
        r"cl[ôo]ture[^\n]*?(\d{4}[/-]\d{2}[/-]\d{2})",
        r"cl[ôo]ture[^\n]*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"fermeture[^\n]*(\d{4}[/-]\d{2}[/-]\d{2})",
        r"fermeture[^\n]*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"date[^\n]*soumission[^\n]*(\d{4}[/-]\d{2}[/-]\d{2})",
        r"(\d{4}[/-]\d{2}[/-]\d{2}).*?(?:11:00|h\s*00)",
    ]
    patterns_visite = [
        r"visite[^\n]*(\d{4}[/-]\d{2}[/-]\d{2})",
        r"visite[^\n]*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        r"(\d{4}[/-]\d{2}[/-]\d{2}).*?visite",
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}).*?visite",
    ]

    date_cloture = None
    date_visite  = None

    for pat in patterns_cloture:
        m = re.search(pat, texte_ao, re.IGNORECASE)
        if m:
            date_cloture = m.group(1)
            break

    for pat in patterns_visite:
        m = re.search(pat, texte_ao, re.IGNORECASE)
        if m:
            date_visite = m.group(1)
            break

    if date_cloture:
        jo_cloture = _jours_ouvrables_depuis_auj(date_cloture)
        details["date_cloture"] = date_cloture
        details["jo_cloture"]   = jo_cloture
        if jo_cloture is not None:
            if jo_cloture < 5:
                alertes.append(
                    f"🔴 ALERTE CRITIQUE — Clôture le {date_cloture} : "
                    f"seulement {jo_cloture} jour(s) ouvrable(s) depuis aujourd'hui. "
                    f"MINIMUM REQUIS : 5 jours ouvrables. → IMPACT NÉGATIF FORT sur le score."
                )
            else:
                alertes.append(
                    f"✅ Clôture le {date_cloture} : {jo_cloture} jour(s) ouvrable(s) disponibles."
                )

    if date_visite:
        jo_visite = _jours_ouvrables_depuis_auj(date_visite)
        details["date_visite"] = date_visite
        details["jo_visite"]   = jo_visite
        if jo_visite is not None:
            if jo_visite < 5:
                alertes.append(
                    f"🔴 ALERTE — Visite le {date_visite} : "
                    f"seulement {jo_visite} jour(s) ouvrable(s) depuis aujourd'hui. "
                    f"MINIMUM REQUIS : 5 jours ouvrables. → POINT FAIBLE."
                )
            else:
                alertes.append(
                    f"✅ Visite le {date_visite} : {jo_visite} jour(s) ouvrable(s) disponibles."
                )

    return {
        "alertes":      alertes,
        "details":      details,
        "alerte_texte": "\n".join(alertes) if alertes else "Aucune date clé détectée automatiquement.",
    }

from extracteur import (
    extraire_texte_multiple,
    feedback_fichiers,
    LABEL_UPLOAD,
    HELP_UPLOAD,
    TYPES_ACCEPTES,
)

try:
    from donnees_test import get_fichiers_test
    _DONNEES_TEST_DISPO = True
except ImportError:
    _DONNEES_TEST_DISPO = False

llm_manager = LLMManager()

_DROP_CSS = """
<style>
[data-testid='stFileUploader'] {
    border: 2px dashed #2E75B6 !important;
    border-radius: 12px !important;
    background: #D5E8F0 !important;
    padding: 24px !important;
    transition: border-color 0.2s, background 0.2s;
}
[data-testid='stFileUploader']:hover {
    border-color: #1E3A5F !important;
    background: #BDD7EE !important;
}
</style>
"""


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — sauvegarde le provider dans session_state
# ─────────────────────────────────────────────────────────────────────────────

def _noter_provider(res: dict) -> None:
    """
    Après chaque appel llm_manager.analyze(), appelle cette fonction.
    Elle écrit le nom du provider ayant répondu dans st.session_state
    afin que la sidebar de app_modular.py puisse l'afficher dynamiquement.
    """
    provider = res.get("provider") or llm_manager.provider_actif()
    if provider:
        st.session_state["llm_dernier_provider"] = provider


# ─────────────────────────────────────────────────────────────────────────────
# CHARGEMENT DES PROJETS AVEC LEURS DOCUMENTS
# ─────────────────────────────────────────────────────────────────────────────

def _charger_projets_avec_documents(entreprise_id: str) -> list:
    try:
        database.apply_supabase_auth()
        result = (
            database.supabase
            .table("projets_antecedents")
            .select("*, projet_documents(*)")
            .eq("entreprise_id", entreprise_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        st.warning(f"⚠️ Projets non chargés : {e}")
        return []


def _construire_contexte_projets(projets: list) -> str:
    if not projets:
        return "Aucun projet de référence fourni."
    lignes = []
    for p in projets:
        docs     = p.get("projet_documents") or []
        noms_doc = ", ".join(d.get("nom_fichier", "") for d in docs) if docs else "aucun document"
        lignes.append(
            f"- {p.get('nom_projet', 'Sans nom')} "
            f"({float(p.get('montant') or 0):,.0f} $, "
            f"{p.get('duree_jours') or 0} jours, "
            f"statut: {p.get('statut', 'inconnu')}, réalisé: {p.get('date_realisation') or '—'})"
            f"\n  Specs: {p.get('specifications') or 'N/A'}"
            f"\n  Documents: {noms_doc}"
        )
    return "\n".join(lignes)


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION STRUCTURE DU BORDEREAU
# ─────────────────────────────────────────────────────────────────────────────

def _extraire_structure_bordereau(texte: str) -> dict | None:
    prompt = f"""
Tu es un analyste de documents de construction au Québec.
Analyse ce texte et extrait la structure EXACTE du bordereau de prix.

TEXTE DU DOCUMENT :
{texte[:8000]}

INSTRUCTIONS :
- Identifie TOUTES les catégories de travaux (ex: TRAVAUX D'ARCHITECTURE, TRAVAUX ÉLECTRIQUE, etc.)
- Pour chaque catégorie, liste TOUS les items avec leur numéro et description EXACTE
- Reproduis les descriptions mot pour mot depuis le document
- Identifie les sous-totaux et totaux
- Si un item a une description longue sur plusieurs lignes, inclus-la complète
- Détecte le numéro d'appel d'offres, le nom du projet, le client

Réponds UNIQUEMENT en JSON valide, aucun texte avant ou après :
{{
  "numero_ao": "",
  "nom_projet": "",
  "client": "",
  "lieu": "",
  "note_instructions": "",
  "categories": [
    {{
      "nom": "TRAVAUX D'ARCHITECTURE",
      "items": [
        {{
          "numero": 1,
          "description": "Description exacte du document",
          "type": "forfaitaire"
        }}
      ],
      "sous_total_label": "Sous-total pour les Architecture"
    }}
  ],
  "items_hors_categorie": [
    {{
      "numero": 25,
      "description": "Cautionnements et assurances",
      "type": "forfaitaire"
    }}
  ],
  "total_label": "TOTAL DE LA SOUMISSION (avant taxes)",
  "champs_identification": ["Nom de l'entreprise du soumissionnaire", "Numéro d'entreprise au Québec", "Adresse électronique", "Nom de la personne autorisée", "Fonction", "No de téléphone", "Signature", "DATE"]
}}
"""
    res = llm_manager.analyze(prompt, max_tokens=3000)
    # ── Sauvegarde du provider même dans les fonctions utilitaires ──
    if res["success"] and res.get("provider"):
        llm_manager._dernier_actif = res["provider"]

    if not res["success"]:
        return None

    texte_res = res["result"]
    texte_res = re.sub(r"^```(?:json)?", "", texte_res.strip()).rstrip("` \n")
    try:
        return json.loads(texte_res)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", texte_res)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def _extraire_sections_devis(texte: str) -> dict | None:
    prompt = f"""
Tu es un ingénieur électricien au Québec. Analyse ce devis technique.

TEXTE DU DEVIS :
{texte[:10000]}

Extrais les informations structurées suivantes :

Réponds UNIQUEMENT en JSON valide :
{{
  "sections_techniques": [
    {{
      "numero_section": "26 05 00",
      "titre": "Électricité – Exigences générales",
      "nb_pages": 34,
      "resume": "2-3 phrases résumant l'essentiel"
    }}
  ],
  "normes_applicables": ["CAN/ULC-S524", "CAN/ULC-S536", "CAN/ULC-S537", "CAN/ULC-S1001"],
  "qualifications_requises": [
    {{
      "qualification": "Technicien certifié ACAI",
      "obligatoire": true,
      "pour": "Vérification ULC-S537",
      "note": "Doit être INDÉPENDANT de l'installateur"
    }}
  ],
  "contraintes_operationnelles": [
    "Bâtiment occupé — coordination PCIS obligatoire",
    "Travaux de nuit possibles sans supplément"
  ],
  "materiaux_specifiques": [
    {{
      "description": "Panneau principal d'alarme incendie encastré",
      "marque_ou_standard": "ULC certifié",
      "section_reference": "28 31 00"
    }}
  ],
  "presence_amiante_plomb": true,
  "type_batiment": "Hôpital en opération",
  "organisme_public": true
}}
"""
    res = llm_manager.analyze(prompt, max_tokens=2000)
    # ── Sauvegarde du provider ──
    if res["success"] and res.get("provider"):
        llm_manager._dernier_actif = res["provider"]

    if not res["success"]:
        return None

    texte_res = res["result"]
    texte_res = re.sub(r"^```(?:json)?", "", texte_res.strip()).rstrip("` \n")
    try:
        return json.loads(texte_res)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", texte_res)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION DE CHAMPS STRUCTURÉS
# ─────────────────────────────────────────────────────────────────────────────

def _extraire_liste(texte: str, marqueur: str) -> str:
    pattern = rf"{marqueur}.*?\n(.*?)(?=\n#{1,3} |\Z)"
    match   = re.search(pattern, texte, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extraire_champ(texte: str, *patterns) -> str:
    for pat in patterns:
        m = re.search(pat, texte, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _parser_analyse_structuree(result: str, nom_projet: str,
                                numero_projet: str, rec: str,
                                score: int, text_brut: str,
                                structure_bordereau: dict | None = None,
                                sections_devis: dict | None = None) -> dict:
    nom_extrait = _extraire_champ(result,
        r"(?:projet|contrat|objet)\s*[:\-]\s*(.+?)[\n\r]",
        r"(?:travaux de|réalisation de)\s+(.+?)[\n\r]",
    )
    client = _extraire_champ(result,
        r"(?:client|donneur d.ouvrage|maître d.ouvrage)\s*[:\-]\s*(.+?)[\n\r]",
        r"(?:pour|commandité par)\s+(.+?)[\n\r]",
    )
    lieu = _extraire_champ(result,
        r"(?:lieu|adresse|emplacement|site)\s*[:\-]\s*(.+?)[\n\r]",
        r"(?:situé à|located at)\s+(.+?)[\n\r]",
    )
    section = _extraire_champ(result,
        r"(?:section|division|lot)\s*[:\-]?\s*(\d{4,5}[^\n\r]*)",
        r"(\d{4,5}\s*[-–]\s*[A-ZÀ-Ü][^\n\r]{3,40})",
    )
    jours_str = _extraire_champ(result,
        r"(\d+)\s*jours?\s*ouvrés?",
        r"(\d+)\s*jours?\s*(?:de travail|calendrier)",
    )
    jours_ouvres = int(jours_str) if jours_str.isdigit() else 0

    if structure_bordereau:
        client  = structure_bordereau.get("client")  or client
        lieu    = structure_bordereau.get("lieu")    or lieu
        section = section or ""

    return {
        "nom_projet":    nom_projet or (structure_bordereau or {}).get("nom_projet") or nom_extrait or "Projet sans nom",
        "numero_projet": numero_projet or (structure_bordereau or {}).get("numero_ao") or "",
        "client":        client,
        "lieu":          lieu,
        "section":       section,
        "jours_ouvres":  jours_ouvres,
        "recommendation": rec,
        "score":          score,
        "points_forts":   _extraire_liste(result, r"POINTS FORTS[^#]*"),
        "points_faibles": _extraire_liste(result, r"POINTS FAIBLES[^#]*"),
        "actions":        _extraire_liste(result, r"ACTIONS PRIORITAIRES[^#]*"),
        "result_text":    result,
        "structure_bordereau": structure_bordereau,
        "sections_devis":      sections_devis,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SAUVEGARDE
# ─────────────────────────────────────────────────────────────────────────────

def _sauvegarder_soumission(user, result, rec, score,
                             nom_projet, numero_projet, uploaded_files):
    try:
        soumission_data = {
            "numero_projet":        numero_projet,
            "nom_projet":           nom_projet,
            "document":             uploaded_files[0] if len(uploaded_files) == 1 else None,
            "analyse_json":         {"raw_response": result},
            "recommendation":       rec,
            "score":                score,
            "statut":               "qualifie" if rec == "GO" else "non_qualifie",
            "points_forts":         _extraire_liste(result, r"POINTS FORTS[^#]*"),
            "points_faibles":       _extraire_liste(result, r"POINTS FAIBLES[^#]*"),
            "actions_recommandees": _extraire_liste(result, r"ACTIONS PRIORITAIRES[^#]*"),
        }
        soumission = database.save_soumission(user["id"], soumission_data)
        if isinstance(soumission, dict):
            return soumission.get("id")
        return "ok" if soumission else None
    except Exception as e:
        st.warning(f"⚠️ Sauvegarde soumission : {e}")
        return None


def _sauvegarder_analyse(user, result, rec, score,
                          nom_projet, numero_projet,
                          nb_fichiers, soumission_id=None):
    try:
        database.apply_supabase_auth()
        payload = {
            "entreprise_id":    user.get("id"),
            "entreprise_email": user.get("contact_email", ""),
            "file_name":        f"{numero_projet} — {nom_projet} ({nb_fichiers} fichier(s))",
            "recommendation":   rec,
            "score":            score,
            "result_text":      result,
        }
        if soumission_id and soumission_id != "ok":
            payload["soumission_id"] = soumission_id
        database.supabase.table("analyses").insert(payload).execute()
        return True
    except Exception as e:
        st.warning(f"⚠️ Sauvegarde analyses : {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# ONGLET PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def show_analyse_tab(user, projets_antecedents=None):
    st.header("🔍 Lancer une préqualification")
    st.markdown(_DROP_CSS, unsafe_allow_html=True)

    entreprise_id = str(user["id"])
    projets = _charger_projets_avec_documents(entreprise_id)
    if not projets and projets_antecedents:
        projets = projets_antecedents

    _fichiers_test, _nom_test, _numero_test = (
        get_fichiers_test() if _DONNEES_TEST_DISPO else (None, "", "")
    )
    if _fichiers_test:
        st.success(
            f"🧪 **AO de test chargé automatiquement** — {_fichiers_test[0].name}  \n"
            "Vérifiez les champs ci-dessous et cliquez sur **Lancer l'analyse**."
        )

    st.markdown("##### 📂 Documents de l'appel d'offres")
    uploaded_files = st.file_uploader(
        label=LABEL_UPLOAD,
        type=TYPES_ACCEPTES,
        accept_multiple_files=True,
        key="analyse_docs",
        help=HELP_UPLOAD,
    )
    feedback_fichiers(uploaded_files)

    if not uploaded_files and _fichiers_test:
        uploaded_files = _fichiers_test
        st.caption(f"📎 Fichier de test actif : **{_fichiers_test[0].name}**")

    nb_projets = len(projets)
    if nb_projets:
        nb_docs_total = sum(len(p.get("projet_documents") or []) for p in projets)
        st.info(
            f"📚 **{nb_projets} projet(s) de référence** disponible(s) "
            f"({nb_docs_total} document(s)) — l'IA s'en servira pour enrichir l'analyse."
        )
    else:
        st.caption("_Aucun projet de référence — ajoutez-en dans la section Projets._")

    if st.session_state.get("analyse_result"):
        nom_dispo = st.session_state["analyse_result"].get("nom_projet", "")
        st.success(
            f"✅ Analyse disponible pour le générateur : **{nom_dispo}**  \n"
            "Rendez-vous dans l'onglet **📝 Générateur d'Offres**."
        )

    st.markdown("---")

    with st.form("analyse_form"):
        numero_projet = st.text_input(
            "🔢 Numéro du projet",
            value=_numero_test or "",
        )
        nom_projet = st.text_input(
            "📋 Nom du projet",
            value=_nom_test or "",
        )
        submit = st.form_submit_button("🚀 Lancer l'analyse", use_container_width=False)

    if not submit:
        return
    if not uploaded_files:
        st.error("❌ Veuillez déposer au moins un document")
        return
    if not nom_projet:
        st.error("❌ Le nom du projet est obligatoire")
        return

    with st.spinner("🤖 Extraction et analyse IA en cours…"):
        try:
            text = extraire_texte_multiple(uploaded_files)
            if not text.strip():
                st.error("❌ Aucun texte extrait des documents fournis")
                return

            today_str       = datetime.today().strftime("%Y-%m-%d")
            projets_context = _construire_contexte_projets(projets)

            # ── Étape 1 : Extraction structure bordereau ──────────────
            structure_bordereau = None
            sections_devis      = None

            with st.status("**Étape 1/4** — Extraction de la structure des documents…") as s_pre:
                structure_bordereau = _extraire_structure_bordereau(text)
                sections_devis      = _extraire_sections_devis(text)
                nb_items = sum(
                    len(c.get("items", []))
                    for c in (structure_bordereau or {}).get("categories", [])
                ) + len((structure_bordereau or {}).get("items_hors_categorie", []))
                nb_sections = len((sections_devis or {}).get("sections_techniques", []))
                # ── Afficher le provider utilisé à l'étape 1 ──
                provider_etape1 = llm_manager.provider_actif()
                st.session_state["llm_dernier_provider"] = provider_etape1
                s_pre.update(
                    label=(
                        f"✅ Étape 1 — {nb_items} items bordereau, {nb_sections} sections devis"
                        f" · {provider_etape1}"
                    ),
                    state="complete"
                )

            # ── Étape 2 : Validation des dates (Python — pas d'IA) ────
            with st.status("**Étape 2/4** — Validation des dates clés…") as s_dates:
                validation_dates = _verifier_dates_ao(text, today_str)
                nb_alertes = len(validation_dates["alertes"])
                s_dates.update(
                    label=f"✅ Étape 2 — {nb_alertes} alerte(s) de dates · (calcul Python, pas d'IA)",
                    state="complete"
                )

            # ── Étape 3 : Prompt 1 — Analyste AO ─────────────────────
            contexte_bordereau = ""
            if structure_bordereau:
                cats = structure_bordereau.get("categories", [])
                hors = structure_bordereau.get("items_hors_categorie", [])
                lignes_b = [f"BORDEREAU DÉTECTÉ — {nb_items} items :"]
                for cat in cats:
                    lignes_b.append(f"\n  [{cat['nom']}]")
                    for it in cat.get("items", []):
                        lignes_b.append(f"    Item {it['numero']} : {it['description'][:80]}")
                for it in hors:
                    lignes_b.append(f"    Item {it['numero']} : {it['description'][:80]}")
                contexte_bordereau = "\n".join(lignes_b)

            contexte_devis = ""
            if sections_devis:
                normes = ", ".join(sections_devis.get("normes_applicables", []))
                quals  = "; ".join(
                    f"{q['qualification']} ({'OBLIGATOIRE' if q.get('obligatoire') else 'souhaité'})"
                    for q in sections_devis.get("qualifications_requises", [])
                )
                contraintes = "\n  - ".join(sections_devis.get("contraintes_operationnelles", []))
                contexte_devis = (
                    f"DEVIS TECHNIQUE :\n"
                    f"  Normes : {normes}\n"
                    f"  Qualifications : {quals}\n"
                    f"  Contraintes : {contraintes}\n"
                    f"  Amiante/plomb : {'OUI' if sections_devis.get('presence_amiante_plomb') else 'NON'}\n"
                    f"  Type bâtiment : {sections_devis.get('type_batiment', '')}"
                )

            prompt_analyste = f"""
Tu es un analyste spécialisé en appels d'offres de construction au Québec.
Tu travailles pour {user.get('nom_entreprise', 'cette entreprise')} comme employé senior.
Tu te comportes comme un expert en {', '.join(user.get('specialites', ['construction'])) if user.get('specialites') else 'construction'}.

MISSION : Analyser le document AO et produire un SOMMAIRE FACTUEL complet.
RÈGLE ABSOLUE : Tu te bases UNIQUEMENT sur les documents fournis. Zéro invention, zéro hallucination.

DOCUMENT AO (texte brut) :
{text[:5000]}

STRUCTURE DÉTECTÉE :
{contexte_bordereau}
{contexte_devis}

PROJETS ANTÉRIEURS DE L'ENTREPRISE :
{projets_context}

ALERTES DATES (calculées automatiquement) :
{validation_dates['alerte_texte']}

Rédige en français professionnel canadien québécois :

## SOMMAIRE DE L'APPEL D'OFFRES
- Numéro AO, nom projet, client, lieu, section spécialisée
- Travaux demandés (liste des grandes catégories du bordereau)
- Dates clés : visite, clôture, début/fin travaux avec jours ouvrables calculés

## COMPARAISON AVEC LES PROJETS ANTÉRIEURS
- Projets similaires de l'entreprise (type, envergure, montant)
- Niveau d'expérience : identique / similaire / partiel / aucun
- Points de convergence concrets (cite les projets par nom)

## CONTRAINTES ET RISQUES IDENTIFIÉS
- Contraintes opérationnelles du chantier
- Qualifications spéciales requises
- Risques techniques particuliers
"""

            sommaire_ao = ""
            with st.status("**Étape 3/4** — Analyste AO : sommaire et comparaison projets…") as s3:
                res_analyste = llm_manager.analyze(prompt_analyste, max_tokens=1500)
                # ── Sauvegarde provider étape 3 ──
                _noter_provider(res_analyste)
                if res_analyste["success"]:
                    sommaire_ao = res_analyste["result"]
                    provider_e3 = res_analyste.get("provider", llm_manager.provider_actif())
                    s3.update(
                        label=f"✅ Étape 3 — Sommaire AO complété · {provider_e3}",
                        state="complete"
                    )
                else:
                    s3.update(label="⚠️ Étape 3 — Analyste AO indisponible", state="error")

            # ── Étape 4 : Prompt 2 — Évaluateur / Rédacteur final ────
            prompt_evaluateur = f"""
Tu es un évaluateur professionnel et rédacteur senior spécialisé en soumissions de construction au Québec.
Tu travailles comme employé de {user.get('nom_entreprise', 'cette entreprise')}.
Spécialité : {', '.join(user.get('specialites', ['construction'])) if user.get('specialites') else 'construction'}.

MISSION : À partir de l'analyse ci-dessous, rédiger l'évaluation finale complète et la recommandation.
RÈGLE ABSOLUE : Factuel, professionnel, basé UNIQUEMENT sur les faits fournis. Zéro hallucination.

SOMMAIRE ÉTABLI PAR L'ANALYSTE :
{sommaire_ao}

PROFIL ENTREPRISE :
- Nom : {user.get('nom_entreprise', 'N/A')}
- Spécialités : {', '.join(user.get('specialites', [])) if user.get('specialites') else 'Non spécifiées'}
- Licence RBQ : {user.get('licence_rbq', 'N/A')}

ALERTES DATES CONFIRMÉES :
{validation_dates['alerte_texte']}

DATE DU JOUR : {today_str}

📅 RÈGLE DATES — OBLIGATOIRE :
- Date visite    : < 5 jours ouvrables depuis aujourd'hui → POINT FAIBLE MAJEUR
- Date clôture   : < 5 jours ouvrables depuis aujourd'hui → POINT FAIBLE MAJEUR + impact score
- Date visite    : ≥ 5 jours ouvrables → neutre ou point fort si > 10 jours

⚠️ AVERTISSEMENT IA OBLIGATOIRE — Commencer par :
"⚠️ AVERTISSEMENT : Cette analyse est générée par un système d'intelligence artificielle.
Bien que nous nous efforcions de fournir des informations précises, des erreurs
d'interprétation peuvent survenir. Vérifiez toutes les informations critiques
dans le document original avant de décider."

STYLE D'ÉCRITURE :
- Analyse : 2ème/3ème personne ("Vous possédez", "L'entreprise a")
- Recommandation finale : 1ère personne ("Je recommande GO")

🎯 GRILLE DE SCORING OBLIGATOIRE — TOTAL SUR 100 POINTS :

Critère 1 — EXPÉRIENCES SIMILAIRES (40 pts)
  • Projets antérieurs identiques (type + envergure)  : 40 pts
  • Projets similaires, envergure différente           : 25 pts
  • Projets partiellement similaires                  : 15 pts
  • Aucune expérience documentée                      :  0 pts

Critère 2 — DÉLAI DE PRÉPARATION (30 pts)
  Seuil critique : MINIMUM 5 jours ouvrables requis.
  Calcule les jours ouvrables entre aujourd'hui ({today_str}) et la clôture :
  • > 10 jours ouvrables : 30 pts  ✅ Très confortable
  •  6 à 10 jours        : 20 pts  ⚠️ Serré mais faisable
  •  5 jours exactement  : 10 pts  🔴 Limite — risque élevé
  •  < 5 jours ouvrables :  0 pts  🔴 INSUFFISANT

Critère 3 — ADÉQUATION TECHNIQUE ET LICENCES (20 pts)
  • Spécialité exacte + toutes licences présentes     : 20 pts
  • Spécialité présente, certifications partielles    : 12 pts
  • Sous-traitants requis pour partie importante      :  6 pts
  • Hors spécialité                                   :  0 pts

Critère 4 — CAPACITÉ OPÉRATIONNELLE (10 pts)
  • Aucune contrainte majeure                         : 10 pts
  • Contraintes modérées                              :  6 pts
  • Contraintes importantes (hôpital, PCIS, nuit)    :  3 pts
  • Contraintes rédhibitoires                         :  0 pts

RÈGLE DE COHÉRENCE SCORE ↔ RECOMMANDATION — ABSOLUMENT OBLIGATOIRE :
  Score  0 à 49  →  NO-GO      → écrire exactement "Je recommande NO-GO"
  Score 50 à 69  →  PEUT-ÊTRE  → écrire exactement "Je recommande PEUT-ÊTRE"
  Score 70 à 100 →  GO         → écrire exactement "Je recommande GO"
⛔ LE SCORE DICTE LA RECOMMANDATION — JAMAIS L'INVERSE.

📊 STRUCTURE DE LA RÉPONSE (respecter l'ordre et les titres exacts) :

### 1. AVERTISSEMENT IA
### 2. CONTEXTE DE L'APPEL D'OFFRES
### 3. DATES CLÉS ET DÉLAIS ⏰
### 4. ANALYSE DU BORDEREAU PAR CATÉGORIE 📋
### 5. ADÉQUATION AVEC L'EXPÉRIENCE 🏗️
### 6. POINTS FORTS ✅ (maximum 5)
### 7. POINTS FAIBLES ⚠️ (maximum 5)
### 8. CRITÈRES D'ADMISSIBILITÉ ET QUALIFICATIONS REQUISES 📋
### 9. ACTIONS PRIORITAIRES 🎯 (maximum 5 actions concrètes)
### 10. RECOMMANDATION FINALE 💭
    Détail du score :
    - Expériences similaires  : X/40
    - Délai de préparation    : X/30  (jours ouvrables avant clôture — seuil min : 5 jours)
    - Adéquation technique    : X/20
    - Capacité opérationnelle : X/10
    TOTAL                     : X/100
### 11. SCORE : X/100
"""

            result = ""
            with st.status("**Étape 4/4** — Évaluateur : rédaction de l'évaluation finale…") as s4:
                res_eval = llm_manager.analyze(prompt_evaluateur, max_tokens=2500)
                # ── Sauvegarde provider étape 4 (le plus important — dernier utilisé) ──
                _noter_provider(res_eval)
                if not res_eval["success"]:
                    st.error(f"❌ {res_eval['error']}")
                    return
                result = res_eval["result"]
                provider_e4 = res_eval.get("provider", llm_manager.provider_actif())
                s4.update(
                    label=f"✅ Étape 4 — Évaluation finale rédigée · {provider_e4}",
                    state="complete"
                )

            # ── Affichage ─────────────────────────────────────────────
            st.markdown("### 📋 Résultat de l'analyse IA")

            if sommaire_ao:
                with st.expander("🔎 Sommaire AO — Analyste (détails)", expanded=False):
                    st.markdown(sommaire_ao)

            if validation_dates["alertes"]:
                st.markdown("#### ⏰ Validation automatique des dates")
                for alerte in validation_dates["alertes"]:
                    if "🔴" in alerte:
                        st.error(alerte)
                    elif "✅" in alerte:
                        st.success(alerte)
                    else:
                        st.warning(alerte)

            if structure_bordereau and structure_bordereau.get("categories"):
                with st.expander("📄 Structure du bordereau détectée", expanded=False):
                    for cat in structure_bordereau["categories"]:
                        st.markdown(f"**{cat['nom']}** — {len(cat.get('items', []))} items")
                        for it in cat.get("items", []):
                            st.caption(f"  Item {it['numero']} : {it['description'][:100]}")
                    if structure_bordereau.get("items_hors_categorie"):
                        st.markdown("**Frais généraux**")
                        for it in structure_bordereau["items_hors_categorie"]:
                            st.caption(f"  Item {it['numero']} : {it['description'][:100]}")

            if sections_devis:
                with st.expander("📐 Exigences techniques du devis", expanded=False):
                    normes = sections_devis.get("normes_applicables", [])
                    if normes:
                        st.markdown(f"**Normes :** {', '.join(normes)}")
                    for q in sections_devis.get("qualifications_requises", []):
                        badge = "🔴 OBLIGATOIRE" if q.get("obligatoire") else "🟡 Souhaité"
                        st.markdown(f"{badge} — **{q['qualification']}** : {q.get('pour', '')} {('⚠️ ' + q.get('note','')) if q.get('note') else ''}")
                    for c in sections_devis.get("contraintes_operationnelles", []):
                        st.warning(c)

            st.markdown("---")
            st.markdown(result)

            # ── Détection score ────────────────────────────────────────
            score = 0
            m = re.search(r"###\s*11\.?\s*SCORE\s*[:\-]?\s*(\d{1,3})(?:\/100)?", result, re.IGNORECASE)
            if m:
                score = min(int(m.group(1)), 100)
            else:
                m = re.search(r"\bSCORE\s*[:\-]\s*(\d{1,3})(?:\/100)?", result, re.IGNORECASE)
                if m:
                    score = min(int(m.group(1)), 100)
                else:
                    m = re.search(r"\b(\d{1,3})\/100\b", result)
                    if m:
                        score = min(int(m.group(1)), 100)

            if score >= 70:
                rec = "GO"
            elif score >= 50:
                rec = "PEUT-ÊTRE"
            else:
                rec = "NO-GO"

            analyse_structuree = _parser_analyse_structuree(
                result, nom_projet, numero_projet, rec, score, text,
                structure_bordereau=structure_bordereau,
                sections_devis=sections_devis,
            )
            st.session_state["analyse_result"]   = analyse_structuree
            st.session_state["analyse_texte_ao"] = text

            soumission_id = _sauvegarder_soumission(
                user, result, rec, score, nom_projet, numero_projet, uploaded_files
            )
            saved_analyse = _sauvegarder_analyse(
                user, result, rec, score, nom_projet, numero_projet,
                len(uploaded_files), soumission_id
            )

            if soumission_id and saved_analyse:
                st.success("✅ Analyse sauvegardée et liée à votre entreprise !")
            elif soumission_id:
                st.success("✅ Analyse sauvegardée dans les soumissions.")
            else:
                st.warning("⚠️ L'analyse a été effectuée mais n'a pas pu être sauvegardée.")

            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            with col1:
                reco_color = {"GO": "🟢", "NO-GO": "🔴", "PEUT-ÊTRE": "🟡"}.get(rec, "⚪")
                st.metric("Recommandation", f"{reco_color} {rec}")
            with col2:
                st.metric("Score", f"{score}/100")
            with col3:
                # ── Affichage du modèle utilisé dans les métriques de résultat ──
                provider_final = st.session_state.get("llm_dernier_provider", llm_manager.provider_actif())
                st.metric("Modèle IA", provider_final)

            st.markdown("---")
            st.info(
                f"✅ **Analyse prête pour le générateur !**  \n"
                f"Projet : **{nom_projet}**  \n"
                f"Structure bordereau : **{nb_items} items** détectés  \n"
                f"Cliquez sur le bouton ci-dessous pour créer la soumission."
            )

            if st.button(
                "📝 Générer une offre →",
                type="primary",
                use_container_width=False,
                key="btn_goto_generateur"
            ):
                st.session_state["onglet_actif"] = "generateur"
                st.rerun()

        except Exception as e:
            st.error(f"❌ Erreur lors de l'analyse : {str(e)}")
            import traceback
            st.code(traceback.format_exc())