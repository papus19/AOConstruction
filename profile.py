"""
Gestion du profil utilisateur
"""
import streamlit as st
import forms
import database
from storage import upload_logo, delete_logo


def show_profile_completion():
    """Affiche le formulaire de complétion du profil"""
    st.warning("⚠️ Veuillez compléter votre profil pour continuer")
    
    try:
        profile_data = forms.profile_completion_form(st.session_state.user)
        
        if profile_data:
            database.apply_supabase_auth()
            
            logo_updated = False
            if profile_data.get("logo_file"):
                try:
                    logo_url = upload_logo(
                        database.supabase, 
                        profile_data["logo_file"], 
                        st.session_state.user['id']
                    )
                    
                    if logo_url:
                        database.supabase.table('entreprises').update({
                            "logo_url": logo_url
                        }).eq('id', st.session_state.user['id']).execute()
                        
                        user_updated = database.supabase.table('entreprises').select("*").eq(
                            'id', st.session_state.user['id']
                        ).execute()
                        
                        if user_updated.data and len(user_updated.data) > 0:
                            st.session_state.user = user_updated.data[0]
                            logo_updated = True
                            st.success("✅ Logo uploadé avec succès !")
                    else:
                        st.warning("⚠️ L'upload du logo a échoué")
                        
                except Exception as e:
                    st.error(f"❌ Erreur lors de l'enregistrement du logo : {str(e)}")
            
            if profile_data.get("projets"):
                projets_added = 0
                for projet in profile_data["projets"]:
                    if database.add_projet_antecedent(projet):
                        projets_added += 1
                if projets_added > 0:
                    st.success(f"✅ {projets_added} projet(s) ajouté(s) avec succès !")
            
            st.session_state.profile_completed = True
            st.session_state.default_tab = 0
            st.success("✅ Profil complété ! Redirection vers le tableau de bord...")
            import time
            time.sleep(1.5)
            st.rerun()
            
    except Exception as e:
        st.error(f"❌ Erreur lors de la complétion du profil : {str(e)}")


def show_profile_tab(user):
    """Affiche l'onglet Mon profil"""
    st.header("👤 Vos informations")
    
    st.subheader("Entreprise")
    st.write(f"**Nom :** {user.get('nom_entreprise', 'N/A')}")
    st.write(f"**NEQ :** {user.get('numero_neq', 'N/A')}")
    st.write(f"**Licence RBQ :** {user.get('licence_rbq', 'N/A')}")
    st.write(f"**Spécialités :** {', '.join(user.get('specialites', [])) if user.get('specialites') else 'Aucune'}")
    st.write(f"**Adresse :** {user.get('adresse', '')}, {user.get('ville', '')}, {user.get('province', '')} {user.get('code_postal', '')}")
    
    st.subheader("Contact")
    st.write(f"**Nom :** {user.get('contact_nom', 'N/A')}")
    st.write(f"**Téléphone :** {user.get('contact_telephone', 'N/A')}")
    st.write(f"**Courriel :** {user.get('contact_email', 'N/A')}")
    
    st.subheader("Logo de l'entreprise")
    
    col_logo, col_upload = st.columns([1, 1])
    
    with col_logo:
        logo_url = user.get('logo_url')
        
        if logo_url:
            try:
                # Vérifier si c'est une URL ou du base64
                if logo_url.startswith('http'):
                    st.image(logo_url, width=200, caption="Logo actuel")
                else:
                    # C'est du base64
                    st.markdown(
                        f'<img src="data:image/png;base64,{logo_url}" width="200" style="border-radius: 8px; border: 2px solid #1E90FF;">',
                        unsafe_allow_html=True
                    )
                    st.caption("✅ Logo actuel")
            except Exception as e:
                st.error(f"❌ Erreur: {str(e)}")
        else:
            st.info("📷 Aucun logo enregistré")
    
    with col_upload:
        with st.form("update_logo_form"):
            st.write("**Remplacer le logo**")
            new_logo = st.file_uploader(
                "Choisir un nouveau logo",
                type=['png', 'jpg', 'jpeg'],
                help="Formats acceptés: PNG, JPG, JPEG (max 2MB)"
            )
            submit_logo = st.form_submit_button("📤 Uploader le nouveau logo")
            
            if submit_logo and new_logo:
                try:
                    if new_logo.size > 2 * 1024 * 1024:
                        st.error("❌ Le logo doit faire moins de 2 MB")
                    else:
                        database.apply_supabase_auth()
                        
                        if user.get('logo_url'):
                            delete_logo(database.supabase, user['logo_url'])
                        
                        logo_url = upload_logo(database.supabase, new_logo, user['id'])
                        
                        if logo_url:
                            result = database.supabase.table('entreprises').update({
                                "logo_url": logo_url
                            }).eq('id', user['id']).execute()
                            
                            if result.data and len(result.data) > 0:
                                user_updated = database.supabase.table('entreprises').select("*").eq(
                                    'id', user['id']
                                ).execute()
                                
                                if user_updated.data and len(user_updated.data) > 0:
                                    st.session_state.user = user_updated.data[0]
                                    st.success("✅ Logo remplacé avec succès !")
                                    st.info("🔄 Rechargement de la page pour afficher le nouveau logo...")
                                    import time
                                    time.sleep(1)
                                    st.rerun()
                            else:
                                st.error("❌ Erreur lors du remplacement du logo")
                        else:
                            st.error("❌ Erreur lors de l'upload du logo")
                            
                except Exception as e:
                    st.error(f"❌ Erreur lors de l'upload : {str(e)}")
            elif submit_logo and not new_logo:
                st.warning("⚠️ Veuillez sélectionner un fichier")
    
    st.markdown("---")
    
    if st.button("✏️ Modifier le profil complet"):
        st.session_state.profile_completed = False
        st.rerun()