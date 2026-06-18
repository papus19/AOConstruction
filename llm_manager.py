"""
Gestion des fournisseurs LLM — Version 3.0
Ordre de priorité : Gemini → Groq → Mistral → OpenRouter → Cohere → OpenAI
Tous gratuits (sauf OpenAI — dernier recours)
Gestion explicite 429 avec fallback automatique silencieux
"""
import requests
import config


class LLMManager:
    def __init__(self):
        self.providers      = []
        self._dernier_actif = None
        self._init_providers()

    def _init_providers(self):
    
        # 2️⃣ Groq — 14 400 req/jour, ultra-rapide
        if getattr(config, "GROQ_API_KEY", None):
            self.providers.append({
                "name":    "Groq LLaMA 3.3 70B",
                "api_key": config.GROQ_API_KEY,
                "type":    "groq",
                "url":     "https://api.groq.com/openai/v1/chat/completions",
                "model":   "llama-3.3-70b-versatile"
            })

        # 1️⃣ Gemini (Google AI Studio) — ~1000 req/jour, contexte 1M tokens
        if getattr(config, "GEMINI_API_KEY", None):
            try:
                import google.generativeai as genai
                genai.configure(api_key=config.GEMINI_API_KEY)
                model = genai.GenerativeModel("gemini-2.0-flash-exp")
                self.providers.append({
                    "name":   "Gemini 2.0 Flash",
                    "client": model,
                    "type":   "gemini"
                })
            except Exception as e:
                print(f"[LLM] Gemini non disponible : {str(e)[:100]}")

        # 3️⃣ Mistral — 1 milliard tokens/mois, fort en français
        if getattr(config, "MISTRAL_API_KEY", None):
            self.providers.append({
                "name":    "Mistral Small",
                "api_key": config.MISTRAL_API_KEY,
                "type":    "openai_compat",
                "url":     "https://api.mistral.ai/v1/chat/completions",
                "model":   "mistral-small-latest"
            })

        # 4️⃣ OpenRouter — 50 req/jour, 24+ modèles gratuits (filet de sécurité)
        if getattr(config, "OPENROUTER_API_KEY", None):
            self.providers.append({
                "name":    "OpenRouter (DeepSeek R1)",
                "api_key": config.OPENROUTER_API_KEY,
                "type":    "openai_compat",
                "url":     "https://openrouter.ai/api/v1/chat/completions",
                "model":   "deepseek/deepseek-r1:free",
                "headers_extra": {
                    "HTTP-Referer": "https://electrique-inno.ca",
                    "X-Title":      "Analyseur AO Électrique Inno"
                }
            })

        # 5️⃣ Cohere — 1000 req/mois, excellent en français
        if getattr(config, "COHERE_API_KEY", None):
            self.providers.append({
                "name":    "Cohere Command R+",
                "api_key": config.COHERE_API_KEY,
                "type":    "cohere",
                "url":     "https://api.cohere.com/v2/chat",
                "model":   "command-r-plus-08-2024"
            })

        # 6️⃣ OpenAI — Dernier recours (payant)
        if getattr(config, "OPENAI_API_KEY", None):
            self.providers.append({
                "name":    "OpenAI GPT-4o",
                "api_key": config.OPENAI_API_KEY,
                "type":    "openai_compat",
                "url":     "https://api.openai.com/v1/chat/completions",
                "model":   "gpt-4o"
            })

        if not self.providers:
            print("⚠️  Aucun provider LLM configuré — vérifiez vos clés API dans .env")
        else:
            noms = [p["name"] for p in self.providers]
            print(f"[LLM] Providers actifs ({len(noms)}) : {' → '.join(noms)}")

    # ─────────────────────────────────────────────────────────────
    # Méthode principale
    # ─────────────────────────────────────────────────────────────
    def analyze(self, prompt: str, max_tokens: int = 2000) -> dict:
        errors = []

        for provider in self.providers:
            try:
                result = self._call_provider(provider, prompt, max_tokens)
                if result is not None:
                    self._dernier_actif = provider["name"]
                    return {
                        "success":  True,
                        "result":   result,
                        "provider": provider["name"],
                        "error":    None
                    }

            except _QuotaError as e:
                errors.append(f"{provider['name']} : quota dépassé (429)")
                continue
            except _TimeoutError:
                errors.append(f"{provider['name']} : délai dépassé")
                continue
            except _ConnectionError:
                errors.append(f"{provider['name']} : connexion impossible")
                continue
            except Exception as e:
                msg = str(e)
                if "429" in msg or "quota" in msg.lower() or "rate" in msg.lower():
                    errors.append(f"{provider['name']} : quota dépassé")
                else:
                    errors.append(f"{provider['name']} : {msg[:80]}")
                continue

        # ── Tous les providers ont échoué ─────────────────────────
        tous_quota = errors and all(
            "quota" in e.lower() or "429" in e for e in errors
        )
        if tous_quota:
            msg_final = (
                "⚠️ Tous les services IA ont atteint leur limite de requêtes. "
                "Attendez quelques minutes ou ajoutez vos clés API dans le fichier .env\n"
                f"Détail : {' | '.join(errors)}"
            )
        elif errors:
            msg_final = (
                f"❌ Tous les services IA sont indisponibles.\n"
                f"Détail : {' | '.join(errors)}"
            )
        else:
            msg_final = "❌ Aucun provider LLM configuré."

        return {"success": False, "result": None, "provider": None, "error": msg_final}

    # ─────────────────────────────────────────────────────────────
    # Dispatcher par type de provider
    # ─────────────────────────────────────────────────────────────
    def _call_provider(self, provider: dict, prompt: str, max_tokens: int):
        ptype = provider["type"]

        if ptype == "gemini":
            return self._call_gemini(provider, prompt, max_tokens)
        elif ptype == "groq":
            return self._call_openai_compat(provider, prompt, max_tokens)
        elif ptype == "openai_compat":
            return self._call_openai_compat(provider, prompt, max_tokens)
        elif ptype == "cohere":
            return self._call_cohere(provider, prompt, max_tokens)
        else:
            raise Exception(f"Type inconnu : {ptype}")

    # ─────────────────────────────────────────────────────────────
    # Gemini (SDK Python)
    # ─────────────────────────────────────────────────────────────
    def _call_gemini(self, provider, prompt, max_tokens):
        try:
            response = provider["client"].generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": 0.3
                }
            )
            return response.text
        except Exception as e:
            msg = str(e)
            if "429" in msg or "quota" in msg.lower() or "exhausted" in msg.lower():
                raise _QuotaError(msg)
            raise

    # ─────────────────────────────────────────────────────────────
    # Format OpenAI-compatible (Groq, Mistral, OpenRouter, OpenAI)
    # ─────────────────────────────────────────────────────────────
    def _call_openai_compat(self, provider, prompt, max_tokens):
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type":  "application/json"
        }
        # Headers additionnels (ex: OpenRouter)
        if provider.get("headers_extra"):
            headers.update(provider["headers_extra"])

        try:
            resp = requests.post(
                provider["url"],
                headers=headers,
                json={
                    "model":       provider["model"],
                    "messages":    [{"role": "user", "content": prompt}],
                    "max_tokens":  max_tokens,
                    "temperature": 0.3
                },
                timeout=45
            )
        except requests.exceptions.Timeout:
            raise _TimeoutError()
        except requests.exceptions.ConnectionError:
            raise _ConnectionError()

        if resp.status_code == 429:
            raise _QuotaError(f"HTTP 429 — {resp.text[:100]}")

        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # ─────────────────────────────────────────────────────────────
    # Cohere (API v2 — format différent)
    # ─────────────────────────────────────────────────────────────
    def _call_cohere(self, provider, prompt, max_tokens):
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type":  "application/json"
        }
        try:
            resp = requests.post(
                provider["url"],
                headers=headers,
                json={
                    "model":       provider["model"],
                    "messages":    [{"role": "user", "content": prompt}],
                    "max_tokens":  max_tokens,
                    "temperature": 0.3
                },
                timeout=45
            )
        except requests.exceptions.Timeout:
            raise _TimeoutError()
        except requests.exceptions.ConnectionError:
            raise _ConnectionError()

        if resp.status_code == 429:
            raise _QuotaError(f"HTTP 429 — {resp.text[:100]}")

        resp.raise_for_status()
        data = resp.json()
        # Cohere v2 : message.content[0].text
        try:
            return data["message"]["content"][0]["text"]
        except (KeyError, IndexError):
            # Fallback si structure différente
            return data.get("text") or str(data)

    # ─────────────────────────────────────────────────────────────
    # Utilitaires
    # ─────────────────────────────────────────────────────────────
    def provider_actif(self) -> str:
        """Retourne le nom du dernier provider ayant répondu avec succès."""
        if self._dernier_actif:
            return self._dernier_actif
        return self.providers[0]["name"] if self.providers else "Aucun configuré"

    def liste_providers(self) -> list:
        """Retourne la liste des providers configurés avec leur ordre."""
        return [
            {"ordre": i + 1, "nom": p["name"], "type": p["type"]}
            for i, p in enumerate(self.providers)
        ]

    def statut_providers(self) -> str:
        """Résumé lisible de l'état des providers pour affichage UI."""
        if not self.providers:
            return "⚠️ Aucun provider configuré"
        lignes = [f"{i+1}. {p['name']}" for i, p in enumerate(self.providers)]
        actif = f"\n✅ Dernier utilisé : **{self._dernier_actif}**" if self._dernier_actif else ""
        return "\n".join(lignes) + actif


# ─────────────────────────────────────────────────────────────────
# Exceptions internes
# ─────────────────────────────────────────────────────────────────
class _QuotaError(Exception):
    pass

class _TimeoutError(Exception):
    pass

class _ConnectionError(Exception):
    pass