"""
Fonctions de gestion de la base de données Supabase
"""
import streamlit as st
from supabase import create_client
import config


# Initialiser les clients Supabase
supabase = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)

supabase_admin = None
if config.SUPABASE_SERVICE_ROLE_KEY:
    try:
        supabase_admin = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    except Exception as e:
        st.warning(f"⚠️ Service role non disponible : {str(e)[:100]}")


def apply_supabase_auth():
    """Applique le token d'authentification aux requêtes Supabase"""
    try:
        token = st.session_state.get('access_token')
        if token and isinstance(token, str) and token.strip():
            supabase.postgrest.auth(token)
    except Exception as e:
        st.warning(f"⚠️ Erreur d'authentification : {str(e)}")


def signup_user(data):
    """Inscription d'un nouvel utilisateur"""
    try:
        if not data.get("numero_neq") or not data.get("licence_rbq"):
            st.error("❌ Le NEQ et la licence RBQ sont obligatoires")
            return False
        
        if not data.get("contact_email") or "@" not in data.get("contact_email", ""):
            st.error("❌ L'adresse courriel est invalide")
            return False
        
        if not data.get("password") or len(data.get("password", "")) < 6:
            st.error("❌ Le mot de passe doit contenir au moins 6 caractères")
            return False
        
        try:
            existing_user = get_user_by_email(data["contact_email"])
            if existing_user:
                st.error("❌ Cette adresse courriel est déjà utilisée. Veuillez vous connecter.")
                return False
        except:
            pass
            
        try:
            response = supabase.auth.sign_up({
                "email": data["contact_email"], 
                "password": data["password"],
                "options": {
                    "data": {
                        "nom_entreprise": data["nom_entreprise"],
                        "numero_neq": data["numero_neq"],
                        "licence_rbq": data["licence_rbq"]
                    }
                }
            })
        except Exception as auth_error:
            error_msg = str(auth_error).lower()
            if "rate limit" in error_msg:
                st.error("⏱️ Trop de tentatives d'inscription. Veuillez patienter 60 secondes.")
                st.info("💡 Si vous avez déjà un compte, utilisez l'onglet Connexion.")
                return False
            else:
                raise auth_error
        
        if not response.user or not response.user.id:
            st.error("❌ Erreur lors de la création du compte. Veuillez réessayer.")
            return False
        
        user_id = response.user.id
        
        entreprise_data = {
            "nom_entreprise": data["nom_entreprise"],
            "numero_neq": data["numero_neq"],
            "licence_rbq": data["licence_rbq"],
            "specialites": data.get("specialites", []),
            "adresse": data.get("adresse", ""),
            "ville": data.get("ville", ""),
            "province": data.get("province", ""),
            "code_postal": data.get("code_postal", ""),
            "pays": data.get("pays", "Canada"),
            "contact_nom": data.get("contact_nom", ""),
            "contact_telephone": data.get("contact_telephone", ""),
            "contact_email": data["contact_email"],
            "user_id": user_id
        }

        insertion_success = False
        
        if response.session and response.session.access_token:
            try:
                temp_client = create_client(config.SUPABASE_URL, config.SUPABASE_ANON_KEY)
                temp_client.postgrest.auth(response.session.access_token)
                result = temp_client.table('entreprises').insert(entreprise_data).execute()
                
                if result.data and len(result.data) > 0:
                    insertion_success = True
                    try:
                        supabase.auth.sign_out()
                    except:
                        pass
            except Exception as e:
                st.warning(f"⚠️ Tentative 1 échouée : {str(e)[:100]}")
        
        if not insertion_success and supabase_admin:
            try:
                result = supabase_admin.table('entreprises').insert(entreprise_data).execute()
                if result.data and len(result.data) > 0:
                    insertion_success = True
            except Exception as e:
                st.warning(f"⚠️ Tentative 2 échouée : {str(e)[:100]}")
        
        if not insertion_success:
            try:
                result = supabase.table('entreprises').insert(entreprise_data).execute()
                if result.data and len(result.data) > 0:
                    insertion_success = True
            except Exception as e:
                st.error(f"❌ Toutes les tentatives d'insertion ont échoué")
                st.info("💡 Votre compte a été créé mais le profil n'a pas pu être enregistré.")
                st.info("🔧 Veuillez contacter le support avec ce message d'erreur :")
                st.code(str(e))
        
        return insertion_success

    except Exception as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg:
            st.error("⏱️ Trop de tentatives. Veuillez patienter 60 secondes.")
            st.info("💡 Si vous avez déjà un compte, utilisez l'onglet Connexion.")
        elif "already registered" in error_msg or "already exists" in error_msg:
            st.error("❌ Cette adresse courriel est déjà utilisée. Veuillez vous connecter.")
        elif "invalid email" in error_msg:
            st.error("❌ L'adresse courriel est invalide")
        elif "password" in error_msg:
            st.error("❌ Le mot de passe ne respecte pas les critères requis")
        elif "row-level security" in error_msg or "policy" in error_msg:
            st.error("❌ Erreur de permissions de la base de données")
            st.info("💡 Contactez l'administrateur pour corriger les policies RLS")
        else:
            st.error(f"❌ Erreur lors de l'inscription : {str(e)}")
        return False


def login_user(email, password):
    """Connexion d'un utilisateur"""
    try:
        if not email or not password:
            st.error("❌ Veuillez entrer votre courriel et mot de passe")
            return False
        
        session = supabase.auth.sign_in_with_password({"email": email, "password": password})
        
        if not session or not session.session or not session.session.access_token:
            st.error("❌ Erreur de connexion. Veuillez vérifier vos identifiants.")
            return False
        
        st.session_state.access_token = session.session.access_token
        apply_supabase_auth()

        result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
        
        if result.data and len(result.data) > 0:
            st.session_state.user = result.data[0]
            st.session_state.logged_in = True
            st.session_state.profile_completed = bool(st.session_state.user.get('logo_url'))
            if 'active_tab' not in st.session_state:
                st.session_state.active_tab = 0
            return True
        else:
            st.error("❌ Impossible de récupérer les informations de votre profil")
            return False
            
    except Exception as e:
        error_msg = str(e).lower()
        if "email not confirmed" in error_msg or "email_not_confirmed" in error_msg:
            st.error("📧 Votre courriel n'a pas encore été validé. Veuillez cliquer sur le lien dans le courriel de confirmation que nous vous avons envoyé. Pensez à vérifier dans vos courriels indésirables (spam).")
        elif "invalid login" in error_msg or "invalid credentials" in error_msg:
            st.error("❌ Courriel ou mot de passe incorrect")
        elif "too many requests" in error_msg or "rate limit" in error_msg:
            st.error("⏱️ Trop de tentatives de connexion. Veuillez patienter quelques minutes.")
        else:
            st.error(f"❌ Erreur de connexion : {str(e)}")
        return False


def get_user_by_email(email):
    """Récupère un utilisateur par son email"""
    try:
        result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
        return result.data[0] if result.data and len(result.data) > 0 else None
    except Exception as e:
        st.warning(f"⚠️ Erreur lors de la vérification du courriel : {str(e)}")
        return None


def add_projet_antecedent(projet_data):
    """Ajoute un projet antérieur"""
    try:
        apply_supabase_auth()
        
        if not projet_data.get("nom_projet"):
            st.error("❌ Le nom du projet est obligatoire")
            return False
        
        data = {
            "entreprise_id": st.session_state.user['id'],
            "nom_projet": projet_data["nom_projet"],
            "montant": projet_data.get("montant", 0),
            "duree_jours": projet_data.get("duree_jours", 0),
            "specifications": projet_data.get("specifications", "")
        }
        
        if projet_data.get("document"):
            try:
                from storage import upload_document_projet
                doc_url = upload_document_projet(supabase, projet_data["document"], st.session_state.user['id'])
                if doc_url:
                    data["document_url"] = doc_url
            except ImportError:
                st.warning("⚠️ Module storage non disponible. Le document ne sera pas uploadé.")
            except Exception as e:
                st.warning(f"⚠️ Erreur lors de l'upload du document : {str(e)}")
        
        result = supabase.table('projets_antecedents').insert(data).execute()
        
        if result.data and len(result.data) > 0:
            st.success("✅ Projet ajouté avec succès")
            return True
        else:
            st.error("❌ Erreur lors de l'ajout du projet")
            return False
            
    except Exception as e:
        st.error(f"❌ Erreur lors de l'ajout du projet : {str(e)}")
        return False


def save_soumission(entreprise_id, soumission_data):
    """Sauvegarde une analyse de soumission"""
    try:
        apply_supabase_auth()
        
        data_to_save = {
            "entreprise_id": entreprise_id,
            "numero_projet": soumission_data.get("numero_projet", ""),
            "nom_projet": soumission_data.get("nom_projet", ""),
            "analyse_json": soumission_data.get("analyse_json", {}),
            "recommendation": soumission_data.get("recommendation", "INCONNU"),
            "score": soumission_data.get("score", 0),
            "statut": soumission_data.get("statut", "en_attente")
        }
        
        if soumission_data.get("document"):
            try:
                from storage import upload_soumission
                doc_url = upload_soumission(supabase, soumission_data["document"], entreprise_id)
                if doc_url:
                    data_to_save["document_url"] = doc_url
            except ImportError:
                pass
            except Exception as e:
                st.warning(f"⚠️ Document non uploadé : {str(e)}")
        
        result = supabase.table('soumissions').insert(data_to_save).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        else:
            return None
            
    except Exception as e:
        st.error(f"❌ Erreur lors de la sauvegarde : {str(e)}")
        return None