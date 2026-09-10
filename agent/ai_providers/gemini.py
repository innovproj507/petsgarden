# agent/ai_providers/gemini.py — Adaptador de IA: Google Gemini
# Generado por AgentKit

"""
Conexion con la API de Gemini via el SDK oficial (google-genai).
Documentacion: https://ai.google.dev/gemini-api/docs
"""

import logging
import os

from google import genai
from google.genai import types

from agent.ai_providers.base import ProveedorIA

logger = logging.getLogger("agentkit")

# El modelo se cambia desde .env, sin tocar el codigo. Ver CLAUDE.md 2.1 para precios
# actualizados: cambian seguido, confirma en ai.google.dev/pricing antes de repetirle
# una cifra vieja al usuario.
MODELO = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash"

# Mismo criterio que con Claude: el tope cubre tambien el razonamiento interno del
# modelo, no solo el texto visible de la respuesta.
MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS") or "4096")


class ProveedorGemini(ProveedorIA):
    """Proveedor de IA usando la API de Google Gemini."""

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            logger.warning("GEMINI_API_KEY no esta configurada: el agente no va a poder responder")
        self.client = genai.Client(api_key=api_key)

    def _a_contenidos(self, mensajes: list[dict]) -> list["types.Content"]:
        """
        Gemini no usa "assistant" como Claude: sus turnos del modelo son "model".
        El historial llega en formato Claude (user/assistant) porque memory.py es
        el mismo archivo sin importar que proveedor de IA este activo.
        """
        return [
            types.Content(
                role=("model" if m["role"] == "assistant" else "user"),
                parts=[types.Part(text=m["content"])],
            )
            for m in mensajes
        ]

    async def generar(self, system_prompt: str, mensajes: list[dict]) -> tuple[str, dict]:
        """Genera una respuesta con Gemini. Ver ProveedorIA.generar para el contrato."""
        try:
            respuesta = await self.client.aio.models.generate_content(
                model=MODELO,
                contents=self._a_contenidos(mensajes),
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=MAX_TOKENS,
                ),
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error llamando a Gemini: {e}")
            return "", {"error": True}

        texto = (respuesta.text or "").strip()
        uso = respuesta.usage_metadata
        candidato = respuesta.candidates[0] if respuesta.candidates else None

        return texto, {
            "error": False,
            "cortado": bool(candidato and str(candidato.finish_reason) == "MAX_TOKENS"),
            "input_tokens": getattr(uso, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(uso, "candidates_token_count", 0) or 0,
        }
