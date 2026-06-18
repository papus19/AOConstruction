"""
Composants UI réutilisables
"""
import streamlit as st
import config


def display_header():
    """Affiche l'en-tête de l'application"""
    st.markdown(config.CUSTOM_CSS, unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 20])
    with col1:
        try:
            st.image(config.MOKAFAD_LOGO_URL, width=48)
        except:
            st.markdown("⚡", unsafe_allow_html=True)
    with col2:
        st.markdown(
            '<h1 style="color: #104E8B; font-weight: 700; margin-top: 10px;">MOKAFAD - Solution Soumission IA</h1>',
            unsafe_allow_html=True
        )


def display_logo_sidebar(user):
    """Affiche le logo de l'entreprise dans la sidebar"""
    # Logo MOKAFAD
    try:
        st.image(config.MOKAFAD_LOGO_URL, width=80)
    except:
        st.markdown("⚡ **MOKAFAD**", unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Logo de l'entreprise
    logo_url = user.get('logo_url')
    
    if logo_url:
        try:
            # Vérifier si c'est une URL ou du base64
            if logo_url.startswith('http'):
                st.image(logo_url, width=150, caption="Logo entreprise")
            else:
                # C'est du base64, afficher avec markdown
                st.markdown(
                    f'<div style="text-align: center;"><img src="data:image/png;base64,{logo_url}" width="150" style="border-radius: 8px;"></div>',
                    unsafe_allow_html=True
                )
        except Exception as e:
            st.error(f"❌ Erreur affichage: {str(e)}")
            st.markdown("🏢", unsafe_allow_html=True)
    else:
        st.info("📷 Aucun logo enregistré")