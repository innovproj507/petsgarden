# agent/ai_providers/__init__.py — Factory de proveedores de IA
# Generado por AgentKit

"""
Elige el proveedor de IA segun la variable AI_PROVIDER del .env.
"""

import os

from agent.ai_providers.base import ProveedorIA

PROVEEDORES_IA_SOPORTADOS = ("anthropic", "gemini")


def obtener_proveedor_ia() -> ProveedorIA:
    """
    Retorna el proveedor de IA configurado en .env. Default: anthropic.

    A diferencia de obtener_proveedor() (WhatsApp), acá SÍ hay un default: el agente
    no puede funcionar sin IA, y "anthropic" es la opcion con la que este sistema esta
    mas probado. Si AI_PROVIDER trae un valor que no reconocemos, ahí sí se rechaza.
    """
    proveedor = os.getenv("AI_PROVIDER", "").strip().lower() or "anthropic"

    if proveedor == "anthropic":
        from agent.ai_providers.anthropic import ProveedorAnthropic

        return ProveedorAnthropic()

    if proveedor == "gemini":
        from agent.ai_providers.gemini import ProveedorGemini

        return ProveedorGemini()

    raise ValueError(
        f"Proveedor de IA no soportado: '{proveedor}'. "
        f"Valores validos: {' | '.join(PROVEEDORES_IA_SOPORTADOS)}"
    )


__all__ = ["ProveedorIA", "PROVEEDORES_IA_SOPORTADOS", "obtener_proveedor_ia"]
