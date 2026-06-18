"""
generateur_offres.py — Orchestrateur principal
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ce fichier est le point d'entrée unique appelé par app.py.
Il orchestre les modules spécialisés sans dupliquer leur logique.

MODULES IMPORTÉS :
  chiffrage.py      → prix unitaires, quantités, calcul soumission
  offre_technique.py → mémoire technique, validation conformité
  courriel.py       → génération du courriel d'envoi
  exports.py        → Word, Excel, PDF, aperçus, téléchargements
  formulaire_ao.py  → formulaire officiel AO

RESPONSABILITÉS RESTANTES ICI :
  - Persistance Supabase (sauvegarder_offre, statuts)
  - UI Streamlit de l'onglet principal (show_generateur_tab)
  - Cycle de vie des statuts (STATUTS_CFG)
  - Onglet Mes Offres (show_mes_offres_tab)
"""

import json
import re
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

import database
import projet_documents as pdocs
import devis_cmeq as _cmeq

# ── Imports des modules spécialisés ──────────────────────────────────────────
from chiffrage import (
    charger_projets_reference,
    extraire_prix_unitaires,
    extraire_quantites_appel_offre,
    calculer_soumission,
    extraire_bordereau_ao,
    proposer_prix_bordereau,
)
from offre_technique import (
    generer_offre_technique,
    valider_conformite_offre,
)
from courriel import generer_email_soumission
from exports import (
    generer_docx,
    generer_xlsx,
    generer_pdf,
    afficher_telechargements,
    apercu_word_html,
    apercu_excel_html,
)
from formulaire_ao import afficher_section_formulaire_ao

# Alias rétro-compatibles (générateur_offres_ui.py les importe encore)
_generer_docx        = generer_docx
_generer_xlsx        = generer_xlsx
_generer_pdf         = generer_pdf
_generer_pdf_combine = generer_pdf
_apercu_word_html    = apercu_word_html
_apercu_excel_html   = apercu_excel_html


# ═════════════════════════════════════════════════════════════════════════════
# CYCLE DE VIE DES STATUTS
# ═════════════════════════════════════════════════════════════════════════════

STATUTS_CFG = {
    "brouillon":          {"label": "Brouillon",             "emoji": "📝", "visible_mes_offres": False},
    "en_revision":        {"label": "En révision",            "emoji": "🔍", "visible_mes_offres": False},
    "en_attente_envoi":   {"label": "En attente d'envoi",    "emoji": "⏸️", "visible_mes_offres": False},
    "envoyee":            {"label": "Envoyée",                "emoji": "📤", "visible_mes_offres": True},
    "en_attente_reponse": {"label": "En attente de réponse", "emoji": "⏳", "visible_mes_offres": True},
    "acceptee":           {"label": "Acceptée",               "emoji": "🎉", "visible_mes_offres": True},
    "refusee":            {"label": "Refusée",                "emoji": "❌", "visible_mes_offres": True},
    # Rétro-compatibilité
    "a_valider":          {"label": "À valider",              "emoji": "📋", "visible_mes_offres": False},
    "validee":            {"label": "Validée",                "emoji": "✅", "visible_mes_offres": True},
    "en_attente":         {"label": "En attente",             "emoji": "⏳", "visible_mes_offres": True},
}

STATUTS_MES_OFFRES = [k for k, v in STATUTS_CFG.items() if v["visible_mes_offres"]]
STATUTS_EN_COURS   = ["brouillon", "en_revision", "en_attente_envoi", "a_valider"]


# ═════════════════════════════════════════════════════════════════════════════
# PERSISTANCE SUPABASE
# ═════════════════════════════════════════════════════════════════════════════

def sauvegarder_offre(
    entreprise_id: str,
    soumission_id: str,
    offre_complete: dict,
    statut: str,
) -> dict | None:
    """
    Crée ou met à jour une offre dans la table Supabase `offres`.

    Args:
        entreprise_id: UUID de l'entreprise.
        soumission_id: UUID de la soumission liée (peut être "").
        offre_complete: Dict complet de l'offre (exigences, technique, financière).
        statut: Statut initial (ex. "brouillon", "envoyee").

    Returns:
        Dict de la ligne créée/mise à jour, None si erreur.
    """
    try:
        database.apply_supabase_auth()
        sid = soumission_id if soumission_id else None
        payload = {
            "entreprise_id": entreprise_id,
            "statut":        statut,
            "contenu":       json.dumps(offre_complete, ensure_ascii=False),
        }
        if sid:
            payload["soumission_id"] = sid

        offre_id = st.session_state.get("offre_data", {}).get("offre_id")
        if offre_id:
            res = database.supabase.table("offres").update(payload).eq("id", offre_id).execute()
        else:
            res = database.supabase.table("offres").insert(payload).execute()

        return res.data[0] if res.data else None
    except Exception as e:
        st.error(f"❌ Erreur sauvegarde : {e}")
        return None


def _sauvegarder_statut_offre(offre_id: str, nouveau_statut: str) -> bool:
    """
    Met à jour uniquement le statut d'une offre existante.

    Args:
        offre_id: UUID de l'offre dans Supabase.
        nouveau_statut: Nouveau statut à appliquer.

    Returns:
        True si succès, False si erreur.
    """
    try:
        database.apply_supabase_auth()
        database.supabase.table("offres").update({
            "statut": nouveau_statut,
        }).eq("id", offre_id).execute()
        return True
    except Exception as e:
        st.error(f"❌ Erreur mise à jour statut : {e}")
        return False


# ═════════════════════════════════════════════════════════════════════════════
# HELPER — OFFRES EN COURS (dans onglet Validation)
# ═════════════════════════════════════════════════════════════════════════════

def _afficher_offres_en_cours(user: dict) -> None:
    """
    Affiche les offres en brouillon/révision/attente d'envoi dans l'onglet
    Validation, avec bouton pour les rouvrir.
    """
    try:
        database.apply_supabase_auth()
        res = database.supabase.table("offres").select("*").eq(
            "entreprise_id", user["id"]
        ).in_("statut", STATUTS_EN_COURS).order("updated_at", desc=True).execute()
        offres_en_cours = res.data or []
    except Exception:
        offres_en_cours = []

    if not offres_en_cours:
        return

    st.markdown("### 📋 Offres en cours (non encore envoyées)")
    for offre in offres_en_cours:
        statut  = offre.get("statut", "brouillon")
        cfg     = STATUTS_CFG.get(statut, {"emoji": "•", "label": statut})
        contenu = offre.get("contenu", {})
        if isinstance(contenu, str):
            try:
                contenu = json.loads(contenu)
            except Exception:
                contenu = {}
        nom = (
            contenu.get("offre_technique", {}).get("titre_offre")
            or contenu.get("exigences", {}).get("nom_projet")
            or f"Offre {offre.get('id','')[:8]}"
        )
        date_maj = str(offre.get("updated_at", ""))[:10]

        col_info, col_action = st.columns([4, 1])
        with col_info:
            st.markdown(f"{cfg['emoji']} **{nom}** — *{cfg['label']}* — Modifiée le {date_maj}")
        with col_action:
            if st.button("Ouvrir", key=f"ouvrir_en_cours_{offre['id']}", use_container_width=True):
                st.session_state["offre_en_cours_id"]   = offre["id"]
                st.session_state["offre_en_cours_data"] = offre
                st.info(f"✅ Offre **{nom}** chargée.")

    st.markdown("---")


# ═════════════════════════════════════════════════════════════════════════════
# HELPER — CHIFFRAGE CLASSIQUE (fallback sans bordereau structuré)
# ═════════════════════════════════════════════════════════════════════════════

def _lancer_chiffrage_complet(
    analyse: dict,
    texte_ao: str,
    projets: list,
    specialite: str,
    user: dict,
    offre_data: dict,
) -> None:
    """
    Chiffrage en 3 étapes IA (prix unitaires → quantités → calcul).
    Utilisé quand il n'y a pas de bordereau structuré dans l'AO.
    Met à jour st.session_state et appelle st.rerun() en fin.
    """
    taux_h_val  = offre_data.get("taux_h", 65.0)
    conting_val = offre_data.get("contingence", 10)
    projets_val = offre_data.get("projets_choisis", projets)
    resultats   = {}

    with st.status("**Étape 1/3** — Extraction des prix unitaires…") as s:
        pu = extraire_prix_unitaires(projets_val or projets, specialite, taux_horaire=taux_h_val)
        if pu:
            pu["taux_horaire_moyen"] = taux_h_val
            resultats["prix_unitaires"] = pu
            s.update(label=f"✅ Étape 1 — {len(pu.get('prix_unitaires', []))} prix extraits", state="complete")
        else:
            pu = {"specialite": specialite, "taux_horaire_moyen": taux_h_val, "prix_unitaires": []}
            resultats["prix_unitaires"] = pu
            s.update(label="⚠️ Étape 1 — Banque de prix vide", state="error")

    with st.status("**Étape 2/3** — Extraction des quantités de l'AO…") as s:
        qtes = extraire_quantites_appel_offre(analyse, texte_ao)
        if qtes:
            resultats["quantites"] = qtes
            s.update(label=f"✅ Étape 2 — {len(qtes.get('travaux', []))} postes", state="complete")
        else:
            qtes = {"travaux": []}
            resultats["quantites"] = qtes
            s.update(label="⚠️ Étape 2 — Quantités non extraites", state="error")

    with st.status("**Étape 3/3** — Calcul de la soumission…") as s:
        soumission = calculer_soumission(pu, qtes, analyse, user)
        if soumission:
            sous_ht  = soumission["sous_total_ht"]
            conting  = sous_ht * (conting_val / 100)
            avant_tx = sous_ht + conting
            tps      = avant_tx * 0.05
            tvq      = avant_tx * 0.09975
            soumission.update({
                "contingence_pct":   conting_val,
                "contingence":       round(conting,  2),
                "total_avant_taxes": round(avant_tx, 2),
                "tps":               round(tps,      2),
                "tvq":               round(tvq,      2),
                "total_ttc":         round(avant_tx + tps + tvq, 2),
            })
            resultats["soumission"] = soumission
            st.session_state["offre_generee"]              = resultats
            st.session_state.offre_data["soumission"]      = soumission
            st.session_state.offre_data["prix_unitaires"]  = pu
            s.update(label=f"✅ Total TTC : {soumission['total_ttc']:,.2f} $", state="complete")
        else:
            s.update(label="❌ Calcul échoué", state="error")

    st.rerun()


def _afficher_resultats_chiffrage() -> None:
    """Affiche les résultats du chiffrage classique depuis session state."""
    if "offre_generee" not in st.session_state:
        return

    resultats  = st.session_state["offre_generee"]
    soumission = resultats.get("soumission") or {}
    pu         = resultats.get("prix_unitaires") or {}

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total TTC",       f"{soumission.get('total_ttc', 0):,.0f} $")
    m2.metric("Total heures MO", f"{soumission.get('total_heures', 0):,.1f} h")
    m3.metric("Postes",          len(soumission.get("postes", [])))
    m4.metric("Prix unitaires",  len(pu.get("prix_unitaires", [])))

    sub1, sub2 = st.tabs(["💰 Devis détaillé", "📐 Prix unitaires"])
    with sub1:
        postes = soumission.get("postes", [])
        if postes:
            import pandas as pd
            df = pd.DataFrame([{
                "Code":        p.get("code",""),
                "Description": p.get("description",""),
                "Qté":         p.get("quantite",0),
                "Unité":       p.get("unite",""),
                "H/unité":     p.get("heures_par_unite",0),
                "H total":     p.get("heures_total",0),
                "MO ($)":      p.get("cout_mo",0),
                "Mat. ($)":    p.get("cout_materiel",0),
                "Total ($)":   p.get("total_poste",0),
                "Source":      p.get("source",""),
            } for p in postes])
            st.dataframe(df, use_container_width=True, hide_index=True)
    with sub2:
        prix = pu.get("prix_unitaires", [])
        if prix:
            import pandas as pd
            df_pu = pd.DataFrame([{
                "Code":           p.get("code",""),
                "Description":    p.get("description",""),
                "Unité":          p.get("unite",""),
                "H/unité":        p.get("heures_par_unite",0),
                "Mat./unité ($)": p.get("materiel_par_unite",0),
                "Source":         p.get("source_projet",""),
            } for p in prix])
            st.dataframe(df_pu, use_container_width=True, hide_index=True)
        else:
            st.info("Ajoutez des spécifications à vos projets pour enrichir la banque de prix.")

    if st.button("🔄 Relancer le chiffrage", use_container_width=True, key="btn_rechiffrage"):
        st.session_state.pop("offre_generee", None)
        st.session_state.offre_data.pop("soumission", None)
        st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# ONGLET PRINCIPAL — show_generateur_tab
# ═════════════════════════════════════════════════════════════════════════════

def show_generateur_tab(user: dict, analyse: dict | None = None, texte_ao: str = "") -> None:
    """
    Point d'entrée principal appelé depuis app.py.
    Affiche les 6 onglets du générateur d'offres.

    Args:
        user: Profil entreprise connecté.
        analyse: Dict d'analyse du projet courant (peut être None).
        texte_ao: Texte brut de l'AO pour le chiffrage.
    """
    st.header("📝 Générateur d'Offres")

    if "offre_data" not in st.session_state:
        st.session_state.offre_data = {}

    if not analyse:
        st.info("💡 Analysez d'abord un appel d'offre dans l'onglet **Analyse** pour générer une offre.")
        return

    entreprise_id = str(user["id"])
    specialites   = user.get("specialites") or []
    specialite    = specialites[0] if specialites else "construction générale"

    with st.spinner("📂 Chargement des projets de référence…"):
        projets = charger_projets_reference(entreprise_id)

    # ── Log du modèle LLM utilisé — lu dynamiquement depuis session_state ──
    # Affiché uniquement après une analyse — pas de fallback sur provider_actif()
    # pour éviter d'afficher Gemini alors que c'est Groq qui a répondu.
    llm_actif = st.session_state.get("llm_dernier_provider")
    if llm_actif:
        st.caption(f"🤖 Modèle IA : `{llm_actif}`")

    # Avertissement NO-GO / PEUT-ÊTRE
    rec   = analyse.get("recommendation", analyse.get("rec", "INCONNU"))
    score = analyse.get("score", 0)
    points_faibles_raw = analyse.get("points_faibles", [])
    if isinstance(points_faibles_raw, str):
        points_faibles = [l.strip("•- ").strip() for l in points_faibles_raw.split("\n") if l.strip()]
    elif isinstance(points_faibles_raw, list):
        points_faibles = points_faibles_raw
    else:
        points_faibles = []

    if rec in ("NO-GO", "NON"):
        st.error(f"⛔ **Recommandation NO-GO** (score {score}/100)")
        for pf in points_faibles[:5]:
            st.error(f"• {pf}")
        if not st.checkbox("⚠️ Je comprends les risques et souhaite quand même générer une offre.", key="chk_nogo"):
            st.stop()
    elif rec in ("PEUT-ÊTRE", "PEUT_ETRE"):
        st.warning(f"⚠️ **Recommandation PEUT-ÊTRE** (score {score}/100)")
        for pf in points_faibles[:5]:
            st.warning(f"• {pf}")
    elif rec in ("GO", "OUI"):
        st.success(f"✅ **Recommandation GO** — Score {score}/100")

    with st.expander("📌 Appel d'offre cible", expanded=True):
        c1, c2, c3 = st.columns(3)
        c1.info(f"**Projet :** {analyse.get('nom_projet', '—')}")
        c2.info(f"**Client :** {analyse.get('client', '—')}")
        c3.info(f"**Lieu :** {analyse.get('lieu', '—')}")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "⚙️ Paramètres & Projets",
        "📄 Offre Technique",
        "💰 Offre Financière",
        "✅ Validation",
        "📤 Envoi",
        "📊 Suivi Statut",
    ])

    # ── TAB 1 — Paramètres & Projets ──────────────────────────────────────
    with tab1:
        st.subheader("1️⃣ Documents du projet & Paramètres")
        st.markdown("#### 📂 Documents du projet")
        pdocs.show_chargement_documents(key_prefix="gen")

        texte_ao_docs = (pdocs.texte_invitation() + "\n\n" + pdocs.texte_cahier_charges()).strip()
        if texte_ao_docs:
            st.session_state["texte_ao_courant"] = texte_ao_docs
            if not texte_ao:
                texte_ao = texte_ao_docs

        st.markdown("---")
        st.markdown("#### 📐 Taux horaire main-d'œuvre")

        methode_taux = st.radio(
            "Méthode de calcul du taux",
            options=["cmeq", "manuel"],
            format_func=lambda x: (
                "📐 Option A — Grille CMEQ" if x == "cmeq" else "✏️  Option B — Taux personnalisé"
            ),
            key="methode_taux_radio", horizontal=True,
        )

        if methode_taux == "cmeq":
            if "grille_cmeq" not in st.session_state:
                st.session_state["grille_cmeq"] = _cmeq.charger_grille_profil(user)
            calcul_cmeq = _cmeq.calculer_taux(st.session_state["grille_cmeq"])
            taux_h = calcul_cmeq["taux_total"]
            col_a1, col_a2, col_a3, col_a4 = st.columns(4)
            col_a1.metric("Coût MO",           f"{calcul_cmeq['cout_mo']:.2f} $/h")
            col_a2.metric("Frais",             f"{calcul_cmeq['F'] + calcul_cmeq['G_montant']:.2f} $/h")
            col_a3.metric("Profit",            f"{calcul_cmeq['H_montant']:.2f} $/h")
            col_a4.metric("🎯 Taux facturable", f"{taux_h:.2f} $/h", delta="Grille CMEQ")
        else:
            if "sections_taux_manuel" not in st.session_state:
                st.session_state["sections_taux_manuel"] = [
                    {"label": "Main-d'œuvre (salaire + charges)", "montant": 81.98},
                    {"label": "Véhicule et équipements",           "montant": 16.02},
                    {"label": "Frais généraux (25%)",              "montant": 24.50},
                    {"label": "Profit (10%)",                       "montant": 12.25},
                ]
            sections = st.session_state["sections_taux_manuel"]
            for i, sec in enumerate(sections):
                c1, c2, c3 = st.columns([4, 2, 1])
                with c1:
                    sections[i]["label"] = st.text_input(
                        f"Section {i+1}", value=sec["label"],
                        key=f"sec_label_{i}", label_visibility="collapsed"
                    )
                with c2:
                    sections[i]["montant"] = st.number_input(
                        "$/h", value=float(sec["montant"]), min_value=0.0, max_value=500.0, step=0.5,
                        key=f"sec_montant_{i}", label_visibility="collapsed"
                    )
                with c3:
                    if st.button("✕", key=f"sec_del_{i}"):
                        st.session_state["sections_taux_manuel"].pop(i)
                        st.rerun()
            if st.button("＋ Ajouter une section", key="btn_add_section"):
                st.session_state["sections_taux_manuel"].append({"label": "Nouvelle section", "montant": 0.0})
                st.rerun()
            taux_h = round(sum(s["montant"] for s in sections), 2)
            st.markdown(
                f"<div style='background:#1E3A5F;color:white;padding:8px 14px;"
                f"border-radius:6px;font-weight:bold;'>✅ Taux horaire total : {taux_h:.2f} $/h</div>",
                unsafe_allow_html=True,
            )

        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            contingence = st.slider("Contingence (%)", 0, 25, 10, key="contingence_slider")
        with col2:
            st.info(f"**Spécialité détectée :** {specialite}")

        st.session_state.offre_data["taux_h"]     = taux_h
        st.session_state.offre_data["contingence"] = contingence
        st.session_state.offre_data["specialite"]  = specialite

        st.markdown("---")
        st.subheader("2️⃣ Projets antérieurs à valoriser")

        if not projets:
            st.warning("⚠️ Aucun projet de référence trouvé.")
            st.session_state.offre_data["projets_choisis"] = []
        else:
            st.success(f"✅ {len(projets)} projet(s) disponible(s)")
            options_proj = {
                f"{p['nom_projet']} — {float(p.get('montant') or 0):,.0f} $": p
                for p in projets
            }
            choix_proj = st.multiselect(
                "Sélectionnez les projets similaires à mettre en valeur",
                list(options_proj.keys()),
                default=list(options_proj.keys())[:min(3, len(options_proj))],
                key="multiselect_projets"
            )
            st.session_state.offre_data["projets_choisis"] = [options_proj[c] for c in choix_proj]

    # ── TAB 2 — Offre Technique ────────────────────────────────────────────
    with tab2:
        st.subheader("3️⃣ Offre Technique — Mémoire et sections du cahier de charges")

        texte_ao_effectif = (
            pdocs.texte_ao_complet().strip()
            or st.session_state.get("texte_ao_courant", "").strip()
            or st.session_state.get("analyse_texte_ao", "").strip()
            or texte_ao.strip()
        )
        if texte_ao_effectif:
            st.session_state["texte_ao_courant"] = texte_ao_effectif
            st.success(f"✅ Document AO chargé ({len(texte_ao_effectif):,} car.)")
        else:
            st.error("❌ **Aucun document chargé.** Allez dans l'onglet Paramètres & Projets.")

        # Bordereau depuis l'analyse
        structure_bordereau = analyse.get("structure_bordereau") or {}
        if not st.session_state.offre_data.get("bordereau_ao"):
            if structure_bordereau and structure_bordereau.get("categories"):
                sections_norm = []
                for cat in structure_bordereau["categories"]:
                    items_norm = [
                        {
                            "no":           str(it.get("numero", "")),
                            "description":  it.get("description", ""),
                            "unite":        "forfait" if it.get("type") == "forfaitaire" else it.get("type", "forfait"),
                            "quantite":     1,
                            "prix_unitaire": None,
                            "source_prix":  None,
                        }
                        for it in cat.get("items", [])
                    ]
                    sections_norm.append({"titre": cat["nom"], "items": items_norm})
                st.session_state.offre_data["bordereau_ao"] = sections_norm

        sections_bordereau = st.session_state.offre_data.get("bordereau_ao", [])
        if sections_bordereau:
            total_items = sum(len(s["items"]) for s in sections_bordereau)
            st.info(f"📋 **Bordereau** — {total_items} items dans {len(sections_bordereau)} sections.")

        st.markdown("---")
        st.markdown("#### 🤖 Mémoire technique")
        btn_memoire = st.button(
            "🤖 Générer le mémoire technique",
            type="primary", key="btn_memoire",
            disabled=not texte_ao_effectif
        )

        if btn_memoire:
            projets_choisis = st.session_state.offre_data.get("projets_choisis", projets)
            soumission_tmp  = st.session_state.offre_data.get("soumission", {})
            pu_tmp          = st.session_state.offre_data.get("prix_unitaires", {"specialite": specialite})
            with st.spinner("L'IA rédige le mémoire technique…"):
                technique = generer_offre_technique(
                    analyse, soumission_tmp, pu_tmp, user,
                    projets_choisis, texte_ao=texte_ao_effectif,
                )
                if technique:
                    st.session_state.offre_data["offre_technique"] = technique
                    st.success("✅ Mémoire technique rédigé !")
                    st.rerun()
                else:
                    st.error("❌ Génération échouée. Relancez.")

        if st.session_state.offre_data.get("offre_technique"):
            offre_tech = st.session_state.offre_data["offre_technique"]
            st.success("✅ Mémoire disponible — modifiable ci-dessous")

            offre_tech["titre_offre"] = st.text_input(
                "✏️ Titre de l'offre",
                value=offre_tech.get("titre_offre") or offre_tech.get("titre", ""),
                key="edit_titre"
            )
            st.markdown("### Introduction")
            offre_tech["introduction"] = st.text_area(
                "Introduction", value=offre_tech.get("introduction", ""),
                height=120, key="edit_intro"
            )
            st.markdown("### Compréhension du mandat")
            offre_tech["comprehension_projet"] = st.text_area(
                "Compréhension",
                value=offre_tech.get("comprehension_projet") or offre_tech.get("comprehension_mandat", ""),
                height=120, key="edit_comprehension"
            )
            st.markdown("### Garanties")
            garanties = offre_tech.get("garanties_qualite") or offre_tech.get("garanties", [])
            new_gar = st.text_area(
                "Garanties (une par ligne)", value="\n".join(garanties),
                height=80, key="edit_garanties"
            )
            offre_tech["garanties_qualite"] = [g.strip() for g in new_gar.split("\n") if g.strip()]
            offre_tech["garanties"]         = offre_tech["garanties_qualite"]

            if st.button("💾 Sauvegarder le mémoire", type="primary", key="btn_save_memoire"):
                st.session_state.offre_data["offre_technique"] = offre_tech
                st.success("✅ Mémoire sauvegardé.")

        st.markdown("---")
        st.markdown("## 📋 Formulaire officiel de soumission")
        afficher_section_formulaire_ao(analyse=analyse, user=user, projets=projets)

    # ── TAB 3 — Offre Financière ───────────────────────────────────────────
    with tab3:
        st.subheader("4️⃣ Offre Financière — Chiffrage et bordereau de prix")

        sections_bordereau = st.session_state.offre_data.get("bordereau_ao", [])

        # Extraction depuis le document bordereau
        texte_bord_docs = pdocs.texte_bordereau()
        if texte_bord_docs.strip() and not sections_bordereau:
            bord_extrait = extraire_bordereau_ao(
                texte_ao=texte_bord_docs,
                analyse=analyse,
                projets_references=projets,
            )
            if bord_extrait and bord_extrait.get("sections"):
                sections_norm = []
                for sec in bord_extrait["sections"]:
                    sections_norm.append({
                        "titre": sec["titre"],
                        "items": [
                            {
                                "no":           it.get("no",""),
                                "description":  it.get("description",""),
                                "unite":        it.get("unite","forfait"),
                                "quantite":     it.get("quantite",1),
                                "prix_unitaire": it.get("prix_unitaire"),
                                "source_prix":  it.get("source_prix"),
                                "a_saisir":     it.get("a_saisir", it.get("prix_unitaire") is None),
                            }
                            for it in sec.get("items", [])
                        ]
                    })
                st.session_state.offre_data["bordereau_ao"] = sections_norm
                sections_bordereau = sections_norm

        if not sections_bordereau:
            st.warning("⚠️ Aucun bordereau disponible. Lancez le chiffrage classique ci-dessous.")
            if st.button("🚀 Lancer le chiffrage complet", type="primary",
                         use_container_width=True, key="btn_chiffrage"):
                _lancer_chiffrage_complet(
                    analyse, texte_ao, projets, specialite, user,
                    st.session_state.offre_data
                )
            _afficher_resultats_chiffrage()
        else:
            taux_h_val  = st.session_state.offre_data.get("taux_h", 65.0)
            projets_val = st.session_state.offre_data.get("projets_choisis", projets)

            if st.button("💡 Proposer les prix automatiquement", type="primary",
                         use_container_width=True, key="btn_proposer_prix"):
                with st.status("Recherche des prix…") as s:
                    prix_proposes = proposer_prix_bordereau(
                        sections=sections_bordereau,
                        projets=projets_val or projets,
                        taux_h=taux_h_val,
                        analyse=analyse,
                        user=user,
                        texte_ao=texte_ao or st.session_state.get("texte_ao_courant",""),
                    )
                    st.session_state.offre_data["bordereau_ao"]   = prix_proposes["sections"]
                    st.session_state.offre_data["items_sans_prix"] = prix_proposes["items_sans_prix"]
                    nb_ok = prix_proposes["nb_prix_trouves"]
                    nb_m  = prix_proposes["nb_prix_manquants"]
                    s.update(label=f"✅ {nb_ok} prix trouvés — {nb_m} items sans référence", state="complete")
                st.rerun()

            items_sans_prix = st.session_state.offre_data.get("items_sans_prix", [])
            if items_sans_prix:
                # Recalculer la liste réelle en temps réel (l'utilisateur a peut-être déjà saisi des prix)
                items_encore_manquants = [
                    isp for isp in items_sans_prix
                    if not any(
                        it.get("no") == isp.get("no") and float(it.get("prix_unitaire") or 0) > 0
                        for sec in st.session_state.offre_data.get("bordereau_ao", [])
                        if sec.get("titre") == isp.get("section")
                        for it in sec.get("items", [])
                    )
                ]

                if items_encore_manquants:
                    with st.expander(
                        f"✏️ **{len(items_encore_manquants)} item(s) sans prix — cliquez pour saisir**",
                        expanded=True
                    ):
                        st.caption("Aucun projet antérieur ne couvre ces items. Saisissez les prix manuellement.")
                        st.markdown("---")

                        # ══════════════════════════════════════════════════════════
                        # CORRECTION BUG 1 — Formulaire prix manuels
                        # ──────────────────────────────────────────────────────────
                        # AVANT : key=f"manuel_{section[:10]}_{no_item}"
                        #   → Doublons si deux sections partagent les 10 premiers
                        #     caractères (ex: "Électricit…" × 2 sections).
                        #
                        # APRÈS : key=f"manuel_{idx_form}_{no_item_clean}"
                        #   → idx_form = index global de l'item dans la liste
                        #     complète → garanti unique peu importe les noms.
                        #   → no_item_clean = version sans espaces/caractères
                        #     spéciaux pour éviter les problèmes de parsing
                        #     internes de Streamlit.
                        # ══════════════════════════════════════════════════════════

                        # CORRECTION BUG 2 — form_submit_button manquant
                        # Le warning "Missing Submit Button" venait du fait que
                        # st.form() existait sans st.form_submit_button() appelé
                        # de façon inconditionnelle dans le bloc with.
                        # Le bouton est maintenant toujours présent dans le form.

                        with st.form("form_prix_manuels", clear_on_submit=False):
                            prix_manuels_tmp = {}
                            for idx_form, isp in enumerate(items_encore_manquants):
                                no_item  = isp.get("no", "")
                                section  = isp.get("section", "")
                                desc     = isp.get("description", "")
                                raison   = isp.get("raison", "Aucune référence trouvée")

                                # Clé unique : index global + no_item nettoyé
                                no_item_clean = re.sub(r"[^a-zA-Z0-9]", "_", str(no_item))
                                widget_key = f"manuel_{idx_form}_{no_item_clean}"

                                c_desc, c_input, c_raison = st.columns([4, 2, 3])
                                c_desc.markdown(f"**#{no_item}** — {desc}  \n*{section}*")
                                prix_manuels_tmp[f"{section}|{no_item}"] = c_input.number_input(
                                    "Prix ($)",
                                    value=0.0, min_value=0.0, step=100.0,
                                    key=widget_key,
                                    label_visibility="collapsed",
                                )
                                c_raison.caption(f"_{raison}_")

                            # Bouton submit toujours présent dans le form (corrige le warning)
                            submitted = st.form_submit_button(
                                "💾 Appliquer les prix saisis",
                                type="primary",
                                use_container_width=True,
                            )

                        # Traitement après soumission (hors du bloc with form)
                        if submitted:
                            nb_appliques = 0
                            for cle, prix_saisi in prix_manuels_tmp.items():
                                if prix_saisi and float(prix_saisi) > 0:
                                    section_titre, no = cle.split("|", 1)
                                    for sec in st.session_state.offre_data.get("bordereau_ao", []):
                                        if sec.get("titre") == section_titre:
                                            for it in sec.get("items", []):
                                                if str(it.get("no", "")) == str(no):
                                                    it["prix_unitaire"] = float(prix_saisi)
                                                    it["source_prix"]   = "Saisie manuelle"
                                                    it["a_saisir"]      = False
                                                    nb_appliques += 1
                            # Mettre à jour items_sans_prix — retirer ceux qui ont maintenant un prix
                            st.session_state.offre_data["items_sans_prix"] = [
                                isp for isp in items_sans_prix
                                if not any(
                                    it.get("no") == isp.get("no") and float(it.get("prix_unitaire") or 0) > 0
                                    for sec in st.session_state.offre_data.get("bordereau_ao", [])
                                    if sec.get("titre") == isp.get("section")
                                    for it in sec.get("items", [])
                                )
                            ]
                            st.success(f"✅ {nb_appliques} prix appliqué(s).")
                            st.rerun()
                else:
                    st.success("✅ Tous les items ont maintenant un prix.")

            total_ht = 0.0
            import pandas as pd

            for sec_idx, sec in enumerate(st.session_state.offre_data.get("bordereau_ao", [])):
                st.markdown(f"##### {sec['titre']}")

                items = sec.get("items", [])
                if not items:
                    continue

                # Construire le DataFrame pour data_editor
                rows = []
                for it in items:
                    rows.append({
                        "No":          str(it.get("no", "")),
                        "Description": it.get("description", ""),
                        "Qté":         float(it.get("quantite") or 1),
                        "Unité":       it.get("unite", "forfait"),
                        "Prix unit. $": float(it.get("prix_unitaire") or 0.0),
                        "Total $":     0.0,   # calculé après
                        "Source":      it.get("source_prix") or "",
                    })

                df = pd.DataFrame(rows)

                edited = st.data_editor(
                    df,
                    key=f"de_s{sec_idx}",
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "No":           st.column_config.TextColumn("No",    width="small",  disabled=True),
                        "Description":  st.column_config.TextColumn("Description", width="large", disabled=True),
                        "Qté":          st.column_config.NumberColumn("Qté", width="small",  disabled=True, format="%.0f"),
                        "Unité":        st.column_config.TextColumn("Unité", width="small",  disabled=True),
                        "Prix unit. $": st.column_config.NumberColumn("Prix unit. $", width="medium",
                                            min_value=0.0, step=100.0, format="$ %.2f"),
                        "Total $":      st.column_config.NumberColumn("Total $", width="medium",
                                            disabled=True, format="$ %.2f"),
                        "Source":       None,   # masquée dans l'UI — conservée dans les données pour les exports
                    },
                )

                # Appliquer les prix édités + recalculer totaux
                for i, it in enumerate(items):
                    nouveau_prix       = float(edited.iloc[i]["Prix unit. $"] or 0.0)
                    qte_val            = float(it.get("quantite") or 1)
                    it["prix_unitaire"] = nouveau_prix
                    it["total"]         = round(nouveau_prix * qte_val, 2)
                    total_ht           += it["total"]
                    # Mettre à jour Total $ dans le df pour affichage (cosmétique)
                    edited.at[i, "Total $"] = it["total"]

                # Sous-total section
                sous_total_sec = sum(float(it.get("total") or 0) for it in items)
                st.markdown(
                    f"<div style='text-align:right;font-size:13px;color:#1E3A5F;"
                    f"font-weight:600;padding:4px 8px;background:#D5E8F0;"
                    f"border-radius:4px;margin-bottom:8px;'>"
                    f"Sous-total — {sec['titre']} : {sous_total_sec:,.2f} $</div>",
                    unsafe_allow_html=True,
                )
                st.markdown("")

            contingence_pct = st.slider(
                "Contingence (%)", 0, 20,
                st.session_state.offre_data.get("contingence", 10),
                key="fin_contingence"
            )
            st.session_state.offre_data["contingence"] = contingence_pct

            contingence = round(total_ht * contingence_pct / 100, 2)
            avant_taxes = round(total_ht + contingence, 2)
            tps         = round(avant_taxes * 0.05,    2)
            tvq         = round(avant_taxes * 0.09975, 2)
            total_ttc   = round(avant_taxes + tps + tvq, 2)

            rec_col1, rec_col2 = st.columns(2)
            with rec_col1:
                st.markdown(f"**Sous-total HT :** {total_ht:,.2f} $")
                st.markdown(f"**Contingence :** {contingence:,.2f} $")
                st.markdown(f"**Total avant taxes :** {avant_taxes:,.2f} $")
            with rec_col2:
                st.markdown(f"**TPS (5%) :** {tps:,.2f} $")
                st.markdown(f"**TVQ (9,975%) :** {tvq:,.2f} $")
                st.markdown(f"### 💰 **TOTAL TTC : {total_ttc:,.2f} $**")

            soumission_fin = {
                "postes": [it for sec in st.session_state.offre_data.get("bordereau_ao", []) for it in sec.get("items", [])],
                "sous_total_ht":       total_ht,
                "contingence":         contingence,
                "contingence_pct":     contingence_pct,
                "total_avant_taxes":   avant_taxes,
                "tps":                 tps,
                "tvq":                 tvq,
                "total_ttc":           total_ttc,
            }
            st.session_state.offre_data["soumission"] = soumission_fin

            st.markdown("---")
            offre_tech = st.session_state.offre_data.get("offre_technique")
            if not offre_tech:
                st.warning("⚠️ Rédigez d'abord le **mémoire technique** (onglet précédent).")
            else:
                num_clean = str(analyse.get("nom_projet", "projet")).replace(" ", "_")
                if st.button("⚙️ Générer Word + Excel + PDF", type="primary", key="btn_gen_docs"):
                    with st.spinner("Génération Word…"):
                        st.session_state["pdf_soumission_docx"] = generer_docx(offre_tech, soumission_fin, analyse, user)
                    with st.spinner("Génération Excel…"):
                        st.session_state["pdf_soumission_xlsx"] = generer_xlsx(soumission_fin, analyse, user)
                    with st.spinner("Génération PDF…"):
                        st.session_state["pdf_soumission"] = generer_pdf(offre_tech, soumission_fin, analyse, user)
                    st.success("✅ Documents générés.")
                afficher_telechargements(offre_tech, soumission_fin, num_clean, user, suffix="fin")

    # ── TAB 4 — Validation ────────────────────────────────────────────────
    with tab4:
        st.subheader("5️⃣ Valider la conformité")
        _afficher_offres_en_cours(user)

        soumission = st.session_state.offre_data.get("soumission")
        offre_tech = st.session_state.offre_data.get("offre_technique")

        if not soumission or not offre_tech:
            st.warning("⚠️ Complétez d'abord le chiffrage et le mémoire technique.")
        else:
            if st.button("✅ Lancer la validation automatique", key="btn_validation"):
                offre_complete = {
                    "exigences":        analyse,
                    "offre_technique":  offre_tech,
                    "offre_financiere": soumission,
                    "date_creation":    str(datetime.now()),
                }
                with st.spinner("🔎 Validation en cours…"):
                    conformite = valider_conformite_offre(offre_complete, analyse)
                st.session_state.offre_data["conformite"]     = conformite
                st.session_state.offre_data["offre_complete"] = offre_complete

            if st.session_state.offre_data.get("conformite"):
                conformite  = st.session_state.offre_data["conformite"]
                score_conf  = conformite.get("score_conformite", 0) or 0
                pret        = conformite.get("pret_a_envoyer", False)
                raison_bloc = conformite.get("raison_blocage", "")

                nb_total    = conformite.get("items_ao_total", 0)
                nb_couverts = conformite.get("items_couverts", 0)
                if nb_total:
                    st.progress(nb_couverts / nb_total,
                                text=f"Couverture : {nb_couverts}/{nb_total} items")

                couleur = "🟢" if score_conf >= 80 else "🟡" if score_conf >= 50 else "🔴"
                m1, m2, m3 = st.columns(3)
                m1.metric("Score de conformité", f"{couleur} {score_conf}%")
                if nb_total:
                    m2.metric("Items couverts", f"{nb_couverts}/{nb_total}")
                items_manquants = conformite.get("items_manquants", [])
                m3.metric("Items à corriger", len(items_manquants))

                if pret:
                    st.success("✅ Offre prête à envoyer — tous les items sont couverts")
                elif score_conf >= 50:
                    st.warning(f"⚠️ Partiellement conforme — {raison_bloc}")
                else:
                    st.error(f"🔴 Non conforme — {raison_bloc}")

                # ── CORRECTIONS DIRECTES ────────────────────────────────────
                if items_manquants:
                    st.markdown("---")
                    st.markdown("#### ✏️ Corrections requises — modifiez directement ci-dessous")
                    st.caption("Chaque correction est appliquée immédiatement sur l'offre. "
                               "Relancez la validation après avoir tout corrigé.")

                    for idx_it, it in enumerate(items_manquants):
                        probleme = it.get("probleme", "")
                        no_item  = it.get("no", str(idx_it + 1))
                        desc_it  = it.get("description", "")
                        priorite = it.get("priorite", "normale")
                        section_it = it.get("section", "")

                        emoji_prio = "🔴" if priorite == "critique" else "🟡"
                        with st.expander(
                            f"{emoji_prio} Item {no_item} — {desc_it[:80]} → *{probleme[:60]}*",
                            expanded=(priorite == "critique")
                        ):
                            # Déterminer le type de correction selon le problème
                            prob_lower = probleme.lower()

                            # CAS 1 — Prix manquant dans le bordereau
                            if any(k in prob_lower for k in ["prix", "manquant", "saisir", "compléter"]):
                                st.info("💰 **Prix manquant dans le bordereau financier**")
                                # Trouver l'item dans le bordereau
                                item_trouve = None
                                sec_trouve  = None
                                for sec in st.session_state.offre_data.get("bordereau_ao", []):
                                    for it_b in sec.get("items", []):
                                        if (str(it_b.get("no","")) == str(no_item) or
                                            it_b.get("description","").lower()[:30] == desc_it.lower()[:30]):
                                            item_trouve = it_b
                                            sec_trouve  = sec
                                            break
                                    if item_trouve:
                                        break

                                if item_trouve and sec_trouve:
                                    st.caption(f"Section : **{sec_trouve.get('titre','')}**  "
                                               f"· Unité : {item_trouve.get('unite','forfait')}")
                                    nouveau_prix = st.number_input(
                                        f"Prix unitaire ($)",
                                        value=float(item_trouve.get("prix_unitaire") or 0.0),
                                        min_value=0.0, step=100.0,
                                        key=f"val_prix_{no_item}_{idx_it}"
                                    )
                                    if st.button("💾 Appliquer ce prix",
                                                 key=f"val_apply_{no_item}_{idx_it}",
                                                 type="primary"):
                                        item_trouve["prix_unitaire"] = nouveau_prix
                                        item_trouve["total"]         = round(
                                            nouveau_prix * float(item_trouve.get("quantite") or 1), 2)
                                        item_trouve["a_saisir"]      = False
                                        # Recalculer soumission
                                        total_recalc = sum(
                                            float(i.get("total") or 0)
                                            for s in st.session_state.offre_data.get("bordereau_ao",[])
                                            for i in s.get("items",[])
                                        )
                                        contig_r = st.session_state.offre_data.get("contingence",10)
                                        avant_r  = round(total_recalc * (1 + contig_r/100), 2)
                                        st.session_state.offre_data["soumission"].update({
                                            "sous_total_ht":     total_recalc,
                                            "total_avant_taxes": avant_r,
                                            "tps":               round(avant_r * 0.05,    2),
                                            "tvq":               round(avant_r * 0.09975, 2),
                                            "total_ttc":         round(avant_r * 1.14975, 2),
                                        })
                                        st.session_state.offre_data.pop("conformite", None)
                                        st.success(f"✅ Prix {nouveau_prix:,.2f} $ appliqué. Relancez la validation.")
                                        st.rerun()
                                else:
                                    st.warning("Item non trouvé dans le bordereau. "
                                               "Vérifiez l'onglet **💰 Offre Financière**.")

                            # CAS 2 — Description non conforme / section manquante dans le mémoire
                            elif any(k in prob_lower for k in ["description", "section", "mandat",
                                                                "conformé", "mémoire", "technique"]):
                                st.info("📄 **Section manquante ou non conforme dans le mémoire technique**")
                                c_titre, c_contenu = st.columns([1, 2])
                                titre_fix = c_titre.text_input(
                                    "Titre de la section",
                                    value=desc_it[:60],
                                    key=f"val_titre_{no_item}_{idx_it}"
                                )
                                contenu_fix = c_contenu.text_area(
                                    "Contenu de la section",
                                    placeholder=f"Rédigez ici la section concernant : {desc_it}",
                                    height=100,
                                    key=f"val_contenu_{no_item}_{idx_it}"
                                )
                                if st.button("➕ Ajouter au mémoire technique",
                                             key=f"val_add_sec_{no_item}_{idx_it}",
                                             type="primary",
                                             disabled=not contenu_fix):
                                    ot = st.session_state.offre_data.get("offre_technique", {})
                                    supp = ot.get("sections_supplementaires", [])
                                    supp.append({"titre": titre_fix, "contenu": contenu_fix})
                                    ot["sections_supplementaires"] = supp
                                    st.session_state.offre_data["offre_technique"] = ot
                                    st.session_state.offre_data.pop("conformite", None)
                                    st.success(f"✅ Section «{titre_fix}» ajoutée. Relancez la validation.")
                                    st.rerun()

                            # CAS 3 — Autre problème générique
                            else:
                                st.info(f"📋 **Problème détecté :** {probleme}")
                                contenu_gen = st.text_area(
                                    "Votre correction",
                                    placeholder="Décrivez ou ajoutez l'information manquante…",
                                    height=80,
                                    key=f"val_gen_{no_item}_{idx_it}"
                                )
                                if st.button("➕ Ajouter au mémoire",
                                             key=f"val_gen_add_{no_item}_{idx_it}",
                                             disabled=not contenu_gen):
                                    ot = st.session_state.offre_data.get("offre_technique", {})
                                    supp = ot.get("sections_supplementaires", [])
                                    supp.append({"titre": f"Item {no_item} — {desc_it[:40]}", "contenu": contenu_gen})
                                    ot["sections_supplementaires"] = supp
                                    st.session_state.offre_data["offre_technique"] = ot
                                    st.session_state.offre_data.pop("conformite", None)
                                    st.success("✅ Ajouté. Relancez la validation.")
                                    st.rerun()

                    st.markdown("---")
                    if st.button("🔄 Relancer la validation après corrections",
                                 type="primary", use_container_width=True,
                                 key="btn_revalider"):
                        offre_complete = {
                            "exigences":        analyse,
                            "offre_technique":  st.session_state.offre_data.get("offre_technique", {}),
                            "offre_financiere": st.session_state.offre_data.get("soumission", {}),
                            "date_creation":    str(datetime.now()),
                        }
                        with st.spinner("🔎 Revalidation en cours…"):
                            conformite = valider_conformite_offre(offre_complete, analyse)
                        st.session_state.offre_data["conformite"]     = conformite
                        st.session_state.offre_data["offre_complete"] = offre_complete
                        st.rerun()

                for p in conformite.get("points_manquants", []):
                    st.warning(p)
                for r in conformite.get("recommandations", []):
                    st.info(r)

            st.markdown("---")
            col_rev, col_appr = st.columns(2)
            with col_rev:
                if st.button("🔍 Soumettre pour révision", use_container_width=True, key="btn_revision"):
                    if st.session_state.offre_data.get("offre_complete"):
                        saved = sauvegarder_offre(entreprise_id, "", st.session_state.offre_data["offre_complete"], "brouillon")
                        if saved:
                            st.session_state.offre_data["offre_id"] = saved["id"]
                        st.success("✅ Offre soumise pour révision.")
            with col_appr:
                if st.button("✅ Approuver et préparer l'envoi", type="primary", use_container_width=True, key="btn_approuver"):
                    if st.session_state.offre_data.get("offre_complete"):
                        saved = sauvegarder_offre(entreprise_id, "", st.session_state.offre_data["offre_complete"], "validee")
                        if saved:
                            st.session_state.offre_data["offre_id"] = saved["id"]
                        st.success("✅ Offre approuvée.")

    # ── TAB 5 — Envoi ─────────────────────────────────────────────────────
    with tab5:
        st.subheader("6️⃣ Finaliser et envoyer")

        if not st.session_state.offre_data.get("offre_complete"):
            st.warning("⚠️ Validez d'abord l'offre dans l'onglet Validation.")
        else:
            exigences  = st.session_state.offre_data.get("offre_complete", {}).get("exigences", analyse)
            offre_tech = st.session_state.offre_data.get("offre_technique", {})
            soumission = st.session_state.offre_data.get("soumission", {})

            if "email_offre" not in st.session_state.offre_data:
                with st.spinner("📧 Génération du courriel…"):
                    st.session_state.offre_data["email_offre"] = generer_email_soumission(
                        exigences, offre_tech, user
                    )

            email_data = st.session_state.offre_data["email_offre"]
            exp_email  = user.get("contact_email") or user.get("email", "")
            exp_nom    = user.get("contact_nom") or user.get("prenom_nom", "")

            note_interne = email_data.get("note_interne", "")
            if note_interne:
                st.warning(f"📝 **Note avant envoi :** {note_interne}")

            col_exp, col_dest = st.columns(2)
            with col_exp:
                st.info(f"**De :** {exp_nom}  \n{exp_email}")
            with col_dest:
                email_dest = email_data.get("destinataire_email", "")
                dest_nom   = email_data.get("destinataire_nom", "")
                if email_dest:
                    st.success(f"**À :** {dest_nom or ''} — {email_dest}")
                else:
                    email_dest = st.text_input("Saisir le courriel du destinataire", key="email_dest_manuel")

            sujet = st.text_input("📌 Sujet", value=email_data.get("sujet", ""), key="sujet_courriel")
            corps = st.text_area("✏️ Corps du courriel", value=email_data.get("corps", ""),
                                 height=280, key="corps_courriel")

            st.markdown("---")
            num_clean = str(analyse.get("nom_projet", "projet")).replace(" ", "_")
            if st.button("⚙️ Générer les documents à joindre", type="primary", key="btn_gen_envoi"):
                with st.spinner("Génération Word…"):
                    st.session_state["pdf_soumission_docx"] = generer_docx(offre_tech, soumission, analyse, user)
                with st.spinner("Génération Excel…"):
                    st.session_state["pdf_soumission_xlsx"] = generer_xlsx(soumission, analyse, user)
                with st.spinner("Génération PDF…"):
                    st.session_state["pdf_soumission"] = generer_pdf(offre_tech, soumission, analyse, user)
                st.success("✅ Documents prêts.")

            afficher_telechargements(offre_tech, soumission, num_clean, user, suffix="envoi")

            st.markdown("---")
            texte_complet = f"À : {email_dest}\nDe : {exp_email}\nSujet : {sujet}\n\n{corps}"
            st.code(texte_complet, language=None)
            st.caption("Copiez ce texte dans Outlook ou Gmail, puis joignez les fichiers téléchargés.")

            st.markdown("---")
            if st.button("📤 Confirmer l'envoi de la soumission", type="primary",
                         use_container_width=True, key="btn_confirmer_envoi"):
                offre_id = st.session_state.offre_data.get("offre_id")
                if offre_id:
                    ok = _sauvegarder_statut_offre(offre_id, "envoyee")
                    if ok:
                        st.success("✅ Offre marquée comme **envoyée**.")
                        st.balloons()
                else:
                    saved = sauvegarder_offre(
                        entreprise_id, "",
                        st.session_state.offre_data.get("offre_complete", {}),
                        "envoyee"
                    )
                    if saved:
                        st.session_state.offre_data["offre_id"] = saved["id"]
                        st.success("✅ Offre sauvegardée et envoyée.")
                        st.balloons()

    # ── TAB 6 — Suivi Statut ──────────────────────────────────────────────
    with tab6:
        st.subheader("📊 Suivi du statut de l'offre")

        if not st.session_state.offre_data.get("offre_id"):
            st.info("ℹ️ Sauvegardez et envoyez d'abord votre offre.")
        else:
            statut_suivi = st.selectbox(
                "Nouveau statut",
                ["en_attente_reponse", "acceptee", "refusee"],
                format_func=lambda x: {
                    "en_attente_reponse": "⏳ En attente de réponse",
                    "acceptee":           "🎉 Acceptée",
                    "refusee":            "❌ Refusée",
                }[x]
            )
            if st.button("🔄 Mettre à jour le statut", type="primary", key="btn_update_statut"):
                ok = _sauvegarder_statut_offre(st.session_state.offre_data["offre_id"], statut_suivi)
                if ok:
                    st.success(f"✅ Statut : {statut_suivi}")
                    if statut_suivi == "acceptee":
                        st.balloons()


# ═════════════════════════════════════════════════════════════════════════════
# ONGLET MES OFFRES
# ═════════════════════════════════════════════════════════════════════════════

def _extraire_infos_offre(offre: dict) -> dict:
    """Extrait les infos d'affichage d'une offre depuis son contenu JSON."""
    contenu = offre.get("contenu", {})
    if isinstance(contenu, str):
        try:
            contenu = json.loads(contenu)
        except Exception:
            contenu = {}
    nom = (
        contenu.get("offre_technique", {}).get("titre_offre")
        or contenu.get("exigences", {}).get("nom_projet")
        or f"Offre {offre.get('id', '')[:8]}"
    )
    numero    = contenu.get("exigences", {}).get("numero_projet") or "—"
    client    = contenu.get("exigences", {}).get("client") or "—"
    offre_fin = contenu.get("offre_financiere", {})
    total_ttc = offre_fin.get("total_ttc") or 0
    date_maj  = (offre.get("updated_at") or "")[:10]
    return {
        "nom": nom, "numero": numero, "client": client,
        "total_ttc": total_ttc, "date_maj": date_maj, "contenu": contenu
    }


def show_mes_offres_tab(user: dict) -> None:
    """
    Affiche uniquement les offres envoyées et post-envoi.
    Permet de changer le statut et de démarrer un projet si acceptée.

    Args:
        user: Profil entreprise connecté.
    """
    st.header("📁 Mes Offres")

    try:
        database.apply_supabase_auth()
        result = database.supabase.table("offres").select("*").eq(
            "entreprise_id", user["id"]
        ).in_("statut", STATUTS_MES_OFFRES).order("updated_at", desc=True).execute()
        offres_list = result.data or []
    except Exception as e:
        st.error(f"Erreur chargement : {e}")
        offres_list = []

    if not offres_list:
        st.info(
            "📭 **Aucune offre envoyée pour l'instant.**\n\n"
            "Les offres apparaissent ici une fois confirmées comme envoyées. "
            "Retrouvez vos brouillons dans **Générateur d'Offres → onglet Validation**."
        )
        return

    col_f1, col_f2 = st.columns([2, 1])
    with col_f1:
        recherche = st.text_input("Rechercher", placeholder="Ex: relocalisation, 226-623")
    with col_f2:
        filtre_statut = st.selectbox(
            "Filtrer par statut",
            options=["Tous"] + STATUTS_MES_OFFRES,
            format_func=lambda x: "Tous" if x == "Tous"
                else f"{STATUTS_CFG.get(x, {}).get('emoji','•')} {STATUTS_CFG.get(x, {}).get('label', x)}"
        )

    st.markdown("---")
    nb = 0

    for offre in offres_list:
        statut = offre.get("statut", "envoyee")
        if filtre_statut != "Tous" and statut != filtre_statut:
            continue
        infos = _extraire_infos_offre(offre)
        if recherche:
            terme = recherche.lower()
            if terme not in infos["nom"].lower() and terme not in infos["numero"].lower():
                continue
        nb += 1
        cfg = STATUTS_CFG.get(statut, {"label": statut, "emoji": "•"})

        col1, col2, col3 = st.columns([4, 2, 2])
        with col1:
            st.markdown(f"### {cfg['emoji']} {infos['nom']}")
            st.caption(f"No {infos['numero']}  ·  {infos['client']}  ·  Maj: {infos['date_maj']}")
            if infos["total_ttc"] > 0:
                st.caption(f"**{infos['total_ttc']:,.0f} $ TTC**")
        with col2:
            nouveau = st.selectbox(
                "Statut",
                options=STATUTS_MES_OFFRES,
                index=STATUTS_MES_OFFRES.index(statut) if statut in STATUTS_MES_OFFRES else 0,
                key=f"sel_{offre['id']}",
                format_func=lambda x: f"{STATUTS_CFG.get(x,{}).get('emoji','•')} {STATUTS_CFG.get(x,{}).get('label',x)}",
            )
            if nouveau != statut:
                if st.button("Appliquer", key=f"apply_{offre['id']}"):
                    if _sauvegarder_statut_offre(offre["id"], nouveau):
                        st.success("Statut mis à jour!")
                        st.rerun()
        with col3:
            if statut == "acceptee":
                if st.button("🚀 Démarrer le projet", key=f"projet_{offre['id']}", type="primary"):
                    st.session_state["offre_pour_projet"] = {
                        "id": offre["id"], "nom_projet": infos["nom"],
                        "offre_data": infos["contenu"],
                    }
                    st.success(f"Offre sélectionnée : **{infos['nom']}**")
        st.markdown("---")

    if nb == 0:
        st.warning("Aucune offre ne correspond aux filtres.")