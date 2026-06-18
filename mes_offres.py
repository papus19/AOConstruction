"""
mes_offres.py — Tableau de bord des offres
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Responsabilités :
  - show_sidebar_offres(user)  → bloc compact dans la sidebar
  - show_mes_offres_tab(user)  → onglet principal complet

Intégration dans app.py :
    import mes_offres
    mes_offres.show_sidebar_offres(user)   # dans le bloc with st.sidebar
    mes_offres.show_mes_offres_tab(user)   # dans l'onglet tab4
"""

import json
from datetime import datetime

import streamlit as st
import database

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG STATUTS
# ─────────────────────────────────────────────────────────────────────────────

STATUTS = {
    "brouillon":          {"label": "Brouillon",     "emoji": "📝", "color": "#6c757d", "groupe": "en_cours"},
    "en_revision":        {"label": "En révision",   "emoji": "🔍", "color": "#fd7e14", "groupe": "en_cours"},
    "a_valider":          {"label": "À valider",     "emoji": "📋", "color": "#fd7e14", "groupe": "en_cours"},
    "validee":            {"label": "Validée",       "emoji": "✅", "color": "#20c997", "groupe": "en_cours"},
    "en_attente_envoi":   {"label": "Att. envoi",    "emoji": "⏸️", "color": "#ffc107", "groupe": "en_cours"},
    "envoyee":            {"label": "Envoyée",       "emoji": "📤", "color": "#0d6efd", "groupe": "envoyee"},
    "en_attente_reponse": {"label": "Att. réponse",  "emoji": "⏳", "color": "#0dcaf0", "groupe": "envoyee"},
    "en_attente":         {"label": "En attente",    "emoji": "⏳", "color": "#0dcaf0", "groupe": "envoyee"},
    "acceptee":           {"label": "Acceptée",      "emoji": "🎉", "color": "#198754", "groupe": "terminee"},
    "refusee":            {"label": "Refusée",       "emoji": "❌", "color": "#dc3545", "groupe": "terminee"},
}

GROUPES = {
    "en_cours":  {"label": "🔧 En cours",  "statuts": ["brouillon","en_revision","a_valider","validee","en_attente_envoi"]},
    "envoyee":   {"label": "📤 Envoyées",  "statuts": ["envoyee","en_attente_reponse","en_attente"]},
    "terminee":  {"label": "🏁 Terminées","statuts": ["acceptee","refusee"]},
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _charger_offres(entreprise_id: str) -> list:
    try:
        database.apply_supabase_auth()
        res = (
            database.supabase.table("offres")
            .select("*")
            .eq("entreprise_id", entreprise_id)
            .order("updated_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        st.error(f"Erreur chargement offres : {e}")
        return []


def _parse_contenu(offre: dict) -> dict:
    c = offre.get("contenu", {})
    if isinstance(c, str):
        try:
            return json.loads(c)
        except Exception:
            return {}
    return c or {}


def _infos(offre: dict) -> dict:
    contenu   = _parse_contenu(offre)
    exigences = contenu.get("exigences") or {}
    fin       = contenu.get("offre_financiere") or {}
    tech      = contenu.get("offre_technique") or {}
    projet    = exigences.get("projet") or {}

    nom = (
        tech.get("titre_offre")
        or exigences.get("nom_projet")
        or projet.get("nom")
        or f"Offre {str(offre.get('id',''))[:8]}"
    )
    return {
        "nom":       nom,
        "numero":    exigences.get("numero_projet") or projet.get("numero") or "—",
        "client":    exigences.get("client") or "—",
        "lieu":      exigences.get("lieu") or projet.get("lieu") or "—",
        "section":   exigences.get("section") or "—",
        "total_ttc": float(fin.get("total_ttc") or 0),
        "date_maj":  str(offre.get("updated_at", ""))[:10],
        "date_cree": str(offre.get("created_at", ""))[:10],
        "contenu":   contenu,
    }


def _badge(statut: str) -> str:
    cfg = STATUTS.get(statut, {"emoji": "•", "label": statut, "color": "#aaa"})
    return (
        f"<span style='background:{cfg['color']};color:white;padding:2px 10px;"
        f"border-radius:12px;font-size:11px;font-weight:600;white-space:nowrap;'>"
        f"{cfg['emoji']} {cfg['label']}</span>"
    )


def _sauvegarder_statut(offre_id: str, statut: str) -> bool:
    try:
        database.apply_supabase_auth()
        database.supabase.table("offres").update({"statut": statut}).eq("id", offre_id).execute()
        return True
    except Exception as e:
        st.error(f"Erreur mise à jour statut : {e}")
        return False


def _reprendre_offre(offre: dict) -> None:
    """
    Charge une offre sauvegardée en session et redirige vers
    l'onglet Générateur d'Offres pour continuer le travail.
    """
    contenu   = _parse_contenu(offre)
    exigences = contenu.get("exigences") or {}
    inf       = _infos(offre)

    # Restaurer offre_data complet en session
    st.session_state["offre_data"] = {
        "offre_id":         offre.get("id"),
        "exigences":        exigences,
        "offre_technique":  contenu.get("offre_technique"),
        "soumission":       contenu.get("offre_financiere"),
        "offre_financiere": contenu.get("offre_financiere"),
        "bordereau_ao":     contenu.get("bordereau_ao", []),
        "contingence":      contenu.get("contingence", 10),
        "offre_complete":   contenu,
        "conformite":       None,
    }

    # Restaurer analyse_result pour déverrouiller le générateur
    st.session_state["analyse_result"] = exigences if exigences else {"nom_projet": inf["nom"]}

    # Naviguer vers Espace de travail → onglet Générateur (index 1)
    st.session_state["sidebar_section"] = "travail"
    st.session_state["_goto_tab"]       = 1


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — BLOC COMPACT
# ─────────────────────────────────────────────────────────────────────────────

def show_sidebar_offres(user: dict) -> None:
    """
    Bloc compact dans la sidebar Streamlit.
    Affiche les offres par groupe (En cours / Envoyées / Terminées).
    Bouton ▶ sur chaque offre pour la reprendre directement.
    """
    offres = _charger_offres(user["id"])
    if not offres:
        return

    st.markdown("---")
    st.markdown("##### 📁 Mes offres")

    for groupe_id, groupe_cfg in GROUPES.items():
        offres_groupe = [o for o in offres if o.get("statut", "brouillon") in groupe_cfg["statuts"]]
        if not offres_groupe:
            continue

        with st.expander(
            f"{groupe_cfg['label']} ({len(offres_groupe)})",
            expanded=(groupe_id == "en_cours")
        ):
            for o in offres_groupe[:5]:
                inf    = _infos(o)
                statut = o.get("statut", "brouillon")
                cfg    = STATUTS.get(statut, {"emoji": "•", "color": "#aaa"})
                nom_court = inf["nom"][:26] + ("…" if len(inf["nom"]) > 26 else "")

                col_info, col_btn = st.columns([4, 1])
                montant = f" · {inf['total_ttc']:,.0f}$" if inf["total_ttc"] else ""
                col_info.markdown(
                    f"<div style='font-size:12px;line-height:1.4;'>"
                    f"{cfg['emoji']} <b>{nom_court}</b><br>"
                    f"<span style='color:#888;font-size:10px;'>{inf['date_maj']}{montant}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if col_btn.button("▶", key=f"sb_{o['id']}", help="Reprendre cette offre"):
                    _reprendre_offre(o)
                    st.rerun()

    st.markdown("")
    if st.button("📁 Voir toutes mes offres", use_container_width=True, key="sb_toutes"):
        st.session_state["sidebar_section"] = "travail"
        st.session_state["_goto_tab"]       = 3
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# ONGLET PRINCIPAL — TABLEAU DE BORD COMPLET
# ─────────────────────────────────────────────────────────────────────────────

def show_mes_offres_tab(user: dict) -> None:
    """
    Onglet Mes Offres — tableau de bord complet :
    - Métriques globales
    - Filtres (groupe, recherche, tri)
    - Carte par offre : statut, montant, dates
    - Bouton Reprendre (rouvre dans le Générateur d'Offres)
    - Panneau détail dépliable : technique, financier, documents
    """
    st.header("📁 Mes Offres")

    offres = _charger_offres(user["id"])

    if not offres:
        st.info(
            "📭 **Aucune offre sauvegardée pour l'instant.**\n\n"
            "Créez votre première offre dans l'onglet **📝 Générateur d'Offres**."
        )
        return

    # ── Métriques globales ───────────────────────────────────────
    nb_cours    = sum(1 for o in offres if o.get("statut","brouillon") in GROUPES["en_cours"]["statuts"])
    nb_envoyees = sum(1 for o in offres if o.get("statut","brouillon") in GROUPES["envoyee"]["statuts"])
    nb_acceptes = sum(1 for o in offres if o.get("statut") == "acceptee")
    val_totale  = sum(_infos(o)["total_ttc"] for o in offres if o.get("statut") == "acceptee")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total",           len(offres))
    m2.metric("En cours",        nb_cours)
    m3.metric("Envoyées",        nb_envoyees)
    m4.metric("Acceptées",       nb_acceptes)
    m5.metric("Valeur acceptée", f"{val_totale:,.0f} $" if val_totale else "—")
    st.markdown("---")

    # ── Filtres ──────────────────────────────────────────────────
    cf1, cf2, cf3 = st.columns([3, 2, 2])
    with cf1:
        recherche = st.text_input("🔍 Rechercher", placeholder="Nom, numéro, client…", key="mo_search")
    with cf2:
        filtre_groupe = st.selectbox(
            "Groupe",
            options=["Tous"] + list(GROUPES.keys()),
            format_func=lambda x: "Tous les statuts" if x == "Tous" else GROUPES[x]["label"],
            key="mo_groupe"
        )
    with cf3:
        tri = st.selectbox("Trier par", ["Date ↓", "Montant ↓", "Nom ↑"], key="mo_tri")

    # Appliquer filtres + tri
    offres_f = list(offres)
    if filtre_groupe != "Tous":
        ok = set(GROUPES[filtre_groupe]["statuts"])
        offres_f = [o for o in offres_f if o.get("statut","brouillon") in ok]
    if recherche:
        t = recherche.lower()
        offres_f = [
            o for o in offres_f
            if t in _infos(o)["nom"].lower()
            or t in _infos(o)["numero"].lower()
            or t in _infos(o)["client"].lower()
        ]
    if tri == "Montant ↓":
        offres_f = sorted(offres_f, key=lambda o: _infos(o)["total_ttc"], reverse=True)
    elif tri == "Nom ↑":
        offres_f = sorted(offres_f, key=lambda o: _infos(o)["nom"].lower())

    if not offres_f:
        st.warning("Aucune offre ne correspond aux filtres.")
        return

    st.caption(f"{len(offres_f)} offre(s) affichée(s) sur {len(offres)}")
    st.markdown("---")

    # ── Cartes offres ────────────────────────────────────────────
    for offre in offres_f:
        statut = offre.get("statut", "brouillon")
        cfg    = STATUTS.get(statut, {"emoji": "•", "label": statut, "color": "#aaa"})
        inf    = _infos(offre)
        oid    = offre["id"]

        # ── En-tête carte ─────────────────────────────────────
        col_titre, col_badge, col_actions = st.columns([5, 2, 3])

        with col_titre:
            st.markdown(f"### {cfg['emoji']} {inf['nom']}")
            meta = [x for x in [
                f"No {inf['numero']}" if inf["numero"] != "—" else None,
                inf["client"]         if inf["client"]  != "—" else None,
                inf["lieu"]           if inf["lieu"]    != "—" else None,
            ] if x]
            meta.append(f"Créée {inf['date_cree']}  ·  MAJ {inf['date_maj']}")
            st.caption("  ·  ".join(meta))
            if inf["total_ttc"] > 0:
                st.markdown(
                    f"<span style='font-size:20px;font-weight:700;color:#1E3A5F;'>"
                    f"{inf['total_ttc']:,.2f} $</span>",
                    unsafe_allow_html=True,
                )

        with col_badge:
            st.markdown(
                f"<div style='padding-top:10px;'>{_badge(statut)}</div>",
                unsafe_allow_html=True,
            )
            # Changement de statut inline
            nouveau = st.selectbox(
                "Statut",
                options=list(STATUTS.keys()),
                index=list(STATUTS.keys()).index(statut) if statut in STATUTS else 0,
                key=f"sel_{oid}",
                label_visibility="collapsed",
                format_func=lambda x: f"{STATUTS[x]['emoji']} {STATUTS[x]['label']}"
            )
            if nouveau != statut:
                if st.button("✔ Appliquer", key=f"apply_{oid}", use_container_width=True):
                    if _sauvegarder_statut(oid, nouveau):
                        if nouveau == "acceptee":
                            st.balloons()
                        st.rerun()

        with col_actions:
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

            # Bouton principal selon le groupe
            groupe_offre = cfg.get("groupe", "en_cours")
            if groupe_offre == "en_cours":
                if st.button(
                    "▶️ Reprendre le travail",
                    key=f"reprendre_{oid}",
                    type="primary",
                    use_container_width=True,
                    help="Ouvre cette offre dans le Générateur d'Offres pour continuer"
                ):
                    _reprendre_offre(offre)
                    st.rerun()
            elif statut == "acceptee":
                if st.button(
                    "🚀 Démarrer le projet",
                    key=f"projet_{oid}",
                    type="primary",
                    use_container_width=True
                ):
                    st.session_state["offre_pour_projet"] = {
                        "id":         oid,
                        "nom_projet": inf["nom"],
                        "offre_data": inf["contenu"],
                    }
                    st.session_state["sidebar_section"] = "travail"
                    st.session_state["_goto_tab"]       = 4
                    st.rerun()
            else:
                # Envoyée — permettre quand même de rouvrir pour modifier
                if st.button(
                    "✏️ Modifier",
                    key=f"modifier_{oid}",
                    use_container_width=True,
                ):
                    _reprendre_offre(offre)
                    st.rerun()

            # Bouton toggle détail
            detail_ouvert = st.session_state.get(f"detail_{oid}", False)
            if st.button(
                "🔽 Détail / Documents" if not detail_ouvert else "🔼 Fermer le détail",
                key=f"toggle_{oid}",
                use_container_width=True,
            ):
                st.session_state[f"detail_{oid}"] = not detail_ouvert
                st.rerun()

        # ── Panneau détail ──────────────────────────────────────
        if st.session_state.get(f"detail_{oid}", False):
            contenu    = inf["contenu"]
            offre_tech = contenu.get("offre_technique") or {}
            offre_fin  = contenu.get("offre_financiere") or {}
            exigences  = contenu.get("exigences") or {}
            bord_ao    = contenu.get("bordereau_ao") or []

            dtab1, dtab2, dtab3, dtab4 = st.tabs([
                "📋 Résumé", "📄 Offre Technique", "💰 Offre Financière", "📥 Documents"
            ])

            with dtab1:
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Projet :** {inf['nom']}")
                    st.markdown(f"**Numéro :** {inf['numero']}")
                    st.markdown(f"**Client :** {inf['client']}")
                    st.markdown(f"**Lieu :** {inf['lieu']}")
                    st.markdown(f"**Section :** {inf['section']}")
                with c2:
                    st.markdown(f"**Statut :** {_badge(statut)}", unsafe_allow_html=True)
                    st.markdown(f"**Créée le :** {inf['date_cree']}")
                    st.markdown(f"**Modifiée le :** {inf['date_maj']}")
                    if inf["total_ttc"] > 0:
                        st.markdown(f"**Total TTC :** {inf['total_ttc']:,.2f} $")
                if exigences.get("sommaire"):
                    st.info(exigences["sommaire"])

            with dtab2:
                if offre_tech:
                    if offre_tech.get("introduction"):
                        st.markdown("**Introduction**")
                        st.write(offre_tech["introduction"])
                    phases = (
                        (offre_tech.get("approche_methodologique") or {}).get("phases")
                        or offre_tech.get("methodologie", [])
                    )
                    if phases:
                        st.markdown("**Phases**")
                        for p in phases:
                            st.markdown(
                                f"- **{p.get('nom') or p.get('phase','')}** "
                                f"({p.get('duree','')}) : {p.get('description','')}"
                            )
                    equipe = offre_tech.get("equipe_proposee") or offre_tech.get("equipe", [])
                    if equipe:
                        st.markdown("**Équipe**")
                        for m in equipe:
                            qual = m.get("experience") or m.get("qualification","")
                            st.markdown(f"- {m.get('role','')} : **{m.get('nom','')}** — {qual}")
                    garanties = offre_tech.get("garanties_qualite") or offre_tech.get("garanties", [])
                    if garanties:
                        st.markdown("**Garanties**")
                        for g in garanties:
                            st.markdown(f"- {g}")
                else:
                    st.info("Aucune offre technique sauvegardée pour cette offre.")

            with dtab3:
                if bord_ao:
                    grand_total = 0.0
                    for sec in bord_ao:
                        st.markdown(
                            f"<div style='background:#2E75B6;color:white;font-weight:bold;"
                            f"font-size:12px;padding:4px 10px;border-radius:3px;margin:8px 0 4px;'>"
                            f"{sec.get('titre','').upper()}</div>",
                            unsafe_allow_html=True,
                        )
                        sous_total_sec = 0.0
                        for it in sec.get("items", []):
                            prix  = float(it.get("prix_unitaire") or 0)
                            qte   = float(it.get("quantite") or 1)
                            total = round(prix * qte, 2)
                            sous_total_sec += total
                            ci, cd, ct = st.columns([1, 5, 2])
                            ci.caption(str(it.get("no", "")))
                            cd.write(it.get("description", ""))
                            ct.write(f"{total:,.2f} $" if total else "—")
                        grand_total += sous_total_sec
                        st.markdown(
                            f"<div style='text-align:right;font-size:12px;color:#1E3A5F;"
                            f"font-weight:600;padding:2px 0 8px;'>"
                            f"Sous-total : {sous_total_sec:,.2f} $</div>",
                            unsafe_allow_html=True,
                        )
                    # Totaux
                    contig_pct = int(contenu.get("contingence") or 10)
                    contig     = round(grand_total * contig_pct / 100, 2)
                    avant_tx   = round(grand_total + contig, 2)
                    tps        = round(avant_tx * 0.05, 2)
                    tvq        = round(avant_tx * 0.09975, 2)
                    ttc        = round(avant_tx + tps + tvq, 2)
                    st.markdown("---")
                    t1, t2, t3, t4 = st.columns(4)
                    t1.metric("Sous-total HT",   f"{grand_total:,.2f} $")
                    t2.metric("Contingence",     f"{contig:,.2f} $")
                    t3.metric("Taxes (TPS+TVQ)", f"{tps+tvq:,.2f} $")
                    t4.metric("TOTAL TTC",       f"{ttc:,.2f} $")
                elif offre_fin:
                    postes      = offre_fin.get("postes") or []
                    sous_ht     = float(offre_fin.get("sous_total_ht") or offre_fin.get("total_ht") or 0)
                    total_ttc_f = float(offre_fin.get("total_ttc") or 0)
                    for p in postes:
                        ca, cb, cc = st.columns([4, 1, 2])
                        ca.write(p.get("description", ""))
                        cb.write(f"{p.get('heures', p.get('quantite', 0))} h")
                        cc.write(f"{p.get('total', 0):,.2f} $")
                    if total_ttc_f:
                        st.markdown("---")
                        r1, r2 = st.columns(2)
                        r1.metric("Sous-total HT", f"{sous_ht:,.2f} $")
                        r2.metric("TOTAL TTC",     f"{total_ttc_f:,.2f} $")
                else:
                    st.info("Aucune offre financière sauvegardée.")

            with dtab4:
                st.markdown("#### 📥 Régénérer les documents")
                st.caption(
                    "Génère les fichiers depuis les données sauvegardées. "
                    "Pour modifier le contenu, cliquez **▶️ Reprendre le travail**."
                )

                if st.button("⚙️ Générer Word + Excel + PDF", key=f"gen_{oid}", type="primary"):
                    try:
                        from exports import generer_docx, generer_xlsx, generer_pdf

                        # Injecter le bordereau et la contingence en session pour les exports
                        if "offre_data" not in st.session_state:
                            st.session_state["offre_data"] = {}
                        st.session_state["offre_data"]["bordereau_ao"] = bord_ao
                        st.session_state["offre_data"]["contingence"]  = contenu.get("contingence", 10)

                        with st.spinner("Word…"):
                            st.session_state[f"docs_{oid}_docx"] = generer_docx(offre_tech, offre_fin, exigences, user)
                        with st.spinner("Excel…"):
                            st.session_state[f"docs_{oid}_xlsx"] = generer_xlsx(offre_fin, exigences, user)
                        with st.spinner("PDF…"):
                            st.session_state[f"docs_{oid}_pdf"]  = generer_pdf(offre_tech, offre_fin, exigences, user)
                        st.success("✅ Documents prêts.")
                    except Exception as e:
                        import traceback
                        st.error(f"Erreur génération : {e}")
                        st.code(traceback.format_exc())

                docx_b = st.session_state.get(f"docs_{oid}_docx")
                xlsx_b = st.session_state.get(f"docs_{oid}_xlsx")
                pdf_b  = st.session_state.get(f"docs_{oid}_pdf")

                if docx_b or xlsx_b or pdf_b:
                    nom_clean = inf["nom"].replace(" ", "_")[:40]
                    d1, d2, d3 = st.columns(3)
                    if docx_b:
                        d1.download_button(
                            "📄 Word",
                            data=docx_b,
                            file_name=f"Offre_{nom_clean}.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key=f"dl_docx_{oid}",
                            use_container_width=True,
                        )
                    if xlsx_b:
                        d2.download_button(
                            "📊 Excel",
                            data=xlsx_b,
                            file_name=f"Offre_{nom_clean}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_xlsx_{oid}",
                            use_container_width=True,
                        )
                    if pdf_b:
                        d3.download_button(
                            "📑 PDF",
                            data=pdf_b,
                            file_name=f"Offre_{nom_clean}.pdf",
                            mime="application/pdf",
                            key=f"dl_pdf_{oid}",
                            use_container_width=True,
                        )
                else:
                    st.info("Cliquez sur **Générer Word + Excel + PDF** pour préparer les fichiers.")

        st.markdown("---")