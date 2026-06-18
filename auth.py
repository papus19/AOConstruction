"""
Gestion de l'authentification
"""
import streamlit as st
import forms
import database


def show_login_page():
    """Affiche la page de connexion"""
    with st.form("login_form"):
        email = st.text_input("📧 Courriel")
        password = st.text_input("🔒 Mot de passe", type="password")
        submit = st.form_submit_button("➡️ Se connecter", use_container_width=False)
        
        if submit:
            if database.login_user(email, password):
                st.success("✅ Connexion réussie !")
                st.rerun()


def show_signup_page():
    """Affiche la page d'inscription"""
    signup_data = forms.signup_form()
    
    if signup_data:
        if not signup_data.get("numero_neq") or not signup_data.get("licence_rbq"):
            st.error("❌ Le NEQ et la licence RBQ sont obligatoires pour créer un compte")
        elif database.get_user_by_email(signup_data["contact_email"]):
            st.error("❌ Cette adresse courriel est déjà utilisée")
        elif database.signup_user(signup_data):
            st.session_state.pop('signup_data', None)
            st.success("✅ Votre compte a été créé avec succès !")
            st.success("📧 Un courriel de validation a été envoyé à **{}**".format(signup_data["contact_email"]))
            st.warning("⚠️ Pensez à vérifier dans vos courriels indésirables (spam)")
            
            if st.button("🔐 Se connecter maintenant"):
                st.rerun()
