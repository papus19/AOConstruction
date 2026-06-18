"""
formulaire_ao.py — Formulaire officiel de soumission
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Responsabilités :
  - Extraction de la structure d'un PDF de formulaire (pdfplumber)
  - Analyse IA : mapping champs → profil entreprise
  - Génération PDF rempli (overlay ReportLab sur PDF original)
  - Génération Word du formulaire structuré
  - Aperçu HTML du formulaire
  - Affichage UI Streamlit (_afficher_section_formulaire_ao)

Les fonctions _fao_* sont pures (pas de st.).
La fonction afficher_section_formulaire_ao() utilise st.
"""

import io
import re
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
import projet_documents as pdocs
from llm_manager import LLMManager

llm_manager = LLMManager()

# Sections optionnelles que l'utilisateur peut ajouter au formulaire
SECTIONS_OPTIONNELLES = {
    "curriculum_vitae_equipe": "CV de l'équipe de projet",
    "references_clients":      "Références clients détaillées",
    "plan_ssst":               "Plan santé-sécurité (SSST)",
    "assurances":              "Preuves d'assurance",
    "sous_traitants":          "Liste des sous-traitants proposés",
    "methodologie":            "Méthodologie d'exécution détaillée",
    "plan_qualite":            "Plan qualité",
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# 1. EXTRACTION DE LA STRUCTURE DU PDF
# ─────────────────────────────────────────────────────────────────────────────

def extraire_structure_formulaire(pdf_bytes: bytes) -> dict:
    """
    Lit le PDF et extrait : texte par page, annexes détectées,
    zones à remplir (lignes ___, champs avec ":").

    Args:
        pdf_bytes: Contenu binaire du fichier PDF.

    Returns:
        Dict avec nb_pages, pages[], annexes[], zones_a_remplir[], texte_complet.
    """
    import pdfplumber

    pages_data, annexes, zones = [], [], []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        nb_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            pg    = i + 1
            texte = page.extract_text() or ""
            lignes = texte.split("\n")

            for ligne in lignes:
                l = ligne.strip()

                # Détection des annexes
                if "ANNEXE" in l.upper() and any(c.isdigit() for c in l):
                    m = re.search(r"ANNEXE\s+[\d\.]+\s*[-–]?\s*(.{0,80})", l, re.I)
                    if m and m.group(0).strip() not in [a["titre"] for a in annexes]:
                        annexes.append({"page": pg, "titre": m.group(0).strip()})

                # Détection des zones à remplir
                mots_zone = [
                    "Nom", "Adresse", "Téléphone", "Courriel", "Fax", "Site",
                    "NEQ", "RBQ", "TPS", "TVQ", "représentant", "Titre",
                    "Signature", "Date", "Cellulaire", "Numéro", "Par :", "Montant",
                    "Fonction", "AMF", "Début", "Fin"
                ]
                if "_____" in l or (
                    any(kw.lower() in l.lower() for kw in mots_zone)
                    and len(l) < 120
                    and (":" in l or "_" in l or "." * 5 in l)
                ):
                    zones.append({"page": pg, "texte_ligne": l[:120]})

            pages_data.append({"page": pg, "texte": texte[:3000]})

    return {
        "nb_pages":       nb_pages,
        "pages":          pages_data,
        "annexes":        annexes,
        "zones_a_remplir": zones[:80],
        "texte_complet":  "\n\n---PAGE---\n\n".join(
            f"[PAGE {p['page']}]\n{p['texte']}" for p in pages_data
        )[:12000],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. ANALYSE IA DU FORMULAIRE
# ─────────────────────────────────────────────────────────────────────────────

def analyser_formulaire_ia(
    structure: dict,
    profil: dict,
    projets: list,
    analyse_ao: dict,
) -> dict:
    """
    L'IA cartographie chaque champ du formulaire vers les données du profil.
    Identifie les champs pré-remplis automatiquement et les champs manquants.

    Args:
        structure: Résultat de extraire_structure_formulaire().
        profil: Profil entreprise complet.
        projets: Liste des projets antérieurs (max 3 utilisés).
        analyse_ao: Dict d'analyse du projet courant.

    Returns:
        Dict avec champs_remplis[], champs_manquants[], alertes[],
        sections_detectees[], resume.
    """
    refs = ""
    for p in (projets or [])[:3]:
        refs += (
            f"\n- {p.get('nom_projet','?')}: {float(p.get('montant',0)):,.0f}$ | "
            f"Client: {p.get('client','?')} | Réalisé: {p.get('date_realisation','?')}"
        )

    prompt = f"""Tu es un analyste spécialisé en appels d'offres publics au Québec.

## FORMULAIRE À ANALYSER
{structure['texte_complet']}

## ANNEXES DÉTECTÉES
{json.dumps(structure['annexes'], ensure_ascii=False)}

## PROFIL ENTREPRISE
{json.dumps({
    "nom":              profil.get("nom_entreprise",""),
    "adresse":          profil.get("adresse",""),
    "ville":            profil.get("ville",""),
    "province":         profil.get("province",""),
    "code_postal":      profil.get("code_postal",""),
    "telephone":        profil.get("contact_telephone",""),
    "courriel":         profil.get("contact_email",""),
    "site_web":         profil.get("site_web",""),
    "rbq":              profil.get("licence_rbq",""),
    "neq":              profil.get("numero_neq",""),
    "tps":              profil.get("numero_tps",""),
    "tvq":              profil.get("numero_tvq",""),
    "contact_nom":      profil.get("contact_nom",""),
    "contact_titre":    profil.get("contact_titre",""),
    "contact_cellulaire": profil.get("contact_cellulaire",""),
    "statut_juridique": profil.get("statut_juridique","Société par actions"),
    "amf":              profil.get("numero_amf",""),
}, ensure_ascii=False)}

## PROJETS ANTÉRIEURS
{refs or "Aucun"}

## APPEL D'OFFRES
{json.dumps({
    "numero": (analyse_ao or {}).get("projet",{}).get("numero",""),
    "nom":    (analyse_ao or {}).get("projet",{}).get("nom",""),
    "lieu":   (analyse_ao or {}).get("projet",{}).get("lieu",""),
    "dates":  (analyse_ao or {}).get("dates",{}),
}, ensure_ascii=False)}

Analyse TOUS les champs à remplir dans ce formulaire.
Pour chaque champ, vérifie si la donnée est disponible dans le profil.

Réponds UNIQUEMENT en JSON valide (pas de markdown) :

{{"champs_remplis":[{{"id":"nom_entreprise","label":"Nom complet du soumissionnaire","valeur":"...","source":"profil","page":4}}],
"champs_manquants":[{{"id":"numero_tps","label":"Numéro TPS/TVH","raison_manquante":"Non configuré","priorite":"haute","page":4,"exemple":"123456789RT0001"}}],
"alertes":[{{"type":"critique","message":"La lettre d'engagement de caution requiert les coordonnées de votre assureur.","page":11,"action_requise":"Contacter votre assureur avant le dépôt"}}],
"sections_detectees":[{{"id":"identification","titre":"Identification du soumissionnaire","page":4,"completable_auto":true}}],
"montant_soumission_requis":true,
"signature_physique_requise":true,
"resume":"Formulaire de X pages. Y champs pré-remplis, Z champs manquants."}}"""

    res = llm_manager.analyze(prompt, max_tokens=4000)

    fallback = {
        "champs_remplis":    [],
        "champs_manquants":  [],
        "alertes": [{"type": "info", "message": "Analyse IA indisponible.", "page": 0, "action_requise": ""}],
        "sections_detectees":          [],
        "montant_soumission_requis":   True,
        "signature_physique_requise":  True,
        "resume": "Analyse non disponible — remplissez les champs manuellement.",
    }

    if not res["success"]:
        fallback["alertes"][0]["message"] = f"Analyse IA indisponible : {res.get('error', 'erreur inconnue')}"
        return fallback

    reponse = res["result"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        return json.loads(reponse)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", reponse)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return fallback


# ─────────────────────────────────────────────────────────────────────────────
# 3. GÉNÉRATION PDF REMPLI (overlay ReportLab)
# ─────────────────────────────────────────────────────────────────────────────

def generer_pdf_formulaire(
    pdf_bytes: bytes,
    champs_remplis: list,
    champs_karl: dict,
) -> bytes | None:
    """
    Remplit le PDF officiel avec un overlay ReportLab par-dessus le PDF original.
    Détecte les zones à remplir (lignes ___) via pdfplumber, puis écrit les
    valeurs directement avec pypdf + reportlab.

    Args:
        pdf_bytes: PDF original du formulaire AO.
        champs_remplis: Champs pré-remplis par l'IA (de analyser_formulaire_ia).
        champs_karl: Saisies manuelles de l'utilisateur (overrides l'IA).

    Returns:
        bytes du PDF rempli, None si erreur.
    """
    try:
        import pdfplumber
        from reportlab.pdfgen import canvas
        from pypdf import PdfReader, PdfWriter
        import io as _io

        # 1. Construire le dictionnaire de valeurs finales
        valeurs_finales = {}
        for c in champs_remplis:
            valeurs_finales[c.get("label", c.get("id", ""))] = c.get("valeur", "")
        valeurs_finales.update({k: v for k, v in champs_karl.items() if v})

        KEYWORDS = {
            "nom":             valeurs_finales.get("nom_entreprise", champs_karl.get("nom_entreprise", "")),
            "raison sociale":  valeurs_finales.get("nom_entreprise", champs_karl.get("nom_entreprise", "")),
            "soumissionnaire": valeurs_finales.get("nom_entreprise", champs_karl.get("nom_entreprise", "")),
            "adresse":         champs_karl.get("adresse", ""),
            "téléphone":       champs_karl.get("telephone", ""),
            "telephone":       champs_karl.get("telephone", ""),
            "courriel":        champs_karl.get("courriel_corp", ""),
            "site internet":   champs_karl.get("site_web", ""),
            "neq":             champs_karl.get("neq", ""),
            "rbq":             champs_karl.get("rbq", ""),
            "tps":             champs_karl.get("tps", ""),
            "tvq":             champs_karl.get("tvq", ""),
            "représentant":    champs_karl.get("contact_nom", ""),
            "titre":           champs_karl.get("contact_titre", ""),
            "fonction":        champs_karl.get("contact_titre", ""),
            "lettres":         champs_karl.get("montant_lettres", ""),
            "chiffres":        champs_karl.get("montant_chiffres", ""),
            "date":            champs_karl.get("date_soumission", datetime.now().strftime("%d/%m/%Y")),
            "montant":         champs_karl.get("montant_chiffres", ""),
        }

        # 2. Scanner le PDF pour trouver les zones à remplir
        annotations = {}
        with pdfplumber.open(_io.BytesIO(pdf_bytes)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                page_h = float(page.height)
                page_w = float(page.width)
                words  = page.extract_words() or []
                annotations[page_idx] = []

                for kw, valeur in KEYWORDS.items():
                    if not valeur:
                        continue
                    valeur = str(valeur).strip()
                    if not valeur:
                        continue

                    for word in words:
                        if kw.lower() in word.get("text", "").lower():
                            y_ref = float(word.get("top", 0))
                            x_ref = float(word.get("x1", word.get("x0", 0)))

                            zone_found = None
                            for w2 in words:
                                if "_" in w2.get("text", "") and abs(float(w2.get("top", 0)) - y_ref) < 6:
                                    if float(w2.get("x0", 0)) >= x_ref - 5:
                                        zone_found = w2
                                        break

                            if zone_found:
                                x_write     = float(zone_found.get("x0", x_ref + 5)) + 2
                                y_pdfplumber = float(zone_found.get("top", y_ref))
                                y_reportlab  = page_h - y_pdfplumber - 10
                                annotations[page_idx].append((x_write, y_reportlab, valeur, page_w, page_h))
                            else:
                                x_write      = x_ref + 5
                                y_pdfplumber = float(word.get("top", y_ref))
                                y_reportlab  = page_h - y_pdfplumber - 10
                                line_txt     = ""
                                for w2 in words:
                                    if abs(float(w2.get("top", 0)) - y_ref) < 6:
                                        line_txt += w2.get("text", "") + " "
                                if ":" in line_txt or "_" in line_txt:
                                    annotations[page_idx].append((x_write, y_reportlab, valeur, page_w, page_h))
                            break

        # 3. Générer les overlays ReportLab
        reader = PdfReader(_io.BytesIO(pdf_bytes))
        writer = PdfWriter()

        for page_idx, page in enumerate(reader.pages):
            page_annotations = annotations.get(page_idx, [])

            if page_annotations:
                overlay_buf = _io.BytesIO()
                ph = float(page.mediabox.height)
                pw = float(page.mediabox.width)
                c  = canvas.Canvas(overlay_buf, pagesize=(pw, ph))
                c.setFont("Helvetica", 8)
                c.setFillColorRGB(0.1, 0.1, 0.6)

                seen_values = set()
                for (x, y, val, page_w_orig, page_h_orig) in page_annotations:
                    key = f"{round(x)},{round(y)},{val[:20]}"
                    if key in seen_values:
                        continue
                    seen_values.add(key)
                    max_chars   = max(10, int((pw - x) / 5))
                    val_display = val[:max_chars]
                    if 0 < x < pw and 0 < y < ph:
                        c.drawString(x, y, val_display)

                c.save()
                overlay_buf.seek(0)
                overlay_reader = PdfReader(overlay_buf)
                page.merge_page(overlay_reader.pages[0])

            writer.add_page(page)

        output_buf = _io.BytesIO()
        writer.write(output_buf)
        result = output_buf.getvalue()

        if len(result) < 1000:
            st.warning("⚠️ PDF généré trop petit — retour au PDF original.")
            return pdf_bytes

        return result

    except Exception as e:
        st.error(f"❌ Erreur génération PDF : {e}")
        import traceback
        st.code(traceback.format_exc())
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. GÉNÉRATION WORD DU FORMULAIRE
# ─────────────────────────────────────────────────────────────────────────────

def generer_word_formulaire(
    profil: dict,
    analyse_ia: dict,
    champs_karl: dict,
    sections_opt: list,
    info_ao: dict,
) -> bytes:
    """
    Génère un document Word structuré du formulaire de soumission.
    Utilise Node.js + docx (npm).

    Args:
        profil: Profil entreprise.
        analyse_ia: Résultat de analyser_formulaire_ia().
        champs_karl: Saisies manuelles de l'utilisateur.
        sections_opt: IDs des sections optionnelles à inclure.
        info_ao: Infos du projet (numero, nom).

    Returns:
        bytes du fichier .docx, b"" si erreur.
    """
    def v(champ_id: str, defaut: str = "________________________") -> str:
        if champs_karl.get(champ_id):
            return champs_karl[champ_id]
        for c in analyse_ia.get("champs_remplis", []):
            if c.get("id") == champ_id:
                return c.get("valeur", defaut)
        mp = {
            "nom_entreprise":      profil.get("nom_entreprise", ""),
            "adresse":             (
                f"{profil.get('adresse','')} {profil.get('ville','')} "
                f"({profil.get('province','')}) {profil.get('code_postal','')}".strip()
            ),
            "telephone":           profil.get("contact_telephone", ""),
            "courriel_corp":       profil.get("contact_email", ""),
            "site_web":            profil.get("site_web", ""),
            "rbq":                 profil.get("licence_rbq", ""),
            "neq":                 profil.get("numero_neq", ""),
            "contact_nom":         profil.get("contact_nom", ""),
            "contact_titre":       profil.get("contact_titre", ""),
            "nom_lettres_moulees": profil.get("contact_nom", "").upper(),
            "fonction_moulees":    profil.get("contact_titre", "").upper(),
        }
        return mp.get(champ_id, defaut) or defaut

    num_ao    = info_ao.get("numero", info_ao.get("nom", ""))
    titre_ao  = info_ao.get("nom", "")
    date_sub  = champs_karl.get("date_soumission", datetime.now().strftime("%d %B %Y"))
    montant_l = v("montant_lettres", "À compléter avant dépôt")
    montant_c = v("montant_chiffres", "À compléter")

    # Sections optionnelles en JS
    sections_opt_js = ""
    for sid in (sections_opt or []):
        titre   = SECTIONS_OPTIONNELLES.get(sid, sid)
        contenu = champs_karl.get(f"section_{sid}", "À compléter")
        sections_opt_js += f"""
sections.push(new Paragraph({{ pageBreak: true, children: [] }}));
sections.push(titreSection({json.dumps(titre.upper())}));
sections.push(new Paragraph({{ spacing: {{ before: 200, after: 200 }},
  children: [new TextRun({{ text: {json.dumps(contenu)}, font: "Arial", size: 18 }})] }}));
"""

    script = f"""
const fs = require('fs');
const {{ Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
         AlignmentType, BorderStyle, WidthType, ShadingType, Header, Footer,
         VerticalAlign }} = require('docx');

const THIN  = {{ style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" }};
const NONE  = {{ style: BorderStyle.NONE, size: 0, color: "FFFFFF" }};
const borders = {{ top: THIN, bottom: THIN, left: THIN, right: THIN }};

function cell(txt, opts={{}}) {{
  const {{ bold=false, bg="FFFFFF", color="1a1a1a", w=4680, span=1 }} = opts;
  return new TableCell({{
    columnSpan: span, borders,
    width: {{ size: w, type: WidthType.DXA }},
    shading: {{ fill: bg, type: ShadingType.CLEAR }},
    margins: {{ top: 80, bottom: 80, left: 140, right: 140 }},
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({{ children: [new TextRun({{
      text: String(txt||""), bold, color, font: "Arial", size: bold ? 18 : 18
    }})] }})]
  }});
}}

function row(...cols) {{ return new TableRow({{ children: cols }}); }}

function titreSection(t) {{
  return new Paragraph({{ spacing: {{ before: 320, after: 160 }},
    border: {{ bottom: {{ style: BorderStyle.SINGLE, size: 8, color: "2E5FA3", space: 1 }} }},
    children: [new TextRun({{ text: t, bold: true, color: "2E5FA3", font: "Arial", size: 22, allCaps: true }})]
  }});
}}

function ligneChamp(label, valeur) {{
  return new Table({{ width: {{ size: 9360, type: WidthType.DXA }}, columnWidths: [2640, 6720],
    rows: [row(cell(label, {{bold: true, bg: "F0F4FA", w: 2640}}), cell(valeur||"________________________", {{w: 6720}}))]
  }});
}}

function sp(a=120) {{ return new Paragraph({{ spacing: {{ before: a }}, children: [] }}); }}

const sections = [];

sections.push(new Paragraph({{ alignment: AlignmentType.CENTER, spacing: {{ after: 80 }},
  children: [new TextRun({{ text: "FORMULAIRE DE SOUMISSION", bold: true, font: "Arial",
    size: 32, color: "2E5FA3", allCaps: true }})] }}));
sections.push(new Paragraph({{ alignment: AlignmentType.CENTER, spacing: {{ after: 40 }},
  children: [new TextRun({{ text: {json.dumps(titre_ao)}, font: "Arial", size: 22, color: "444444" }})] }}));
sections.push(new Paragraph({{ alignment: AlignmentType.CENTER, spacing: {{ after: 280 }},
  children: [new TextRun({{ text: "No : " + {json.dumps(num_ao)}, font: "Arial", size: 20, color: "666666" }})] }}));

sections.push(titreSection("1.  IDENTIFICATION DU SOUMISSIONNAIRE"));
sections.push(sp(80));
sections.push(ligneChamp("Raison sociale (REQ)",       {json.dumps(v('nom_entreprise'))}));
sections.push(sp(50)); sections.push(ligneChamp("Adresse complète",    {json.dumps(v('adresse'))}));
sections.push(sp(50)); sections.push(ligneChamp("Téléphone",            {json.dumps(v('telephone'))}));
sections.push(sp(50)); sections.push(ligneChamp("Site internet",        {json.dumps(v('site_web'))}));
sections.push(sp(50)); sections.push(ligneChamp("Courriel corporatif",  {json.dumps(v('courriel_corp'))}));
sections.push(sp(50)); sections.push(ligneChamp("Numéro d'entreprise (NEQ)", {json.dumps(v('neq'))}));
sections.push(sp(50)); sections.push(ligneChamp("Licence RBQ",          {json.dumps(v('rbq'))}));
sections.push(sp(50)); sections.push(ligneChamp("TPS/TVH",              {json.dumps(v('tps', champs_karl.get('tps','À compléter')))}));
sections.push(sp(50)); sections.push(ligneChamp("TVQ",                  {json.dumps(v('tvq', champs_karl.get('tvq','À compléter')))}));

sections.push(new Paragraph({{ pageBreak: true, children: [] }}));
sections.push(titreSection("2.  ANNEXE — BORDEREAU DE PRIX"));
sections.push(new Table({{ width: {{ size: 9360, type: WidthType.DXA }}, columnWidths: [4680, 4680],
  rows: [
    row(cell("MONTANT EN LETTRES", {{ bold: true, bg: "F0F4FA", w: 4680 }}),
        cell("MONTANT EN CHIFFRES", {{ bold: true, bg: "F0F4FA", w: 4680 }})),
    row(cell({json.dumps(montant_l)}, {{ w: 4680 }}), cell({json.dumps(montant_c)}, {{ w: 4680 }})),
  ]
}}));
sections.push(sp(200));
sections.push(ligneChamp("Date de soumission", {json.dumps(date_sub)}));

sections.push(new Paragraph({{ pageBreak: true, children: [] }}));
sections.push(titreSection("3.  DÉCLARATION D'ABSENCE — CNESST"));
sections.push(sp(80));
sections.push(ligneChamp("Nom soumissionnaire",   {json.dumps(v('nom_entreprise'))}));
sections.push(sp(50)); sections.push(ligneChamp("Représentant autorisé", {json.dumps(v('contact_nom'))}));
sections.push(sp(50)); sections.push(ligneChamp("Titre représentant",    {json.dumps(v('contact_titre'))}));

sections.push(new Paragraph({{ pageBreak: true, children: [] }}));
sections.push(titreSection("4.  SIGNATURE DU SOUMISSIONNAIRE"));
sections.push(new Table({{ width: {{ size: 9360, type: WidthType.DXA }}, columnWidths: [4680, 4680],
  rows: [
    row(cell("Signature :",             {{ bold: true, bg: "F0F4FA", w: 4680 }}), cell("", {{ w: 4680 }})),
    row(cell("Nom (lettres moulées) :", {{ bold: true, bg: "F0F4FA", w: 4680 }}), cell({json.dumps(v('nom_lettres_moulees'))}, {{ w: 4680 }})),
    row(cell("Fonction :",              {{ bold: true, bg: "F0F4FA", w: 4680 }}), cell({json.dumps(v('fonction_moulees'))}, {{ w: 4680 }})),
    row(cell("Date :",                  {{ bold: true, bg: "F0F4FA", w: 4680 }}), cell({json.dumps(date_sub)}, {{ w: 4680 }})),
  ]
}}));

{sections_opt_js}

const doc = new Document({{
  styles: {{ default: {{ document: {{ run: {{ font: "Arial", size: 20 }} }} }} }},
  sections: [{{
    properties: {{ page: {{ size: {{ width: 12240, height: 15840 }},
      margin: {{ top: 1200, right: 1200, bottom: 1200, left: 1440 }} }} }},
    children: sections,
  }}]
}});

Packer.toBuffer(doc).then(buf => {{
  fs.writeFileSync('/tmp/fao_word.docx', buf);
  console.log('OK');
}}).catch(e => {{ console.error('ERR', e.message); process.exit(1); }});
"""

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(script)
            tmp_js = f.name
        r = subprocess.run(["node", tmp_js], capture_output=True, text=True, timeout=60)
        os.unlink(tmp_js)
        if "OK" in r.stdout and os.path.exists("/tmp/fao_word.docx"):
            with open("/tmp/fao_word.docx", "rb") as f:
                return f.read()
        st.warning(f"Word : {(r.stderr or r.stdout)[:200]}")
    except Exception as e:
        st.warning(f"Erreur Word : {e}")
    return b""


# ─────────────────────────────────────────────────────────────────────────────
# 5. APERÇU HTML DU FORMULAIRE
# ─────────────────────────────────────────────────────────────────────────────

def apercu_html_formulaire(
    profil: dict,
    analyse_ia: dict,
    champs_karl: dict,
    sections_opt: list,
    info_ao: dict,
    alertes: list,
) -> str:
    """
    Génère un aperçu HTML du formulaire de soumission prêt à afficher.

    Returns:
        Chaîne HTML complète.
    """
    def v(cid: str, defaut: str = "") -> str:
        if champs_karl.get(cid):
            return champs_karl[cid]
        for c in analyse_ia.get("champs_remplis", []):
            if c.get("id") == cid:
                return c.get("valeur", defaut)
        mp = {
            "nom_entreprise":      profil.get("nom_entreprise", ""),
            "adresse":             (
                f"{profil.get('adresse','')} {profil.get('ville','')} "
                f"({profil.get('province','')}) {profil.get('code_postal','')}".strip()
            ),
            "telephone":           profil.get("contact_telephone", ""),
            "courriel_corp":       profil.get("contact_email", ""),
            "site_web":            profil.get("site_web", ""),
            "rbq":                 profil.get("licence_rbq", ""),
            "neq":                 profil.get("numero_neq", ""),
            "contact_nom":         profil.get("contact_nom", ""),
            "contact_titre":       profil.get("contact_titre", ""),
            "nom_lettres_moulees": profil.get("contact_nom", "").upper(),
            "fonction_moulees":    profil.get("contact_titre", "").upper(),
        }
        return mp.get(cid, defaut) or defaut

    def ligne(label: str, val: str, manq: bool = False) -> str:
        clr = "#cc2200" if manq else "#1a1a1a"
        ico = "⚠️ " if manq else ""
        txt = val or '<em style="color:#aaa">Non renseigné</em>'
        return f'<tr><td class="L">{label}</td><td style="color:{clr};padding:7px 14px">{ico}{txt}</td></tr>'

    alertes_html = "".join(
        f'<div class="al al-{a.get("type","info")}">'
        f'<strong>{"🔴" if a.get("type")=="critique" else "🟡"} {a.get("type","Info").upper()}</strong>'
        f' — Page {a.get("page","?")} — {a.get("message","")}'
        f'{"<br><em>→ " + a["action_requise"] + "</em>" if a.get("action_requise") else ""}</div>'
        for a in alertes
    )

    sections_opt_html = "".join(
        f'<div class="section"><h2 class="st">📎 {SECTIONS_OPTIONNELLES.get(sid, sid)}</h2>'
        f'<div style="background:#f9f9f9;padding:14px;border-radius:6px;border-left:3px solid #2E5FA3">'
        f'<p style="white-space:pre-wrap">{champs_karl.get(f"section_{sid}","À compléter")}</p></div></div>'
        for sid in (sections_opt or [])
    )

    num_ao    = info_ao.get("numero", info_ao.get("nom", ""))
    date_sub  = champs_karl.get("date_soumission", datetime.now().strftime("%d %B %Y"))
    montant_l = v("montant_lettres",  champs_karl.get("montant_lettres",  "⚠️ À compléter avant dépôt"))
    montant_c = v("montant_chiffres", champs_karl.get("montant_chiffres", "⚠️ À compléter"))

    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<style>
* {{box-sizing:border-box;margin:0;padding:0}}
body {{font-family:Arial,sans-serif;font-size:13px;background:#f0f2f5;color:#1a1a1a}}
.page {{background:white;max-width:860px;margin:20px auto;padding:38px 46px;
        box-shadow:0 2px 12px rgba(0,0,0,.12);border-radius:4px}}
.entete {{border-bottom:3px solid #2E5FA3;padding-bottom:18px;margin-bottom:24px;
          display:flex;justify-content:space-between;align-items:flex-end}}
.entete h1 {{font-size:19px;color:#2E5FA3;font-weight:800;text-transform:uppercase;letter-spacing:1px}}
.badge {{background:#2E5FA3;color:white;padding:5px 13px;border-radius:20px;font-size:11px;font-weight:700}}
.section {{margin-bottom:24px}}
.st {{font-size:14px;font-weight:800;color:#2E5FA3;text-transform:uppercase;
      letter-spacing:.4px;padding:9px 0;border-bottom:2px solid #E0E8F5;margin-bottom:14px}}
table.ch {{width:100%;border-collapse:collapse}}
table.ch tr {{border-bottom:1px solid #eee}}
.L {{width:32%;padding:7px 12px;background:#F0F4FA;font-weight:600;color:#2E5FA3;
     font-size:12px;vertical-align:top}}
.mt {{background:#F8FAF0;border:2px solid #5a8c00;border-radius:6px;padding:14px 18px;margin:10px 0}}
.mt .ml {{font-size:11px;color:#5a8c00;font-weight:700;text-transform:uppercase}}
.mt .mv {{font-size:15px;font-weight:700;color:#2a5000;margin-top:3px}}
.al {{padding:11px 15px;border-radius:5px;margin-bottom:9px;font-size:12px}}
.al-critique {{background:#FFF0F0;border-left:4px solid #cc2200}}
.al-attention {{background:#FFFBEC;border-left:4px solid #f5a623}}
.al-info {{background:#EBF1FB;border-left:4px solid #2E5FA3}}
.footer {{margin-top:36px;padding-top:12px;border-top:1px solid #ddd;
          display:flex;justify-content:space-between;font-size:10px;color:#999}}
</style></head><body><div class="page">

<div class="entete">
  <div><h1>Formulaire de Soumission</h1><p>{v('nom_entreprise')}</p></div>
  <div class="badge">No {num_ao}</div>
</div>

{f'<div style="margin-bottom:20px">{alertes_html}</div>' if alertes_html else ''}

<div class="section">
  <h2 class="st">1. Identification du soumissionnaire</h2>
  <table class="ch">
    {ligne("Raison sociale (REQ)", v('nom_entreprise'))}
    {ligne("Adresse complète",     v('adresse'))}
    {ligne("Téléphone",            v('telephone'))}
    {ligne("Site internet",        v('site_web'))}
    {ligne("Courriel corporatif",  v('courriel_corp'))}
    {ligne("NEQ",   v('neq'),  not v('neq'))}
    {ligne("RBQ",   v('rbq'),  not v('rbq'))}
    {ligne("TPS/TVH", v('tps', champs_karl.get('tps','')), not champs_karl.get('tps','') and not v('tps'))}
    {ligne("TVQ",     v('tvq', champs_karl.get('tvq','')), not champs_karl.get('tvq','') and not v('tvq'))}
  </table>
</div>

<div class="section">
  <h2 class="st">2. Annexe — Bordereau de prix</h2>
  <div class="mt"><div class="ml">Montant total en lettres</div>
    <div class="mv">{montant_l}</div></div>
  <div class="mt"><div class="ml">Montant total en chiffres ($)</div>
    <div class="mv">{montant_c}</div></div>
</div>

<div class="section">
  <h2 class="st">3. Signature du soumissionnaire</h2>
  <table class="ch">
    {ligne("Nom (lettres moulées)", v('nom_lettres_moulees'))}
    {ligne("Fonction",              v('fonction_moulees'))}
    {ligne("Date",                  date_sub)}
  </table>
</div>

{sections_opt_html}

<div class="footer">
  <span>Formulaire de soumission — Confidentiel</span>
  <span>{v('nom_entreprise')} — {date_sub}</span>
</div>
</div></body></html>"""


# ─────────────────────────────────────────────────────────────────────────────
# 6. AFFICHAGE UI STREAMLIT
# ─────────────────────────────────────────────────────────────────────────────

def afficher_section_formulaire_ao(analyse: dict, user: dict, projets: list) -> None:
    """
    Affiche l'interface complète du formulaire officiel AO dans Streamlit.
    Orchestre : détection PDF → analyse IA → saisie manuelle → génération docs.

    Args:
        analyse: Dict d'analyse du projet courant.
        user: Profil entreprise (utilisé comme profil).
        projets: Projets antérieurs pour le mapping des champs.
    """
    SS = "fao_"  # préfixe session state

    # Initialisation de l'état
    for k, d in [
        ("analyse_ia",  None),
        ("champs_karl", {}),
        ("sections_opt", []),
        ("pdf_rempli",  None),
        ("word_bytes",  b""),
        ("html_apercu", ""),
        ("mode_apercu", False),
    ]:
        if SS + k not in st.session_state:
            st.session_state[SS + k] = d

    profil = user

    # Récupérer le PDF du formulaire depuis les documents chargés
    pdf_bytes, nom_pdf = pdocs.get_bytes_formulaire()

    if not pdf_bytes:
        st.info(
            "📎 **Aucun formulaire PDF détecté** dans les documents chargés. "
            "Chargez le formulaire de soumission du donneur d'ouvrage dans la catégorie "
            "**💰 Bordereau de prix & Formulaires** (onglet Paramètres & Projets)."
        )
        return

    col_pdf, col_btn = st.columns([3, 2])
    col_pdf.success(f"✅ Formulaire détecté : **{nom_pdf}**")

    with col_btn:
        btn_analyser = st.button(
            "🤖 Analyser & pré-remplir avec l'IA",
            type="primary", key="fao_btn_analyser",
            disabled=bool(st.session_state[SS + "analyse_ia"]),
        )
        if st.session_state[SS + "analyse_ia"] and st.button("🔄 Réanalyser", key="fao_reanalyser"):
            st.session_state[SS + "analyse_ia"]  = None
            st.session_state[SS + "champs_karl"] = {}
            st.rerun()

    if btn_analyser:
        with st.spinner("Extraction de la structure du formulaire…"):
            structure = extraire_structure_formulaire(pdf_bytes)
        with st.spinner("L'IA cherche vos données dans le profil et vos projets antérieurs…"):
            st.session_state[SS + "analyse_ia"] = analyser_formulaire_ia(
                structure, profil, projets, analyse or {}
            )
        st.rerun()

    if not st.session_state[SS + "analyse_ia"]:
        return

    ia          = st.session_state[SS + "analyse_ia"]
    champs_karl = st.session_state[SS + "champs_karl"]

    st.success(f"✅ {ia.get('resume', 'Analyse terminée.')}")

    # Affichage des alertes
    alertes = ia.get("alertes", [])
    if alertes:
        st.markdown("##### ⚠️ Points d'attention")
        for a in alertes:
            fn = st.error if a.get("type") == "critique" else (
                 st.warning if a.get("type") == "attention" else st.info)
            fn(
                f"{'🔴' if a.get('type')=='critique' else '🟡'} "
                f"**Page {a.get('page','?')}** — {a.get('message','')}"
                + (f"\n\n→ *{a['action_requise']}*" if a.get('action_requise') else "")
            )

    # Champs pré-remplis
    champs_remplis = ia.get("champs_remplis", [])
    if champs_remplis:
        with st.expander(f"✅ {len(champs_remplis)} champs pré-remplis automatiquement"):
            for c in champs_remplis:
                src = "🏢 profil" if c.get("source") == "profil" else "📂 projets"
                st.markdown(
                    f"{src} | **{c.get('label', c.get('id',''))}** "
                    f"*(p.{c.get('page','?')})* → `{c.get('valeur','')}`"
                )

    # Champs manquants — formulaire de saisie
    champs_manquants = ia.get("champs_manquants", [])
    if champs_manquants:
        st.markdown("##### 📝 Informations manquantes — à compléter")
        with st.form("fao_form_manquants"):
            vals_tmp = {}
            for c in champs_manquants:
                cid   = c.get("id", "")
                label = c.get("label", cid)
                ex    = c.get("exemple", "")
                prio  = c.get("priorite", "normale")
                hint  = (
                    f"{'🔴' if prio=='haute' else '🟡'} Page {c.get('page','?')}"
                    + (f" — ex : {ex}" if ex else "")
                )
                vals_tmp[cid] = st.text_input(
                    label, value=champs_karl.get(cid, ""),
                    help=hint, key=f"fao_m_{cid}"
                )

            st.divider()
            st.markdown("**💰 Montant de la soumission**")

            # Auto-remplissage depuis le chiffrage financier si disponible
            total_ttc_calc = (st.session_state.get("offre_data") or {}).get("soumission", {}).get("total_ttc", 0) or 0
            montant_chiffres_auto = f"{total_ttc_calc:,.2f}".replace(",", " ") if total_ttc_calc else ""

            # Conversion automatique en lettres (simple)
            def _num_en_lettres(montant: float) -> str:
                """Convertit un montant en toutes lettres (français, simplifié)."""
                try:
                    import math
                    n = int(math.floor(montant))
                    cents = round((montant - n) * 100)
                    unites = ["", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
                              "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
                              "dix-sept", "dix-huit", "dix-neuf"]
                    dizaines = ["", "dix", "vingt", "trente", "quarante", "cinquante",
                                "soixante", "soixante-dix", "quatre-vingt", "quatre-vingt-dix"]

                    def _centaines(n):
                        if n == 0: return ""
                        if n < 20: return unites[n]
                        d, u = divmod(n, 10)
                        if d == 7:  return "soixante-" + (unites[10 + u] if u > 0 else "dix")
                        if d == 9:  return "quatre-vingt-" + (unites[10 + u] if u > 0 else "dix")
                        sep = "-et-" if u == 1 and d not in (8, 9) else ("-" if u > 0 else "")
                        return dizaines[d] + sep + (unites[u] if u > 0 else "")

                    def _milliers(n):
                        if n == 0: return "zéro"
                        parts = []
                        if n >= 1_000_000:
                            m, n = divmod(n, 1_000_000)
                            parts.append(("un million" if m == 1 else _milliers(m) + " millions"))
                        if n >= 1_000:
                            m, n = divmod(n, 1_000)
                            parts.append("mille" if m == 1 else _centaines(m) + " mille")
                        if n >= 100:
                            m, n = divmod(n, 100)
                            parts.append(("cent" if m == 1 else unites[m] + " cent") + ("s" if n == 0 and m > 1 else ""))
                            if n > 0: parts.append(_centaines(n))
                        elif n > 0:
                            parts.append(_centaines(n))
                        return " ".join(p for p in parts if p)

                    result = _milliers(n).capitalize() + " dollars"
                    if cents > 0:
                        result += f" et {_centaines(cents)} cents"
                    return result
                except Exception:
                    return ""

            montant_lettres_auto = _num_en_lettres(total_ttc_calc) if total_ttc_calc else ""

            if total_ttc_calc and not champs_karl.get("montant_chiffres"):
                st.info(f"💡 **Montant auto-détecté depuis le chiffrage :** {montant_chiffres_auto} $")

            c1, c2, c3 = st.columns(3)
            vals_tmp["montant_lettres"]  = c1.text_input(
                "En toutes lettres",
                value=champs_karl.get("montant_lettres", montant_lettres_auto),
                placeholder="Ex : Deux cent quarante-cinq mille dollars",
                key="fao_ml"
            )
            vals_tmp["montant_chiffres"] = c2.text_input(
                "En chiffres ($)",
                value=champs_karl.get("montant_chiffres", montant_chiffres_auto),
                placeholder="245 000,00",
                key="fao_mc"
            )
            vals_tmp["date_soumission"]  = c3.text_input(
                "Date",
                value=champs_karl.get("date_soumission", datetime.now().strftime("%d %B %Y")),
                key="fao_ds"
            )

            if st.form_submit_button("💾 Sauvegarder", type="primary"):
                st.session_state[SS + "champs_karl"].update(
                    {k: v for k, v in vals_tmp.items() if v}
                )
                st.success("✅ Informations sauvegardées!")
                st.rerun()

    champs_karl = st.session_state[SS + "champs_karl"]

    # Sections optionnelles
    with st.expander("📎 Ajouter des sections complémentaires (optionnel)"):
        cols = st.columns(2)
        sel  = list(st.session_state[SS + "sections_opt"])
        for i, (sid, titre) in enumerate(SECTIONS_OPTIONNELLES.items()):
            chk = cols[i % 2].checkbox(titre, value=sid in sel, key=f"fao_opt_{sid}")
            if chk and sid not in sel:
                sel.append(sid)
            elif not chk and sid in sel:
                sel.remove(sid)
        st.session_state[SS + "sections_opt"] = sel

        for sid in sel:
            contenu = st.text_area(
                SECTIONS_OPTIONNELLES.get(sid, sid),
                value=champs_karl.get(f"section_{sid}", ""),
                height=90, key=f"fao_cont_{sid}"
            )
            st.session_state[SS + "champs_karl"][f"section_{sid}"] = contenu

    # Génération des documents
    st.markdown("##### 🚀 Générer les documents de soumission")
    info_ao  = (analyse or {}).get("projet", {})
    nom_ao   = (info_ao.get("numero") or info_ao.get("nom") or "formulaire_ao").replace(" ","_").replace("/","-")
    nom_entr = profil.get("nom_entreprise","entreprise").replace(" ","_")

    col_g1, col_g2, col_g3 = st.columns(3)
    gen_pdf    = col_g1.button("📄 PDF — Formulaire officiel rempli", use_container_width=True, key="fao_gpdf")
    gen_word   = col_g2.button("📝 Word — Document structuré",         use_container_width=True, key="fao_gword")
    gen_apercu = col_g3.button("👁️ Aperçu HTML",                       use_container_width=True, key="fao_gapercu")

    if gen_pdf:
        with st.spinner("Remplissage du formulaire PDF original…"):
            result = generer_pdf_formulaire(pdf_bytes, champs_remplis, champs_karl)
        if result:
            st.session_state[SS + "pdf_rempli"] = result
            st.success(f"✅ PDF prêt — {len(result)//1024} Ko")

    if gen_word:
        with st.spinner("Génération du document Word…"):
            result = generer_word_formulaire(
                profil, ia, champs_karl,
                st.session_state[SS + "sections_opt"], info_ao
            )
        if result:
            st.session_state[SS + "word_bytes"] = result
            st.success("✅ Word prêt")

    if gen_apercu:
        with st.spinner("Génération de l'aperçu…"):
            result = apercu_html_formulaire(
                profil, ia, champs_karl,
                st.session_state[SS + "sections_opt"], info_ao, alertes
            )
        st.session_state[SS + "html_apercu"] = result
        st.session_state[SS + "mode_apercu"] = True
        st.success("✅ Aperçu prêt")

    # Boutons de téléchargement
    dl1, dl2 = st.columns(2)

    if st.session_state[SS + "pdf_rempli"]:
        dl1.download_button(
            "📄 Télécharger le formulaire PDF rempli",
            data=st.session_state[SS + "pdf_rempli"],
            file_name=f"{nom_ao}_Soumission_{nom_entr}.pdf",
            mime="application/pdf",
            use_container_width=True, key="fao_dl_pdf"
        )

    if st.session_state[SS + "word_bytes"]:
        dl2.download_button(
            "📝 Télécharger le document Word",
            data=st.session_state[SS + "word_bytes"],
            file_name=f"{nom_ao}_Soumission_{nom_entr}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True, key="fao_dl_word"
        )

    # Rendu de l'aperçu HTML
    if st.session_state[SS + "mode_apercu"] and st.session_state[SS + "html_apercu"]:
        st.markdown("#### 👁️ Aperçu — Formulaire de soumission")
        components.html(st.session_state[SS + "html_apercu"], height=900, scrolling=True)