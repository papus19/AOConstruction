"""
projet_documents.py — Gestion des documents par catégorie pour un projet AO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Extraction multi-méthode : pdfplumber → pypdf → OCR (tesseract)
"""

import io
import streamlit as st

# ── Imports extraction ──────────────────────────────────────────────────────
try:
    import pdfplumber
    _PDFPLUMBER = True
except ImportError:
    _PDFPLUMBER = False

try:
    import pypdf
    _PYPDF = True
except ImportError:
    _PYPDF = False

try:
    import pytesseract
    from pdf2image import convert_from_bytes
    from PIL import Image
    _OCR = True
except ImportError:
    _OCR = False

try:
    import docx as _docx
    _DOCX = True
except ImportError:
    _DOCX = False

try:
    import openpyxl
    _XLSX = True
except ImportError:
    _XLSX = False

try:
    import pandas as pd
    _PANDAS = True
except ImportError:
    _PANDAS = False


# ─── Catégories ──────────────────────────────────────────────────────────────

CATEGORIES = {
    "invitation": {
        "label":       "📋 Invitation / Avis d'AO",
        "description": "Invitation à soumissionner, avis public, description du projet, dates clés",
        "requis":      True,
    },
    "cahier_charges": {
        "label":       "📐 Cahier des charges & Devis technique",
        "description": "Devis de construction, spécifications techniques, plans, addenda, normes exigées",
        "requis":      True,
    },
    "bordereau": {
        "label":       "💰 Bordereau de prix & Formulaires",
        "description": "Bordereau de prix vierge, formulaire de soumission, devis quantitatif",
        "requis":      True,
    },
    "autres": {
        "label":       "📎 Autres documents",
        "description": "Plans d'étage, photos, rapports d'inspection, documents de référence",
        "requis":      False,
    },
}


# ─── Extraction de texte multi-méthode ───────────────────────────────────────

def _extraire_pdf(file_bytes: bytes) -> tuple[str, str]:
    """
    Essaie plusieurs méthodes d'extraction dans l'ordre.
    Retourne (texte, méthode_utilisée).
    """
    texte = ""

    # Méthode 1 : pdfplumber
    if _PDFPLUMBER:
        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            texte = "\n\n".join(p for p in pages if p.strip())
            if len(texte.strip()) > 50:
                return texte, "pdfplumber"
        except Exception:
            pass

    # Méthode 2 : pypdf
    if _PYPDF:
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages  = [page.extract_text() or "" for page in reader.pages]
            texte  = "\n\n".join(p for p in pages if p.strip())
            if len(texte.strip()) > 50:
                return texte, "pypdf"
        except Exception:
            pass

    # Méthode 3 : OCR tesseract (PDFs scannés / images)
    if _OCR:
        try:
            images = convert_from_bytes(file_bytes, dpi=200)
            pages  = []
            for img in images:
                t = pytesseract.image_to_string(img, lang="fra+eng")
                if t.strip():
                    pages.append(t)
            texte = "\n\n".join(pages)
            if len(texte.strip()) > 20:
                return texte, "OCR (tesseract)"
        except Exception:
            pass

    return "", "aucune méthode"


def _extraire_image(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """OCR direct sur image PNG/JPG/PWG/TIFF."""
    if not _OCR:
        return "", "OCR non disponible"
    try:
        img = Image.open(io.BytesIO(file_bytes))
        texte = pytesseract.image_to_string(img, lang="fra+eng")
        if texte.strip():
            return texte, "OCR image"
    except Exception:
        pass
    return "", "échec OCR image"


def _extraire_excel(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """Extrait le texte d'un fichier Excel (.xlsx/.xls)."""
    # Méthode 1 : openpyxl
    if _XLSX and filename.lower().endswith((".xlsx", ".xlsm")):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            lignes = []
            for sheet in wb.worksheets:
                lignes.append(f"=== FEUILLE : {sheet.title} ===")
                for row in sheet.iter_rows(values_only=True):
                    vals = [str(c) for c in row if c is not None and str(c).strip()]
                    if vals:
                        lignes.append("\t".join(vals))
            texte = "\n".join(lignes)
            if texte.strip():
                return texte, "openpyxl"
        except Exception:
            pass
    # Méthode 2 : pandas
    if _PANDAS:
        try:
            dfs = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, dtype=str)
            lignes = []
            for sheet_name, df in dfs.items():
                lignes.append(f"=== FEUILLE : {sheet_name} ===")
                lignes.append(df.to_string(index=False))
            texte = "\n".join(lignes)
            if texte.strip():
                return texte, "pandas"
        except Exception:
            pass
    return "", "aucune méthode Excel"


def _extraire_texte(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """Routeur par extension. Retourne (texte, méthode)."""
    fname = filename.lower()
    if fname.endswith(".pdf"):
        return _extraire_pdf(file_bytes)
    elif fname.endswith((".docx", ".doc")):
        if _DOCX:
            try:
                doc  = _docx.Document(io.BytesIO(file_bytes))
                texte = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                return texte, "python-docx"
            except Exception:
                pass
        return "", "aucune méthode"
    elif fname.endswith((".xlsx", ".xls", ".xlsm")):
        return _extraire_excel(file_bytes, filename)
    elif fname.endswith((".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp", ".pwg")):
        return _extraire_image(file_bytes, filename)
    elif fname.endswith(".txt"):
        try:
            return file_bytes.decode("utf-8", errors="replace"), "txt"
        except Exception:
            return "", "aucune méthode"
    return "", "format non supporté"


# ─── Session ─────────────────────────────────────────────────────────────────

def _init():
    if "docs_projet" not in st.session_state:
        st.session_state["docs_projet"] = {
            cat: {"fichiers": [], "texte_combine": ""}
            for cat in CATEGORIES
        }


def get_texte(cat: str) -> str:
    _init()
    return st.session_state["docs_projet"].get(cat, {}).get("texte_combine", "")


def get_fichiers(cat: str) -> list:
    _init()
    return st.session_state["docs_projet"].get(cat, {}).get("fichiers", [])


def texte_invitation()     -> str: return get_texte("invitation")
def texte_cahier_charges() -> str: return get_texte("cahier_charges")
def texte_bordereau()      -> str: return get_texte("bordereau")


def get_bytes_formulaire(categories=None):
    """
    Retourne les bytes bruts du premier PDF trouvé dans les catégories indiquées.
    Priorité : bordereau → invitation → cahier_charges.
    Retourne (bytes, nom_fichier) ou (None, "").
    Utilisé par le générateur de formulaire pour remplir le PDF original.
    """
    _init()
    cats = categories or ["bordereau", "invitation", "cahier_charges"]
    for cat in cats:
        for f in get_fichiers(cat):
            b = f.get("bytes")
            if b and f.get("nom", "").lower().endswith(".pdf"):
                return b, f["nom"]
    return None, ""


def texte_tous() -> str:
    _init()
    parties = []
    for cat, meta in CATEGORIES.items():
        t = get_texte(cat)
        if t.strip():
            parties.append(f"=== {meta['label'].upper()} ===\n{t}")
    return "\n\n".join(parties)


def est_complet() -> dict:
    return {cat: bool(get_texte(cat).strip()) for cat in CATEGORIES}


def texte_ao_complet() -> str:
    """
    Retourne le texte consolidated pour les modules offre_technique et offre_financiere.
    Priorité : cahier_charges > invitation > tous.
    """
    cdc = texte_cahier_charges()
    inv = texte_invitation()
    brd = texte_bordereau()
    parties = []
    if inv.strip():
        parties.append(f"=== INVITATION / AO ===\n{inv}")
    if cdc.strip():
        parties.append(f"=== CAHIER DES CHARGES ===\n{cdc}")
    if brd.strip():
        parties.append(f"=== BORDEREAU DE PRIX ===\n{brd}")
    return "\n\n".join(parties)


# ─── UI ──────────────────────────────────────────────────────────────────────

def show_chargement_documents(key_prefix: str = "docs") -> bool:
    _init()
    etat     = est_complet()
    n_ok     = sum(1 for ok in etat.values() if ok)
    n_req    = sum(1 for cat in CATEGORIES if CATEGORIES[cat]["requis"])
    n_req_ok = sum(1 for cat, ok in etat.items() if ok and CATEGORIES[cat]["requis"])

    # ── Barre de statut globale ──────────────────────────────────────────
    if n_req_ok == n_req:
        st.success(
            f"✅ **Documents complets** — {n_ok}/{len(CATEGORIES)} catégories chargées. "
            "Passez à l'onglet **📝 Générateur d'Offres**."
        )
    else:
        manquants = [
            CATEGORIES[cat]["label"]
            for cat in CATEGORIES
            if CATEGORIES[cat]["requis"] and not etat[cat]
        ]
        st.info(
            f"📂 **{n_ok}/{len(CATEGORIES)} catégories chargées.** "
            f"Manquants : {', '.join(manquants)}"
        )

    # ── Upload par catégorie ──────────────────────────────────────────────
    for cat, meta in CATEGORIES.items():
        fichiers = get_fichiers(cat)
        statut   = "✅" if etat[cat] else ("🔴" if meta["requis"] else "⚪")

        with st.expander(
            f"{statut} **{meta['label']}** "
            f"{'*(requis)*' if meta['requis'] else '*(optionnel)*'}"
            + (f" — {len(fichiers)} fichier(s)" if fichiers else ""),
            expanded=not etat[cat] and meta["requis"],
        ):
            st.caption(meta["description"])
            st.caption("📎 Formats : PDF, Word, Excel, PNG, JPG, PWG (plans)")

            # ── Fichiers déjà chargés ───────────────────────────────
            if fichiers:
                for i, fi in enumerate(fichiers):
                    c1, c2, c3 = st.columns([5, 3, 1])
                    methode = fi.get("methode", "")
                    nb_car  = fi.get("nb_chars", 0)
                    icone   = "🔍" if "OCR" in methode else ("✅" if nb_car > 50 else "⚠️")
                    c1.markdown(f"📄 **{fi['nom']}**")
                    c2.caption(
                        f"{fi['taille_kb']:.0f} KB — {nb_car:,} car."
                        + (f" *({methode})*" if methode else "")
                    )
                    if nb_car == 0:
                        c2.error("❌ Texte non extrait")
                    if c3.button("✕", key=f"{key_prefix}_del_{cat}_{i}"):
                        fichiers.pop(i)
                        st.session_state["docs_projet"][cat]["texte_combine"] = (
                            "\n\n".join(f["texte"] for f in fichiers)
                        )
                        # Invalider les données dérivées
                        _invalider_derives()
                        st.rerun()

            # ── Upload ──────────────────────────────────────────────
            uploaded = st.file_uploader(
                "Ajouter des fichiers",
                accept_multiple_files=True,
                type=["pdf", "docx", "txt", "xlsx", "xls",
                      "png", "jpg", "jpeg", "tiff", "pwg"],
                key=f"{key_prefix}_upload_{cat}",
                label_visibility="collapsed",
            )

            if uploaded:
                noms_existants = {f["nom"] for f in fichiers}
                nouveaux = [uf for uf in uploaded if uf.name not in noms_existants]
                if nouveaux:
                    progress = st.progress(0, text=f"Extraction de {len(nouveaux)} fichier(s)…")
                    for idx, uf in enumerate(nouveaux):
                        progress.progress(
                            (idx + 1) / len(nouveaux),
                            text=f"📄 Extraction : {uf.name}…"
                        )
                        file_bytes      = uf.read()
                        texte, methode  = _extraire_texte(file_bytes, uf.name)
                        fichiers.append({
                            "nom":       uf.name,
                            "taille_kb": len(file_bytes) / 1024,
                            "nb_chars":  len(texte),
                            "texte":     texte,
                            "methode":   methode,
                            "bytes":     file_bytes,   # ← bytes bruts pour remplissage PDF
                        })

                    st.session_state["docs_projet"][cat]["texte_combine"] = (
                        "\n\n".join(f["texte"] for f in fichiers)
                    )
                    st.session_state["docs_projet"][cat]["fichiers"] = fichiers
                    progress.empty()

                    # Synchroniser texte_ao pour les autres modules
                    _synchroniser_texte_ao()
                    _invalider_derives()

                    nb_ok_ext = sum(1 for f in nouveaux if f in fichiers and
                                    next((x["nb_chars"] for x in fichiers if x["nom"]==f.name), 0) > 50)
                    st.success(
                        f"✅ **{len(nouveaux)} fichier(s) ajouté(s)** dans {meta['label']}."
                    )
                    # Afficher avertissement si texte vide
                    vides = [f for f in fichiers if f.get("nb_chars", 0) == 0]
                    if vides:
                        st.warning(
                            f"⚠️ **{len(vides)} fichier(s) sans texte extractible** "
                            f"({', '.join(v['nom'] for v in vides)}). "
                            "Ces fichiers sont probablement des PDFs scannés. "
                            "L'OCR a été tenté — si le résultat est 0 car., le fichier "
                            "contient uniquement des images sans texte (plans, photos)."
                        )

            # ── Vider la catégorie ───────────────────────────────────
            if fichiers:
                if st.button(
                    f"🗑️ Vider cette catégorie",
                    key=f"{key_prefix}_reset_{cat}",
                ):
                    st.session_state["docs_projet"][cat] = {"fichiers": [], "texte_combine": ""}
                    _invalider_derives()
                    st.rerun()

    # ── Réinitialisation globale ──────────────────────────────────────────
    st.markdown("---")
    if st.button("🔄 Réinitialiser tous les documents", key=f"{key_prefix}_reset_all"):
        st.session_state["docs_projet"] = {
            cat: {"fichiers": [], "texte_combine": ""} for cat in CATEGORIES
        }
        _invalider_derives()
        st.success("✅ Réinitialisé.")
        st.rerun()

    return n_req_ok == n_req


def _synchroniser_texte_ao():
    """
    Met à jour st.session_state["analyse_texte_ao"] et ["texte_ao_courant"]
    avec le texte consolidé — utilisé par generateur_offres.py.
    """
    texte = texte_ao_complet()
    if texte.strip():
        st.session_state["analyse_texte_ao"] = texte
        st.session_state["texte_ao_courant"] = texte


def _invalider_derives():
    """Supprime les données dérivées quand les documents changent."""
    offre_data = st.session_state.get("offre_data", {})
    for k in ["bordereau_ao", "offre_technique", "soumission", "items_sans_prix"]:
        offre_data.pop(k, None)
    st.session_state.pop("offre_generee", None)