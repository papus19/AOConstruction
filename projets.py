"""
Gestion des projets — v2.3
Fix : RLS corrigée dans Supabase + storage3 direct pour upload
"""

import datetime
import uuid
import streamlit as st
import database

# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
<style>
[data-testid='stFileUploader'] {
    border: 2px dashed #2E75B6 !important;
    border-radius: 12px !important;
    background: #D5E8F0 !important;
    padding: 20px !important;
    transition: border-color .2s, background .2s;
}
[data-testid='stFileUploader']:hover {
    border-color: #1E3A5F !important;
    background: #BDD7EE !important;
}
.badge-remporte { background:#D1FAE5; color:#065F46; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.badge-perdu    { background:#FEE2E2; color:#991B1B; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
.badge-en-cours { background:#FEF3C7; color:#92400E; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
</style>
"""

STATUTS = ["en cours", "remporté", "perdu"]

ICONE_FICHIER = {
    "pdf":  "📄", "xlsx": "📊", "xls": "📊", "csv": "📊",
    "docx": "📝", "doc":  "📝", "txt": "📝",
    "png":  "🖼️", "jpg":  "🖼️", "jpeg": "🖼️",
    "dwg":  "📐", "dxf":  "📐",
}

_MIME_MAP = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain", "csv": "text/csv",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp",
    "dwg": "application/acad", "dxf": "application/dxf",
    "zip": "application/zip",
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _taille_label(nb_bytes) -> str:
    if not nb_bytes:
        return "—"
    kb = nb_bytes / 1024
    return f"{kb/1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"

def _icone(nom: str) -> str:
    ext = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
    return ICONE_FICHIER.get(ext, "📎")

def _content_type(nom: str) -> str:
    ext = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
    return _MIME_MAP.get(ext, "application/octet-stream")

def _badge(statut: str) -> str:
    css = {"remporté": "badge-remporte", "perdu": "badge-perdu"}.get(statut, "badge-en-cours")
    return f'<span class="{css}">{statut.capitalize()}</span>'


# ─────────────────────────────────────────────────────────────────────────────
# STORAGE — storage3 direct avec service_role key
# ─────────────────────────────────────────────────────────────────────────────

def _upload_vers_storage(nom: str, contenu: bytes, entreprise_id: str) -> str | None:
    """Upload via storage3 direct — évite les conflits avec postgrest.auth()."""
    import config
    from storage3 import SyncStorageClient
    from datetime import datetime as dt

    ext          = nom.rsplit(".", 1)[-1] if "." in nom else "bin"
    timestamp    = dt.now().strftime("%Y%m%d_%H%M%S")
    file_name    = f"projet_{entreprise_id}_{timestamp}_{uuid.uuid4().hex[:6]}.{ext}"
    content_type = _content_type(nom)

    key = config.SUPABASE_SERVICE_ROLE_KEY or config.SUPABASE_ANON_KEY
    storage = SyncStorageClient(
        f"{config.SUPABASE_URL}/storage/v1",
        {"apiKey": key, "Authorization": f"Bearer {key}"},
    )
    storage.from_("documents").upload(
        path=file_name,
        file=contenu,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    url = storage.from_("documents").get_public_url(file_name)
    return url or None


# ─────────────────────────────────────────────────────────────────────────────
# BASE DE DONNÉES
# ─────────────────────────────────────────────────────────────────────────────

def _charger_projets(entreprise_id: str) -> list:
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
        st.error(f"❌ Chargement impossible : {e}")
        return []


def _creer_projet(entreprise_id: str, data: dict) -> str | None:
    try:
        database.apply_supabase_auth()
        result = (
            database.supabase
            .table("projets_antecedents")
            .insert({
                "entreprise_id":    entreprise_id,
                "nom_projet":       data["nom_projet"],
                "montant":          data["montant"],
                "duree_jours":      data["duree_jours"],
                "statut":           data["statut"],
                "specifications":   data.get("specifications", ""),
                "date_realisation": data.get("date_realisation") or None,
            })
            .execute()
        )
        return result.data[0]["id"] if result.data else None
    except Exception as e:
        st.error(f"❌ Création projet : {e}")
        return None


def _modifier_projet(projet_id: str, data: dict) -> bool:
    try:
        database.apply_supabase_auth()
        result = (
            database.supabase
            .table("projets_antecedents")
            .update({
                "nom_projet":       data["nom_projet"],
                "montant":          data["montant"],
                "duree_jours":      data["duree_jours"],
                "statut":           data["statut"],
                "specifications":   data.get("specifications", ""),
                "date_realisation": data.get("date_realisation") or None,
            })
            .eq("id", projet_id)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        st.error(f"❌ Modification : {e}")
        return False


def _supprimer_projet(projet_id: str) -> bool:
    try:
        database.apply_supabase_auth()
        database.supabase.table("projets_antecedents").delete().eq("id", projet_id).execute()
        return True
    except Exception as e:
        st.error(f"❌ Suppression projet : {e}")
        return False


def _inserer_document_bd(projet_id: str, entreprise_id: str, nom: str, url: str, taille: int):
    """Insert dans projet_documents avec service_role key — contourne RLS."""
    import config
    from postgrest import SyncPostgrestClient

    key = config.SUPABASE_SERVICE_ROLE_KEY or config.SUPABASE_ANON_KEY
    pg  = SyncPostgrestClient(
        base_url=f"{config.SUPABASE_URL}/rest/v1",
        headers={
            "apikey":        key,
            "Authorization": f"Bearer {key}",
            "Prefer":        "return=representation",
        },
    )
    result = pg.table("projet_documents").insert({
        "projet_id":     projet_id,
        "entreprise_id": entreprise_id,
        "nom_fichier":   nom,
        "document_url":  url,
        "taille_bytes":  taille,
    }).execute()
    print(f"[BD] Insert : {result.data}")


def _supprimer_document(doc_id: str, doc_url: str) -> bool:
    try:
        try:
            import config
            from storage3 import SyncStorageClient
            key = config.SUPABASE_SERVICE_ROLE_KEY or config.SUPABASE_ANON_KEY
            storage = SyncStorageClient(
                f"{config.SUPABASE_URL}/storage/v1",
                {"apiKey": key, "Authorization": f"Bearer {key}"},
            )
            if '/documents/' in doc_url:
                chemin = doc_url.split('/documents/')[-1].split('?')[0]
                storage.from_('documents').remove([chemin])
        except Exception:
            pass
        database.apply_supabase_auth()
        database.supabase.table("projet_documents").delete().eq("id", doc_id).execute()
        return True
    except Exception as e:
        st.error(f"❌ Suppression document : {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD DEPUIS CACHE
# ─────────────────────────────────────────────────────────────────────────────

def _uploader_depuis_cache(projet_id: str, entreprise_id: str, cache: list) -> tuple[int, int]:
    ok, ko = 0, 0
    for item in cache:
        nom     = item["nom"]
        contenu = item["bytes"]
        taille  = item["size"]
        try:
            url = _upload_vers_storage(nom, contenu, entreprise_id)
            if not url:
                raise ValueError("URL vide")
            _inserer_document_bd(projet_id, entreprise_id, nom, url, taille)
            ok += 1
        except Exception as e:
            st.warning(f"⚠️ {nom} : {e}")
            ko += 1
    return ok, ko


# ─────────────────────────────────────────────────────────────────────────────
# FORMULAIRE PROJET
# ─────────────────────────────────────────────────────────────────────────────

def _formulaire_projet(form_key, defaults=None, submit_label="💾 Sauvegarder"):
    d = defaults or {}
    with st.form(form_key, clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            nom = st.text_input("Nom du projet *", value=d.get("nom_projet", ""),
                                placeholder="Ex : CSSMB École secondaire Saint-Laurent")
            montant = st.number_input("Montant ($)", min_value=0,
                                      value=int(d.get("montant") or 0), step=1000)
            duree = st.number_input("Durée (jours ouvrés)", min_value=1,
                                    value=int(d.get("duree_jours") or 30))
            date_val = d.get("date_realisation")
            if isinstance(date_val, str) and date_val:
                try:
                    date_val = datetime.date.fromisoformat(date_val)
                except ValueError:
                    date_val = None
            date_real = st.date_input("Date de réalisation", value=date_val or None)
        with col2:
            statut = st.selectbox("Statut", options=STATUTS,
                                  index=STATUTS.index(d.get("statut", "en cours")))
            specs = st.text_area("Spécifications libres", value=d.get("specifications", ""),
                                 height=148,
                                 placeholder="Section électrique, envergure, leçons apprises…")
        soumis = st.form_submit_button(submit_label, type="primary")

    if soumis:
        if not nom.strip():
            st.error("❌ Le nom du projet est obligatoire.")
            return None
        return {
            "nom_projet":       nom.strip(),
            "montant":          montant,
            "duree_jours":      duree,
            "statut":           statut,
            "specifications":   specs.strip(),
            "date_realisation": str(date_real) if date_real else None,
        }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SECTION DOCUMENTS
# ─────────────────────────────────────────────────────────────────────────────

def _afficher_documents(projet: dict, entreprise_id: str):
    st.markdown(_CSS, unsafe_allow_html=True)
    docs = projet.get("projet_documents") or []
    pid  = str(projet["id"])

    st.markdown(f"**📁 Documents du projet** ({len(docs)})")

    if docs:
        for doc in docs:
            doc_id  = str(doc.get("id", ""))
            nom_doc = doc.get("nom_fichier", "—")
            url     = doc.get("document_url", "")
            taille  = doc.get("taille_bytes") or 0

            col_icone, col_info, col_dl, col_del = st.columns([0.5, 6, 1, 1])
            with col_icone:
                st.markdown(f"<div style='font-size:20px;padding-top:6px'>{_icone(nom_doc)}</div>",
                            unsafe_allow_html=True)
            with col_info:
                st.markdown(f"**{nom_doc}**  \n"
                            f"<span style='color:#94A3B8;font-size:12px'>{_taille_label(taille)}</span>",
                            unsafe_allow_html=True)
            with col_dl:
                if url:
                    st.link_button("⬇️", url, help=f"Télécharger {nom_doc}")
            with col_del:
                if st.button("🗑", key=f"del_doc_{doc_id}", help="Supprimer"):
                    st.session_state[f"confirm_del_doc_{doc_id}"] = True

            if st.session_state.get(f"confirm_del_doc_{doc_id}"):
                st.warning(f"Supprimer **{nom_doc}** ?")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Confirmer", key=f"yes_deldoc_{doc_id}"):
                        if _supprimer_document(doc_id, url):
                            st.session_state.pop(f"confirm_del_doc_{doc_id}", None)
                            st.success("Supprimé.")
                            st.rerun()
                with c2:
                    if st.button("❌ Annuler", key=f"no_deldoc_{doc_id}"):
                        st.session_state.pop(f"confirm_del_doc_{doc_id}", None)
                        st.rerun()
    else:
        st.caption("_Aucun document pour l'instant_")

    # ── Zone upload ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**➕ Ajouter des documents**")
    st.caption("PDF, Excel, Word, images, plans DWG… — Tous formats")

    upload_key = f"upload_docs_{pid}"
    cache_key  = f"upload_cache_{pid}"

    def _on_change():
        fichiers = st.session_state.get(upload_key) or []
        cache = []
        for f in fichiers:
            try:
                cache.append({"nom": f.name, "bytes": f.read(), "size": f.size})
            except Exception:
                pass
        st.session_state[cache_key] = cache

    st.file_uploader(
        label="Glissez vos fichiers ici ou cliquez",
        type=None,
        accept_multiple_files=True,
        key=upload_key,
        on_change=_on_change,
    )

    cache = st.session_state.get(cache_key) or []
    nb    = len(cache)

    col_i, col_b = st.columns([3, 1])
    with col_i:
        if nb:
            total = sum(c["size"] for c in cache)
            st.info(f"📎 **{nb} fichier(s)** prêt(s) — {_taille_label(total)}")
    with col_b:
        enregistrer = st.button(
            f"📤 Enregistrer ({nb})" if nb else "📤 Enregistrer",
            key=f"btn_upload_{pid}",
            type="primary",
            disabled=(nb == 0),
            use_container_width=True,
        )

    if enregistrer and cache:
        with st.spinner("Enregistrement en cours…"):
            ok, ko = _uploader_depuis_cache(pid, entreprise_id, cache)
        if ok:
            st.success(f"✅ {ok} document(s) enregistré(s) !")
        if ko:
            st.error(f"❌ {ko} document(s) en erreur")
        st.session_state.pop(upload_key, None)
        st.session_state.pop(cache_key, None)
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# ONGLET PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def show_projets_tab(user):
    st.markdown(_CSS, unsafe_allow_html=True)
    st.header("🏗️ Projets")
    st.caption("Chaque projet est un dossier. Ajoutez-y des documents — l'IA s'en sert pour enrichir les analyses.")

    entreprise_id = str(user["id"])

    with st.expander("➕ Créer un nouveau projet", expanded=False):
        data_nouveau = _formulaire_projet("form_nouveau_projet", submit_label="🚀 Créer le projet")
        if data_nouveau:
            nouveau_id = _creer_projet(entreprise_id, data_nouveau)
            if nouveau_id:
                st.success(f"✅ Projet **{data_nouveau['nom_projet']}** créé !")
                st.session_state["projet_ouvert"] = nouveau_id
                st.rerun()

    st.markdown("---")

    projets = _charger_projets(entreprise_id)

    if not projets:
        st.info("📭 Aucun projet. Créez votre premier projet ci-dessus.")
        return

    nb_remporte = sum(1 for p in projets if p.get("statut") == "remporté")
    nb_cours    = sum(1 for p in projets if p.get("statut") == "en cours")
    total_ca    = sum(float(p.get("montant") or 0) for p in projets if p.get("statut") == "remporté")
    nb_docs     = sum(len(p.get("projet_documents") or []) for p in projets)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total",           len(projets))
    m2.metric("Remportés",       nb_remporte)
    m3.metric("En cours",        nb_cours)
    m4.metric("CA remporté ($)", f"{total_ca:,.0f}")
    m5.metric("Documents",       nb_docs)

    st.markdown("---")

    filtre = st.radio("Afficher :", ["Tous", "remporté", "en cours", "perdu"],
                      horizontal=True, label_visibility="collapsed")
    liste = projets if filtre == "Tous" else [p for p in projets if p.get("statut") == filtre]

    if not liste:
        st.caption("_Aucun projet pour ce filtre._")
        return

    projet_ouvert = st.session_state.get("projet_ouvert")

    for projet in liste:
        pid       = str(projet.get("id", ""))
        nom       = projet.get("nom_projet", "Sans nom")
        docs      = projet.get("projet_documents") or []
        nb_docs_p = len(docs)
        statut    = projet.get("statut", "en cours")
        montant   = float(projet.get("montant") or 0)
        duree     = projet.get("duree_jours") or 0
        date_r    = projet.get("date_realisation") or ""

        auto_open = (projet_ouvert == pid)
        if auto_open:
            st.session_state.pop("projet_ouvert", None)

        label_exp = (f"**{nom}**  ·  {nb_docs_p} doc{'s' if nb_docs_p != 1 else ''}  "
                     f"·  {montant:,.0f} $  ·  {duree}j")

        with st.expander(label_exp, expanded=auto_open):
            edit_key    = f"edit_mode_{pid}"
            confirm_key = f"confirm_del_{pid}"
            if edit_key not in st.session_state:
                st.session_state[edit_key] = False

            if not st.session_state[edit_key]:
                st.markdown(_badge(statut), unsafe_allow_html=True)
                c1, c2, c3 = st.columns(3)
                c1.metric("Montant",     f"{montant:,.0f} $")
                c2.metric("Durée",       f"{duree} jours")
                c3.metric("Réalisation", date_r or "—")
                if projet.get("specifications"):
                    st.markdown(f"**Spécifications :** {projet['specifications']}")

                st.markdown("---")
                _afficher_documents(projet, entreprise_id)

                st.markdown("---")
                bc1, bc2, _ = st.columns([1, 1, 5])
                with bc1:
                    if st.button("✏️ Modifier", key=f"btn_edit_{pid}"):
                        st.session_state[edit_key] = True
                        st.rerun()
                with bc2:
                    if st.button("🗑 Supprimer", key=f"btn_del_{pid}"):
                        st.session_state[confirm_key] = True
                        st.rerun()

                if st.session_state.get(confirm_key):
                    st.warning(f"⚠️ Supprimer **{nom}** et ses **{nb_docs_p} document(s)** ?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ Confirmer", key=f"yes_del_{pid}"):
                            if _supprimer_projet(pid):
                                st.session_state.pop(confirm_key, None)
                                st.success(f"Projet **{nom}** supprimé.")
                                st.rerun()
                    with c2:
                        if st.button("❌ Annuler", key=f"no_del_{pid}"):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
            else:
                st.markdown("##### ✏️ Modifier le projet")
                data_edit = _formulaire_projet(f"form_edit_{pid}", defaults=projet,
                                               submit_label="💾 Sauvegarder")
                if data_edit:
                    if _modifier_projet(pid, data_edit):
                        st.session_state[edit_key] = False
                        st.success("✅ Projet mis à jour.")
                        st.rerun()
                if st.button("↩️ Annuler", key=f"btn_annuler_{pid}"):
                    st.session_state[edit_key] = False
                    st.rerun()
                st.markdown("---")
                _afficher_documents(projet, entreprise_id)


# ─────────────────────────────────────────────────────────────────────────────
# UTILITAIRE IA
# ─────────────────────────────────────────────────────────────────────────────

def get_projets_context_pour_ia(entreprise_id: str, max_projets: int = 5) -> str:
    try:
        database.apply_supabase_auth()
        result = (
            database.supabase
            .table("projets_antecedents")
            .select("nom_projet, montant, duree_jours, statut, specifications, date_realisation, projet_documents(nom_fichier)")
            .eq("entreprise_id", entreprise_id)
            .eq("statut", "remporté")
            .order("created_at", desc=True)
            .limit(max_projets)
            .execute()
        )
        projets = result.data or []
    except Exception:
        return ""

    if not projets:
        return ""

    lignes = ["=== RÉFÉRENCE : PROJETS REMPORTÉS ==="]
    for p in projets:
        docs     = p.get("projet_documents") or []
        noms_doc = ", ".join(d.get("nom_fichier", "") for d in docs) if docs else "aucun"
        lignes.append(f"• {p['nom_projet']} | {float(p.get('montant') or 0):,.0f} $ "
                      f"| {p.get('duree_jours') or 0} jours | Réalisé : {p.get('date_realisation') or '—'}")
        if p.get("specifications"):
            lignes.append(f"  Specs : {p['specifications']}")
        lignes.append(f"  Docs : {noms_doc}")

    return "\n".join(lignes)