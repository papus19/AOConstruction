"""
MOKAFAD - Solution Soumission IA
Application principale v3.7
Changements vs v3.6 :
  - Import mes_offres (nouveau module)
  - Sidebar : ajout mes_offres.show_sidebar_offres(user) après les boutons nav
  - Onglet tab4 "Mes Offres" : remplacé par mes_offres.show_mes_offres_tab(user)
"""
import streamlit as st
import config
import database
import ui_components
import auth
import profile
import dashboard
import analyse
import projets
import generateur_offres
import devis_cmeq
import projet_documents as pdocs
import gestion_projets
import mes_offres          # ← NOUVEAU


# ── Configuration de la page ──────────────────────────────────────────
st.set_page_config(
    page_title="MOKAFAD - Solution Soumission IA",
    page_icon="⚡",
    layout="wide"
)

# ── Vérification des clés ─────────────────────────────────────────────
if not config.SUPABASE_URL or not config.SUPABASE_ANON_KEY:
    st.error("Variables manquantes dans .env")
    st.stop()

# ── Initialisation de la session ──────────────────────────────────────
for key, default in [
    ('logged_in',         False),
    ('user',              None),
    ('profile_completed', False),
    ('access_token',      None),
    ('show_login_tab',    True),
    ('default_tab',       0),
    ('sidebar_section',   'dashboard'),
    ('analyse_result',    None),
    ('analyse_texte_ao',  ""),
    ('offre_generee',     None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── En-tête ───────────────────────────────────────────────────────────
ui_components.display_header()

# ── CSS global ────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap');

.stTabs [data-baseweb="tab-list"] {
  gap: 4px; background: #f1f5f9; padding: 6px;
  border-radius: 12px; border: 1px solid #e2e8f0;
}
.stTabs [data-baseweb="tab"] {
  font-family: 'DM Sans', sans-serif !important;
  font-size: 14px !important; font-weight: 500 !important;
  color: #475569 !important; padding: 10px 18px !important;
  border-radius: 8px !important; border: none !important;
  background: transparent !important; white-space: nowrap !important;
}
.stTabs [data-baseweb="tab"]:hover { background: #ffffff !important; color: #1e293b !important; }
.stTabs [aria-selected="true"] {
  background: #ffffff !important; color: #1e6fe8 !important;
  font-weight: 600 !important; box-shadow: 0 1px 3px rgba(0,0,0,0.1) !important;
}
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }
.stTabs [data-baseweb="tab-border"]    { display: none !important; }

section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e2e8f0; }
.stApp { background: #f4f6f9; }
</style>
""", unsafe_allow_html=True)

# ── Auth Supabase ─────────────────────────────────────────────────────
if st.session_state.logged_in and st.session_state.access_token:
    database.apply_supabase_auth()


# ════════════════════════════════════════════════════════════════════
# ONGLETS PRINCIPAUX
# ════════════════════════════════════════════════════════════════════

def _render_main_tabs(user, projets_antecedents):

    # ── Synchronisation automatique texte_ao ────────────────────
    pdocs._init()
    texte_ao_sync = pdocs.texte_ao_complet()
    if texte_ao_sync.strip():
        st.session_state["analyse_texte_ao"] = texte_ao_sync
        st.session_state["texte_ao_courant"] = texte_ao_sync

    docs_ok    = pdocs.est_complet()
    n_docs_ok  = sum(1 for ok in docs_ok.values() if ok)
    label_docs = f"📂 Documents ({n_docs_ok}/4)" if n_docs_ok > 0 else "📂 Documents du projet"

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🔍 Nouvelle analyse",
        "📝 Générateur d'Offres",
        label_docs,
        "📁 Mes Offres",
        "📋 Gestion de Projet",
        "📐 Grille CMEQ",
    ])

    # ── Onglet 1 : Analyse ───────────────────────────────────────
    with tab1:
        _show_analyse_avec_callback(user, projets_antecedents)

    # ── Onglet 2 : Générateur d'offres ───────────────────────────
    with tab2:
        analyse_courante = st.session_state.get("analyse_result")

        if analyse_courante is None:
            st.info(
                "📋 **Aucune analyse en cours.**\n\n"
                "Pour générer une offre, commencez par analyser un appel d'offres dans "
                "l'onglet **🔍 Nouvelle analyse**, puis revenez ici.\n\n"
                "Ou reprenez une offre existante depuis **📁 Mes Offres** ou la sidebar."
            )
            st.markdown("---")
            st.markdown("#### Ou sélectionnez une analyse existante :")
            try:
                database.apply_supabase_auth()
                res = database.supabase.table("soumissions").select(
                    "id, nom_projet, numero_projet, recommendation, score, created_at"
                ).eq("entreprise_id", user["id"]).order("created_at", desc=True).limit(10).execute()
                soumissions = res.data if res and res.data else []
            except Exception:
                soumissions = []

            if soumissions:
                choix = st.selectbox(
                    "Reprendre une analyse existante",
                    options=soumissions,
                    format_func=lambda x: (
                        f"{'🟢' if x.get('recommendation')=='GO' else '🟡' if x.get('recommendation')=='PEUT-ÊTRE' else '🔴'} "
                        f"{x.get('nom_projet','Sans nom')} — Score: {x.get('score',0)}/100"
                    ),
                    key="select_soumission_existante"
                )
                if st.button("▶️ Utiliser cette analyse", type="primary", key="btn_charger_analyse"):
                    st.session_state["analyse_result"] = choix
                    st.session_state["analyse_texte_ao"] = ""
                    st.rerun()
            else:
                st.warning("Aucune soumission trouvée. Analysez d'abord un appel d'offres.")
        else:
            if st.session_state.get("offre_generee") is None:
                st.session_state.pop("offre_generee", None)

            try:
                generateur_offres.show_generateur_tab(
                    user     = user,
                    analyse  = analyse_courante if isinstance(analyse_courante, dict) else None,
                    texte_ao = st.session_state.get("analyse_texte_ao", "") or "",
                )
            except Exception as e:
                st.error(f"Erreur générateur d'offres : {e}")
                import traceback; st.code(traceback.format_exc())

    # ── Onglet 3 : Documents du projet ───────────────────────────
    with tab3:
        st.header("📂 Documents du projet")
        st.markdown(
            "Chargez ici tous les documents reçus pour ce projet d'appel d'offres. "
            "Classez-les par catégorie — le **Générateur d'Offres** s'en servira "
            "automatiquement pour rédiger l'offre technique et l'offre financière."
        )
        st.markdown("---")
        try:
            docs_complets = pdocs.show_chargement_documents(key_prefix="app_tab3")
            texte_ao_sync = (
                pdocs.texte_invitation()
                + ("\n\n" if pdocs.texte_invitation() else "")
                + pdocs.texte_cahier_charges()
            ).strip()
            if texte_ao_sync:
                st.session_state["analyse_texte_ao"] = texte_ao_sync

            if docs_complets:
                st.markdown("---")
                st.success(
                    "✅ Documents complets — Passez maintenant à l'onglet "
                    "**📝 Générateur d'Offres** pour générer l'offre."
                )
                if st.button("▶️ Aller au Générateur d'Offres →", type="primary",
                             key="btn_goto_generateur_depuis_docs"):
                    st.session_state["_goto_tab"] = 2
                    st.rerun()
        except Exception as e:
            st.error(f"Erreur Documents : {e}")
            import traceback; st.code(traceback.format_exc())

    # ── Onglet 4 : Mes Offres ─────────────────────────────────────
    with tab4:
        try:
            mes_offres.show_mes_offres_tab(user)
        except Exception as e:
            st.error(f"Erreur Mes Offres : {e}")
            import traceback; st.code(traceback.format_exc())

    # ── Onglet 5 : Gestion de projet ─────────────────────────────
    with tab5:
        try:
            gestion_projets.show_gestion_projets_tab(user)
        except Exception as e:
            st.error(f"Erreur Gestion de Projet : {e}")
            import traceback; st.code(traceback.format_exc())

    # ── Onglet 6 : Grille CMEQ ───────────────────────────────────
    with tab6:
        try:
            devis_cmeq.show_devis_cmeq_tab(user)
        except Exception as e:
            st.error(f"Erreur grille CMEQ : {e}")
            import traceback; st.code(traceback.format_exc())


def _show_analyse_avec_callback(user, projets_antecedents):
    avant  = st.session_state.get("last_analyse")
    result = analyse.show_analyse_tab(user, projets_antecedents)

    if result and isinstance(result, dict):
        st.session_state["analyse_result"]   = result.get("analyse") or result
        st.session_state["analyse_texte_ao"] = result.get("texte_ao", "")

    apres = st.session_state.get("last_analyse")
    if apres and apres != avant and isinstance(apres, dict):
        st.session_state["analyse_result"]   = apres.get("analyse") or apres
        st.session_state["analyse_texte_ao"] = apres.get("texte_ao", "")

    if st.session_state.get("analyse_result"):
        st.markdown("---")
        if st.button("📝 Générer une offre →", type="primary",
                     use_container_width=True, key="btn_goto_generateur_tab1"):
            st.session_state["_goto_tab"] = 1
            st.info("✅ Analyse transférée ! Cliquez sur l'onglet **Générateur d'Offres**.")


# ════════════════════════════════════════════════════════════════════
# AUTHENTIFICATION
# ════════════════════════════════════════════════════════════════════

if not st.session_state.logged_in:
    tab1, tab2 = st.tabs(["Connexion", "Inscription"])
    with tab1:
        auth.show_login_page()
    with tab2:
        auth.show_signup_page()

elif not st.session_state.profile_completed:
    profile.show_profile_completion()

else:
    user = st.session_state.user

    try:
        database.apply_supabase_auth()
        projets_response = (
            database.supabase
            .table("projets_antecedents")
            .select("*, projet_documents(*)")
            .eq("entreprise_id", user["id"])
            .order("created_at", desc=True)
            .execute()
        )
        projets_antecedents = projets_response.data or []
    except Exception as e:
        st.warning(f"⚠️ Erreur chargement projets : {e}")
        projets_antecedents = []

    # ── SIDEBAR ───────────────────────────────────────────────────
    with st.sidebar:
        ui_components.display_logo_sidebar(user)
        st.write(f"**{user.get('contact_nom', 'Utilisateur')}**")
        st.write(f"**{user.get('nom_entreprise', 'Entreprise')}**")
        st.write(f"{user.get('ville', '')}, {user.get('province', '')}")

        st.markdown("---")
        st.markdown("##### Navigation")

        if st.button("📊 Tableau de bord", key="nav_dashboard", use_container_width=True):
            st.session_state.sidebar_section = "dashboard"; st.rerun()

        nb_projets = len(projets_antecedents)
        nb_docs    = sum(len(p.get("projet_documents") or []) for p in projets_antecedents)
        label_proj = f"🏗️ Projets ({nb_projets})" if nb_projets else "🏗️ Projets"
        if nb_docs:
            label_proj += f" · {nb_docs} doc{'s' if nb_docs > 1 else ''}"

        if st.button(label_proj, key="nav_projets", use_container_width=True):
            st.session_state.sidebar_section = "projets"; st.rerun()

        if st.button("👤 Mon profil", key="nav_profil", use_container_width=True):
            st.session_state.sidebar_section = "profil"; st.rerun()

        if st.button("🛠️ Espace de travail", key="nav_travail", use_container_width=True):
            st.session_state.sidebar_section = "travail"; st.rerun()

        if st.session_state.get("analyse_result"):
            st.markdown("---")
            nom_p = st.session_state["analyse_result"].get("nom_projet", "")
            st.success(f"✅ Analyse prête\n\n_{nom_p}_")
            if st.button("📝 Générer l'offre", key="nav_gen_offre", use_container_width=True):
                st.session_state.sidebar_section = "travail"; st.rerun()

        mes_offres.show_sidebar_offres(user)

        st.markdown("---")
        labels = {
            "dashboard": "📊 Tableau de bord",
            "projets":   "🏗️ Projets antérieurs",
            "profil":    "👤 Mon profil",
            "travail":   "🛠️ Espace de travail",
        }
        active = st.session_state.get("sidebar_section", "dashboard")
        st.caption(f"Vue active : **{labels.get(active, active)}**")

        # ── Modèle LLM — lu depuis session_state (mis à jour par analyse.py) ──
        # Affiché uniquement après une analyse — pas de fallback sur provider_actif()
        # pour éviter d'afficher Gemini alors que c'est Groq qui a répondu.
        llm_actif = st.session_state.get("llm_dernier_provider")
        if llm_actif:
            st.caption(f"🤖 Modèle IA : `{llm_actif}`")

        st.markdown("---")
        if st.button("🚪 Déconnexion", use_container_width=True):
            try:
                database.supabase.auth.sign_out()
            except Exception:
                pass
            st.session_state.clear()
            st.rerun()

    # ── CONTENU PRINCIPAL ─────────────────────────────────────────
    active = st.session_state.get("sidebar_section", "dashboard")

    if active == "dashboard":
        dashboard.show_dashboard(user)
    elif active == "projets":
        projets.show_projets_tab(user)
    elif active == "profil":
        profile.show_profile_tab(user)
    else:
        _render_main_tabs(user, projets_antecedents)