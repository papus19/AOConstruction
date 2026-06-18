"""
Configuration de l'application MOKAFAD
"""
import os
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration Supabase
SUPABASE_URL              = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY         = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Configuration LLM — ordre de priorité : Gemini → Groq → Mistral → OpenRouter → Cohere → OpenAI
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
MISTRAL_API_KEY     = os.getenv("MISTRAL_API_KEY")
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")
COHERE_API_KEY      = os.getenv("COHERE_API_KEY")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")

# URLs
MOKAFAD_LOGO_URL = "https://unhbihdenqzokxiednos.supabase.co/storage/v1/object/public/logos/logo-mokafad.png"

# Style CSS
CUSTOM_CSS = """
<style>
    [data-testid="stAppViewContainer"] {
        background-color: #F0F8FF;
    }
    [data-testid="stSidebar"] {
        background-color: white;
        border-right: 2px solid #B0E0E6;
    }
    .stButton>button {
        background-color: #1E90FF !important;
        color: white !important;
        border-radius: 8px !important;
        padding: 0.6rem 1.8rem !important;
        font-weight: 600 !important;
        width: auto !important;
        margin: 0.5rem auto !important;
        display: block !important;
        box-shadow: 0 2px 4px rgba(30, 144, 255, 0.3) !important;
    }
    .stButton>button:hover {
        background-color: #104E8B !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(30, 144, 255, 0.4) !important;
    }
    .stTabs [data-baseweb="tab"] {
        color: #104E8B !important;
        font-weight: 600 !important;
    }
    .stTabs [aria-selected="true"] {
        color: white !important;
        background-color: #1E90FF !important;
        border-radius: 8px 8px 0 0 !important;
    }
    h1, h2, h3 {
        color: #104E8B !important;
    }
    div[data-testid="stMetricValue"] {
        color: #104E8B !important;
    }
</style>
"""