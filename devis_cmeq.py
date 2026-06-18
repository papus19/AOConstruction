"""
Module de référence CMEQ — Grille de taux IC/I
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Source : Grille officielle CMEQ, en vigueur au 27 avril 2025
Secteur : Industriel / Commercial / Institutionnel (IC/I)

Fonctionnalités :
  - Affichage de la grille de taux avec calculs en cascade
  - Ajustement de chaque section (A à H) par l'utilisateur
  - Calcul du taux horaire total avec aperçu en temps réel
  - Sauvegarde du profil de taux dans Supabase
  - Widget compact pour intégration dans le générateur d'offres
"""

import streamlit as st
import json
from datetime import datetime

try:
    import database
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


# ═════════════════════════════════════════════════════════════════════════════
# CONSTANTES — GRILLE CMEQ IC/I AU 27 AVRIL 2025
# ═════════════════════════════════════════════════════════════════════════════

GRILLE_CMEQ_DEFAUT = {
    # ── Coût horaire main-d'œuvre (A → E) ────────────────────────────────
    "A_salaire_ccq":               48.37,   # Salaire CCQ — temps simple
    "B_avantages_sociaux_const":   16.23,   # Avantages sociaux construction
    "C_avantages_sociaux_gouv":     8.99,   # Avantages sociaux gouvernementaux
    "D_cotisations_fixes":          1.94,   # Cotisations fixes
    "E_clauses_monetaires":         6.45,   # Clauses monétaires normatives
    # ── Frais d'entreprise (F + G) ────────────────────────────────────────
    "F_vehicule_equipements":      16.02,   # Véhicule + équipements
    "G_frais_exploitation_pct":    25.0,    # Frais exploitation — % sur (MO+F)
    # ── Profit (H) ────────────────────────────────────────────────────────
    "H_profit_pct":                10.0,    # Profit entrepreneur — % sur avant-profit
}

SECTIONS_META = {
    "A_salaire_ccq": {
        "lettre": "A", "groupe": "mo",
        "label": "Salaire CCQ — temps simple",
        "unite": "$/h", "type": "montant",
        "min": 0.0, "max": 150.0, "step": 0.01,
        "aide": "Taux de salaire horaire de base selon la convention collective CCQ pour le secteur IC/I.",
    },
    "B_avantages_sociaux_const": {
        "lettre": "B", "groupe": "mo",
        "label": "Avantages sociaux — construction",
        "unite": "$/h", "type": "montant",
        "min": 0.0, "max": 60.0, "step": 0.01,
        "aide": "Régime de retraite, assurance collective, vacances et jours fériés selon CCQ.",
    },
    "C_avantages_sociaux_gouv": {
        "lettre": "C", "groupe": "mo",
        "label": "Avantages sociaux — gouvernementaux",
        "unite": "$/h", "type": "montant",
        "min": 0.0, "max": 40.0, "step": 0.01,
        "aide": "CNESST, RRQ, assurance emploi, RQAP — charges patronales obligatoires.",
    },
    "D_cotisations_fixes": {
        "lettre": "D", "groupe": "mo",
        "label": "Cotisations fixes",
        "unite": "$/h", "type": "montant",
        "min": 0.0, "max": 15.0, "step": 0.01,
        "aide": "Formation professionnelle (CPQMÉ), cotisation CMEQ et autres cotisations fixes.",
    },
    "E_clauses_monetaires": {
        "lettre": "E", "groupe": "mo",
        "label": "Clauses monétaires normatives",
        "unite": "$/h", "type": "montant",
        "min": 0.0, "max": 30.0, "step": 0.01,
        "aide": "Indemnités de déplacement, repas, outils et autres clauses de la convention collective.",
    },
    "F_vehicule_equipements": {
        "lettre": "F", "groupe": "frais",
        "label": "Véhicule et équipements",
        "unite": "$/h", "type": "montant",
        "min": 0.0, "max": 80.0, "step": 0.01,
        "aide": "Amortissement et coût d'utilisation des véhicules de service et petits équipements.",
    },
    "G_frais_exploitation_pct": {
        "lettre": "G", "groupe": "frais",
        "label": "Frais d'exploitation",
        "unite": "%", "type": "pourcentage",
        "min": 0.0, "max": 60.0, "step": 0.5,
        "aide": "Frais généraux et admin (loyer, assurances, licences, comptabilité…). Appliqué sur (MO+F).",
    },
    "H_profit_pct": {
        "lettre": "H", "groupe": "profit",
        "label": "Profit entrepreneur",
        "unite": "%", "type": "pourcentage",
        "min": 0.0, "max": 40.0, "step": 0.5,
        "aide": "Marge bénéficiaire nette. Appliquée sur le total avant profit. Recommandation CMEQ : 10 %.",
    },
}


# ═════════════════════════════════════════════════════════════════════════════
# CALCULS
# ═════════════════════════════════════════════════════════════════════════════

def calculer_taux(grille: dict) -> dict:
    """
    Calcule le taux horaire complet à partir de la grille.
    Retourne tous les sous-totaux intermédiaires.

    Formule :
        cout_mo      = A + B + C + D + E
        avant_profit = (cout_mo + F) × (1 + G%)
        taux_total   = avant_profit × (1 + H%)
    """
    A     = float(grille.get("A_salaire_ccq", 0))
    B     = float(grille.get("B_avantages_sociaux_const", 0))
    C     = float(grille.get("C_avantages_sociaux_gouv", 0))
    D     = float(grille.get("D_cotisations_fixes", 0))
    E     = float(grille.get("E_clauses_monetaires", 0))
    F     = float(grille.get("F_vehicule_equipements", 0))
    G_pct = float(grille.get("G_frais_exploitation_pct", 25.0))
    H_pct = float(grille.get("H_profit_pct", 10.0))

    cout_mo      = round(A + B + C + D + E, 2)
    base_frais   = cout_mo + F
    G_montant    = round(base_frais * (G_pct / 100), 2)
    avant_profit = round(base_frais + G_montant, 2)
    H_montant    = round(avant_profit * (H_pct / 100), 2)
    taux_total   = round(avant_profit + H_montant, 2)

    return {
        "A": round(A, 2), "B": round(B, 2), "C": round(C, 2),
        "D": round(D, 2), "E": round(E, 2),
        "cout_mo":       cout_mo,
        "F":             round(F, 2),
        "G_pct":         round(G_pct, 2),
        "G_montant":     G_montant,
        "avant_profit":  avant_profit,
        "H_pct":         round(H_pct, 2),
        "H_montant":     H_montant,
        "taux_total":    taux_total,
    }


# ═════════════════════════════════════════════════════════════════════════════
# PERSISTANCE SUPABASE
# ═════════════════════════════════════════════════════════════════════════════

def charger_grille_profil(user: dict) -> dict:
    """Charge la grille personnalisée depuis Supabase (ou défauts CMEQ)."""
    if not _DB_AVAILABLE:
        return dict(GRILLE_CMEQ_DEFAUT)
    try:
        database.apply_supabase_auth()
        res = (
            database.supabase.table("entreprises")
            .select("parametres_cmeq")
            .eq("id", user["id"])
            .execute()
        )
        if res.data and res.data[0].get("parametres_cmeq"):
            params = res.data[0]["parametres_cmeq"]
            if isinstance(params, str):
                params = json.loads(params)
            merged = dict(GRILLE_CMEQ_DEFAUT)
            merged.update(params)
            return merged
    except Exception:
        pass
    return dict(GRILLE_CMEQ_DEFAUT)


def sauvegarder_grille_profil(user: dict, grille: dict) -> bool:
    """Sauvegarde la grille personnalisée dans la table entreprises."""
    if not _DB_AVAILABLE:
        return False
    try:
        database.apply_supabase_auth()
        database.supabase.table("entreprises").update({
            "parametres_cmeq": json.dumps(grille),
        }).eq("id", user["id"]).execute()
        return True
    except Exception as e:
        st.error(f"❌ Erreur sauvegarde CMEQ : {e}")
        return False


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS UI
# ═════════════════════════════════════════════════════════════════════════════

def _badge_delta(val_actuelle: float, val_defaut: float) -> str:
    """Retourne une badge HTML vert/rouge selon l'écart avec le défaut CMEQ."""
    if val_defaut == 0:
        return ""
    delta = ((val_actuelle - val_defaut) / val_defaut) * 100
    if abs(delta) < 0.05:
        return "<span style='color:#28a745;font-size:0.75em;'>✅ CMEQ</span>"
    couleur = "#dc3545" if delta > 0 else "#28a745"
    signe = "+" if delta > 0 else ""
    return f"<span style='color:{couleur};font-size:0.75em;font-weight:bold;'>{signe}{delta:.1f}%</span>"


def _tableau_grille_html(calcul: dict, grille: dict) -> str:
    """Construit le tableau HTML d'aperçu de la grille."""
    BF = "#1E3A5F"; BM = "#2E75B6"; BL = "#ffffff"

    def tr(lettre, label, valeur, bg="#f8f9fa", bold=False, color="#212529"):
        fw = "bold" if bold else "normal"
        return (
            f"<tr style='background:{bg};'>"
            f"<td style='padding:5px 8px;border:1px solid #dee2e6;text-align:center;"
            f"font-weight:bold;color:{BF};width:24px;font-size:.85em;'>{lettre}</td>"
            f"<td style='padding:5px 8px;border:1px solid #dee2e6;font-size:.83em;"
            f"color:{color};font-weight:{fw};'>{label}</td>"
            f"<td style='padding:5px 8px;border:1px solid #dee2e6;text-align:right;"
            f"font-weight:{fw};white-space:nowrap;color:{color};font-size:.88em;'>{valeur}</td>"
            f"</tr>"
        )

    def tr_total(label, valeur, bg=BF):
        return (
            f"<tr style='background:{bg};'>"
            f"<td colspan='2' style='padding:6px 10px;color:{BL};font-weight:bold;"
            f"font-size:.88em;border:1px solid #dee2e6;'>{label}</td>"
            f"<td style='padding:6px 10px;color:{BL};font-weight:bold;"
            f"text-align:right;white-space:nowrap;font-size:.92em;"
            f"border:1px solid #dee2e6;'>{valeur}</td>"
            f"</tr>"
        )

    html = (
        "<table style='width:100%;border-collapse:collapse;"
        "font-family:Arial,sans-serif;'>"
        f"<thead><tr style='background:{BF};'>"
        f"<th style='padding:6px;color:{BL};text-align:center;font-size:.8em;'>§</th>"
        f"<th style='padding:6px;color:{BL};text-align:left;font-size:.8em;'>Description</th>"
        f"<th style='padding:6px;color:{BL};text-align:right;font-size:.8em;'>Taux</th>"
        "</tr></thead><tbody>"
    )

    sections_mo = [
        ("A", "Salaire CCQ",            f"{calcul['A']:.2f} $/h"),
        ("B", "Avantages sociaux const.",f"{calcul['B']:.2f} $/h"),
        ("C", "Avantages sociaux gouv.", f"{calcul['C']:.2f} $/h"),
        ("D", "Cotisations fixes",       f"{calcul['D']:.2f} $/h"),
        ("E", "Clauses monétaires",      f"{calcul['E']:.2f} $/h"),
    ]
    for i, (l, lbl, val) in enumerate(sections_mo):
        html += tr(l, lbl, val, bg="#f8f9fa" if i % 2 == 0 else BL)
    html += tr_total(f"Coût MO (A+B+C+D+E)", f"{calcul['cout_mo']:.2f} $/h", bg=BM)

    html += tr("F", "Véhicule + équipements",  f"{calcul['F']:.2f} $/h",      bg="#f0f4ff")
    html += tr("G", f"Frais exploit. ({calcul['G_pct']:.1f}%)", f"{calcul['G_montant']:.2f} $/h", bg="#e8f0fe")
    html += tr_total(f"Avant profit (MO+F+G)", f"{calcul['avant_profit']:.2f} $/h", bg="#154360")

    html += tr("H", f"Profit ({calcul['H_pct']:.1f}%)", f"{calcul['H_montant']:.2f} $/h", bg="#fef9e7")

    html += (
        f"<tr style='background:{BF};'>"
        f"<td colspan='2' style='padding:8px 10px;color:{BL};font-weight:bold;"
        f"font-size:.95em;border:2px solid #dee2e6;'>🎯 TAUX FACTURABLE TOTAL</td>"
        f"<td style='padding:8px 10px;color:{BL};font-weight:bold;"
        f"font-size:1.05em;text-align:right;white-space:nowrap;"
        f"border:2px solid #dee2e6;'>{calcul['taux_total']:.2f} $/h</td>"
        f"</tr>"
    )
    html += "</tbody></table>"
    return html


# ═════════════════════════════════════════════════════════════════════════════
# ONGLET PRINCIPAL
# ═════════════════════════════════════════════════════════════════════════════

def show_devis_cmeq_tab(user: dict) -> dict:
    """
    Onglet complet de gestion de la grille CMEQ.
    Retourne un dict avec la grille active et le taux calculé
    (pour injection dans le générateur d'offres).
    """
    st.header("📐 Grille de taux CMEQ")
    st.caption(
        "Source : Grille officielle CMEQ — Secteur IC/I, en vigueur au 27 avril 2025  |  "
        "Ajustez les sections selon votre réalité d'entreprise."
    )

    # ── Chargement ───────────────────────────────────────────────────────
    if "grille_cmeq" not in st.session_state:
        with st.spinner("Chargement du profil de taux…"):
            st.session_state["grille_cmeq"] = charger_grille_profil(user)

    grille = dict(st.session_state["grille_cmeq"])
    calcul = calculer_taux(grille)
    calcul_ref = calculer_taux(GRILLE_CMEQ_DEFAUT)

    # ── KPI en haut ──────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Coût MO (A→E)",        f"{calcul['cout_mo']:.2f} $/h",
              help="Coût direct de la main-d'œuvre, sections A à E.")
    c2.metric("+ Frais (F+G)",         f"{calcul['F'] + calcul['G_montant']:.2f} $/h",
              help="Véhicule + frais d'exploitation.")
    c3.metric("Avant profit",          f"{calcul['avant_profit']:.2f} $/h",
              help="Total avant la marge bénéficiaire.")
    ecart = calcul["taux_total"] - calcul_ref["taux_total"]
    delta_str = f"{ecart:+.2f} vs CMEQ" if abs(ecart) >= 0.01 else "= taux CMEQ"
    c4.metric("🎯 Taux facturable",    f"{calcul['taux_total']:.2f} $/h",
              delta=delta_str,
              delta_color="off" if abs(ecart) < 0.01 else "normal")

    st.markdown("---")

    # ── Layout : formulaire | aperçu ────────────────────────────────────
    col_form, col_view = st.columns([3, 2])

    changed = False  # flag pour détecter les modifications

    with col_form:

        # Boutons d'action
        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button("↺ Remettre aux valeurs CMEQ 2025",
                         use_container_width=True, key="btn_reset_cmeq"):
                st.session_state["grille_cmeq"] = dict(GRILLE_CMEQ_DEFAUT)
                st.success("✅ Valeurs CMEQ restaurées.")
                st.rerun()
        with bc2:
            if st.button("💾 Sauvegarder dans mon profil",
                         type="primary", use_container_width=True, key="btn_save_cmeq"):
                ok = sauvegarder_grille_profil(user, grille)
                if ok:
                    st.success("✅ Grille sauvegardée dans votre profil.")

        st.markdown("")

        # ── Groupe A–E : Coût MO ────────────────────────────────────────
        with st.expander("💼 Coût horaire main-d'œuvre — Sections A à E", expanded=True):
            st.caption(
                "Ces taux proviennent de la convention collective CCQ. "
                "Ne les modifiez que si vous opérez hors CCQ ou dans un secteur différent."
            )

            cles_mo = [
                "A_salaire_ccq", "B_avantages_sociaux_const",
                "C_avantages_sociaux_gouv", "D_cotisations_fixes", "E_clauses_monetaires",
            ]
            for cle in cles_mo:
                meta    = SECTIONS_META[cle]
                defaut  = GRILLE_CMEQ_DEFAUT[cle]
                valeur  = float(grille.get(cle, defaut))

                ca, cb, cc = st.columns([3, 2, 1])
                with ca:
                    st.markdown(
                        f"**{meta['lettre']}** &nbsp; {meta['label']}  \n"
                        f"<span style='color:#999;font-size:.78em;'>{meta['aide']}</span>",
                        unsafe_allow_html=True,
                    )
                with cb:
                    nouvelle = st.number_input(
                        label=f"sect_{meta['lettre']}",
                        label_visibility="collapsed",
                        min_value=meta["min"], max_value=meta["max"],
                        value=valeur, step=meta["step"], format="%.2f",
                        key=f"inp_cmeq_{cle}",
                    )
                    if abs(nouvelle - valeur) > 1e-6:
                        grille[cle] = nouvelle
                        changed = True
                with cc:
                    st.markdown(_badge_delta(nouvelle, defaut), unsafe_allow_html=True)

            calcul_live = calculer_taux(grille)
            st.markdown(
                f"<div style='background:#1E3A5F;color:white;padding:7px 12px;"
                f"border-radius:5px;margin-top:10px;font-weight:bold;font-size:.9em;'>"
                f"Sous-total coût MO = {calcul_live['cout_mo']:.2f} $/h</div>",
                unsafe_allow_html=True,
            )

        # ── Groupe F–G : Frais d'entreprise ─────────────────────────────
        with st.expander("🏢 Frais d'entreprise — Sections F et G", expanded=True):
            st.caption(
                "Ajustez F et G selon vos coûts réels. "
                "Une PME avec peu de véhicules aura un F plus bas ; "
                "des frais généraux élevés (locaux, admin) augmentent G."
            )

            for cle in ["F_vehicule_equipements", "G_frais_exploitation_pct"]:
                meta   = SECTIONS_META[cle]
                defaut = GRILLE_CMEQ_DEFAUT[cle]
                valeur = float(grille.get(cle, defaut))

                ca, cb, cc = st.columns([3, 2, 1])
                with ca:
                    st.markdown(
                        f"**{meta['lettre']}** &nbsp; {meta['label']} ({meta['unite']})  \n"
                        f"<span style='color:#999;font-size:.78em;'>{meta['aide']}</span>",
                        unsafe_allow_html=True,
                    )
                with cb:
                    nouvelle = st.number_input(
                        label=f"sect_{meta['lettre']}",
                        label_visibility="collapsed",
                        min_value=meta["min"], max_value=meta["max"],
                        value=valeur, step=meta["step"],
                        format="%.2f" if meta["type"] == "montant" else "%.1f",
                        key=f"inp_cmeq_{cle}",
                    )
                    if abs(nouvelle - valeur) > 1e-6:
                        grille[cle] = nouvelle
                        changed = True
                with cc:
                    st.markdown(_badge_delta(nouvelle, defaut), unsafe_allow_html=True)

            calcul_live = calculer_taux(grille)
            st.caption(
                f"G en dollars = **{calcul_live['G_montant']:.2f} $/h** "
                f"(base MO+F = {calcul_live['cout_mo'] + calcul_live['F']:.2f} $/h)"
            )
            st.markdown(
                f"<div style='background:#2E75B6;color:white;padding:7px 12px;"
                f"border-radius:5px;margin-top:8px;font-weight:bold;font-size:.9em;'>"
                f"Avant profit (MO+F+G) = {calcul_live['avant_profit']:.2f} $/h</div>",
                unsafe_allow_html=True,
            )

        # ── Groupe H : Profit ────────────────────────────────────────────
        with st.expander("💰 Profit entrepreneur — Section H", expanded=True):
            meta   = SECTIONS_META["H_profit_pct"]
            defaut = GRILLE_CMEQ_DEFAUT["H_profit_pct"]
            valeur = float(grille.get("H_profit_pct", defaut))

            ca, cb, cc = st.columns([3, 2, 1])
            with ca:
                st.markdown(
                    f"**H** &nbsp; {meta['label']} (%)  \n"
                    f"<span style='color:#999;font-size:.78em;'>{meta['aide']}</span>",
                    unsafe_allow_html=True,
                )
            with cb:
                nouvelle_h = st.number_input(
                    label="sect_H", label_visibility="collapsed",
                    min_value=0.0, max_value=40.0, value=valeur,
                    step=0.5, format="%.1f", key="inp_cmeq_H",
                )
                if abs(nouvelle_h - valeur) > 1e-6:
                    grille["H_profit_pct"] = nouvelle_h
                    changed = True
            with cc:
                st.markdown(_badge_delta(nouvelle_h, defaut), unsafe_allow_html=True)

            calcul_live = calculer_taux(grille)
            st.caption(
                f"H en dollars = **{calcul_live['H_montant']:.2f} $/h** "
                f"sur avant-profit de {calcul_live['avant_profit']:.2f} $/h"
            )

        # Persistance auto en session si changement
        if changed:
            st.session_state["grille_cmeq"] = grille
            st.rerun()

    # ── Aperçu visuel ────────────────────────────────────────────────────
    with col_view:
        st.subheader("Aperçu de la grille")

        calcul = calculer_taux(grille)
        st.markdown(_tableau_grille_html(calcul, grille), unsafe_allow_html=True)

        # Comparaison vs CMEQ officiel
        ecart = calcul["taux_total"] - calcul_ref["taux_total"]
        st.markdown("")
        if abs(ecart) < 0.01:
            st.success("✅ Conforme aux taux CMEQ 2025")
        elif ecart > 0:
            st.info(
                f"📈 **+{ecart:.2f} $/h** vs CMEQ ({calcul_ref['taux_total']:.2f} $/h)  \n"
                "Votre taux est plus élevé que la référence."
            )
        else:
            st.warning(
                f"📉 **{ecart:.2f} $/h** vs CMEQ ({calcul_ref['taux_total']:.2f} $/h)  \n"
                "Vérifiez que ce taux couvre bien tous vos frais réels."
            )

        st.markdown("---")
        st.markdown("#### 💡 Valeur selon les heures")
        for label, h in [
            ("8 h (1 jour)",    8),
            ("80 h (~2 sem.)", 80),
            ("300 h (~2 mois)", 300),
            ("800 h (~6 mois)", 800),
        ]:
            mo_seul = h * calcul["cout_mo"]
            total   = h * calcul["taux_total"]
            profit  = h * calcul["H_montant"]
            st.caption(
                f"**{label}** : MO {mo_seul:,.0f} $ · "
                f"Total {total:,.0f} $ · Profit {profit:,.0f} $"
            )

        st.markdown("---")
        with st.expander("ℹ️ À propos de cette grille"):
            st.markdown("""
**Source :** Maîtres électriciens du Québec (CMEQ)  
**Secteur :** IC/I — Industriel, Commercial, Institutionnel  
**Référence :** 27 avril 2025

**Sections A–E** : Fixées par la convention collective CCQ.  
**Sections F–G** : Vos coûts d'entreprise réels — à adapter.  
**Section H** : Votre marge bénéficiaire — recommandation CMEQ : 10 %.

Ce taux est automatiquement utilisé dans le **Générateur d'offres** 
lorsque vous activez l'option *«Utiliser le taux CMEQ»*.
            """)

    return {
        "grille":     grille,
        "calcul":     calcul,
        "taux_total": calcul["taux_total"],
        "cout_mo":    calcul["cout_mo"],
    }


# ═════════════════════════════════════════════════════════════════════════════
# WIDGET COMPACT — Intégration dans le générateur d'offres
# ═════════════════════════════════════════════════════════════════════════════

def widget_taux_cmeq(user: dict, key_suffix: str = "") -> float:
    """
    Widget compact à placer dans l'onglet Générateur d'offres ou la sidebar.
    Permet de choisir entre le taux CMEQ calculé et un taux manuel.
    Retourne le taux horaire à utiliser pour le chiffrage.
    """
    if "grille_cmeq" not in st.session_state:
        st.session_state["grille_cmeq"] = charger_grille_profil(user)

    calcul = calculer_taux(st.session_state["grille_cmeq"])
    taux_cmeq = calcul["taux_total"]

    mode = st.radio(
        "Source du taux horaire",
        options=["cmeq", "manuel"],
        format_func=lambda x: (
            f"📐 Taux CMEQ calculé ({taux_cmeq:.2f} $/h)" if x == "cmeq"
            else "✏️  Taux personnalisé"
        ),
        key=f"mode_taux_cmeq_{key_suffix}",
        horizontal=True,
    )

    if mode == "cmeq":
        st.info(
            f"**{taux_cmeq:.2f} $/h** · "
            f"MO {calcul['cout_mo']:.2f} + F {calcul['F']:.2f} "
            f"+ G {calcul['G_montant']:.2f} + H {calcul['H_montant']:.2f}  \n"
            f"*Modifiez la grille dans l'onglet **📐 Grille CMEQ**.*"
        )
        return taux_cmeq
    else:
        return st.number_input(
            "Taux horaire ($/h)",
            min_value=40.0, max_value=300.0,
            value=taux_cmeq, step=5.0,
            key=f"taux_manuel_cmeq_{key_suffix}",
        )