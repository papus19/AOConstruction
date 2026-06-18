"""
MOKAFAD - Module Gestion de Projet
Modifications :
  B — Hiérarchie Jalon → Livrable → Activité → Tâche avec liaisons obligatoires
  C — Génération IA d'un plan complet depuis la soumission (Claude Sonnet)
      + Suggestions contextuelles légères (Gemini/Groq via LLMManager)
  D — Fix ressources : persist dans session_state avant rerun
      Fix suggestion IA : contexte construction + indentation corrigée
      Ajout bouton "Générer plan IA" dans l'onglet Planification
  E — Remplacement de l'arborescence/tableau par un composant HTML bidirectionnel
      (st.components.v1.html) avec :
        · Tableau moderne hiérarchique expand/collapse
        · Édition inline dans la ligne
        · Dates calculées automatiquement (durée + dépendances)
        · Sauvegarde directe dans session_state sans copier-coller
"""

import streamlit as st
import streamlit.components.v1 as components
import config
import database
from llm_manager import LLMManager
from datetime import datetime, date, timedelta
import json
from typing import List, Optional
import uuid


# ══════════════════════════════════════════════════════════════════════
# HELPERS GÉNÉRAUX
# ══════════════════════════════════════════════════════════════════════

def _uid() -> str:
    return str(uuid.uuid4())[:8]


# ══════════════════════════════════════════════════════════════════════
# UTILITAIRES DATES (Python — miroir du JS)
# ══════════════════════════════════════════════════════════════════════

def _add_workdays(start_str: str, days: int) -> str:
    """Ajoute `days` jours ouvrables à une date ISO."""
    if not start_str:
        return start_str
    try:
        d = date.fromisoformat(start_str[:10])
        added = 0
        while added < max(days - 1, 0):
            d += timedelta(days=1)
            if d.weekday() < 5:
                added += 1
        return d.isoformat()
    except Exception:
        return start_str


def _recalc_dates(elements: list, project_start: str) -> list:
    """
    Recalcule date_debut / date_fin pour chaque élément selon ses dépendances.
    Si un élément A dépend de B, date_debut(A) = lendemain ouvrable de date_fin(B).
    """
    el_map = {e["id"]: dict(e) for e in elements}
    resolved = set()

    def resolve(eid):
        if eid in resolved or eid not in el_map:
            return
        el = el_map[eid]
        for dep_id in el.get("dependances", []):
            resolve(dep_id)
        deps = [el_map[d] for d in el.get("dependances", []) if d in el_map]
        debut = el.get("date_debut") or project_start or date.today().isoformat()
        if deps:
            latest = max(
                (dep.get("date_fin") or dep.get("date_debut") or "1900-01-01")
                for dep in deps
            )
            d = date.fromisoformat(latest[:10])
            d += timedelta(days=1)
            while d.weekday() >= 5:
                d += timedelta(days=1)
            debut = d.isoformat()
        el_map[eid]["date_debut"] = debut
        duree = max(int(el.get("duree_jours") or 1), 1)
        el_map[eid]["date_fin"] = _add_workdays(debut, duree)
        resolved.add(eid)

    for el in elements:
        resolve(el["id"])
    return list(el_map.values())


def _flatten_plan(plan: dict) -> list:
    """Aplatit la structure hiérarchique en liste plate ordonnée."""
    result = []
    for j in plan.get("jalons", []):
        result.append(dict(j, type="jalon"))
        for l in plan.get("livrables", []):
            if l.get("jalon_id") != j["id"]:
                continue
            result.append(dict(l, type="livrable"))
            for a in plan.get("activites", []):
                if a.get("livrable_id") != l["id"]:
                    continue
                result.append(dict(a, type="activite"))
                for t in plan.get("taches", []):
                    if t.get("activite_id") != a["id"]:
                        continue
                    result.append(dict(t, type="tache"))
    return result


def _unflatten_plan(elements: list, plan: dict) -> dict:
    """Remet les éléments dans la structure plan après édition JS."""
    plan["jalons"]    = [e for e in elements if e.get("type") == "jalon"]
    plan["livrables"] = [e for e in elements if e.get("type") == "livrable"]
    plan["activites"] = [e for e in elements if e.get("type") == "activite"]
    plan["taches"]    = [e for e in elements if e.get("type") == "tache"]
    return plan


# ══════════════════════════════════════════════════════════════════════
# COMPOSANT HTML BIDIRECTIONNEL — Tableau de planification
# ══════════════════════════════════════════════════════════════════════

def _build_planning_component(elements: list, responsables: list, project_start: str) -> str:
    """
    Génère le HTML+JS complet du composant de planification.
    Communique avec Streamlit via window.parent.postMessage.
    """
    data_json         = json.dumps(elements,     ensure_ascii=False)
    responsables_json = json.dumps(responsables, ensure_ascii=False)
    ps_json           = json.dumps(project_start or date.today().isoformat())

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'DM Sans','Segoe UI',sans-serif;background:#f8fafc;padding:6px 2px 16px;font-size:15px;}}

/* ── TABLE ── */
.tbl{{background:#fff;border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;box-shadow:0 1px 6px rgba(0,0,0,.05);}}
.cols{{display:grid;grid-template-columns:28px 7px 1fr 115px 105px 72px 116px 116px 70px 130px 72px;padding:0 6px;}}
.th{{padding:10px 4px;font-size:11px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em;}}
.tbl-head{{border-bottom:2px solid #e2e8f0;background:#f8fafc;}}
.row{{border-bottom:1px solid #f1f5f9;transition:background .1s;cursor:default;}}
.row:hover .row-inner{{background:#f0f9ff!important;}}
.row-inner{{padding:4px 6px;}}
.cell{{padding:3px 4px;display:flex;align-items:center;}}

/* ── TAGS & BADGES ── */
.tag{{display:inline-flex;align-items:center;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;white-space:nowrap;}}
.avatar{{width:26px;height:26px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;flex-shrink:0;}}

/* ── BUTTONS ── */
.btn{{padding:6px 13px;border-radius:7px;border:none;cursor:pointer;font-size:13px;font-weight:500;font-family:inherit;transition:all .15s;line-height:1.4;}}
.btn:hover{{opacity:.85;transform:translateY(-1px);}}
.btn-primary{{background:#0f172a;color:#fff;}}
.btn-ghost{{background:#f1f5f9;color:#475569;border:1px solid #e2e8f0;}}
.btn-link{{background:none;border:1px dashed #cbd5e1;color:#64748b;padding:4px 12px;border-radius:20px;font-size:12px;font-family:inherit;cursor:pointer;transition:all .15s;}}
.btn-link:hover{{border-color:#3b82f6;color:#3b82f6;}}
.btn-icon{{background:none;border:1px solid #e2e8f0;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:13px;color:#64748b;font-family:inherit;transition:all .15s;}}
.btn-icon:hover{{background:#f8fafc;}}
.btn-del{{background:none;border:1px solid #fecaca;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:13px;color:#ef4444;font-family:inherit;transition:all .15s;}}
.btn-del:hover{{background:#fef2f2;}}
.expand-btn{{background:none;border:none;cursor:pointer;color:#94a3b8;padding:2px;border-radius:4px;font-size:15px;line-height:1;font-family:inherit;}}

/* ── PROGRESS ── */
.prog-track{{height:4px;background:#f1f5f9;border-radius:99px;width:72%;overflow:hidden;margin-top:4px;}}
.prog-fill{{height:100%;border-radius:99px;transition:width .3s;}}

/* ── EDIT PANEL ── */
.edit-panel{{padding:16px 20px;animation:fadeIn .18s ease;}}
@keyframes fadeIn{{from{{opacity:0;transform:translateY(-4px)}}to{{opacity:1;transform:translateY(0)}}}}
.edit-grid{{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin-bottom:14px;}}
.field{{display:flex;flex-direction:column;gap:4px;}}
.field label{{font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.05em;}}
.inp{{padding:7px 11px;border:1px solid #cbd5e1;border-radius:7px;font-size:14px;outline:none;font-family:inherit;width:100%;}}
.inp:focus{{border-color:#3b82f6;box-shadow:0 0 0 2px #3b82f620;}}
.inp-ro{{background:#f1f5f9;color:#64748b;cursor:default;}}
.sel{{padding:7px 11px;border:1px solid #cbd5e1;border-radius:7px;font-size:13px;outline:none;background:#fff;font-family:inherit;width:100%;}}
.dep-chip{{padding:4px 12px;border-radius:20px;font-size:12px;cursor:pointer;border:1px solid #e2e8f0;background:#fff;color:#64748b;font-family:inherit;transition:all .15s;}}
.dep-chip:hover{{border-color:#94a3b8;}}

/* ── FILTER BAR ── */
.filter-bar{{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:12px;}}
.f-btn{{padding:5px 14px;border-radius:20px;border:none;cursor:pointer;font-size:12px;font-weight:500;font-family:inherit;transition:all .15s;}}

/* ── STATS ── */
.stats-bar{{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;}}
.stat-card{{background:#fff;border:1px solid #e2e8f0;border-radius:9px;padding:8px 15px;text-align:center;min-width:72px;}}
.stat-val{{font-size:20px;font-weight:700;}}
.stat-lbl{{font-size:11px;color:#94a3b8;font-weight:500;}}

/* ── SAVE FEEDBACK ── */
.save-toast{{position:fixed;bottom:16px;right:16px;background:#10b981;color:#fff;padding:9px 18px;border-radius:8px;font-size:14px;font-weight:600;box-shadow:0 4px 12px rgba(16,185,129,.3);animation:slideUp .3s ease;z-index:9999;}}
@keyframes slideUp{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}

::-webkit-scrollbar{{height:5px;width:5px;}}
::-webkit-scrollbar-track{{background:#f1f5f9;}}
::-webkit-scrollbar-thumb{{background:#cbd5e1;border-radius:3px;}}
</style>
</head>
<body>

<div id="root">
  <div class="stats-bar" id="stats-bar"></div>

  <!-- Filtres -->
  <div class="filter-bar">
    <span style="font-size:12px;color:#64748b;font-weight:600;">TYPE :</span>
    <button class="f-btn" id="ft-all"      onclick="setFilter('type','all')">Tout</button>
    <button class="f-btn" id="ft-jalon"    onclick="setFilter('type','jalon')">Jalons</button>
    <button class="f-btn" id="ft-livrable" onclick="setFilter('type','livrable')">Livrables</button>
    <button class="f-btn" id="ft-activite" onclick="setFilter('type','activite')">Activités</button>
    <button class="f-btn" id="ft-tache"    onclick="setFilter('type','tache')">Tâches</button>
    <span style="color:#e2e8f0;margin:0 2px;">|</span>
    <span style="font-size:12px;color:#64748b;font-weight:600;">STATUT :</span>
    <button class="f-btn" id="fs-all"      onclick="setFilter('statut','all')">Tous</button>
    <button class="f-btn" id="fs-Afaire"   onclick="setFilter('statut','A faire')">À faire</button>
    <button class="f-btn" id="fs-Encours"  onclick="setFilter('statut','En cours')">En cours</button>
    <button class="f-btn" id="fs-Termine"  onclick="setFilter('statut','Termine')">Terminé</button>
    <button class="f-btn" id="fs-Bloque"   onclick="setFilter('statut','Bloque')">Bloqué</button>
    <div style="margin-left:auto;display:flex;gap:6px;">
      <button class="btn btn-ghost" style="font-size:12px;padding:4px 12px;" onclick="expandAll(true)">↕ Tout ouvrir</button>
      <button class="btn btn-ghost" style="font-size:12px;padding:4px 12px;" onclick="expandAll(false)">↕ Tout fermer</button>
    </div>
  </div>

  <!-- Tableau -->
  <div class="tbl">
    <div class="tbl-head cols">
      <div class="th"></div><div class="th"></div>
      <div class="th">Nom</div>
      <div class="th">Statut</div>
      <div class="th">Priorité</div>
      <div class="th">Durée</div>
      <div class="th">Début</div>
      <div class="th">Fin</div>
      <div class="th">Avanc.</div>
      <div class="th">Responsable</div>
      <div class="th"></div>
    </div>
    <div id="tbl-body"></div>
    <div style="border-top:2px solid #f1f5f9;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;background:#fafafa;">
      <button class="btn btn-primary" onclick="addElement('jalon',null)">＋ Ajouter un jalon</button>
      <span id="footer-info" style="font-size:12px;color:#94a3b8;"></span>
    </div>
  </div>

  <!-- Légende -->
  <div style="display:flex;gap:14px;margin-top:10px;flex-wrap:wrap;">
    <span style="font-size:12px;color:#64748b;display:flex;align-items:center;gap:5px;"><span style="width:10px;height:10px;border-radius:2px;background:#3b82f6;display:inline-block;"></span>Jalon</span>
    <span style="font-size:12px;color:#64748b;display:flex;align-items:center;gap:5px;"><span style="width:10px;height:10px;border-radius:2px;background:#10b981;display:inline-block;"></span>Livrable</span>
    <span style="font-size:12px;color:#64748b;display:flex;align-items:center;gap:5px;"><span style="width:10px;height:10px;border-radius:2px;background:#f59e0b;display:inline-block;"></span>Activité</span>
    <span style="font-size:12px;color:#64748b;display:flex;align-items:center;gap:5px;"><span style="width:10px;height:10px;border-radius:2px;background:#8b5cf6;display:inline-block;"></span>Tâche</span>
    <span style="font-size:12px;color:#94a3b8;">🔗 dépendance = dates auto-calculées</span>
  </div>
</div>

<script>
// ═══════════════════════════════════════════
// DONNÉES INJECTÉES PAR PYTHON
// ═══════════════════════════════════════════
let elements       = {data_json};
const RESPONSABLES = {responsables_json};
const PROJECT_START = {ps_json};

// ═══════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════
const TYPE_CFG = {{
  jalon:    {{color:'#3b82f6', indent:0,  label:'Jalon'}},
  livrable: {{color:'#10b981', indent:16, label:'Livrable'}},
  activite: {{color:'#f59e0b', indent:32, label:'Activité'}},
  tache:    {{color:'#8b5cf6', indent:48, label:'Tâche'}},
}};
const STATUT_CFG = {{
  'A faire':  {{color:'#64748b', bg:'#f1f5f9', label:'À faire'}},
  'En cours': {{color:'#d97706', bg:'#fffbeb', label:'En cours'}},
  'Termine':  {{color:'#059669', bg:'#f0fdf4', label:'Terminé'}},
  'Bloque':   {{color:'#dc2626', bg:'#fef2f2', label:'Bloqué'}},
}};
const PRIO_COLOR = {{Critique:'#ef4444',Haute:'#f97316',Normale:'#3b82f6',Basse:'#94a3b8'}};
const CHILD_TYPE  = {{jalon:'livrable',livrable:'activite',activite:'tache'}};

// ═══════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════
let expanded     = new Set(elements.filter(e=>e.type==='jalon').map(e=>e.id));
let editingId    = null;
let editData     = {{}};
let filterType   = 'all';
let filterStatut = 'all';

// ═══════════════════════════════════════════
// DATES
// ═══════════════════════════════════════════
function addWorkdays(startStr, days) {{
  if (!startStr) return startStr;
  const d = new Date(startStr + 'T12:00:00');
  let added = 0;
  const n = Math.max(days - 1, 0);
  while (added < n) {{
    d.setDate(d.getDate() + 1);
    if (d.getDay() !== 0 && d.getDay() !== 6) added++;
  }}
  return d.toISOString().slice(0,10);
}}

function nextWorkday(dateStr) {{
  const d = new Date(dateStr + 'T12:00:00');
  do {{ d.setDate(d.getDate()+1); }} while (d.getDay()===0||d.getDay()===6);
  return d.toISOString().slice(0,10);
}}

function recalcDates(elems) {{
  const map = {{}};
  elems.forEach(e => map[e.id] = {{...e}});
  const resolved = new Set();
  function resolve(id) {{
    if (resolved.has(id)||!map[id]) return;
    const el = map[id];
    (el.dependances||[]).forEach(d => resolve(d));
    const deps = (el.dependances||[]).map(d=>map[d]).filter(Boolean);
    let debut = el.date_debut || PROJECT_START || new Date().toISOString().slice(0,10);
    if (deps.length > 0) {{
      const latest = deps.reduce((mx,dep) => {{
        const df = dep.date_fin||dep.date_debut||'1900-01-01';
        return df > mx ? df : mx;
      }}, '1900-01-01');
      debut = nextWorkday(latest);
    }}
    map[id].date_debut = debut;
    map[id].date_fin   = addWorkdays(debut, Math.max(parseInt(el.duree_jours)||1,1));
    resolved.add(id);
  }}
  elems.forEach(e => resolve(e.id));
  return Object.values(map);
}}

function fmtDate(s) {{
  if (!s) return '—';
  const d = new Date(s+'T12:00:00');
  return d.toLocaleDateString('fr-CA',{{day:'2-digit',month:'short',year:'numeric'}});
}}

function uid() {{ return Math.random().toString(36).slice(2,10); }}

// ═══════════════════════════════════════════
// COMMUNICATION STREAMLIT
// ═══════════════════════════════════════════
function sendToStreamlit(data) {{
  // Envoie les données à Streamlit via postMessage
  window.parent.postMessage({{
    type: 'streamlit:setComponentValue',
    value: JSON.stringify(data)
  }}, '*');
}}

function saveAndSend() {{
  sendToStreamlit({{action: 'update', elements: elements}});
  showToast('✅ Modifications sauvegardées');
}}

function showToast(msg) {{
  const t = document.createElement('div');
  t.className = 'save-toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2500);
}}

// ═══════════════════════════════════════════
// CRUD
// ═══════════════════════════════════════════
function addElement(type, parentId) {{
  const newEl = {{
    id: uid(), type,
    nom: 'Nouveau ' + TYPE_CFG[type].label,
    description: '',
    statut: 'A faire', priorite: 'Normale',
    duree_jours: 1, dependances: [],
    avancement_pct: 0, responsable_id: null, notes: '',
    ...(type==='livrable' ? {{jalon_id:    parentId}} : {{}}),
    ...(type==='activite' ? {{livrable_id: parentId}} : {{}}),
    ...(type==='tache'    ? {{activite_id: parentId}} : {{}}),
  }};
  elements = recalcDates([...elements, newEl]);
  expanded.add(newEl.id);
  if (parentId) expanded.add(parentId);
  startEdit(newEl.id);
}}

function deleteElement(id) {{
  if (!confirm('Supprimer cet élément et ses dépendances ?')) return;
  elements = recalcDates(elements.filter(e => e.id !== id));
  if (editingId === id) {{ editingId=null; editData={{}}; }}
  saveAndSend();
  render();
}}

function startEdit(id) {{
  editingId = id;
  editData  = {{...elements.find(e=>e.id===id)}};
  render();
}}

function cancelEdit() {{
  editingId = null; editData = {{}};
  render();
}}

function saveEdit() {{
  elements = recalcDates(elements.map(e => e.id===editingId ? {{...editData}} : e));
  editingId = null; editData = {{}};
  saveAndSend();
  render();
}}

function updateField(field, value) {{
  editData[field] = value;
  if (field==='duree_jours' && editData.date_debut) {{
    editData.date_fin = addWorkdays(editData.date_debut, Math.max(parseInt(value)||1,1));
    const el = document.getElementById('ef-date-fin');
    if (el) el.value = editData.date_fin||'';
  }}
  if (field==='date_debut' && value) {{
    editData.date_fin = addWorkdays(value, Math.max(parseInt(editData.duree_jours)||1,1));
    const el = document.getElementById('ef-date-fin');
    if (el) el.value = editData.date_fin||'';
  }}
}}

function toggleDep(depId) {{
  const deps = editData.dependances || [];
  editData.dependances = deps.includes(depId)
    ? deps.filter(d=>d!==depId)
    : [...deps, depId];
  // Re-render seulement le panneau deps
  renderDepChips();
}}

function renderDepChips() {{
  const container = document.getElementById('dep-chips-container');
  if (!container) return;
  const others = elements.filter(e=>e.id!==editData.id);
  container.innerHTML = others.length===0
    ? '<span style="font-size:13px;color:#94a3b8;">Aucun autre élément disponible</span>'
    : others.map(e => {{
        const isSel = (editData.dependances||[]).includes(e.id);
        const ec = TYPE_CFG[e.type]?.color||'#64748b';
        return `<button class="dep-chip" onclick="toggleDep('${{e.id}}')"
          style="border-color:${{isSel?ec:'#e2e8f0'}};background:${{isSel?ec+'18':'#fff'}};color:${{isSel?ec:'#64748b'}};font-weight:${{isSel?600:400}};">
          ${{esc(e.nom.slice(0,32))}}${{e.nom.length>32?'…':''}}
        </button>`;
      }}).join('');
}}

// ═══════════════════════════════════════════
// FILTRES & EXPAND
// ═══════════════════════════════════════════
function setFilter(kind, val) {{
  if (kind==='type')   filterType   = val;
  if (kind==='statut') filterStatut = val;
  render();
}}

function expandAll(open) {{
  elements.forEach(e => open ? expanded.add(e.id) : expanded.delete(e.id));
  render();
}}

function toggleExpand(id) {{
  expanded.has(id) ? expanded.delete(id) : expanded.add(id);
  render();
}}

// ═══════════════════════════════════════════
// VISIBLE ELEMENTS
// ═══════════════════════════════════════════
function getVisible() {{
  const result = [];
  elements.filter(e=>e.type==='jalon').forEach(j => {{
    if (filterType==='all'||filterType==='jalon') result.push(j);
    if (!expanded.has(j.id)) return;
    elements.filter(e=>e.type==='livrable'&&e.jalon_id===j.id).forEach(l => {{
      if (filterType==='all'||filterType==='livrable') result.push(l);
      if (!expanded.has(l.id)) return;
      elements.filter(e=>e.type==='activite'&&e.livrable_id===l.id).forEach(a => {{
        if (filterType==='all'||filterType==='activite') result.push(a);
        if (!expanded.has(a.id)) return;
        elements.filter(e=>e.type==='tache'&&e.activite_id===a.id).forEach(t => {{
          if (filterType==='all'||filterType==='tache') result.push(t);
        }});
      }});
    }});
  }});
  return filterStatut==='all' ? result : result.filter(e=>e.statut===filterStatut);
}}

function getChildren(el) {{
  if (el.type==='jalon')    return elements.filter(e=>e.type==='livrable'&&e.jalon_id===el.id);
  if (el.type==='livrable') return elements.filter(e=>e.type==='activite'&&e.livrable_id===el.id);
  if (el.type==='activite') return elements.filter(e=>e.type==='tache'&&e.activite_id===el.id);
  return [];
}}

// ═══════════════════════════════════════════
// RENDER ROW
// ═══════════════════════════════════════════
function esc(s) {{
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function renderRow(el) {{
  const cfg   = TYPE_CFG[el.type];
  const sc    = STATUT_CFG[el.statut] || STATUT_CFG['A faire'];
  const pc    = PRIO_COLOR[el.priorite] || '#94a3b8';
  const kids  = getChildren(el);
  const isExp = expanded.has(el.id);
  const isEd  = editingId===el.id;
  const ct    = CHILD_TYPE[el.type];
  const hasDeps = (el.dependances||[]).length > 0;

  const resp = RESPONSABLES.find(r=>r.id===el.responsable_id);
  const respName = resp ? resp.nom : (el.responsable||'');
  const initials = respName ? respName.split(' ').map(w=>w[0]||'').join('').slice(0,2).toUpperCase() : '';
  const av = el.avancement_pct || 0;

  let html = `<div class="row" id="row-${{el.id}}">`;

  if (!isEd) {{
    html += `<div class="row-inner cols" style="background:${{el.type==='jalon'?'#f8fafc':'#fff'}}">
      <div class="cell" style="justify-content:center;">
        ${{kids.length>0
          ? `<button class="expand-btn" onclick="toggleExpand('${{el.id}}')">${{isExp?'▼':'▶'}}</button>`
          : ''}}
      </div>
      <div class="cell" style="padding-left:${{cfg.indent*0.28}}px;justify-content:center;">
        <div style="width:5px;height:26px;border-radius:3px;background:${{cfg.color}};"></div>
      </div>
      <div class="cell" style="padding-left:${{cfg.indent}}px;flex-direction:column;align-items:flex-start;gap:0;">
        <div style="display:flex;align-items:center;gap:5px;">
          <span style="font-size:15px;font-weight:${{el.type==='jalon'?600:400}};color:#1e293b;">${{esc(el.nom)}}</span>
          ${{hasDeps?'<span title="Dépendances actives" style="font-size:12px;color:#94a3b8;">🔗</span>':''}}
        </div>
        <div class="prog-track"><div class="prog-fill" style="width:${{av}}%;background:${{av>=100?'#10b981':cfg.color}};"></div></div>
      </div>
      <div class="cell"><span class="tag" style="background:${{sc.bg}};color:${{sc.color}};">${{sc.label}}</span></div>
      <div class="cell"><span class="tag" style="background:${{pc}}18;color:${{pc}};">${{esc(el.priorite||'Normale')}}</span></div>
      <div class="cell" style="font-size:14px;color:#64748b;font-family:'DM Mono',monospace;">${{el.duree_jours||1}}j</div>
      <div class="cell" style="font-size:12px;color:#64748b;font-family:'DM Mono',monospace;">${{fmtDate(el.date_debut)}}</div>
      <div class="cell" style="font-size:12px;color:#64748b;font-family:'DM Mono',monospace;">${{fmtDate(el.date_fin)}}</div>
      <div class="cell" style="font-size:13px;font-weight:600;color:${{av>=100?'#059669':'#64748b'}};font-family:'DM Mono',monospace;">${{av}}%</div>
      <div class="cell" style="gap:5px;">
        ${{initials?`<span class="avatar" style="background:${{cfg.color}}20;color:${{cfg.color}};">${{initials}}</span>`:''}}
        <span style="font-size:13px;color:#475569;">${{esc(respName)}}</span>
      </div>
      <div class="cell" style="gap:4px;justify-content:flex-end;">
        <button class="btn-icon" onclick="startEdit('${{el.id}}')">✏️</button>
        <button class="btn-del"  onclick="deleteElement('${{el.id}}')">🗑</button>
      </div>
    </div>`;

    // Bouton ajouter enfant
    if (isExp && ct) {{
      html += `<div style="padding:3px 8px 5px ${{cfg.indent+52}}px;background:#fff;">
        <button class="btn-link" onclick="addElement('${{ct}}','${{el.id}}')">
          ＋ Ajouter ${{TYPE_CFG[ct].label}}
        </button>
      </div>`;
    }}

  }} else {{
    // ── PANNEAU D'ÉDITION INLINE ────────────────────────────────────
    const respOpts = RESPONSABLES.map(r=>
      `<option value="${{r.id}}" ${{editData.responsable_id===r.id?'selected':''}}>${{esc(r.nom)}} (${{esc(r.role)}})</option>`
    ).join('');

    html += `<div class="edit-panel" style="border-left:3px solid ${{cfg.color}};">
      <div class="edit-grid">

        <div class="field" style="flex:1 1 200px;">
          <label>Nom</label>
          <input class="inp" value="${{esc(editData.nom||'')}}" oninput="editData.nom=this.value" />
        </div>

        <div class="field" style="flex:0 0 88px;">
          <label>Durée (j. ouv.)</label>
          <input class="inp" type="number" min="1" value="${{editData.duree_jours||1}}"
            oninput="updateField('duree_jours',parseInt(this.value)||1)" />
        </div>

        <div class="field" style="flex:0 0 142px;">
          <label>Début ${{(editData.dependances||[]).length>0?'<span style=\\"color:#94a3b8;font-size:9px;\\">(auto si dép.)</span>':''}}</label>
          <input class="inp" type="date" value="${{editData.date_debut||''}}"
            oninput="updateField('date_debut',this.value)" />
        </div>

        <div class="field" style="flex:0 0 142px;">
          <label style="color:#94a3b8;">Fin (calculée ↓)</label>
          <input class="inp inp-ro" type="date" id="ef-date-fin" value="${{editData.date_fin||''}}" readonly />
        </div>

        <div class="field" style="flex:0 0 118px;">
          <label>Statut</label>
          <select class="sel" onchange="editData.statut=this.value">
            ${{Object.entries(STATUT_CFG).map(([k,v])=>`<option value="${{k}}" ${{editData.statut===k?'selected':''}}>${{v.label}}</option>`).join('')}}
          </select>
        </div>

        <div class="field" style="flex:0 0 110px;">
          <label>Priorité</label>
          <select class="sel" onchange="editData.priorite=this.value">
            ${{['Basse','Normale','Haute','Critique'].map(p=>`<option value="${{p}}" ${{editData.priorite===p?'selected':''}}>${{p}}</option>`).join('')}}
          </select>
        </div>

        <div class="field" style="flex:0 0 160px;">
          <label>Avancement : <strong id="av-label">${{editData.avancement_pct||0}}%</strong></label>
          <input type="range" min="0" max="100" value="${{editData.avancement_pct||0}}" style="width:100%;"
            oninput="editData.avancement_pct=parseInt(this.value); document.getElementById('av-label').textContent=this.value+'%'" />
        </div>

        ${{RESPONSABLES.length>0
          ? `<div class="field" style="flex:0 0 185px;">
               <label>Responsable</label>
               <select class="sel" onchange="editData.responsable_id=this.value||null">
                 <option value="">— Aucun —</option>
                 ${{respOpts}}
               </select>
             </div>`
          : `<div class="field" style="flex:0 0 160px;">
               <label>Responsable</label>
               <input class="inp" value="${{esc(editData.responsable||'')}}" placeholder="Nom…"
                 oninput="editData.responsable=this.value" />
             </div>`
        }}
      </div>

      <div class="field" style="margin-bottom:12px;">
        <label style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.05em;display:flex;align-items:center;gap:5px;margin-bottom:6px;">
          🔗 Dépendances
          <span style="font-size:11px;color:#94a3b8;font-weight:400;text-transform:none;letter-spacing:0;">— la date de début est repoussée après la fin des éléments cochés</span>
        </label>
        <div id="dep-chips-container" style="display:flex;flex-wrap:wrap;gap:6px;"></div>
      </div>

      <div class="field" style="margin-bottom:12px;">
        <label>Notes</label>
        <textarea class="inp" rows="2" style="resize:vertical;"
          oninput="editData.notes=this.value">${{esc(editData.notes||'')}}</textarea>
      </div>

      <div style="display:flex;gap:8px;">
        <button class="btn btn-primary" onclick="saveEdit()">✓ Sauvegarder</button>
        <button class="btn btn-ghost"   onclick="cancelEdit()">Annuler</button>
      </div>
    </div>`;
  }}

  html += '</div>';
  return html;
}}

// ═══════════════════════════════════════════
// RENDER STATS & FILTRES
// ═══════════════════════════════════════════
function renderStats() {{
  const total   = elements.length;
  const termine = elements.filter(e=>e.statut==='Termine').length;
  const enCours = elements.filter(e=>e.statut==='En cours').length;
  const bloque  = elements.filter(e=>e.statut==='Bloque').length;
  const jalons  = elements.filter(e=>e.type==='jalon').length;
  const totalJ  = elements.filter(e=>e.type==='jalon').reduce((s,e)=>s+(parseInt(e.duree_jours)||0),0);

  document.getElementById('stats-bar').innerHTML = [
    [jalons,  'Jalons',   '#3b82f6'],
    [total,   'Éléments', '#475569'],
    [enCours, 'En cours', '#d97706'],
    [termine, 'Terminés', '#059669'],
    ...(bloque>0?[[bloque,'Bloqués','#dc2626']]:[]),
  ].map(([v,l,c])=>`
    <div class="stat-card">
      <div class="stat-val" style="color:${{c}};">${{v}}</div>
      <div class="stat-lbl">${{l}}</div>
    </div>`).join('');

  const fi = document.getElementById('footer-info');
  if (fi) fi.textContent = `${{total}} éléments · ${{totalJ}} jours ouvrables`;
}}

function renderFilters() {{
  const typeMap = {{all:'ft-all',jalon:'ft-jalon',livrable:'ft-livrable',activite:'ft-activite',tache:'ft-tache'}};
  Object.entries(typeMap).forEach(([k,id])=>{{
    const b=document.getElementById(id); if(!b)return;
    b.style.cssText = k===filterType
      ? 'background:#0f172a;color:#fff;'
      : 'background:#e2e8f0;color:#475569;';
  }});
  const smap = {{all:'fs-all','A faire':'fs-Afaire','En cours':'fs-Encours',Termine:'fs-Termine',Bloque:'fs-Bloque'}};
  Object.entries(smap).forEach(([k,id])=>{{
    const b=document.getElementById(id); if(!b)return;
    const sc=STATUT_CFG[k];
    b.style.cssText = k===filterStatut
      ? `background:${{sc?sc.color:'#0f172a'}};color:#fff;`
      : 'background:#e2e8f0;color:#475569;';
  }});
}}

// ═══════════════════════════════════════════
// RENDER PRINCIPAL
// ═══════════════════════════════════════════
function render() {{
  const visible = getVisible();
  document.getElementById('tbl-body').innerHTML = visible.map(el=>renderRow(el)).join('');
  renderStats();
  renderFilters();
  // Si un panneau d'édition est ouvert, peupler les chips de dépendances
  if (editingId) renderDepChips();
  // Ajuster la hauteur du composant
  adjustHeight();
}}

function adjustHeight() {{
  const h = document.body.scrollHeight + 20;
  window.parent.postMessage({{type:'streamlit:setFrameHeight', height:h}}, '*');
}}

// ═══════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════
elements = recalcDates(elements);
render();

// Observer pour ajuster la hauteur dynamiquement
new ResizeObserver(adjustHeight).observe(document.body);
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════
# FONCTIONS EXISTANTES (inchangées)
# ══════════════════════════════════════════════════════════════════════

def creer_projet_vide(offre_id: str, offre_data: dict, entreprise_id: str) -> dict:
    return {
        "projet_id":       f"proj_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "offre_id":        offre_id,
        "entreprise_id":   entreprise_id,
        "offre_reference": offre_data.get('projet', {}).get('numero', ''),
        "nom_projet": (
            offre_data.get('offre_technique', {}).get('titre_offre')
            or offre_data.get('projet', {}).get('nom', '')
        ),
        "client":         offre_data.get('projet', {}).get('client', 'N/A'),
        "statut":         "demarrage",
        "date_creation":  datetime.now().isoformat(),
        "offre_data":     offre_data,
        "demarrage": {
            "parties_prenantes": [], "hypotheses": [], "risques": [],
            "plan_communication": [], "inclusions": [], "exclusions": [],
        },
        "planification": {
            "date_debut":      offre_data.get('dates', {}).get('travaux_debut', ''),
            "date_fin":        offre_data.get('dates', {}).get('travaux_fin', ''),
            "jalons":          [],
            "livrables":       [],
            "activites":       [],
            "taches":          [],
            "chemin_critique": [],
        },
        "suivi": {
            "jalons": [], "livrables": [], "activites": [], "taches": [],
            "reunions": [], "alertes": [],
        },
        "cloture":    {"elements_fermes": []},
        "postmortem": {"points_forts": [], "ameliorations": [], "conclusion": "", "complete": False},
        "budget":     {"planifie": 0, "reel": 0, "variance": 0},
        "duree":      {
            "planifiee_jours": offre_data.get('dates', {}).get('jours_ouvres', 0),
            "reelle_jours": 0
        },
        "ressources_projet": {
            "humaines":          [],
            "materielles":       [],
            "informationnelles": []
        },
    }


def _element_vide(type_el: str, nom: str = "", parent_id: str = None) -> dict:
    base = {
        "id":                    _uid(),
        "type":                  type_el,
        "nom":                   nom or f"Nouveau {type_el}",
        "description":           "",
        "date_debut":            None,
        "date_fin":              None,
        "duree_jours":           1,
        "statut":                "A faire",
        "priorite":              "Normale",
        "responsable_id":        None,
        "ressources_humaines":   [],
        "ressources_materielles":[],
        "ressources_info":       [],
        "dependances":           [],
        "avancement_pct":        0,
        "notes":                 "",
    }
    if type_el == "livrable":
        base["jalon_id"]    = parent_id
    elif type_el == "activite":
        base["livrable_id"] = parent_id
    elif type_el == "tache":
        base["activite_id"] = parent_id
    return base


def _calcul_avancement(plan: dict):
    for act in plan.get("activites", []):
        taches = [t for t in plan.get("taches", []) if t.get("activite_id") == act["id"]]
        if taches:
            act["avancement_pct"] = int(sum(t.get("avancement_pct", 0) for t in taches) / len(taches))
    for liv in plan.get("livrables", []):
        acts = [a for a in plan.get("activites", []) if a.get("livrable_id") == liv["id"]]
        if acts:
            liv["avancement_pct"] = int(sum(a.get("avancement_pct", 0) for a in acts) / len(acts))
    for jal in plan.get("jalons", []):
        livs = [l for l in plan.get("livrables", []) if l.get("jalon_id") == jal["id"]]
        if livs:
            jal["avancement_pct"] = int(sum(l.get("avancement_pct", 0) for l in livs) / len(livs))


def _migrer_orphelins(plan: dict):
    orphelins = False
    premier_jalon = plan["jalons"][0]["id"] if plan.get("jalons") else None
    for l in plan.get("livrables", []):
        if not l.get("jalon_id"):
            l["jalon_id"] = premier_jalon
            orphelins = True
    premier_livrable = plan["livrables"][0]["id"] if plan.get("livrables") else None
    for a in plan.get("activites", []):
        if not a.get("livrable_id"):
            a["livrable_id"] = premier_livrable
            orphelins = True
    premiere_activite = plan["activites"][0]["id"] if plan.get("activites") else None
    for t in plan.get("taches", []):
        if not t.get("activite_id"):
            t["activite_id"] = premiere_activite
            orphelins = True
    if orphelins:
        st.warning("⚠️ Éléments orphelins rattachés automatiquement. Vérifiez la planification.")


def generer_plan_projet_ia(offre_data: dict, user: dict, dates: dict) -> Optional[dict]:
    try:
        exigences   = offre_data.get('exigences', {})
        offre_tech  = offre_data.get('offre_technique', {})
        offre_fin   = offre_data.get('offre_financiere', {})
        projet_info = offre_data.get('projet', {})
        dates_offre = offre_data.get('dates', {})

        nom_projet   = offre_tech.get('titre_offre') or exigences.get('nom_projet') or projet_info.get('nom', 'Projet')
        client       = exigences.get('client', projet_info.get('client', ''))
        sommaire     = exigences.get('sommaire', '')
        specialites  = ", ".join(user.get('specialites', []))
        date_debut   = dates.get('debut') or dates_offre.get('travaux_debut', '')
        date_fin     = dates.get('fin')   or dates_offre.get('travaux_fin', '')
        jours_ouvres = dates_offre.get('jours_ouvres', 0)
        phases_offre = exigences.get('livrables', [])
        equipe_offre = offre_tech.get('equipe', [])
        equipe_str   = "\n".join([f"  - {m.get('role', m.get('poste', ''))} : {m.get('nom', '')}" for m in equipe_offre]) if equipe_offre else ""
        budget_total = offre_fin.get('total', '') or offre_fin.get('montant_total', '') or offre_fin.get('prix_total', '')
        phases_str   = "\n".join([
            f"  - {p}" if isinstance(p, str)
            else f"  - {p.get('nom', p.get('phase', ''))} ({p.get('duree', p.get('jours', ''))} jours)"
            for p in phases_offre
        ]) if phases_offre else "  (non spécifiées — déduire du sommaire)"
        contenu_brut = json.dumps(offre_data, ensure_ascii=False)[:2000]

        prompt = f"""Tu es un chargé de projet senior spécialisé en construction au Québec.
Génère un plan de projet détaillé basé sur cette offre.

Projet: {nom_projet} | Client: {client} | Spécialité: {specialites}
Période: {date_debut} → {date_fin} ({jours_ouvres} jours ouvrés)
Budget: {budget_total if budget_total else 'non spécifié'}

PHASES: {phases_str}
ÉQUIPE: {equipe_str if equipe_str else '(à définir)'}
OFFRE: {contenu_brut}

Règles: 1 jalon/phase + démarrage + clôture, min 2 livrables/jalon,
min 2 activités/livrable, min 2 tâches/activité spécifiques au métier.

Réponds UNIQUEMENT en JSON valide:
{{"jalons":[{{"id":"j1","nom":"Démarrage","date_fin":"YYYY-MM-DD","livrables":[{{"id":"l1","nom":"Livrable","activites":[{{"id":"a1","nom":"Activité","duree_jours":3,"taches":[{{"id":"t1","nom":"Tâche","duree_jours":1,"responsable":"Rôle"}}]}}]}}]}}],"risques":[{{"description":"","impact":"Moyen","probabilite":"Moyenne","mitigation":""}}],"parties_prenantes":[{{"nom":"","role":"","influence":"Elevee","interet":"Eleve"}}],"inclusions":[],"exclusions":[]}}"""

        mgr    = LLMManager()
        result = mgr.analyze(prompt, max_tokens=4000)
        if not result.get("success"):
            st.warning(f"⚠️ Génération IA non disponible : {result.get('error')}")
            return None
        text = result["result"]
        idx  = text.find('{')
        if idx >= 0:
            return json.loads(text[idx: text.rfind('}') + 1])
        return None
    except Exception as e:
        st.warning(f"⚠️ Génération IA non disponible : {e}")
        return None


def _aplatir_plan_ia(plan_ia: dict, plan: dict):
    for jal_ia in plan_ia.get("jalons", []):
        j = _element_vide("jalon", jal_ia.get("nom", "Jalon"))
        j["date_fin"] = jal_ia.get("date_fin")
        plan["jalons"].append(j)
        for liv_ia in jal_ia.get("livrables", []):
            l = _element_vide("livrable", liv_ia.get("nom", "Livrable"), parent_id=j["id"])
            plan["livrables"].append(l)
            for act_ia in liv_ia.get("activites", []):
                a = _element_vide("activite", act_ia.get("nom", "Activité"), parent_id=l["id"])
                a["duree_jours"] = act_ia.get("duree_jours", 1)
                plan["activites"].append(a)
                for tac_ia in act_ia.get("taches", []):
                    t = _element_vide("tache", tac_ia.get("nom", "Tâche"), parent_id=a["id"])
                    t["duree_jours"] = tac_ia.get("duree_jours", 1)
                    t["notes"]       = tac_ia.get("responsable", "")
                    plan["taches"].append(t)


def _suggestion_ia_legere(contexte: str, demande: str) -> str:
    try:
        mgr    = LLMManager()
        prompt = f"Contexte projet : {contexte}\n\n{demande}\n\nRéponds en français, de façon concise (5 lignes max)."
        result = mgr.analyze(prompt, max_tokens=300)
        return result.get("result", "") if result.get("success") else ""
    except Exception:
        return ""


def analyser_offre_pour_demarrage(offre_data: dict, user: dict) -> dict:
    try:
        nom = offre_data.get('offre_technique', {}).get('titre_offre') or offre_data.get('projet', {}).get('nom', '')
        prompt = f"""Analyse cette offre et suggère des éléments de démarrage.
Projet: {nom}  Entreprise: {user.get('nom_entreprise', '')}
Spécialités: {', '.join(user.get('specialites', []))}
JSON uniquement:
{{"parties_prenantes":[{{"nom":"Client","role":"Commanditaire","influence":"Elevee","interet":"Eleve"}}],"risques":[{{"description":"Retard","impact":"Moyen","probabilite":"Moyenne","mitigation":"Suivi hebdo"}}],"inclusions":["Installation selon plans"],"exclusions":["Travaux civils"]}}"""
        mgr    = LLMManager()
        result = mgr.analyze(prompt, max_tokens=1500)
        if not result.get("success"):
            st.warning(f"Suggestions IA non disponibles : {result.get('error')}")
            return {}
        text = result["result"]
        idx  = text.find('{')
        return json.loads(text[idx: text.rfind('}') + 1]) if idx >= 0 else {}
    except Exception as e:
        st.warning(f"Suggestions IA non disponibles : {e}")
        return {}


def _sauvegarder(projet: dict, user: dict):
    try:
        database.apply_supabase_auth()
        data = {
            'entreprise_id': user['id'],
            'projet_id':     projet['projet_id'],
            'nom_projet':    projet['nom_projet'],
            'statut':        projet['statut'],
            'data':          json.dumps(projet)
        }
        ex = database.supabase.table('gestion_projets').select("id").eq('projet_id', projet['projet_id']).execute()
        if ex.data:
            database.supabase.table('gestion_projets').update(data).eq('projet_id', projet['projet_id']).execute()
        else:
            database.supabase.table('gestion_projets').insert(data).execute()
        st.success("✅ Projet sauvegardé")
    except Exception as e:
        sl  = st.session_state.setdefault('projets_locaux', [])
        idx = next((i for i, p in enumerate(sl) if p['projet_id'] == projet['projet_id']), None)
        if idx is not None:
            sl[idx] = projet
        else:
            sl.append(projet)
        st.warning(f"⚠️ Sauvegarde locale (hors ligne) : {e}")


def _afficher_gantt(elements: list, date_debut_projet: str):
    elems_dates = []
    for el in elements:
        dd = el.get('date_debut')
        df = el.get('date_fin')
        if dd and df:
            try:
                d0 = date.fromisoformat(dd[:10])
                d1 = date.fromisoformat(df[:10])
                elems_dates.append((el['nom'], el['type'], d0, d1, el.get('avancement_pct', 0)))
            except Exception:
                pass
    if not elems_dates:
        st.info("Définissez des dates de début et de fin pour afficher le Gantt.")
        return
    d_min      = min(e[2] for e in elems_dates)
    d_max      = max(e[3] for e in elems_dates)
    total_days = max((d_max - d_min).days + 1, 1)
    COULEURS = {"jalon":"#3B82F6","livrable":"#10B981","activite":"#F59E0B","tache":"#8B5CF6"}
    ICONES   = {"jalon":"J","livrable":"L","activite":"A","tache":"T"}
    html = """<style>
.gantt-wrap{font-family:sans-serif;font-size:12px;overflow-x:auto}
.gantt-row{display:flex;align-items:center;margin:3px 0}
.gantt-label{width:180px;min-width:180px;padding-right:8px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.gantt-track{flex:1;height:22px;background:#f0f0f0;border-radius:4px;position:relative}
.gantt-bar{position:absolute;height:100%;border-radius:4px;display:flex;align-items:center;padding:0 4px;color:#fff;font-size:10px;font-weight:600;overflow:hidden;box-sizing:border-box}
.gantt-progress{position:absolute;height:100%;border-radius:4px;background:rgba(0,0,0,0.25);pointer-events:none}
.gantt-header{display:flex;align-items:center;margin-bottom:4px;font-weight:600;color:#555}
.gantt-badge{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:4px;vertical-align:middle}
</style>
<div class="gantt-wrap">
<div class="gantt-header"><div style="width:180px">Élément</div><div style="flex:1">Calendrier</div></div>"""
    for (nom, typ, d0, d1, avp) in elems_dates:
        left_pct  = (d0 - d_min).days / total_days * 100
        width_pct = max((d1 - d0).days + 1, 1) / total_days * 100
        couleur   = COULEURS.get(typ, "#6B7280")
        icone     = ICONES.get(typ, "?")
        html += f"""<div class="gantt-row">
  <div class="gantt-label" title="{nom}"><span class="gantt-badge" style="background:{couleur}">{icone}</span>{nom}</div>
  <div class="gantt-track">
    <div class="gantt-bar" style="left:{left_pct:.1f}%;width:{width_pct:.1f}%;background:{couleur}">
      {avp}%<div class="gantt-progress" style="width:{avp}%;"></div>
    </div>
  </div>
</div>"""
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)
    cols = st.columns(4)
    for i, (k, c) in enumerate(COULEURS.items()):
        cols[i].markdown(f'<span style="display:inline-block;width:12px;height:12px;background:{c};border-radius:2px;margin-right:4px"></span>{k.capitalize()}', unsafe_allow_html=True)


def _tableau_elements(elements: list, ressources_projet: dict, label: str):
    if not elements:
        st.info(f"Aucun {label} défini.")
        return
    rh_map = {r['id']: r['nom'] for r in ressources_projet.get('humaines', [])}
    rows = []
    for i, el in enumerate(elements):
        resp_noms = ", ".join(rh_map.get(rid, rid) for rid in el.get('ressources_humaines', []))
        rows.append({
            "N°": i, "Nom": el.get('nom', ''), "Statut": el.get('statut', ''),
            "Priorité": el.get('priorite', ''), "Début": (el.get('date_debut') or '')[:10],
            "Fin": (el.get('date_fin') or '')[:10], "Avancement": f"{el.get('avancement_pct', 0)}%",
            "Responsables": resp_noms,
        })
    import pandas as pd
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _form_element(el: dict, key_prefix: str, ressources_projet: dict, tous_elements: list):
    STATUTS   = ["A faire", "En cours", "Termine", "Bloque"]
    PRIORITES = ["Basse", "Normale", "Haute", "Critique"]
    el['nom']         = st.text_input("Nom", el.get('nom', ''), key=f"{key_prefix}_nom")
    el['description'] = st.text_area("Description", el.get('description', ''), height=70, key=f"{key_prefix}_desc")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        dd   = el.get('date_debut')
        dd_v = date.fromisoformat(dd[:10]) if dd else None
        nd   = st.date_input("Début", value=dd_v, key=f"{key_prefix}_dd")
        el['date_debut'] = nd.isoformat() if nd else None
    with c2:
        df   = el.get('date_fin')
        df_v = date.fromisoformat(df[:10]) if df else None
        nf   = st.date_input("Fin", value=df_v, key=f"{key_prefix}_df")
        el['date_fin'] = nf.isoformat() if nf else None
    with c3:
        s_idx = STATUTS.index(el.get('statut', 'A faire')) if el.get('statut') in STATUTS else 0
        el['statut'] = st.selectbox("Statut", STATUTS, index=s_idx, key=f"{key_prefix}_statut")
    with c4:
        p_idx = PRIORITES.index(el.get('priorite', 'Normale')) if el.get('priorite') in PRIORITES else 1
        el['priorite'] = st.selectbox("Priorité", PRIORITES, index=p_idx, key=f"{key_prefix}_prio")
    el['avancement_pct'] = st.slider("Avancement %", 0, 100, el.get('avancement_pct', 0), key=f"{key_prefix}_av")
    el['notes']          = st.text_area("Notes", el.get('notes', ''), height=60, key=f"{key_prefix}_notes")
    if st.button("🤖 Suggestion IA", key=f"{key_prefix}_ia_suggest"):
        with st.spinner("Analyse en cours..."):
            contexte = f"Secteur : construction au Québec. Type : {el.get('type', '')}. Nom : {el.get('nom', '')}. Statut : {el.get('statut', '')}."
            demande  = "Propose 3 sous-tâches concrètes et réalistes pour ce chantier. Réponds en français, 5 lignes max."
            suggestion = _suggestion_ia_legere(contexte, demande)
        if suggestion:
            st.info(f"💡 {suggestion}")
        else:
            st.warning("Suggestion IA non disponible pour le moment.")


# ══════════════════════════════════════════════════════════════════════
# PLANIFICATION — NOUVELLE VERSION AVEC COMPOSANT BIDIRECTIONNEL
# ══════════════════════════════════════════════════════════════════════

def _show_planification(projet: dict, user: dict):
    st.header("Planification")

    plan = projet['planification']
    rp   = projet.get('ressources_projet', {'humaines': [], 'materielles': [], 'informationnelles': []})

    _migrer_orphelins(plan)
    _calcul_avancement(plan)

    # ── Bandeau génération IA ─────────────────────────────────────────
    nb_j = len(plan.get('jalons', []))
    nb_l = len(plan.get('livrables', []))
    nb_a = len(plan.get('activites', []))
    nb_t = len(plan.get('taches', []))

    col_btn, col_info = st.columns([2, 3])
    with col_btn:
        generer = st.button(
            "🤖 Générer le plan complet par IA", type="primary", key="gen_plan_ia",
            help="Génère jalons, livrables, activités et tâches à partir de l'offre technique"
        )
    with col_info:
        if nb_j > 0:
            st.info(f"📊 **{nb_j}** jalons · **{nb_l}** livrables · **{nb_a}** activités · **{nb_t}** tâches")
        else:
            st.warning("⚠️ Aucun plan. Générez par IA ou ajoutez manuellement dans le tableau.")

    if generer:
        offre_data = projet.get('offre_data') or {}
        if not offre_data and projet.get('offre_id'):
            try:
                for table, data_k in [('analyses','analyse_json'),('soumissions','analyse_json'),('offres','contenu')]:
                    row = database.supabase.table(table).select("*").eq('id', projet['offre_id']).execute().data
                    if row:
                        raw = row[0].get(data_k, '{}')
                        offre_data = json.loads(raw) if isinstance(raw, str) else raw
                        break
            except Exception:
                pass
        with st.spinner("🤖 Génération du plan en cours… (30 à 60 secondes)"):
            plan_ia = generer_plan_projet_ia(
                offre_data=offre_data, user=user,
                dates={'debut': plan.get('date_debut',''), 'fin': plan.get('date_fin','')}
            )
        if plan_ia:
            plan['jalons'] = []; plan['livrables'] = []; plan['activites'] = []; plan['taches'] = []
            _aplatir_plan_ia(plan_ia, plan)
            st.session_state['projet_actif'] = projet
            st.success(f"✅ Plan généré : {len(plan['jalons'])} jalons · {len(plan['livrables'])} livrables · {len(plan['activites'])} activités · {len(plan['taches'])} tâches")
            st.rerun()
        else:
            st.error("❌ Génération IA échouée.")

    st.markdown("---")

    # ── Vue : Tableau interactif ou Gantt ────────────────────────────
    vue = st.radio("Vue", ["📋 Tableau interactif", "📊 Gantt"], horizontal=True, key="plan_vue")

    if vue == "📊 Gantt":
        tous = (
            [dict(e, type='jalon')    for e in plan.get('jalons', [])] +
            [dict(e, type='livrable') for e in plan.get('livrables', [])] +
            [dict(e, type='activite') for e in plan.get('activites', [])] +
            [dict(e, type='tache')    for e in plan.get('taches', [])]
        )
        _afficher_gantt(tous, plan.get('date_debut', ''))
        return

    # ── COMPOSANT BIDIRECTIONNEL ─────────────────────────────────────
    # Préparer les données
    elements_flat = _flatten_plan(plan)
    elements_flat = _recalc_dates(elements_flat, plan.get('date_debut', ''))
    responsables  = [{"id": r["id"], "nom": r["nom"], "role": r.get("role", "")} for r in rp.get("humaines", [])]

    # Clé unique par projet pour éviter les conflits entre projets
    comp_key = f"planning_{projet.get('projet_id','default')}"

    # Hauteur dynamique : min 400px, +32px par élément
    height = max(400, len(elements_flat) * 38 + 260)

    # Rendu du composant
    result = components.html(
        _build_planning_component(elements_flat, responsables, plan.get('date_debut', '')),
        height=height,
        scrolling=False,
    )

    # ── Réception des modifications depuis le composant ──────────────
    # st.components.v1.html ne supporte pas nativement setComponentValue,
    # donc on utilise un st.session_state intermédiaire via un hack propre :
    # le composant envoie un postMessage qui est intercepté par un écouteur JS
    # injecté dans la page principale, qui écrit dans un champ caché.
    #
    # SOLUTION ROBUSTE : on ajoute un écouteur dans la page principale Streamlit
    # qui intercepte les messages du composant iframe et les écrit dans un
    # champ text_input masqué, déclenchant le rerun automatique.

    # Injecter l'écouteur dans la page principale (une seule fois)
    listener_key = f"pl_listener_{projet.get('projet_id','default')}"
    if listener_key not in st.session_state:
        st.session_state[listener_key] = True
        st.markdown(f"""
<script>
(function() {{
  if (window._planningListenerActive_{comp_key.replace('-','_')}) return;
  window._planningListenerActive_{comp_key.replace('-','_')} = true;
  window.addEventListener('message', function(e) {{
    if (!e.data || e.data.type !== 'streamlit:setComponentValue') return;
    try {{
      const payload = JSON.parse(e.data.value);
      if (payload.action === 'update' && payload.elements) {{
        // Écrire dans le champ caché via DOM
        const input = document.querySelector('input[data-testid="pl_hidden_{comp_key}"]');
        if (input) {{
          const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          nativeInputValueSetter.call(input, JSON.stringify(payload.elements));
          input.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}
      }}
    }} catch(err) {{ console.error('Planning component error:', err); }}
  }});
}})();
</script>
""", unsafe_allow_html=True)

    # Champ caché qui reçoit les données du JS et déclenche le rerun
    hidden_val = st.text_input(
        "planning_data_hidden",
        key=f"pl_hidden_{comp_key}",
        label_visibility="collapsed",
    )

    # Si des données ont été reçues, les appliquer au projet
    if hidden_val and hidden_val.strip().startswith('['):
        try:
            new_elements = json.loads(hidden_val)
            if isinstance(new_elements, list) and len(new_elements) > 0:
                # Recalculer les dates côté Python (validation)
                new_elements = _recalc_dates(new_elements, plan.get('date_debut', ''))
                # Mettre à jour la structure du plan
                _unflatten_plan(new_elements, plan)
                _calcul_avancement(plan)
                st.session_state['projet_actif'] = projet
                # Réinitialiser le champ pour éviter la boucle
                st.session_state[f"pl_hidden_{comp_key}"] = ""
                st.toast("✅ Tableau mis à jour — pensez à sauvegarder", icon="✅")
        except Exception as e:
            st.warning(f"Erreur de synchronisation : {e}")


# ══════════════════════════════════════════════════════════════════════
# RESSOURCES (inchangé)
# ══════════════════════════════════════════════════════════════════════

def _section_ressources(projet: dict, user: dict):
    st.subheader("Ressources du projet")
    rp = projet.setdefault('ressources_projet', {'humaines': [], 'materielles': [], 'informationnelles': []})
    if not rp['humaines'] and user.get('equipe'):
        for m in user.get('equipe', []):
            rp['humaines'].append({'id': _uid(), 'nom': m.get('nom', ''), 'role': m.get('poste', ''), 'taux_horaire': 75})

    tab_rh, tab_rm, tab_ri = st.tabs(["Humaines", "Matérielles", "Informationnelles"])
    with tab_rh:
        for i, r in enumerate(rp['humaines']):
            with st.expander(r.get('nom', '') or f"Ressource {i+1}", expanded=True):
                c1, c2, c3 = st.columns(3)
                r['nom']          = c1.text_input("Nom",        r.get('nom', ''),                        key=f"rh_n_{i}")
                r['role']         = c2.text_input("Rôle",       r.get('role', ''),                       key=f"rh_r_{i}")
                r['taux_horaire'] = c3.number_input("Taux $/h", value=float(r.get('taux_horaire', 75)),  step=5.0, key=f"rh_t_{i}")
                if st.button("🗑 Supprimer", key=f"rh_del_{i}"):
                    rp['humaines'].pop(i); st.session_state['projet_actif'] = projet; st.rerun()
        if st.button("➕ Ajouter ressource humaine", key="add_rh"):
            rp['humaines'].append({'id': _uid(), 'nom': '', 'role': '', 'taux_horaire': 75})
            st.session_state['projet_actif'] = projet; st.rerun()

    with tab_rm:
        for i, r in enumerate(rp['materielles']):
            with st.expander(r.get('nom', '') or f"Matériel {i+1}", expanded=True):
                c1, c2, c3, c4 = st.columns(4)
                r['nom']           = c1.text_input("Nom",               r.get('nom', ''),                      key=f"rm_n_{i}")
                r['quantite']      = c2.number_input("Qté",             value=int(r.get('quantite', 1)),        step=1,    key=f"rm_q_{i}")
                r['unite']         = c3.text_input("Unité",             r.get('unite', 'u'),                    key=f"rm_u_{i}")
                r['cout_unitaire'] = c4.number_input("Coût unitaire $", value=float(r.get('cout_unitaire', 0)), step=10.0, key=f"rm_c_{i}")
                if st.button("🗑 Supprimer", key=f"rm_del_{i}"):
                    rp['materielles'].pop(i); st.session_state['projet_actif'] = projet; st.rerun()
        if st.button("➕ Ajouter ressource matérielle", key="add_rm"):
            rp['materielles'].append({'id': _uid(), 'nom': '', 'quantite': 1, 'unite': 'u', 'cout_unitaire': 0.0})
            st.session_state['projet_actif'] = projet; st.rerun()

    with tab_ri:
        for i, r in enumerate(rp['informationnelles']):
            with st.expander(r.get('nom', '') or f"Document {i+1}", expanded=True):
                c1, c2 = st.columns(2)
                r['nom']         = c1.text_input("Nom",                r.get('nom', ''),         key=f"ri_n_{i}")
                r['type']        = c2.text_input("Type (plan, spec…)", r.get('type', ''),         key=f"ri_t_{i}")
                r['description'] = st.text_area("Description",         r.get('description', ''), height=60, key=f"ri_d_{i}")
                if st.button("🗑 Supprimer", key=f"ri_del_{i}"):
                    rp['informationnelles'].pop(i); st.session_state['projet_actif'] = projet; st.rerun()
        if st.button("➕ Ajouter ressource informationnelle", key="add_ri"):
            rp['informationnelles'].append({'id': _uid(), 'nom': '', 'type': '', 'description': ''})
            st.session_state['projet_actif'] = projet; st.rerun()


# ══════════════════════════════════════════════════════════════════════
# SUIVI (inchangé)
# ══════════════════════════════════════════════════════════════════════

def _show_suivi(projet: dict):
    st.header("Exécution et Suivi")
    plan  = projet['planification']
    suivi = projet['suivi']
    rp    = projet.get('ressources_projet', {'humaines': [], 'materielles': [], 'informationnelles': []})
    for key in ['jalons', 'livrables', 'activites', 'taches']:
        if not suivi.get(key) and plan.get(key):
            suivi[key] = [{**el, 'avancement_pct': el.get('avancement_pct', 0), 'notes_suivi': ''} for el in plan[key]]
    vue_s = st.radio("Vue suivi", ["Tableau", "Détail"], horizontal=True)
    tous_suivi = (
        [dict(e, type='jalon')    for e in suivi.get('jalons', [])] +
        [dict(e, type='livrable') for e in suivi.get('livrables', [])] +
        [dict(e, type='activite') for e in suivi.get('activites', [])] +
        [dict(e, type='tache')    for e in suivi.get('taches', [])]
    )
    if vue_s == "Tableau":
        _tableau_elements(tous_suivi, rp, "éléments de suivi")
        if st.checkbox("Afficher le Gantt de suivi"):
            _afficher_gantt(tous_suivi, plan.get('date_debut', ''))
    else:
        for label, key in [("Jalons","jalons"),("Livrables","livrables"),("Activités","activites"),("Tâches","taches")]:
            st.subheader(label)
            for i, el in enumerate(suivi.get(key, [])):
                with st.expander(f"{el.get('nom', '')} — {el.get('avancement_pct', 0)}%", expanded=False):
                    el['avancement_pct'] = st.slider("Avancement %", 0, 100, el.get('avancement_pct', 0), key=f"sv_{key}_{i}")
                    STATUTS_S = ["A faire", "En cours", "Termine", "Bloque"]
                    s_idx = STATUTS_S.index(el.get('statut', 'A faire')) if el.get('statut') in STATUTS_S else 0
                    el['statut']      = st.selectbox("Statut", STATUTS_S, index=s_idx, key=f"sv_st_{key}_{i}")
                    el['notes_suivi'] = st.text_area("Notes de suivi", el.get('notes_suivi', ''), height=60, key=f"sv_notes_{key}_{i}")
                    if el['avancement_pct'] == 100 and el.get('statut') == 'Termine':
                        if st.button("Fermer cet élément", key=f"sv_close_{key}_{i}"):
                            projet['cloture'].setdefault('elements_fermes', []).append({"type": key[:-1], "nom": el['nom'], "date_fermeture": datetime.now().isoformat()})
                            st.rerun()
    st.markdown("---")
    st.subheader("Réunions de suivi")
    reunions = suivi.setdefault('reunions', [])
    for i, r in enumerate(reunions):
        with st.expander(f"Réunion — {r.get('date', 'N/A')} — {r.get('titre', '')}", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                rd   = r.get('date')
                rd_v = date.fromisoformat(rd[:10]) if rd else None
                nr   = st.date_input("Date", value=rd_v, key=f"reu_d_{i}")
                r['date']  = nr.isoformat() if nr else None
                r['titre'] = st.text_input("Titre", r.get('titre', ''), key=f"reu_t_{i}")
            with c2:
                r['participants'] = st.text_input("Participants",      r.get('participants', ''), key=f"reu_p_{i}")
                r['lieu']         = st.text_input("Lieu / lien visio", r.get('lieu', ''),         key=f"reu_l_{i}")
            r['ordre_du_jour'] = st.text_area("Ordre du jour",       r.get('ordre_du_jour', ''), height=80, key=f"reu_odj_{i}")
            r['decisions']     = st.text_area("Décisions / actions", r.get('decisions', ''),     height=80, key=f"reu_dec_{i}")
            if st.button("Supprimer", key=f"reu_del_{i}"):
                reunions.pop(i); st.rerun()
    if st.button("➕ Ajouter une réunion"):
        reunions.append({'id': _uid(), 'date': date.today().isoformat(), 'titre': '', 'participants': '', 'lieu': '', 'ordre_du_jour': '', 'decisions': ''})
        st.rerun()


# ══════════════════════════════════════════════════════════════════════
# DÉMARRAGE (inchangé)
# ══════════════════════════════════════════════════════════════════════

def _show_demarrage(projet: dict, user: dict):
    st.header("Phase de Démarrage")
    dem = projet['demarrage']
    st.subheader("Parties prenantes")
    for i, pp in enumerate(dem.get('parties_prenantes', [])):
        with st.expander(pp.get('nom', 'Partie prenante'), expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                pp['nom']  = st.text_input("Nom",  pp.get('nom', ''),  key=f"pp_n_{i}")
                pp['role'] = st.text_input("Rôle", pp.get('role', ''), key=f"pp_r_{i}")
            with c2:
                inf_opts = ["Faible", "Moyenne", "Elevee"]
                inf_val  = pp.get('influence', 'Moyenne') if pp.get('influence') in inf_opts else 'Moyenne'
                pp['influence'] = st.selectbox("Influence", inf_opts, index=inf_opts.index(inf_val), key=f"pp_i_{i}")
                int_opts = ["Faible", "Moyen", "Eleve"]
                int_val  = pp.get('interet', 'Moyen') if pp.get('interet') in int_opts else 'Moyen'
                pp['interet'] = st.selectbox("Intérêt", int_opts, index=int_opts.index(int_val), key=f"pp_in_{i}")
            if st.button("Supprimer", key=f"pp_del_{i}"):
                dem['parties_prenantes'].pop(i); st.rerun()
    if st.button("➕ Ajouter partie prenante"):
        dem.setdefault('parties_prenantes', []).append({'nom': 'Nouveau', 'role': '', 'influence': 'Moyenne', 'interet': 'Moyen'})
        st.rerun()
    st.markdown("---")
    st.subheader("Registre des risques")
    for i, r in enumerate(dem.get('risques', [])):
        with st.expander(r.get('description', 'Risque')[:50], expanded=False):
            r['description'] = st.text_area("Description", r.get('description', ''), height=60, key=f"rq_d_{i}")
            c1, c2 = st.columns(2)
            with c1:
                imp_opts = ["Faible", "Moyen", "Eleve"]
                imp_val  = r.get('impact', 'Moyen') if r.get('impact') in imp_opts else 'Moyen'
                r['impact'] = st.select_slider("Impact", imp_opts, value=imp_val, key=f"rq_i_{i}")
            with c2:
                prob_opts = ["Faible", "Moyenne", "Elevee"]
                prob_val  = r.get('probabilite', 'Moyenne') if r.get('probabilite') in prob_opts else 'Moyenne'
                r['probabilite'] = st.select_slider("Probabilité", prob_opts, value=prob_val, key=f"rq_p_{i}")
            r['mitigation'] = st.text_input("Mitigation", r.get('mitigation', ''), key=f"rq_m_{i}")
            if st.button("Supprimer", key=f"rq_del_{i}"):
                dem['risques'].pop(i); st.rerun()
    if st.button("➕ Ajouter risque"):
        dem.setdefault('risques', []).append({'description': '', 'impact': 'Moyen', 'probabilite': 'Moyenne', 'mitigation': ''})
        st.rerun()
    st.markdown("---")
    st.subheader("Inclusions / Exclusions")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Inclusions**")
        for i, inc in enumerate(dem.get('inclusions', [])):
            cols = st.columns([5, 1])
            dem['inclusions'][i] = cols[0].text_input("", inc, key=f"inc_{i}", label_visibility="collapsed")
            if cols[1].button("✕", key=f"del_inc_{i}"):
                dem['inclusions'].pop(i); st.rerun()
        if st.button("➕ Inclusion"):
            dem.setdefault('inclusions', []).append(""); st.rerun()
    with c2:
        st.markdown("**Exclusions**")
        for i, exc in enumerate(dem.get('exclusions', [])):
            cols = st.columns([5, 1])
            dem['exclusions'][i] = cols[0].text_input("", exc, key=f"exc_{i}", label_visibility="collapsed")
            if cols[1].button("✕", key=f"del_exc_{i}"):
                dem['exclusions'].pop(i); st.rerun()
        if st.button("➕ Exclusion"):
            dem.setdefault('exclusions', []).append(""); st.rerun()


# ══════════════════════════════════════════════════════════════════════
# CLÔTURE & POST-MORTEM (inchangés)
# ══════════════════════════════════════════════════════════════════════

def _show_cloture(projet: dict):
    st.header("Phase de Clôture")
    elements = projet['cloture'].get('elements_fermes', [])
    if not elements:
        st.info("Aucun élément fermé pour le moment.")
        return
    for e in elements:
        st.write(f"**{e['type'].upper()}** : {e['nom']} — {(e.get('date_fermeture') or '')[:10]}")


def _show_postmortem(projet: dict):
    st.header("Post-mortem")
    if projet['statut'] != 'termine':
        st.warning("Disponible une fois le projet marqué comme terminé.")
        return
    pm = projet['postmortem']
    pf = st.text_area("Points forts", "\n".join(pm.get('points_forts', [])), height=120)
    pm['points_forts'] = [l.strip() for l in pf.split('\n') if l.strip()]
    am = st.text_area("À améliorer", "\n".join(pm.get('ameliorations', [])), height=120)
    pm['ameliorations'] = [l.strip() for l in am.split('\n') if l.strip()]
    pm['conclusion'] = st.text_area("Conclusion", pm.get('conclusion', ''), height=150)


# ══════════════════════════════════════════════════════════════════════
# CRÉATION NOUVEAU PROJET (inchangé)
# ══════════════════════════════════════════════════════════════════════

def _extraire_info_offre(offre: dict) -> dict:
    contenu = offre.get('contenu', {})
    if isinstance(contenu, str):
        try:
            contenu = json.loads(contenu)
        except Exception:
            contenu = {}
    nom = (
        contenu.get('offre_technique', {}).get('titre_offre')
        or contenu.get('exigences', {}).get('nom_projet')
        or contenu.get('projet', {}).get('nom')
        or f"Offre {str(offre.get('id', ''))[:8]}"
    )
    numero = contenu.get('exigences', {}).get('numero_projet') or contenu.get('projet', {}).get('numero') or ''
    return {"nom": nom, "numero": numero, "contenu": contenu}


def _creer_nouveau_projet_ui(user: dict) -> Optional[dict]:
    st.subheader("Créer un nouveau projet")
    if st.session_state.get('offre_pour_projet'):
        pre = st.session_state['offre_pour_projet']
        st.success(f"Offre sélectionnée : **{pre['nom_projet']}** — {pre['projet_numero']}")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🚀 Créer le projet avec cette offre", type="primary"):
                p = creer_projet_vide(pre['id'], pre['offre_data'], user['id'])
                if not p['nom_projet']: p['nom_projet'] = pre['nom_projet']
                if not p['offre_reference']: p['offre_reference'] = pre['projet_numero']
                if user.get('equipe'):
                    p['ressources_projet']['humaines'] = [
                        {'id': _uid(), 'nom': m.get('nom',''), 'role': m.get('poste',''), 'taux_horaire': 75}
                        for m in user['equipe']
                    ]
                with st.spinner("🤖 L'IA génère votre plan de projet complet…"):
                    plan_ia = generer_plan_projet_ia(offre_data=pre['offre_data'], user=user, dates={'debut': p['planification']['date_debut'], 'fin': p['planification']['date_fin']})
                if plan_ia:
                    _aplatir_plan_ia(plan_ia, p['planification'])
                    p['demarrage']['risques']           = plan_ia.get('risques', [])
                    p['demarrage']['parties_prenantes'] = plan_ia.get('parties_prenantes', [])
                    p['demarrage']['inclusions']        = plan_ia.get('inclusions', [])
                    p['demarrage']['exclusions']        = plan_ia.get('exclusions', [])
                    st.success("✅ Plan généré par l'IA — vérifiez et ajustez avant de sauvegarder.")
                else:
                    with st.spinner("Analyse IA du démarrage…"):
                        sug = analyser_offre_pour_demarrage(pre['offre_data'], user)
                        if sug: p['demarrage'].update(sug)
                del st.session_state['offre_pour_projet']
                st.session_state['projet_actif'] = p
                st.rerun()
        with c2:
            if st.button("Choisir une autre offre"):
                del st.session_state['offre_pour_projet']; st.rerun()
        return st.session_state.get('projet_actif')

    offres_acc = []
    for table, filtre_k, filtre_v, nom_k, num_k, data_k in [
        ('offres','statut','acceptee',None,None,None),
        ('soumissions','recommendation','GO','nom_projet','projet_numero','analyse_json'),
        ('analyses','recommendation','OUI','nom_projet','projet_numero','analyse_json'),
    ]:
        try:
            rows = database.supabase.table(table).select("*").eq('entreprise_id', user['id']).eq(filtre_k, filtre_v).execute().data or []
            for row in rows:
                if table == 'offres':
                    info = _extraire_info_offre(row)
                    offres_acc.append({'id': row['id'], 'source': table, 'nom_projet': info['nom'], 'projet_numero': info['numero'], 'offre_data': info['contenu']})
                else:
                    raw = row.get(data_k, '{}')
                    try: od = json.loads(raw) if isinstance(raw, str) else raw
                    except: od = {}
                    offres_acc.append({'id': row['id'], 'source': table, 'nom_projet': row.get(nom_k,'N/A'), 'projet_numero': row.get(num_k,''), 'offre_data': od})
        except Exception:
            pass

    vus, offres_u = set(), []
    for o in offres_acc:
        if o['id'] not in vus:
            vus.add(o['id']); offres_u.append(o)

    if not offres_u:
        st.warning("Aucune offre acceptée. Allez dans **Mes Offres**, marquez une offre comme **Acceptée** puis cliquez **Démarrer le projet**.")
        return None

    labels    = [f"{o['nom_projet']} — {o['projet_numero']}" for o in offres_u]
    label_sel = st.selectbox("Choisir une offre", labels)
    if st.button("🚀 Créer le projet", type="primary"):
        o = offres_u[labels.index(label_sel)]
        p = creer_projet_vide(o['id'], o['offre_data'], user['id'])
        if not p['nom_projet']: p['nom_projet'] = o['nom_projet']
        if not p['offre_reference']: p['offre_reference'] = o['projet_numero']
        if user.get('equipe'):
            p['ressources_projet']['humaines'] = [
                {'id': _uid(), 'nom': m.get('nom',''), 'role': m.get('poste',''), 'taux_horaire': 75}
                for m in user['equipe']
            ]
        with st.spinner("🤖 L'IA génère votre plan de projet complet…"):
            plan_ia = generer_plan_projet_ia(offre_data=o['offre_data'], user=user, dates={'debut': p['planification']['date_debut'], 'fin': p['planification']['date_fin']})
        if plan_ia:
            _aplatir_plan_ia(plan_ia, p['planification'])
            p['demarrage']['risques']           = plan_ia.get('risques', [])
            p['demarrage']['parties_prenantes'] = plan_ia.get('parties_prenantes', [])
            p['demarrage']['inclusions']        = plan_ia.get('inclusions', [])
            p['demarrage']['exclusions']        = plan_ia.get('exclusions', [])
            st.success("✅ Plan généré par l'IA — vérifiez et ajustez avant de sauvegarder.")
        else:
            with st.spinner("Analyse IA du démarrage…"):
                sug = analyser_offre_pour_demarrage(o['offre_data'], user)
                if sug: p['demarrage'].update(sug)
        st.session_state['projet_actif'] = p
        st.rerun()
    return st.session_state.get('projet_actif')


# ══════════════════════════════════════════════════════════════════════
# ONGLET PRINCIPAL (inchangé)
# ══════════════════════════════════════════════════════════════════════

def show_gestion_projets_tab(user: dict):
    st.title("Gestion de Projet")
    projet_en_session = st.session_state.get('projet_actif')
    try:
        database.apply_supabase_auth()
        resp    = database.supabase.table('gestion_projets').select("*").eq('entreprise_id', user['id']).order('date_creation', desc=True).execute()
        projets = [json.loads(p['data']) for p in resp.data] if resp.data else []
    except Exception as e:
        st.warning(f"Mode hors ligne : {e}")
        projets = st.session_state.get('projets_locaux', [])

    if projet_en_session:
        ids_db = [p['projet_id'] for p in projets]
        if projet_en_session['projet_id'] not in ids_db:
            projets.insert(0, projet_en_session)

    col1, col2 = st.columns([3, 1])
    projet_actif = None
    with col1:
        if projets:
            opts = [f"{p['nom_projet']} ({p.get('offre_reference','')}) — {p['statut'].upper()}" for p in projets]
            opts.insert(0, "Créer un nouveau projet")
            default_idx = 0
            if projet_en_session:
                try:
                    pid = projet_en_session['projet_id']
                    ids = [p['projet_id'] for p in projets]
                    default_idx = ids.index(pid) + 1
                except ValueError:
                    default_idx = 0
            sel = st.selectbox("Projet", opts, index=default_idx)
            if sel == "Créer un nouveau projet":
                projet_actif = _creer_nouveau_projet_ui(user)
            else:
                projet_actif = projets[opts.index(sel) - 1]
        else:
            projet_actif = _creer_nouveau_projet_ui(user)

    with col2:
        if projet_actif:
            STATUTS_PROJ   = ["demarrage", "planification", "execution", "suivi", "cloture", "termine"]
            s_idx          = STATUTS_PROJ.index(projet_actif['statut']) if projet_actif['statut'] in STATUTS_PROJ else 0
            nouveau_statut = st.selectbox("Statut projet", STATUTS_PROJ, index=s_idx)
            if nouveau_statut != projet_actif['statut']:
                projet_actif['statut'] = nouveau_statut

    if not projet_actif:
        st.info("Créez un nouveau projet pour commencer.")
        return

    st.session_state['projet_actif'] = projet_actif
    st.markdown("---")

    tabs = st.tabs(["Démarrage", "Ressources", "Planification", "Suivi", "Clôture", "Post-mortem"])
    with tabs[0]: _show_demarrage(projet_actif, user)
    with tabs[1]: _section_ressources(projet_actif, user)
    with tabs[2]: _show_planification(projet_actif, user)
    with tabs[3]: _show_suivi(projet_actif)
    with tabs[4]: _show_cloture(projet_actif)
    with tabs[5]: _show_postmortem(projet_actif)

    st.markdown("---")
    if st.button("💾 Sauvegarder le projet", type="primary"):
        _sauvegarder(projet_actif, user)