# agent/ai_providers/base.py — Clase base para proveedores de IA
# Generado por AgentKit

"""
Define la interfaz comun que todo proveedor de IA implementa. Gracias a esto,
brain.py no sabe ni le importa si esta hablando con Claude o con Gemini.
"""

from abc import ABC, abstractmethod


class ProveedorIA(ABC):
    """Interfaz que cada proveedor de IA debe implementar."""

    @abstractmethod
    async def generar(self, system_prompt: str, mensajes: list[dict]) -> tuple[str, dict]:
        """
        Genera una respuesta.

        Args:
            system_prompt: quien es el agente y que sabe del negocio
            mensajes: [{"role": "user"|"assistant", "content": "..."}] — este formato
                      es el mismo sin importar el proveedor de IA activo, porque
                      memory.py no cambia. Cada adaptador lo traduce si su API usa
                      otros nombres de rol (Gemini, por ejemplo, usa "model").

        Returns:
            (texto, info) — info trae al menos:
                "error": bool          True si la llamada fallo del todo
                "cortado": bool        True si se corto por el tope de tokens
                "input_tokens": int
                "output_tokens": int
            Si "error" es True, "texto" viene vacio y brain.py decide que mostrar.
        """
        ...
