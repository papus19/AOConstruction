"""
Tableau de bord SoumIA par MOKAFAD — Theme clair et lisible
"""
import streamlit as st
import database
import json

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600&display=swap');

/* ── Reset Streamlit ── */
.block-container { padding-top: 0.5rem !important; max-width: 1200px; }

:root {
  --bg:         #f4f6f9;
  --surface:    #ffffff;
  --border:     #e2e8f0;
  --border2:    #cbd5e1;
  --blue:       #1e6fe8;
  --blue-light: #eff5ff;
  --green:      #16a34a;
  --green-light:#f0fdf4;
  --orange:     #d97706;
  --orange-light:#fffbeb;
  --red:        #dc2626;
  --red-light:  #fef2f2;
  --yellow:     #b45309;
  --yellow-light:#fefce8;
  --cyan:       #0891b2;
  --cyan-light: #ecfeff;
  --text:       #1e293b;
  --text2:      #475569;
  --muted:      #94a3b8;
  --shadow:     0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md:  0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04);
}

/* ── Header ── */
.dash-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
  padding: 20px 24px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: var(--shadow);
}
.dash-logo {
  width: 48px; height: 48px;
  background: linear-gradient(135deg, #1e6fe8, #0891b2);
  border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  font-family: 'Syne', sans-serif;
  font-weight: 800; font-size: 22px;
  color: #fff;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(30,111,232,0.3);
}
.dash-title {
  font-family: 'Syne', sans-serif;
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  margin: 0; line-height: 1.2;
}
.dash-sub {
  font-family: 'DM Sans', sans-serif;
  font-size: 13px;
  color: var(--text2);
  margin: 2px 0 0 0;
}
.dash-date {
  margin-left: auto;
  text-align: right;
}
.dash-date-val {
  font-family: 'Syne', sans-serif;
  font-size: 14px;
  font-weight: 600;
  color: var(--blue);
}
.dash-date-label {
  font-family: 'DM Sans', sans-serif;
  font-size: 11px;
  color: var(--muted);
}

/* ── Section label ── */
.section-label {
  font-family: 'Syne', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--text2);
  margin: 20px 0 10px 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}

/* ── Grilles KPI ── */
.kpi-grid { display: grid; gap: 12px; margin-bottom: 4px; }
.kpi-grid-4 { grid-template-columns: repeat(4, 1fr); }
.kpi-grid-3 { grid-template-columns: repeat(3, 1fr); }

/* ── Carte KPI ── */
.kpi-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px 16px;
  position: relative;
  overflow: hidden;
  box-shadow: var(--shadow);
  transition: box-shadow 0.2s, transform 0.2s;
}
.kpi-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}
.kpi-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: var(--accent-color, var(--blue));
  border-radius: 14px 14px 0 0;
}
.kpi-accent-bg {
  position: absolute;
  top: 12px; right: 12px;
  width: 36px; height: 36px;
  border-radius: 10px;
  background: var(--accent-bg, var(--blue-light));
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
}
.kpi-value {
  font-family: 'Syne', sans-serif;
  font-size: 38px;
  font-weight: 800;
  color: var(--accent-color, var(--blue));
  line-height: 1;
  margin: 8px 0 4px;
  letter-spacing: -1.5px;
}
.kpi-label {
  font-family: 'DM Sans', sans-serif;
  font-size: 13px;
  color: var(--text2);
  font-weight: 400;
  line-height: 1.3;
}
.kpi-bar {
  margin-top: 14px;
  height: 4px;
  background: var(--border);
  border-radius: 4px;
  overflow: hidden;
}
.kpi-bar-fill {
  height: 100%;
  border-radius: 4px;
  background: var(--accent-color, var(--blue));
  opacity: 0.75;
}

/* ── Cartes flux récents ── */
.flux-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: var(--shadow);
  margin-bottom: 16px;
}
.flux-header {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 10px;
  background: #f8fafc;
}
.flux-header-title {
  font-family: 'Syne', sans-serif;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.flux-header-count {
  margin-left: auto;
  background: var(--blue-light);
  color: var(--blue);
  font-family: 'DM Sans', sans-serif;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 20px;
}

/* ── Ligne item ── */
.item-row {
  display: flex;
  align-items: center;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border);
  gap: 12px;
  transition: background 0.15s;
}
.item-row:last-child { border-bottom: none; }
.item-row:hover { background: #f8fafc; }

.item-dot {
  width: 9px; height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}
.item-main { flex: 1; min-width: 0; }
.item-title {
  font-family: 'DM Sans', sans-serif;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.item-sub {
  font-family: 'DM Sans', sans-serif;
  font-size: 11px;
  color: var(--muted);
  margin-top: 2px;
}

/* ── Badges ── */
.item-badge {
  font-family: 'DM Sans', sans-serif;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  padding: 3px 9px;
  border-radius: 5px;
  flex-shrink: 0;
}
.badge-go     { background: #dcfce7; color: #15803d; }
.badge-non    { background: #fee2e2; color: #dc2626; }
.badge-maybe  { background: #fef9c3; color: #a16207; }
.badge-accept { background: #cffafe; color: #0e7490; }
.badge-envoi  { background: #dcfce7; color: #15803d; }
.badge-refus  { background: #fee2e2; color: #dc2626; }
.badge-brouil { background: #f1f5f9; color: #64748b; }
.badge-cours  { background: #ffedd5; color: #c2410c; }
.badge-done   { background: #dcfce7; color: #15803d; }

.item-score {
  font-family: 'Syne', sans-serif;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
  min-width: 36px;
  text-align: right;
}

/* ── Empty state ── */
.empty-state {
  padding: 32px 20px;
  text-align: center;
  font-family: 'DM Sans', sans-serif;
  font-size: 13px;
  color: var(--muted);
}
.empty-state span { display: block; font-size: 28px; margin-bottom: 8px; }
</style>
"""


def _kpi(icon, value, label, accent_color, accent_bg, bar_pct=None):
    bar = ""
    if bar_pct is not None:
        bar = f'<div class="kpi-bar"><div class="kpi-bar-fill" style="width:{min(bar_pct,100)}%"></div></div>'
    return f"""
<div class="kpi-card" style="--accent-color:{accent_color};--accent-bg:{accent_bg}">
  <div class="kpi-accent-bg">{icon}</div>
  <div class="kpi-value">{value}</div>
  <div class="kpi-label">{label}</div>
  {bar}
</div>"""


def _item_row(dot_color, title, subtitle, badge_html, extra=""):
    return f"""
<div class="item-row">
  <div class="item-dot" style="background:{dot_color}"></div>
  <div class="item-main">
    <div class="item-title">{title}</div>
    <div class="item-sub">{subtitle}</div>
  </div>
  {badge_html}
  {extra}
</div>"""


def show_dashboard(user):
    st.markdown(CSS, unsafe_allow_html=True)

    try:
        database.apply_supabase_auth()
    except Exception as e:
        st.error(f"Erreur connexion : {e}")
        return

    uid = user['id']

    def _count(table, filters):
        try:
            q = database.supabase.table(table).select("id", count="exact")
            for k, v in filters.items():
                q = q.eq(k, v)
            return q.execute().count or 0
        except Exception:
            return 0

    # ── Données ───────────────────────────────────────────────────────
    total_analyses = _count('soumissions', {'entreprise_id': uid})
    go_count       = _count('soumissions', {'entreprise_id': uid, 'recommendation': 'GO'})
    maybe_count    = _count('soumissions', {'entreprise_id': uid, 'recommendation': 'PEUT-ETRE'})
    non_count      = _count('soumissions', {'entreprise_id': uid, 'recommendation': 'NON'})

    total_offres = _count('offres', {'entreprise_id': uid})
    envoyees     = _count('offres', {'entreprise_id': uid, 'statut': 'envoyee'})
    acceptees    = _count('offres', {'entreprise_id': uid, 'statut': 'acceptee'})
    refusees     = _count('offres', {'entreprise_id': uid, 'statut': 'refusee'})

    en_cours = termines = 0
    try:
        gp = database.supabase.table('gestion_projets').select("statut").eq('entreprise_id', uid).execute()
        for row in (gp.data or []):
            s = row.get('statut', '')
            if s == 'termine':
                termines += 1
            elif s in ('demarrage', 'planification', 'execution', 'suivi', 'cloture'):
                en_cours += 1
    except Exception:
        pass

    taux_succes = round(acceptees / total_offres * 100) if total_offres > 0 else 0
    bar_go    = round(go_count    / max(total_analyses, 1) * 100)
    bar_maybe = round(maybe_count / max(total_analyses, 1) * 100)
    bar_non   = round(non_count   / max(total_analyses, 1) * 100)
    bar_env   = round(envoyees    / max(total_offres, 1)   * 100)
    bar_acc   = round(acceptees   / max(total_offres, 1)   * 100)
    bar_ref   = round(refusees    / max(total_offres, 1)   * 100)

    from datetime import date
    import locale
    try:
        locale.setlocale(locale.LC_TIME, 'fr_FR.UTF-8')
    except Exception:
        pass
    aujourd_hui = date.today().strftime("%d %B %Y")

    nom_entreprise = user.get('nom_entreprise', 'Mon entreprise')
    contact        = user.get('contact_nom', '')

    # ── Header ────────────────────────────────────────────────────────
    st.markdown(f"""
<div class="dash-header">
  <div class="dash-logo">S</div>
  <div>
    <div class="dash-title">Tableau de bord</div>
    <div class="dash-sub">SoumIA · {nom_entreprise} · {contact}</div>
  </div>
  <div class="dash-date">
    <div class="dash-date-val">{aujourd_hui}</div>
    <div class="dash-date-label">Vue d'ensemble</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Section 1 : Analyses ─────────────────────────────────────────
    st.markdown('<div class="section-label">Appels d\'offres analysés</div>', unsafe_allow_html=True)
    st.markdown(f"""
<div class="kpi-grid kpi-grid-4">
  {_kpi("📊", total_analyses, "Total analysés",  "#1e6fe8", "#eff5ff", 100)}
  {_kpi("✅", go_count,       "Qualifiés — GO",   "#16a34a", "#f0fdf4", bar_go)}
  {_kpi("🟡", maybe_count,    "Peut-être",        "#b45309", "#fefce8", bar_maybe)}
  {_kpi("❌", non_count,      "Rejetés — NON",    "#dc2626", "#fef2f2", bar_non)}
</div>""", unsafe_allow_html=True)

    # ── Section 2 : Offres ───────────────────────────────────────────
    st.markdown('<div class="section-label">Offres de services</div>', unsafe_allow_html=True)
    st.markdown(f"""
<div class="kpi-grid kpi-grid-4">
  {_kpi("📁", total_offres, "Total offres",        "#1e6fe8", "#eff5ff", 100)}
  {_kpi("📤", envoyees,     "Envoyées au client",  "#16a34a", "#f0fdf4", bar_env)}
  {_kpi("🎉", acceptees,    "Acceptées",           "#0891b2", "#ecfeff", bar_acc)}
  {_kpi("❌", refusees,     "Refusées",            "#dc2626", "#fef2f2", bar_ref)}
</div>""", unsafe_allow_html=True)

    # ── Section 3 : Projets ──────────────────────────────────────────
    st.markdown('<div class="section-label">Projets & performance</div>', unsafe_allow_html=True)
    st.markdown(f"""
<div class="kpi-grid kpi-grid-3">
  {_kpi("⚡", en_cours,          "En cours d'exécution", "#d97706", "#fffbeb")}
  {_kpi("🏁", termines,          "Projets terminés",     "#16a34a", "#f0fdf4")}
  {_kpi("🎯", f"{taux_succes}%", "Taux d'acceptation",   "#0891b2", "#ecfeff", taux_succes)}
</div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Section 4 : Flux récents ─────────────────────────────────────
    col_a, col_b = st.columns(2)

    # Analyses récentes
    with col_a:
        rows_html = ""
        try:
            recent = database.supabase.table('soumissions').select("*").eq(
                'entreprise_id', uid
            ).order('created_at', desc=True).limit(6).execute()

            if recent.data:
                for item in recent.data:
                    rec   = item.get('recommendation', 'N/A')
                    nom   = item.get('nom_projet', 'Sans nom')[:42]
                    score = item.get('score', '—')
                    dat   = (item.get('created_at') or '')[:10]

                    dot       = '#16a34a' if rec == 'GO' else '#dc2626' if rec == 'NON' else '#b45309'
                    badge_cls = 'badge-go' if rec == 'GO' else 'badge-non' if rec == 'NON' else 'badge-maybe'
                    score_col = '#16a34a' if rec == 'GO' else '#dc2626' if rec == 'NON' else '#b45309'

                    rows_html += _item_row(
                        dot, nom, dat,
                        f'<span class="item-badge {badge_cls}">{rec}</span>',
                        f'<span class="item-score" style="color:{score_col}">{score}</span>'
                    )
            else:
                rows_html = '<div class="empty-state"><span>📭</span>Aucune analyse pour le moment</div>'
        except Exception as e:
            rows_html = f'<div class="empty-state"><span>⚠️</span>{str(e)[:80]}</div>'

        st.markdown(f"""
<div class="flux-card">
  <div class="flux-header">
    <span>📊</span>
    <span class="flux-header-title">Analyses récentes</span>
    <span class="flux-header-count">{total_analyses} total</span>
  </div>
  {rows_html}
</div>""", unsafe_allow_html=True)

    # Offres récentes
    with col_b:
        STATUT_CFG = {
            "brouillon":  ('#94a3b8', 'badge-brouil'),
            "a_valider":  ('#b45309', 'badge-maybe'),
            "validee":    ('#16a34a', 'badge-done'),
            "envoyee":    ('#16a34a', 'badge-envoi'),
            "en_attente": ('#d97706', 'badge-cours'),
            "acceptee":   ('#0891b2', 'badge-accept'),
            "refusee":    ('#dc2626', 'badge-refus'),
        }
        rows_html2 = ""
        try:
            offres_rec = database.supabase.table('offres').select("*").eq(
                'entreprise_id', uid
            ).order('updated_at', desc=True).limit(6).execute()

            if offres_rec.data:
                for o in offres_rec.data:
                    statut  = o.get('statut', 'brouillon')
                    contenu = o.get('contenu', {})
                    if isinstance(contenu, str):
                        try:
                            contenu = json.loads(contenu)
                        except Exception:
                            contenu = {}
                    nom = (
                        contenu.get('offre_technique', {}).get('titre_offre')
                        or contenu.get('exigences', {}).get('nom_projet')
                        or f"Offre {str(o.get('id',''))[:8]}"
                    )[:42]
                    ttc_raw = contenu.get('offre_financiere', {}).get('total_ttc', 0)
                    ttc_str = f"{ttc_raw:,.0f} $" if ttc_raw else "—"
                    maj     = (o.get('updated_at') or '')[:10]
                    dot, badge_cls = STATUT_CFG.get(statut, ('#94a3b8', 'badge-brouil'))
                    rows_html2 += _item_row(
                        dot, nom, f"{maj}  ·  {ttc_str}",
                        f'<span class="item-badge {badge_cls}">{statut.replace("_", " ").upper()}</span>'
                    )
            else:
                rows_html2 = '<div class="empty-state"><span>📭</span>Aucune offre pour le moment</div>'
        except Exception as e:
            rows_html2 = f'<div class="empty-state"><span>⚠️</span>{str(e)[:80]}</div>'

        st.markdown(f"""
<div class="flux-card">
  <div class="flux-header">
    <span>📁</span>
    <span class="flux-header-title">Offres récentes</span>
    <span class="flux-header-count">{total_offres} total</span>
  </div>
  {rows_html2}
</div>""", unsafe_allow_html=True)