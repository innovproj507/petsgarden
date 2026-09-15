# agent/brain.py — Cerebro del agente: arma el contexto y llama a la IA
# Generado por AgentKit

"""
Logica de IA del agente. Lee el system prompt de config/prompts.yaml y genera las
respuestas usando el proveedor de IA configurado en .env (Claude o Gemini, ver
agent/ai_providers/). brain.py no sabe ni le importa cual de los dos esta activo.
"""

import logging

import yaml
from dotenv import load_dotenv

from agent.ai_providers import obtener_proveedor_ia

load_dotenv()
logger = logging.getLogger("agentkit")

# Se resuelve una sola vez al importar el modulo, igual que el proveedor de WhatsApp
# en main.py. Si AI_PROVIDER trae un valor invalido, no morimos en el import: se
# guarda el error y generar_respuesta() lo reporta como el aviso tecnico de siempre,
# en vez de tumbar el arranque del servidor por una variable mal escrita.
proveedor_ia = None
error_configuracion_ia: str | None = None
try:
    proveedor_ia = obtener_proveedor_ia()
except Exception as e:  # noqa: BLE001
    error_configuracion_ia = str(e)
    logger.error(f"Proveedor de IA no configurado: {error_configuracion_ia}")


def cargar_config_prompts() -> dict:
    """Lee toda la configuracion desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_system_prompt() -> str:
    """El system prompt: quien es el agente y que sabe del negocio."""
    return cargar_config_prompts().get(
        "system_prompt", "Eres un asistente util. Responde siempre en espanol."
    )


def obtener_mensaje_error() -> str:
    """Que decirle al cliente cuando algo falla de nuestro lado."""
    return cargar_config_prompts().get(
        "error_message",
        "Lo siento, estoy teniendo problemas tecnicos. Por favor intenta de nuevo en unos minutos.",
    )


def obtener_mensaje_fallback() -> str:
    """Que decirle al cliente cuando no se entendio el mensaje."""
    return cargar_config_prompts().get(
        "fallback_message", "Disculpa, no entendi tu mensaje. Podrias reformularlo?"
    )


async def generar_respuesta(mensaje: str, historial: list[dict]) -> tuple[str, bool]:
    """
    Genera una respuesta con el proveedor de IA configurado (Claude o Gemini).

    Args:
        mensaje: el mensaje nuevo del cliente
        historial: los mensajes anteriores, [{"role": "user"|"assistant", "content": "..."}]

    Returns:
        (texto, es_respuesta_real)

        "es_respuesta_real" es False cuando lo que se devuelve es un aviso tecnico
        (error o fallback) y no una respuesta del agente. main.py lo usa para no
        guardar esos avisos en el historial: si se guardaran, quedarian contaminando
        el contexto de todos los mensajes siguientes.
    """
    if proveedor_ia is None:
        logger.error(f"No se puede responder: {error_configuracion_ia}")
        return obtener_mensaje_error(), False

    # Solo se descarta un mensaje realmente vacio. Un umbral mas alto (como "menos de
    # 2 caracteres") rechazaria respuestas validas de una sola tecla — "1", "2", "si" —
    # justo lo que un cliente escribe para elegir una opcion de un menu numerado.
    if not mensaje or not mensaje.strip():
        return obtener_mensaje_fallback(), False

    mensajes = [{"role": m["role"], "content": m["content"]} for m in historial]
    mensajes.append({"role": "user", "content": mensaje})

    system_prompt = cargar_system_prompt()
    texto, info = await proveedor_ia.generar(system_prompt, mensajes)

    if info.get("error"):
        return obtener_mensaje_error(), False

    if info.get("cortado"):
        logger.warning(
            "La respuesta se corto por llegar al tope de tokens. Si pasa seguido, sube "
            "el tope configurado (ANTHROPIC_MAX_TOKENS o GEMINI_MAX_TOKENS segun el "
            "proveedor activo) o acorta el system prompt."
        )

    if not texto:
        logger.warning("El proveedor de IA devolvio una respuesta sin texto")
        return obtener_mensaje_fallback(), False

    logger.info(
        f"Respuesta generada ({info.get('input_tokens', 0)} in / "
        f"{info.get('output_tokens', 0)} out)"
    )
    return texto, True
