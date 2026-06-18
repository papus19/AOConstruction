"""
Interface utilisateur — Générateur d'offres v2.1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Modifications spec v2.1 :
  ✅ #2  Retrait section "Documents de référence" (gen_upload_ref)
  ✅ #3  Avertissements NO-GO (bloquant) / PEUT-ÊTRE (non bloquant)
  ✅ #6  Section "Offres en cours" dans onglet Validation
  ✅ #7  Boutons "Soumettre révision" / "Approuver" dans Validation
  ✅ #8  Aperçus Word / Excel / PDF avant téléchargement dans Envoi
  ✅ #9  Bouton "Confirmer l'envoi" → statut envoyee dans Envoi
  ✅ #10 Filtrage Mes Offres : uniquement statuts post-envoi
  ✅ #11 Message vide explicite dans Mes Offres
"""
import streamlit as st
from datetime import datetime
import json
import re
import io
import database
import generateur_offres
from extracteur import (
    extraire_texte_multiple,
    feedback_fichiers,
    LABEL_UPLOAD,
    HELP_UPLOAD,
    TYPES_ACCEPTES,
)


# ════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════

def _v(val, defaut="⚠️ Non trouvé dans le document"):
    if val is None or val == "" or val == []:
        return defaut
    return val


def _champs_vides(exigences: dict) -> int:
    return sum(1 for k in [
        "nom_projet", "client", "sommaire", "lieu_travaux", "nature_contrat"
    ] if not exigences.get(k))


def _sauvegarder_statut_offre(offre_id: str, nouveau_statut: str) -> bool:
    """Met à jour le statut d'une offre dans Supabase."""
    try:
        database.apply_supabase_auth()
        database.supabase.table("offres").update({
            "statut":     nouveau_statut,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", offre_id).execute()
        return True
    except Exception as e:
        st.error(f"❌ Erreur mise à jour statut : {e}")
        return False


# ════════════════════════════════════════════════════════════════════
# CYCLE DE VIE DES STATUTS
# ════════════════════════════════════════════════════════════════════

STATUTS_CFG = {
    "brouillon":          {"label": "Brouillon",            "emoji": "📝", "visible_mes_offres": False},
    "en_revision":        {"label": "En révision",           "emoji": "🔍", "visible_mes_offres": False},
    "en_attente_envoi":   {"label": "En attente d'envoi",   "emoji": "⏸️", "visible_mes_offres": False},
    "envoyee":            {"label": "Envoyée",               "emoji": "📤", "visible_mes_offres": True},
    "en_attente_reponse": {"label": "En attente de réponse","emoji": "⏳", "visible_mes_offres": True},
    "acceptee":           {"label": "Acceptée",              "emoji": "🎉", "visible_mes_offres": True},
    "refusee":            {"label": "Refusée",               "emoji": "❌", "visible_mes_offres": True},
    # Anciens statuts supportés pour rétro-compatibilité
    "a_valider":          {"label": "À valider",             "emoji": "📋", "visible_mes_offres": False},
    "validee":            {"label": "Validée",               "emoji": "✅", "visible_mes_offres": True},
    "en_attente":         {"label": "En attente",            "emoji": "⏳", "visible_mes_offres": True},
}

# Statuts visibles dans "Mes Offres" (uniquement après envoi)
STATUTS_MES_OFFRES = [k for k, v in STATUTS_CFG.items() if v["visible_mes_offres"]]

# Statuts des offres en cours (visibles dans l'onglet Validation)
STATUTS_EN_COURS = ["brouillon", "en_revision", "en_attente_envoi", "a_valider"]


# ════════════════════════════════════════════════════════════════════
# SECTION "OFFRES EN COURS" — affichée en haut de l'onglet Validation
# ════════════════════════════════════════════════════════════════════

def _afficher_offres_en_cours(user: dict):
    """
    Affiche les offres en brouillon / en_revision / en_attente_envoi
    dans l'onglet Validation, permettant de les rouvrir.
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
    st.caption("Retrouvez ici toutes vos offres en brouillon, en révision ou en attente d'envoi.")

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
                st.info(f"✅ Offre **{nom}** chargée. Modifiez-la dans les onglets ci-dessus.")

    st.markdown("---")


# ════════════════════════════════════════════════════════════════════
# HELPERS APERÇU DOCUMENTS
# ════════════════════════════════════════════════════════════════════

def _apercu_word_html(offre_tech: dict, exigences: dict, user: dict) -> str:
    """Construit un aperçu HTML fidèle au contenu Word."""
    bleu_f = "#1E3A5F"
    bleu_m = "#2E75B6"
    gris   = "#666"

    def section(titre, contenu):
        return (
            f"<div style='margin-bottom:14px;'>"
            f"<div style='background:{bleu_f};color:white;font-weight:bold;"
            f"font-size:12px;padding:5px 10px;border-radius:3px;margin-bottom:6px;'>"
            f"{titre}</div>"
            f"<div style='font-size:11px;line-height:1.6;color:#212529;padding:0 4px;'>"
            f"{contenu}</div></div>"
        )

    parts = []

    # En-tête
    parts.append(
        f"<div style='text-align:center;padding:16px 0 12px;"
        f"border-bottom:2px solid {bleu_m};margin-bottom:16px;'>"
        f"<div style='font-size:17px;font-weight:bold;color:{bleu_f};'>"
        f"{offre_tech.get('titre_offre') or offre_tech.get('titre','Offre de services')}</div>"
        f"<div style='font-size:12px;color:{bleu_m};margin-top:4px;'>"
        f"{user.get('nom_entreprise','')}</div>"
        f"<div style='font-size:10px;color:{gris};margin-top:3px;'>"
        f"RBQ : {user.get('licence_rbq','')} &nbsp;|&nbsp; "
        f"Préparé pour : {exigences.get('client') or 'le donneur d\u2019ouvrage'}"
        f"</div></div>"
    )

    parts.append(section("1. Introduction", offre_tech.get("introduction", "")))
    parts.append(section("2. Compréhension du projet", offre_tech.get("comprehension_projet") or offre_tech.get("comprehension_mandat", "")))

    approche = offre_tech.get("approche_methodologique", {}) or {}
    phases   = approche.get("phases") or offre_tech.get("methodologie", [])
    phases_html = "".join(
        f"<div style='margin:5px 0 5px 10px;'>"
        f"<span style='font-weight:bold;color:{bleu_m};'>"
        f"{ph.get('nom') or ph.get('phase','')} ({ph.get('duree','')})</span>"
        f" — {ph.get('description','')}</div>"
        for ph in phases
    )
    parts.append(section("3. Approche méthodologique",
        f"{approche.get('description','')}<br>{phases_html}"))

    equipe = offre_tech.get("equipe_proposee") or offre_tech.get("equipe", [])
    eq_html = "".join(
        f"<div style='margin:5px 0 5px 10px;'>"
        f"<span style='font-weight:bold;color:{bleu_m};'>"
        f"{m.get('role','')} : {m.get('nom','')}</span><br>"
        f"<span style='font-size:10px;color:{gris};'>{m.get('experience','')}</span></div>"
        for m in equipe
    )
    parts.append(section("4. Équipe proposée", eq_html))

    livrables = offre_tech.get("livrables", [])
    lv_html   = "".join(
        f"<div style='margin:3px 0 3px 10px;'>• <b>{l.get('nom','')}</b>"
        f" — {l.get('description','')} "
        f"<span style='color:{gris};font-size:10px;'>({l.get('format','')})</span></div>"
        for l in livrables
    )
    parts.append(section("5. Livrables", lv_html))

    garanties = offre_tech.get("garanties_qualite") or offre_tech.get("garanties", [])
    gar_html  = "".join(f"<div style='margin:3px 0 3px 10px;'>• {g}</div>" for g in garanties)
    parts.append(section("6. Garanties de qualité", gar_html))

    avantages = offre_tech.get("avantages_concurrentiels", [])
    av_html   = "".join(f"<div style='margin:3px 0 3px 10px;'>• {a}</div>" for a in avantages)
    if av_html:
        parts.append(section("7. Avantages concurrentiels", av_html))

    return (
        f"<div style='background:white;border:1px solid #dee2e6;"
        f"border-radius:6px;padding:16px 20px;font-family:Georgia,serif;"
        f"max-height:480px;overflow-y:auto;'>{''.join(parts)}</div>"
    )


def _apercu_excel_html(offre_fin: dict) -> str:
    """Construit un aperçu HTML du tableau financier."""
    postes     = offre_fin.get("postes") or offre_fin.get("postes_budgetaires", [])
    sous_total = offre_fin.get("sous_total_ht") or offre_fin.get("total_ht", 0)
    tps        = offre_fin.get("tps", sous_total * 0.05)
    tvq        = offre_fin.get("tvq", sous_total * 0.09975)
    ttc        = offre_fin.get("total_ttc", 0)
    th         = offre_fin.get("total_heures", 0)

    rows = "".join(
        f"<tr style='background:{'#f5f7fa' if i % 2 == 0 else '#fff'};'>"
        f"<td style='padding:5px 8px;border:1px solid #dee2e6;'>{p.get('description','')}</td>"
        f"<td style='padding:5px 8px;border:1px solid #dee2e6;text-align:center;'>"
        f"{p.get('jours', (p.get('heures',0) or 0)//8)}</td>"
        f"<td style='padding:5px 8px;border:1px solid #dee2e6;text-align:center;'>"
        f"{p.get('heures') or p.get('quantite',0)}</td>"
        f"<td style='padding:5px 8px;border:1px solid #dee2e6;text-align:right;'>"
        f"${p.get('taux') or p.get('prix_unitaire',0):,.2f}</td>"
        f"<td style='padding:5px 8px;border:1px solid #dee2e6;text-align:right;font-weight:bold;'>"
        f"${p.get('total',0):,.2f}</td></tr>"
        for i, p in enumerate(postes)
    )

    return f"""
<table style='width:100%;font-size:11px;border-collapse:collapse;'>
  <tr style='background:#1e3a5f;color:white;'>
    <th style='padding:6px 8px;text-align:left;'>Description</th>
    <th style='padding:6px 8px;'>Jours</th>
    <th style='padding:6px 8px;'>Heures</th>
    <th style='padding:6px 8px;'>Taux $/h</th>
    <th style='padding:6px 8px;'>Montant</th>
  </tr>
  {rows}
  <tr style='background:#e8f0fe;'>
    <td colspan='2' style='padding:5px 8px;border:1px solid #dee2e6;'>
      <b>Total : {th:.0f} h</b></td>
    <td colspan='2' style='padding:5px 8px;border:1px solid #dee2e6;text-align:right;'>
      Sous-total HT</td>
    <td style='padding:5px 8px;border:1px solid #dee2e6;text-align:right;font-weight:bold;'>
      ${sous_total:,.2f}</td>
  </tr>
  <tr style='background:#e8f0fe;'>
    <td colspan='4' style='padding:5px 8px;border:1px solid #dee2e6;text-align:right;'>
      TPS (5 %)</td>
    <td style='padding:5px 8px;border:1px solid #dee2e6;text-align:right;'>${tps:,.2f}</td>
  </tr>
  <tr style='background:#e8f0fe;'>
    <td colspan='4' style='padding:5px 8px;border:1px solid #dee2e6;text-align:right;'>
      TVQ (9,975 %)</td>
    <td style='padding:5px 8px;border:1px solid #dee2e6;text-align:right;'>${tvq:,.2f}</td>
  </tr>
  <tr style='background:#1e3a5f;color:white;font-weight:bold;'>
    <td colspan='4' style='padding:6px 8px;text-align:right;'>TOTAL TTC</td>
    <td style='padding:6px 8px;text-align:right;font-size:13px;'>${ttc:,.2f}</td>
  </tr>
</table>"""


# ════════════════════════════════════════════════════════════════════
# ONGLET GÉNÉRATEUR D'OFFRES
# ════════════════════════════════════════════════════════════════════

def show_offres_tab(user, projets_antecedents):
    st.header("📝 Générateur d'Offres")

    # ── Charger toutes les soumissions ────────────────────────────
    try:
        database.apply_supabase_auth()
        res = database.supabase.table("soumissions").select("*").eq(
            "entreprise_id", user["id"]
        ).order("created_at", desc=True).execute()
        soumissions_list = res.data if res.data else []
    except Exception as e:
        st.error(f"❌ Erreur chargement : {str(e)}")
        soumissions_list = []

    if not soumissions_list:
        st.info("📭 Aucune soumission trouvée. Analysez d'abord des appels d'offres dans l'onglet **Nouvelle analyse**.")
        return

    # ── Sélection projet ──────────────────────────────────────────
    st.subheader("1️⃣ Sélectionner un projet analysé")

    # Construire les options avec codes couleur dans le label
    def _label_soumission(x):
        rec   = x.get("recommendation", "?")
        score = x.get("score", 0)
        emoji = {"GO": "🟢", "PEUT-ÊTRE": "🟡", "NO-GO": "🔴"}.get(rec, "⚪")
        return f"{emoji} {x.get('nom_projet', 'Sans nom')} — {rec} — Score: {score}/100"

    soumission_selectionnee = st.selectbox(
        "Projet",
        options=soumissions_list,
        format_func=_label_soumission,
    )

    if not soumission_selectionnee:
        return

    # ════════════════════════════════════════════════════════════════
    # ✅ CHANGEMENT #3 — Avertissements NO-GO / PEUT-ÊTRE
    # ════════════════════════════════════════════════════════════════
    rec   = soumission_selectionnee.get("recommendation", "INCONNU")
    score = soumission_selectionnee.get("score", 0)

    # Extraire les points faibles depuis l'analyse pour les afficher
    points_faibles_raw = soumission_selectionnee.get("points_faibles", "")
    if isinstance(points_faibles_raw, str):
        points_faibles = [l.strip("•- ").strip() for l in points_faibles_raw.split("\n") if l.strip()]
    elif isinstance(points_faibles_raw, list):
        points_faibles = points_faibles_raw
    else:
        points_faibles = []

    if rec == "NO-GO":
        st.error(
            f"⛔ **Recommandation NO-GO** (score {score}/100)\n\n"
            f"Ce projet a été identifié comme non rentable ou trop risqué lors de l'analyse."
        )
        if points_faibles:
            st.markdown("**Risques critiques identifiés :**")
            for pf in points_faibles[:5]:
                st.error(f"• {pf}")
        # Case à cocher OBLIGATOIRE — bloque la suite si non cochée
        accepte_risque = st.checkbox(
            "⚠️ Je comprends les risques et souhaite quand même générer une offre pour ce projet.",
            key="checkbox_nogo"
        )
        if not accepte_risque:
            st.stop()

    elif rec == "PEUT-ÊTRE":
        st.warning(
            f"⚠️ **Recommandation PEUT-ÊTRE** (score {score}/100)\n\n"
            f"Ce projet présente des incertitudes. Évaluez bien les points ci-dessous avant de continuer."
        )
        if points_faibles:
            st.markdown("**Points d'attention :**")
            for pf in points_faibles[:5]:
                st.warning(f"• {pf}")
        # Non bloquant — l'utilisateur peut continuer sans cocher

    elif rec == "GO":
        st.success(f"✅ **Recommandation GO** — Score {score}/100 — Projet favorable.")

    # ── Init état de session ──────────────────────────────────────
    if "offre_data" not in st.session_state:
        st.session_state.offre_data = {}

    # ── Tabs ──────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📂 Extraction",
        "🔧 Offre Technique",
        "💰 Offre Financière",
        "✅ Validation",
        "📤 Envoi",
        "📊 Suivi Statut",
    ])

    # ════════════════════════════════════════════════════════════════
    # TAB 1 — EXTRACTION
    # ════════════════════════════════════════════════════════════════
    with tab1:
        st.subheader("2️⃣ Extraire les exigences")

        analyse_json = soumission_selectionnee.get("analyse_json") or {}
        if isinstance(analyse_json, str):
            try:
                analyse_json = json.loads(analyse_json)
            except Exception:
                analyse_json = {}

        st.markdown("##### Option A — Utiliser les données de l'analyse existante")
        if st.button("⚡ Pré-remplir depuis l'analyse sélectionnée", type="primary"):
            raw = analyse_json.get("raw_response", "")
            exigences_prefill = {
                "numero_projet":         soumission_selectionnee.get("numero_projet") or None,
                "nom_projet":            soumission_selectionnee.get("nom_projet") or None,
                "client":                None,
                "contact_email":         None,
                "contact_nom":           None,
                "contact_telephone":     None,
                "date_cloture":          None,
                "date_visite":           None,
                "duree_projet":          None,
                "budget_estime":         None,
                "lieu_travaux":          None,
                "nature_contrat":        None,
                "sommaire":              f"Analyse existante — Score {score}/100",
                "sections_demandees":    [],
                "exigences_techniques":  [],
                "documents_requis":      [],
                "criteres_evaluation":   [],
                "remarques_importantes": [],
            }
            if raw:
                import re as _re
                email_match = _re.search(r"[\w.\-+]+@[\w.\-]+\.[a-z]{2,}", raw, _re.IGNORECASE)
                if email_match:
                    exigences_prefill["contact_email"] = email_match.group(0)
                date_match = _re.search(r"(\d{4}[-/]\d{2}[-/]\d{2})", raw)
                if date_match:
                    exigences_prefill["date_cloture"] = date_match.group(1)
            st.session_state.offre_data["exigences"] = exigences_prefill
            st.success(
                f"✅ Données pré-remplies depuis **{soumission_selectionnee.get('nom_projet', '')}**. "
                "Complétez les champs manquants ou uploadez le document pour une extraction complète."
            )
            st.rerun()

        # ════════════════════════════════════════════════════════
        # ✅ CHANGEMENT #2 — Section "Documents de référence" RETIRÉE
        # Seule la zone d'upload des documents AO reste
        # ════════════════════════════════════════════════════════
        st.markdown("##### Option B — Extraire depuis un nouveau document")
        uploaded_files = st.file_uploader(
            label=LABEL_UPLOAD,
            type=TYPES_ACCEPTES,
            accept_multiple_files=True,
            key="offre_docs",
            help=HELP_UPLOAD,
        )
        feedback_fichiers(uploaded_files)

        if uploaded_files and st.button("🔍 Extraire les exigences depuis le document"):
            with st.spinner("🤖 Extraction en cours…"):
                try:
                    texte = extraire_texte_multiple(uploaded_files)
                    if not texte.strip():
                        st.error("❌ Aucun texte extrait. Si le PDF est scanné, vérifiez que Poppler et Tesseract sont installés.")
                    else:
                        exigences = generateur_offres.extraire_exigences_appel_offre(texte)
                        if exigences:
                            st.session_state.offre_data["exigences"] = exigences
                            st.success("✅ Exigences extraites !")
                        else:
                            st.error("❌ Impossible d'extraire les exigences.")
                except Exception as e:
                    st.error(f"❌ Erreur : {str(e)}")

        # Affichage résultats + édition manuelle
        if st.session_state.offre_data.get("exigences"):
            exigences = st.session_state.offre_data["exigences"]
            nb_vides  = _champs_vides(exigences)

            if nb_vides >= 3:
                st.warning("⚠️ **Informations incomplètes** — Complétez les champs manquants avant de générer l'offre.")
            else:
                st.success("✅ Exigences prêtes")

            col1, col2, col3 = st.columns(3)
            col1.metric("Projet", _v(exigences.get("numero_projet"), "Non trouvé"))
            col2.metric("Client", _v(exigences.get("client"), "Non trouvé"))
            col3.metric("Durée",  _v(exigences.get("duree_projet"), "Non trouvée"))

            with st.expander("✏️ Compléter / corriger les informations", expanded=(nb_vides >= 3)):
                c1, c2 = st.columns(2)
                with c1:
                    val_nom = st.text_input("Nom du projet",     value=exigences.get("nom_projet") or "",    key="edit_ex_nom")
                    val_cli = st.text_input("Client",            value=exigences.get("client") or "",        key="edit_ex_client")
                    val_lie = st.text_input("Lieu des travaux",  value=exigences.get("lieu_travaux") or "",  key="edit_ex_lieu")
                    val_nat = st.text_input("Nature du contrat", value=exigences.get("nature_contrat") or "",key="edit_ex_nature")
                with c2:
                    val_dat = st.text_input("Date de clôture",   value=exigences.get("date_cloture") or "",  key="edit_ex_date")
                    val_dur = st.text_input("Durée du projet",   value=exigences.get("duree_projet") or "",  key="edit_ex_duree")
                    val_ema = st.text_input("Courriel contact",  value=exigences.get("contact_email") or "", key="edit_ex_email")
                    val_bud = st.text_input("Budget estimé",     value=exigences.get("budget_estime") or "", key="edit_ex_budget")
                val_som = st.text_area("Sommaire / description",
                    value=exigences.get("sommaire") or "", height=100, key="edit_ex_sommaire")

                if st.button("💾 Appliquer les corrections", type="primary"):
                    exigences.update({
                        "nom_projet":     val_nom or exigences.get("nom_projet"),
                        "client":         val_cli or exigences.get("client"),
                        "lieu_travaux":   val_lie or exigences.get("lieu_travaux"),
                        "nature_contrat": val_nat or exigences.get("nature_contrat"),
                        "date_cloture":   val_dat or exigences.get("date_cloture"),
                        "duree_projet":   val_dur or exigences.get("duree_projet"),
                        "contact_email":  val_ema or exigences.get("contact_email"),
                        "budget_estime":  val_bud or exigences.get("budget_estime"),
                        "sommaire":       val_som or exigences.get("sommaire"),
                    })
                    st.session_state.offre_data["exigences"] = exigences
                    st.success("✅ Informations mises à jour !")
                    st.rerun()

            with st.expander("📋 Voir le détail des exigences"):
                st.markdown(f"**Nom projet :** {_v(exigences.get('nom_projet'))}")
                st.markdown(f"**Date clôture :** {_v(exigences.get('date_cloture'))}")
                st.markdown(f"**Lieu des travaux :** {_v(exigences.get('lieu_travaux'))}")
                st.markdown(f"**Sommaire :** {_v(exigences.get('sommaire'))}")

                items_meth = exigences.get("sections_demandees") or exigences.get("methodologie_requise") or []
                st.markdown("**Méthodologie / Sections demandées :**")
                for item in (items_meth or ["⚠️ Non trouvé dans le document"]):
                    st.write(f"  • {item}")

                livrables_ex = exigences.get("livrables") or []
                st.markdown("**Livrables attendus :**")
                for item in (livrables_ex or ["⚠️ Non trouvé dans le document"]):
                    st.write(f"  • {item}")

                exig_tech = exigences.get("exigences_techniques") or []
                st.markdown("**Exigences techniques :**")
                for item in (exig_tech or ["⚠️ Non trouvé dans le document"]):
                    st.write(f"  • {item}")

                email = exigences.get("contact_email")
                if email:
                    st.success(f"📧 Courriel détecté : **{email}**")
                else:
                    st.warning("⚠️ Aucun courriel trouvé dans le document.")
                    email_manuel = st.text_input("Entrez le courriel du responsable", key="email_manuel_tab1")
                    if email_manuel:
                        st.session_state.offre_data["exigences"]["contact_email"] = email_manuel

    # ════════════════════════════════════════════════════════════════
    # TAB 2 — OFFRE TECHNIQUE
    # ════════════════════════════════════════════════════════════════
    with tab2:
        st.subheader("3️⃣ Générer l'offre technique")

        if not st.session_state.offre_data.get("exigences"):
            st.warning("⚠️ Extrayez d'abord les exigences (onglet Extraction)")
        else:
            exigences = st.session_state.offre_data["exigences"]
            nb_vides  = _champs_vides(exigences)

            st.markdown("##### 🏗️ Projets antérieurs à valoriser dans l'offre")
            projets_choisis = []
            if projets_antecedents:
                options_proj = {
                    f"{p['nom_projet']} ({p.get('montant', '?')}$)": p
                    for p in projets_antecedents
                }
                choix_proj = st.multiselect(
                    "Projets similaires à mettre en valeur",
                    list(options_proj.keys()),
                    default=list(options_proj.keys())[:3]
                )
                projets_choisis = [options_proj[c] for c in choix_proj]
            else:
                st.info("Aucun projet antérieur — ajoutez-en dans la sidebar.")

            if st.button("🤖 Générer l'offre technique"):
                if nb_vides >= 4:
                    st.error(
                        "⛔ **Génération bloquée** — Trop peu d'informations extraites. "
                        "Retournez à l'onglet Extraction et chargez un meilleur document."
                    )
                else:
                    with st.spinner("🤖 Génération en cours…"):
                        try:
                            offre_tech = generateur_offres.generer_offre_technique(
                                exigences, projets_choisis, user
                            )
                            if offre_tech:
                                st.session_state.offre_data["offre_technique"] = offre_tech
                                st.success("✅ Offre technique générée !")
                                st.rerun()
                        except Exception as e:
                            st.error(f"❌ Erreur : {str(e)}")

            if st.session_state.offre_data.get("offre_technique"):
                offre_tech = st.session_state.offre_data["offre_technique"]
                st.success("✅ Toutes les sections sont modifiables ci-dessous")
                st.markdown("---")

                offre_tech["titre_offre"] = st.text_input(
                    "✏️ Titre de l'offre", value=offre_tech.get("titre_offre", ""), key="edit_titre"
                )

                st.markdown("### 1. Introduction")
                offre_tech["introduction"] = st.text_area(
                    "Introduction", value=offre_tech.get("introduction", ""), height=150, key="edit_intro"
                )

                st.markdown("### 2. Compréhension du projet")
                offre_tech["comprehension_projet"] = st.text_area(
                    "Compréhension du projet", value=offre_tech.get("comprehension_projet", ""),
                    height=150, key="edit_comprehension"
                )

                st.markdown("### 3. Approche méthodologique")
                approche = offre_tech.setdefault("approche_methodologique", {})
                approche["description"] = st.text_area(
                    "Description de l'approche", value=approche.get("description", ""),
                    height=120, key="edit_approche_desc"
                )

                st.markdown("#### Phases du projet")
                phases = approche.setdefault("phases", [])
                phases_a_supprimer = []
                for i, phase in enumerate(phases):
                    with st.expander(f"Phase {i+1} : {phase.get('nom', 'Nouvelle phase')}", expanded=False):
                        phase["nom"]         = st.text_input("Nom",         value=phase.get("nom", ""),         key=f"phase_nom_{i}")
                        phase["duree"]       = st.text_input("Durée",        value=phase.get("duree", ""),       key=f"phase_duree_{i}")
                        phase["description"] = st.text_area("Description",   value=phase.get("description", ""), height=100, key=f"phase_desc_{i}")
                        if st.button("🗑️ Supprimer", key=f"phase_del_{i}"):
                            phases_a_supprimer.append(i)
                for idx in sorted(phases_a_supprimer, reverse=True):
                    phases.pop(idx)
                if st.button("➕ Ajouter une phase"):
                    phases.append({"nom": "Nouvelle phase", "duree": "X jours", "description": ""})
                    st.rerun()

                st.markdown("### 4. Équipe proposée")
                equipe = offre_tech.setdefault("equipe_proposee", [])
                membres_a_supprimer = []
                for i, membre in enumerate(equipe):
                    with st.expander(f"👤 {membre.get('nom', 'Nouveau membre')} — {membre.get('role', '')}", expanded=False):
                        col1, col2 = st.columns(2)
                        with col1:
                            membre["nom"]        = st.text_input("Nom",        value=membre.get("nom", ""),        key=f"mb_nom_{i}")
                            membre["role"]       = st.text_input("Rôle",       value=membre.get("role", ""),       key=f"mb_role_{i}")
                        with col2:
                            membre["experience"] = st.text_input("Expérience", value=membre.get("experience", ""), key=f"mb_exp_{i}")
                        resp_text = "\n".join(membre.get("responsabilites", []))
                        new_resp  = st.text_area("Responsabilités (une par ligne)", value=resp_text, height=80, key=f"mb_resp_{i}")
                        membre["responsabilites"] = [r.strip() for r in new_resp.split("\n") if r.strip()]
                        if st.button("🗑️ Supprimer", key=f"mb_del_{i}"):
                            membres_a_supprimer.append(i)
                for idx in sorted(membres_a_supprimer, reverse=True):
                    equipe.pop(idx)
                if st.button("➕ Ajouter un membre"):
                    equipe.append({"nom": "", "role": "", "experience": "", "responsabilites": []})
                    st.rerun()

                st.markdown("### 5. Livrables")
                livrables = offre_tech.setdefault("livrables", [])
                livrables_a_supprimer = []
                for i, livrable in enumerate(livrables):
                    with st.expander(f"📄 {livrable.get('nom', 'Nouveau livrable')}", expanded=False):
                        livrable["nom"]         = st.text_input("Nom",        value=livrable.get("nom", ""),         key=f"lv_nom_{i}")
                        livrable["description"] = st.text_area("Description", value=livrable.get("description", ""), height=80, key=f"lv_desc_{i}")
                        livrable["format"]      = st.text_input("Format",      value=livrable.get("format", "PDF"),   key=f"lv_fmt_{i}")
                        if st.button("🗑️ Supprimer", key=f"lv_del_{i}"):
                            livrables_a_supprimer.append(i)
                for idx in sorted(livrables_a_supprimer, reverse=True):
                    livrables.pop(idx)
                if st.button("➕ Ajouter un livrable"):
                    livrables.append({"nom": "", "description": "", "format": "PDF"})
                    st.rerun()

                st.markdown("### 6. Garanties qualité")
                garanties_text = "\n".join(offre_tech.get("garanties_qualite", []))
                new_garanties  = st.text_area("Garanties (une par ligne)", value=garanties_text, height=100, key="edit_garanties")
                offre_tech["garanties_qualite"] = [g.strip() for g in new_garanties.split("\n") if g.strip()]

                st.markdown("### 7. Avantages concurrentiels")
                avantages_text = "\n".join(offre_tech.get("avantages_concurrentiels", []))
                new_avantages  = st.text_area("Avantages (un par ligne)", value=avantages_text, height=100, key="edit_avantages")
                offre_tech["avantages_concurrentiels"] = [a.strip() for a in new_avantages.split("\n") if a.strip()]

                if st.button("💾 Sauvegarder les modifications", type="primary"):
                    st.session_state.offre_data["offre_technique"] = offre_tech
                    st.success("✅ Modifications sauvegardées !")

    # ════════════════════════════════════════════════════════════════
    # TAB 3 — OFFRE FINANCIÈRE
    # ════════════════════════════════════════════════════════════════
    with tab3:
        st.subheader("4️⃣ Générer l'offre financière")

        if not st.session_state.offre_data.get("offre_technique"):
            st.warning("⚠️ Générez d'abord l'offre technique")
        else:
            col1, col2 = st.columns(2)
            with col1:
                taux_horaire = st.number_input(
                    "💵 Taux horaire ($/h)", min_value=50, max_value=500,
                    value=125, step=5, key="taux_horaire_input"
                )
            with col2:
                if st.button("💰 Calculer l'offre financière"):
                    try:
                        offre_fin = generateur_offres.calculer_offre_financiere(
                            st.session_state.offre_data["offre_technique"], taux_horaire
                        )
                        if offre_fin:
                            st.session_state.offre_data["offre_financiere"] = offre_fin
                            st.success("✅ Offre financière calculée !")
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erreur : {str(e)}")

            if st.session_state.offre_data.get("offre_financiere"):
                offre_fin   = st.session_state.offre_data["offre_financiere"]
                sous_total  = offre_fin.get("sous_total_ht") or offre_fin.get("total_ht", 0)
                taxes       = offre_fin.get("taxes_totales") or offre_fin.get("taxes", 0)
                total_ttc   = offre_fin.get("total_ttc", 0)
                total_h     = offre_fin.get("total_heures", 0)
                tps         = offre_fin.get("tps", sous_total * 0.05)
                tvq         = offre_fin.get("tvq", sous_total * 0.09975)
                postes      = offre_fin.get("postes") or offre_fin.get("postes_budgetaires", [])

                st.success("✅ Offre financière disponible")
                st.markdown("### 📊 Détail des coûts")

                with st.expander("✏️ Modifier les postes budgétaires", expanded=False):
                    for i, poste in enumerate(postes):
                        st.markdown(f"#### Poste {i+1}: {poste.get('description', '')}")
                        c1, c2, c3 = st.columns(3)
                        qte_actuelle = poste.get("heures") or poste.get("quantite", 0)
                        prix_actuel  = poste.get("taux")   or poste.get("prix_unitaire", taux_horaire)
                        with c1:
                            nouvelle_qte = st.number_input("Heures", min_value=0, value=int(qte_actuelle), step=1, key=f"qte_{i}")
                        with c2:
                            nouveau_prix = st.number_input("Taux ($/h)", min_value=0, value=int(prix_actuel), step=5, key=f"prix_{i}")
                        with c3:
                            st.metric("Total", f"{nouvelle_qte * nouveau_prix:,.2f} $")
                        poste["heures"] = nouvelle_qte
                        poste["taux"]   = nouveau_prix
                        poste["total"]  = nouvelle_qte * nouveau_prix
                        st.markdown("---")

                    if st.button("💾 Recalculer les totaux", type="primary"):
                        nouveau_ht = sum(p.get("total", 0) for p in postes)
                        offre_fin.update({
                            "postes":        postes,
                            "sous_total_ht": nouveau_ht,
                            "total_ht":      nouveau_ht,
                            "tps":           nouveau_ht * 0.05,
                            "tvq":           nouveau_ht * 0.09975,
                            "taxes_totales": nouveau_ht * 0.14975,
                            "taxes":         nouveau_ht * 0.14975,
                            "total_ttc":     nouveau_ht * 1.14975,
                            "total_heures":  sum(p.get("heures", p.get("quantite", 0)) for p in postes),
                        })
                        st.session_state.offre_data["offre_financiere"] = offre_fin
                        st.success("✅ Totaux recalculés !")
                        st.rerun()

                st.markdown("### 📋 Récapitulatif")
                for poste in postes:
                    c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                    c1.write(f"**{poste.get('description', '')}**")
                    c2.write(f"{poste.get('heures', poste.get('quantite', 0))} h")
                    c3.write(f"{poste.get('taux', poste.get('prix_unitaire', 0))} $/h")
                    c4.write(f"**{poste.get('total', 0):,.2f} $**")

                st.markdown("---")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total heures",  f"{total_h:.0f} h")
                c2.metric("Sous-total HT", f"{sous_total:,.2f} $")
                c3.metric("TPS + TVQ",     f"{taxes:,.2f} $")
                c4.metric("TOTAL TTC",     f"{total_ttc:,.2f} $")

                # Génération des documents (bouton)
                st.markdown("---")
                st.markdown("#### 📥 Générer les documents")
                num       = (st.session_state.offre_data.get("exigences") or {}).get("numero_projet") or "projet"
                num_clean = num.replace(" ", "_")

                if st.button("⚙️ Générer tous les documents", type="primary"):
                    with st.spinner("Génération DOCX…"):
                        st.session_state["_docx_bytes"] = generateur_offres._generer_docx(
                            st.session_state.offre_data["offre_technique"], offre_fin,
                            st.session_state.offre_data.get("exigences", {}), user)
                    with st.spinner("Génération Excel…"):
                        st.session_state["_xlsx_bytes"] = generateur_offres._generer_xlsx(
                            offre_fin, st.session_state.offre_data.get("exigences", {}), user)
                    with st.spinner("Génération PDF…"):
                        st.session_state["_pdf_bytes"] = generateur_offres._generer_pdf_combine(
                            st.session_state.offre_data["offre_technique"], offre_fin,
                            st.session_state.offre_data.get("exigences", {}), user)
                    st.success("✅ Documents générés — consultez les aperçus et téléchargements ci-dessous.")

                _afficher_telechargements(
                    st.session_state.offre_data.get("offre_technique", {}),
                    offre_fin,
                    num_clean, user, suffix="fin"
                )

    # ════════════════════════════════════════════════════════════════
    # TAB 4 — VALIDATION
    # ════════════════════════════════════════════════════════════════
    with tab4:
        st.subheader("5️⃣ Valider la conformité")

        # ════════════════════════════════════════════════════════
        # ✅ CHANGEMENT #6 — Section "Offres en cours" en haut
        # ════════════════════════════════════════════════════════
        _afficher_offres_en_cours(user)

        if not st.session_state.offre_data.get("offre_financiere"):
            st.warning("⚠️ Complétez d'abord l'offre financière dans l'onglet précédent.")
        else:
            if st.button("✅ Lancer la validation automatique"):
                try:
                    offre_complete = {
                        "exigences":       st.session_state.offre_data.get("exigences", {}),
                        "offre_technique": st.session_state.offre_data.get("offre_technique", {}),
                        "offre_financiere": st.session_state.offre_data.get("offre_financiere", {}),
                        "date_creation":   str(datetime.now()),
                    }
                    conformite = generateur_offres.valider_conformite_offre(
                        offre_complete,
                        st.session_state.offre_data["exigences"]
                    )
                    st.session_state.offre_data["conformite"]     = conformite
                    st.session_state.offre_data["offre_complete"] = offre_complete
                except Exception as e:
                    st.error(f"❌ Erreur validation : {str(e)}")

            if st.session_state.offre_data.get("conformite"):
                conformite = st.session_state.offre_data["conformite"]
                score_conf = conformite.get("score_conformite", conformite.get("score", 0)) or 0

                col_score, col_statut = st.columns([1, 3])
                with col_score:
                    couleur = "🟢" if score_conf >= 80 else "🟡" if score_conf >= 50 else "🔴"
                    st.metric("Score de conformité", f"{couleur} {score_conf}%")
                with col_statut:
                    if score_conf >= 80:
                        st.success("✅ Offre conforme — prête à soumettre")
                    elif score_conf >= 50:
                        st.warning("⚠️ Partiellement conforme — vous pouvez continuer")
                    else:
                        st.error("🔴 Score faible — vérifiez les points signalés")

                if conformite.get("points_conformes"):
                    st.markdown("#### ✅ Points conformes")
                    for p in conformite["points_conformes"]:
                        st.success(p)

                if conformite.get("points_manquants"):
                    st.markdown("#### ⚠️ Points à vérifier")
                    st.info("Ces points sont non-bloquants.")
                    for p in conformite["points_manquants"]:
                        st.warning(p)

                if conformite.get("recommandations"):
                    st.markdown("### 💡 Recommandations")
                    for r in conformite["recommandations"]:
                        st.info(r)

            # ════════════════════════════════════════════════════
            # ✅ CHANGEMENT #7 — Boutons de transition de statut
            # Remplace l'ancien selectbox de statut
            # ════════════════════════════════════════════════════
            st.markdown("---")
            st.subheader("📋 Prochaine étape")

            col_rev, col_appr = st.columns(2)

            with col_rev:
                if st.button(
                    "🔍 Soumettre pour révision interne",
                    use_container_width=True,
                    key="btn_revision"
                ):
                    if st.session_state.offre_data.get("offre_complete"):
                        try:
                            saved = generateur_offres.sauvegarder_offre(
                                user["id"],
                                soumission_selectionnee["id"],
                                st.session_state.offre_data["offre_complete"],
                                "en_revision"
                            )
                            if saved:
                                st.session_state.offre_data["offre_id"] = saved["id"]
                            st.success("✅ Offre soumise pour révision. Retrouvez-la dans la section **Offres en cours** ci-dessus.")
                        except Exception as e:
                            st.error(f"❌ Erreur : {e}")
                    else:
                        st.warning("⚠️ Lancez d'abord la validation automatique.")

            with col_appr:
                if st.button(
                    "✅ Approuver et préparer l'envoi",
                    type="primary",
                    use_container_width=True,
                    key="btn_approuver"
                ):
                    if st.session_state.offre_data.get("offre_complete"):
                        try:
                            saved = generateur_offres.sauvegarder_offre(
                                user["id"],
                                soumission_selectionnee["id"],
                                st.session_state.offre_data["offre_complete"],
                                "en_attente_envoi"
                            )
                            if saved:
                                st.session_state.offre_data["offre_id"] = saved["id"]
                            st.success("✅ Offre approuvée. Passez à l'onglet **Envoi** pour confirmer la transmission.")
                        except Exception as e:
                            st.error(f"❌ Erreur : {e}")
                    else:
                        st.warning("⚠️ Lancez d'abord la validation automatique.")

    # ════════════════════════════════════════════════════════════════
    # TAB 5 — ENVOI
    # ════════════════════════════════════════════════════════════════
    with tab5:
        st.subheader("6️⃣ Finaliser et envoyer")

        if not st.session_state.offre_data.get("offre_complete"):
            st.warning("⚠️ Validez d'abord l'offre dans l'onglet **Validation**")
        else:
            exigences  = st.session_state.offre_data.get("exigences", {})
            offre_tech = st.session_state.offre_data.get("offre_technique", {})
            offre_fin  = st.session_state.offre_data.get("offre_financiere", {})

            # Générer le courriel si pas encore fait
            if "email_offre" not in st.session_state.offre_data:
                with st.spinner("📧 Génération du courriel…"):
                    email_data = generateur_offres.generer_email_soumission(exigences, offre_tech, user)
                    st.session_state.offre_data["email_offre"] = email_data

            email_data = st.session_state.offre_data["email_offre"]
            exp_email  = user.get("contact_email") or user.get("email", "")
            exp_nom    = user.get("contact_nom") or user.get("prenom_nom", "")

            # Infos d'envoi
            st.markdown("### 📋 Informations d'envoi")
            col_exp, col_dest = st.columns(2)
            with col_exp:
                st.info(f"**De :** {exp_nom}  \n{exp_email}")
            with col_dest:
                email_dest = email_data.get("destinataire_email", "")
                if email_dest:
                    st.success(f"**À :** {email_dest}")
                else:
                    st.warning("⚠️ Aucun courriel destinataire trouvé dans le document.")
                    email_dest = st.text_input(
                        "Saisir le courriel du destinataire",
                        placeholder="ex: appels.offres@organisation.ca",
                        key="email_dest_manuel"
                    )

            sujet = st.text_input("📌 Sujet", value=email_data.get("sujet", ""), key="sujet_courriel")
            st.markdown("✏️ **Corps du courriel** (modifiable)")
            corps = st.text_area(
                label="Corps",
                label_visibility="collapsed",
                value=email_data.get("corps", ""),
                height=280,
                key="corps_courriel"
            )

            with st.expander("👁️ Aperçu rendu du courriel", expanded=False):
                import re as _re
                corps_html = corps.replace("\n\n", "<br><br>").replace("\n", "<br>")
                corps_html = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", corps_html)
                st.markdown(
                    f"""<div style='background:#f8f9fa;border:1px solid #dee2e6;border-radius:8px;
                    padding:20px;font-family:Georgia,serif;font-size:14px;line-height:1.7;color:#212529;'>
                    <div style='margin-bottom:12px;color:#6c757d;font-size:12px;'>
                    <b>À :</b> {email_dest or "(destinataire)"}<br>
                    <b>De :</b> {exp_email}<br>
                    <b>Objet :</b> {sujet}
                    </div>
                    <hr style='border-color:#dee2e6;margin:12px 0;'>
                    {corps_html}
                    </div>""",
                    unsafe_allow_html=True
                )

            st.markdown("---")

            # ════════════════════════════════════════════════════
            # ✅ CHANGEMENT #8 — Aperçus + téléchargements dans Envoi
            # ════════════════════════════════════════════════════
            st.markdown("### 📎 Pièces jointes")
            st.info(
                "💡 Générez les documents, consultez les aperçus, "
                "puis téléchargez-les pour les joindre à votre courriel."
            )

            num       = exigences.get("numero_projet") or "projet"
            num_clean = num.replace(" ", "_")

            if st.button("⚙️ Générer les documents à joindre", type="primary", key="btn_gen_docs_envoi"):
                with st.spinner("Génération DOCX…"):
                    st.session_state["pdf_soumission_docx"] = generateur_offres._generer_docx(
                        offre_tech, offre_fin, exigences, user)
                with st.spinner("Génération Excel…"):
                    st.session_state["pdf_soumission_xlsx"] = generateur_offres._generer_xlsx(
                        offre_fin, exigences, user)
                with st.spinner("Génération PDF…"):
                    st.session_state["pdf_soumission"] = generateur_offres._generer_pdf_combine(
                        offre_tech, offre_fin, exigences, user)
                st.success("✅ Documents prêts — consultez les aperçus ci-dessous avant de télécharger.")

            _afficher_telechargements(offre_tech, offre_fin, num_clean, user, suffix="envoi")

            # Bloc copier-coller
            st.markdown("---")
            st.markdown("### 📋 Copier pour votre client courriel")
            texte_complet = f"À : {email_dest}\nDe : {exp_email}\nSujet : {sujet}\n\n{corps}"
            st.code(texte_complet, language=None)
            st.caption("Copiez ce texte, collez-le dans Outlook ou Gmail, puis joignez les fichiers téléchargés.")

            # ════════════════════════════════════════════════════
            # ✅ CHANGEMENT #9 — Bouton "Confirmer l'envoi" → statut envoyee
            # ════════════════════════════════════════════════════
            st.markdown("---")
            st.markdown("### 📤 Confirmer l'envoi de la soumission")
            st.info(
                "Une fois votre courriel envoyé manuellement depuis Outlook ou Gmail, "
                "cliquez sur le bouton ci-dessous pour mettre à jour le statut de votre offre. "
                "Elle apparaîtra ensuite dans l'onglet **Mes Offres**."
            )

            if st.button(
                "📤 Confirmer l'envoi de la soumission",
                type="primary",
                use_container_width=True,
                key="btn_confirmer_envoi"
            ):
                offre_id = st.session_state.offre_data.get("offre_id")
                if offre_id:
                    # Mettre à jour le statut en base
                    ok = _sauvegarder_statut_offre(offre_id, "envoyee")
                    if ok:
                        st.success(
                            "✅ Offre marquée comme **envoyée**. "
                            "Elle est maintenant visible dans l'onglet **Mes Offres** "
                            "où vous pourrez suivre la réponse du client."
                        )
                        st.balloons()
                else:
                    # Sauvegarder l'offre directement avec le statut envoyee
                    try:
                        saved = generateur_offres.sauvegarder_offre(
                            user["id"],
                            soumission_selectionnee["id"],
                            st.session_state.offre_data["offre_complete"],
                            "envoyee"
                        )
                        if saved:
                            st.session_state.offre_data["offre_id"] = saved["id"]
                            st.success(
                                "✅ Offre sauvegardée et marquée comme **envoyée**. "
                                "Elle est maintenant visible dans **Mes Offres**."
                            )
                            st.balloons()
                    except Exception as e:
                        st.error(f"❌ Erreur : {e}")

    # ════════════════════════════════════════════════════════════════
    # TAB 6 — SUIVI STATUT
    # ════════════════════════════════════════════════════════════════
    with tab6:
        st.subheader("📊 Suivi du statut de l'offre")

        if not st.session_state.offre_data.get("offre_id"):
            st.info("ℹ️ Sauvegardez d'abord votre offre pour accéder au suivi.")
        else:
            st.success(f"✅ Projet : **{soumission_selectionnee.get('nom_projet', '')}**")

            statut_suivi = st.selectbox(
                "Nouveau statut",
                ["en_attente_reponse", "acceptee", "refusee"],
                format_func=lambda x: {
                    "en_attente_reponse": "⏳ En attente de réponse",
                    "acceptee":           "🎉 Acceptée par le client",
                    "refusee":            "❌ Refusée par le client",
                }[x]
            )

            if statut_suivi == "acceptee":
                st.success("🎉 Si acceptée, l'offre sera accessible dans **Gestion de Projet**.")
            if statut_suivi == "refusee":
                st.text_area("Raison du refus (optionnel)", height=80, key="raison_refus")

            if st.button("🔄 Mettre à jour le statut", type="primary"):
                ok = _sauvegarder_statut_offre(
                    st.session_state.offre_data["offre_id"], statut_suivi
                )
                if ok:
                    st.success(f"✅ Statut mis à jour : {statut_suivi}")
                    if statut_suivi == "acceptee":
                        st.balloons()
                        st.success("🚀 Rendez-vous dans l'onglet **Gestion de Projet** !")

            st.markdown("---")
            st.markdown("### 📜 Historique")
            try:
                database.apply_supabase_auth()
                offre_actuelle = database.supabase.table("offres").select("*").eq(
                    "id", st.session_state.offre_data["offre_id"]
                ).execute()
                if offre_actuelle.data:
                    offre = offre_actuelle.data[0]
                    c1, c2 = st.columns(2)
                    c1.metric("Statut actuel",       offre["statut"].upper())
                    c2.metric("Dernière mise à jour", offre["updated_at"][:10])
            except Exception as e:
                st.error(f"Erreur chargement : {str(e)}")


# ════════════════════════════════════════════════════════════════════
# HELPER CENTRALISÉ — APERÇUS + TÉLÉCHARGEMENTS
# Utilisé dans Tab 3 (Offre Financière) ET Tab 5 (Envoi)
# ════════════════════════════════════════════════════════════════════

def _afficher_telechargements(offre_tech: dict, offre_fin: dict,
                               num_clean: str, user: dict, suffix: str = ""):
    """
    Affiche les 3 blocs aperçu + téléchargement (Word, Excel, PDF).
    Réutilisé dans l'onglet Offre Financière et dans l'onglet Envoi.
    """
    exigences  = st.session_state.offre_data.get("exigences", {})
    docx_bytes = st.session_state.get("pdf_soumission_docx") or st.session_state.get("_docx_bytes")
    xlsx_bytes = st.session_state.get("pdf_soumission_xlsx") or st.session_state.get("_xlsx_bytes")
    pdf_bytes  = st.session_state.get("pdf_soumission")      or st.session_state.get("_pdf_bytes")

    col_w, col_x, col_p = st.columns(3)

    # ── WORD ─────────────────────────────────────────────────────
    with col_w:
        st.markdown("**📄 Offre Technique (Word)**")
        if docx_bytes:
            with st.expander("👁️ Aperçu Word", expanded=False):
                apercu_html = _apercu_word_html(offre_tech, exigences, user)
                st.markdown(apercu_html, unsafe_allow_html=True)
            st.download_button(
                "⬇️ Télécharger le Word",
                data=docx_bytes,
                file_name=f"Offre_Technique_{num_clean}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"dl_docx_{suffix}",
                use_container_width=True,
            )
        else:
            st.info("Générez d'abord les documents.")

    # ── EXCEL ────────────────────────────────────────────────────
    with col_x:
        st.markdown("**📊 Offre Financière (Excel)**")
        if xlsx_bytes:
            with st.expander("👁️ Aperçu Excel", expanded=False):
                st.markdown(_apercu_excel_html(offre_fin), unsafe_allow_html=True)
            st.download_button(
                "⬇️ Télécharger l'Excel",
                data=xlsx_bytes,
                file_name=f"Offre_Financiere_{num_clean}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_xlsx_{suffix}",
                use_container_width=True,
            )
        else:
            st.info("Générez d'abord les documents.")

    # ── PDF ──────────────────────────────────────────────────────
    with col_p:
        st.markdown("**📑 Offre Complète (PDF)**")
        if pdf_bytes:
            import base64 as _b64
            b64_pdf = _b64.b64encode(pdf_bytes).decode()
            with st.expander("👁️ Aperçu PDF", expanded=False):
                st.markdown(
                    f'<iframe src="data:application/pdf;base64,{b64_pdf}" '
                    f'width="100%" height="480px" '
                    f'style="border:1px solid #dee2e6;border-radius:4px;"></iframe>',
                    unsafe_allow_html=True
                )
                st.caption("Si le PDF ne s'affiche pas, utilisez Chrome ou Firefox.")
            st.download_button(
                "⬇️ Télécharger le PDF",
                data=pdf_bytes,
                file_name=f"Offre_Complete_{num_clean}.pdf",
                mime="application/pdf",
                key=f"dl_pdf_{suffix}",
                use_container_width=True,
            )
        else:
            st.info("Générez d'abord les documents.")


# ════════════════════════════════════════════════════════════════════
# ONGLET MES OFFRES
# ════════════════════════════════════════════════════════════════════

def _extraire_infos_offre(offre: dict) -> dict:
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
    return {"nom": nom, "numero": numero, "client": client,
            "total_ttc": total_ttc, "date_maj": date_maj, "contenu": contenu}


def show_mes_offres_tab(user):
    """
    Affiche uniquement les offres envoyées et post-envoi.
    ✅ CHANGEMENT #10 — Filtrage par STATUTS_MES_OFFRES
    ✅ CHANGEMENT #11 — Message vide explicite
    """
    st.header("Mes Offres")

    try:
        database.apply_supabase_auth()
        # ════════════════════════════════════════════════════════
        # ✅ CHANGEMENT #10 — Uniquement statuts post-envoi
        # Les brouillons / en_revision / en_attente_envoi
        # ne sont PAS affichés ici → voir onglet Validation
        # ════════════════════════════════════════════════════════
        result = database.supabase.table("offres").select("*").eq(
            "entreprise_id", user["id"]
        ).in_("statut", STATUTS_MES_OFFRES).order("updated_at", desc=True).execute()
        offres_list = result.data or []
    except Exception as e:
        st.error(f"Erreur chargement : {str(e)}")
        offres_list = []

    # ════════════════════════════════════════════════════════════
    # ✅ CHANGEMENT #11 — Message vide explicite avec redirection
    # ════════════════════════════════════════════════════════════
    if not offres_list:
        st.info(
            "📭 **Aucune offre envoyée pour l'instant.**\n\n"
            "Les offres apparaissent ici une fois confirmées comme envoyées au client.\n\n"
            "👉 Retrouvez vos offres en cours (**brouillons, en révision, en attente**) "
            "dans le **Générateur d'Offres → onglet Validation**."
        )
        return

    # Filtres
    col_f1, col_f2 = st.columns([2, 1])
    with col_f1:
        recherche = st.text_input("Rechercher par nom ou numéro", placeholder="Ex: relocalisation, 226-623")
    with col_f2:
        filtre_statut = st.selectbox(
            "Filtrer par statut",
            options=["Tous"] + STATUTS_MES_OFFRES,
            format_func=lambda x: "Tous les statuts" if x == "Tous"
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
            st.markdown("**Statut actuel**")
            st.markdown(f"{cfg['emoji']} {cfg['label'].upper()}")
            nouveau = st.selectbox(
                "Nouveau statut",
                options=STATUTS_MES_OFFRES,
                index=STATUTS_MES_OFFRES.index(statut) if statut in STATUTS_MES_OFFRES else 0,
                key=f"sel_{offre['id']}",
                format_func=lambda x: f"{STATUTS_CFG.get(x,{}).get('emoji','•')} {STATUTS_CFG.get(x,{}).get('label',x)}",
                label_visibility="collapsed"
            )
            if nouveau != statut:
                if st.button("Appliquer", key=f"apply_{offre['id']}"):
                    if _sauvegarder_statut_offre(offre["id"], nouveau):
                        st.success("Statut mis à jour !")
                        st.rerun()

        with col3:
            if st.button("Voir le détail", key=f"detail_{offre['id']}"):
                st.session_state["offre_detail_id"]   = offre["id"]
                st.session_state["offre_detail_data"] = offre

            if statut == "acceptee":
                if st.button("🚀 Démarrer le projet", key=f"projet_{offre['id']}", type="primary"):
                    st.session_state["offre_pour_projet"] = {
                        "id":            offre["id"],
                        "nom_projet":    infos["nom"],
                        "projet_numero": infos["numero"],
                        "offre_data":    infos["contenu"],
                    }
                    st.success(f"Offre sélectionnée : **{infos['nom']}** — Allez dans **Gestion de Projet**.")

        st.markdown("---")

    if nb == 0:
        st.warning("Aucune offre ne correspond aux filtres sélectionnés.")

    # Panneau détail
    if st.session_state.get("offre_detail_id"):
        offre_d    = st.session_state.get("offre_detail_data", {})
        infos_d    = _extraire_infos_offre(offre_d)
        contenu    = infos_d["contenu"]
        offre_tech = contenu.get("offre_technique", {})
        offre_fin  = contenu.get("offre_financiere", {})

        st.markdown("---")
        st.markdown(f"## Détail — {infos_d['nom']}")

        if st.button("✕ Fermer le détail"):
            del st.session_state["offre_detail_id"]
            del st.session_state["offre_detail_data"]
            st.rerun()

        ca, cb = st.columns(2)
        with ca:
            st.markdown(f"**Client :** {infos_d['client']}")
            st.markdown(f"**Numéro :** {infos_d['numero']}")
        with cb:
            cfg_d = STATUTS_CFG.get(offre_d.get("statut", ""), {"emoji": "•", "label": ""})
            st.markdown(f"**Statut :** {cfg_d['emoji']} {cfg_d['label']}")
            st.markdown(f"**Dernière MAJ :** {infos_d['date_maj']}")

        tabs_d = st.tabs(["Offre Technique", "Offre Financière", "Exigences"])

        with tabs_d[0]:
            if offre_tech:
                st.markdown(f"**{offre_tech.get('titre_offre', '')}**")
                st.write(offre_tech.get("introduction", ""))
                phases = offre_tech.get("approche_methodologique", {}).get("phases", [])
                if phases:
                    st.markdown("**Phases**")
                    for p in phases:
                        st.markdown(f"- **{p.get('nom','')}** ({p.get('duree','')}) : {p.get('description','')}")
                equipe = offre_tech.get("equipe_proposee", [])
                if equipe:
                    st.markdown("**Équipe**")
                    for m in equipe:
                        st.markdown(f"- {m.get('role','')} : **{m.get('nom','')}**")
            else:
                st.info("Aucune offre technique disponible.")

        with tabs_d[1]:
            sous_total = offre_fin.get("sous_total_ht") or offre_fin.get("total_ht", 0)
            taxes      = offre_fin.get("taxes_totales") or offre_fin.get("taxes", 0)
            total_ttc  = offre_fin.get("total_ttc", 0)
            postes     = offre_fin.get("postes") or offre_fin.get("postes_budgetaires", [])

            if total_ttc > 0:
                for p in postes:
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(p.get("description", ""))
                    c2.write(f"{p.get('heures', p.get('quantite', 0))} h")
                    c3.write(f"{p.get('total', 0):,.0f} $")
                st.markdown("---")
                ca, cb, cc = st.columns(3)
                ca.metric("Sous-total HT", f"{sous_total:,.0f} $")
                cb.metric("Taxes",         f"{taxes:,.0f} $")
                cc.metric("TOTAL TTC",     f"{total_ttc:,.0f} $")
            else:
                st.info("Aucune offre financière disponible.")

        with tabs_d[2]:
            exigences = contenu.get("exigences", {})
            if exigences:
                st.markdown(f"**Projet :** {_v(exigences.get('nom_projet'))}")
                st.markdown(f"**Client :** {_v(exigences.get('client'))}")
                st.markdown(f"**Clôture :** {_v(exigences.get('date_cloture'))}")
                st.markdown(f"**Durée :** {_v(exigences.get('duree_projet'))}")
                st.markdown(f"**Sommaire :** {_v(exigences.get('sommaire'))}")
            else:
                st.info("Aucune exigence disponible.")