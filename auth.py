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

    # Bouton mot de passe oublié hors du formulaire
    st.markdown("---")
    if st.button("🔑 Mot de passe oublié ?", use_container_width=False):
        st.session_state.page = "reset_password"
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


def show_reset_password_page():
    """Page pour demander un lien de réinitialisation de mot de passe"""
    st.subheader("🔑 Mot de passe oublié")
    st.write("Entrez votre courriel et nous vous enverrons un lien pour réinitialiser votre mot de passe.")

    with st.form("reset_form"):
        email = st.text_input("📧 Votre courriel")
        submit = st.form_submit_button("📨 Envoyer le lien", use_container_width=False)

        if submit:
            if not email or "@" not in email:
                st.error("❌ Veuillez entrer une adresse courriel valide")
            else:
                try:
                    database.supabase.auth.reset_password_email(
                        email,
                        options={"redirect_to": "https://aoconstruction.streamlit.app"}
                    )
                    st.success("✅ Un lien de réinitialisation a été envoyé à **{}**".format(email))
                    st.info("💡 Vérifiez aussi vos courriels indésirables (spam)")
                except Exception as e:
                    st.error(f"❌ Erreur lors de l'envoi : {str(e)}")

    st.markdown("---")
    if st.button("⬅️ Retour à la connexion"):
        st.session_state.page = "login"
        st.rerun()


def show_new_password_page():
    """Page pour entrer le nouveau mot de passe après le lien de reset"""
    st.subheader("🔒 Créer un nouveau mot de passe")

    with st.form("new_password_form"):
        new_password = st.text_input("🔒 Nouveau mot de passe", type="password")
        confirm_password = st.text_input("🔒 Confirmer le mot de passe", type="password")
        submit = st.form_submit_button("✅ Changer le mot de passe", use_container_width=False)

        if submit:
            if not new_password or not confirm_password:
                st.error("❌ Veuillez remplir les deux champs")
            elif new_password != confirm_password:
                st.error("❌ Les mots de passe ne correspondent pas")
            elif len(new_password) < 6:
                st.error("❌ Le mot de passe doit contenir au moins 6 caractères")
            else:
                try:
                    database.supabase.auth.update_user({"password": new_password})
                    st.success("✅ Mot de passe changé avec succès !")
                    st.session_state.page = "login"
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erreur : {str(e)}")

    st.markdown("---")
    if st.button("⬅️ Retour à la connexion"):
        st.session_state.page = "login"
        st.rerun()
