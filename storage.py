"""
Module de gestion du stockage des fichiers (logos, documents) dans Supabase Storage
Modification : upload_document_projet accepte tous les types de fichiers (détection MIME dynamique)
Ajout v2.0   : delete_document — supprime un fichier du bucket 'documents'
"""
import streamlit as st
from datetime import datetime
import os
import mimetypes


# ── Table des types MIME courants (complète mimetypes si nécessaire) ──
_MIME_MAP = {
    # Documents
    "pdf":  "application/pdf",
    "doc":  "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls":  "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt":  "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt":  "text/plain",
    "csv":  "text/csv",
    "rtf":  "application/rtf",
    # Images
    "png":  "image/png",
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "gif":  "image/gif",
    "webp": "image/webp",
    "svg":  "image/svg+xml",
    "tiff": "image/tiff",
    "bmp":  "image/bmp",
    # Archives
    "zip":  "application/zip",
    "rar":  "application/x-rar-compressed",
    "7z":   "application/x-7z-compressed",
    # Autres
    "json": "application/json",
    "xml":  "application/xml",
    "dwg":  "application/acad",
    "dxf":  "application/dxf",
}


def _get_content_type(filename: str) -> str:
    """Détecte le type MIME depuis l'extension du fichier."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _MIME_MAP:
        return _MIME_MAP[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def upload_logo(supabase, logo_file, entreprise_id):
    """
    Upload un logo dans Supabase Storage et retourne l'URL publique.
    """
    try:
        file_bytes     = logo_file.read()
        file_extension = logo_file.name.split('.')[-1].lower()
        timestamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name      = f"logo_{entreprise_id}_{timestamp}.{file_extension}"
        content_type   = _get_content_type(logo_file.name)

        supabase.storage.from_('logos').upload(
            path=file_name,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        return supabase.storage.from_('logos').get_public_url(file_name)

    except Exception as e:
        st.error(f"❌ Erreur lors de l'upload du logo : {str(e)}")
        return None


def delete_logo(supabase, logo_url):
    """Supprime un logo du storage Supabase."""
    try:
        if '/logos/' in logo_url:
            file_name = logo_url.split('/logos/')[-1]
            supabase.storage.from_('logos').remove([file_name])
            return True
        return False
    except Exception as e:
        st.warning(f"⚠️ Erreur lors de la suppression du logo : {str(e)}")
        return False


def upload_document_projet(supabase, document_file, entreprise_id=None):
    """
    Upload un document de projet dans Supabase Storage.
    Accepte tous les types de fichiers — le type MIME est détecté automatiquement.
    Bucket : 'documents'
    """
    try:
        file_bytes   = document_file.read()
        timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_ext = document_file.name.rsplit(".", 1)[-1] if "." in document_file.name else "bin"
        prefix       = f"projet_{entreprise_id}_" if entreprise_id else "projet_"
        file_name    = f"{prefix}{timestamp}.{original_ext}"
        content_type = _get_content_type(document_file.name)

        supabase.storage.from_('documents').upload(
            path=file_name,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        return supabase.storage.from_('documents').get_public_url(file_name)

    except Exception as e:
        st.warning(f"⚠️ Erreur lors de l'upload du document : {str(e)}")
        return None


def delete_document(supabase, document_url: str) -> bool:
    """
    Supprime un document du bucket 'documents' à partir de son URL publique.
    Non bloquant : retourne False sans lever d'exception si la suppression échoue.

    L'URL publique Supabase ressemble à :
    https://xxx.supabase.co/storage/v1/object/public/documents/projet_abc_20240101.pdf
    """
    try:
        if '/documents/' in document_url:
            # Extraire le chemin relatif après '/documents/'
            file_path = document_url.split('/documents/')[-1].split('?')[0]
            supabase.storage.from_('documents').remove([file_path])
            return True
        return False
    except Exception as e:
        st.warning(f"⚠️ Erreur lors de la suppression du document : {str(e)}")
        return False


def upload_soumission(supabase, document_file, entreprise_id=None):
    """
    Upload un document de soumission dans Supabase Storage.
    Accepte tous les types de fichiers — le type MIME est détecté automatiquement.
    """
    try:
        file_bytes   = document_file.read()
        timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_ext = document_file.name.rsplit(".", 1)[-1] if "." in document_file.name else "bin"
        prefix       = f"soumission_{entreprise_id}_" if entreprise_id else "soumission_"
        file_name    = f"{prefix}{timestamp}.{original_ext}"
        content_type = _get_content_type(document_file.name)

        supabase.storage.from_('soumissions').upload(
            path=file_name,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        return supabase.storage.from_('soumissions').get_public_url(file_name)

    except Exception as e:
        st.warning(f"⚠️ Erreur lors de l'upload de la soumission : {str(e)}")
        return None