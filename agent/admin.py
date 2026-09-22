# agent/admin.py — Panel simple para que el equipo vea y responda conversaciones
# Generado por AgentKit

"""
Meta Cloud API directo (a diferencia de Zernio) no trae ninguna bandeja de mensajes
para humanos. Este panel es lo que la reemplaza: lee el historial que ya guarda
memory.py y deja responder manualmente, pausando al bot para esa conversacion
mientras alguien del equipo la atiende.

Protegido con usuario/contraseña (HTTP Basic Auth) via ADMIN_USER / ADMIN_PASSWORD
en el .env. No es un sistema de usuarios — para un negocio chico con un par de
personas atendiendo, alcanza con una sola credencial compartida.
"""

import os
import secrets
from html import escape

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from agent.memory import (
    esta_pausado,
    guardar_mensaje,
    listar_conversaciones,
    obtener_historial,
    pausar_conversacion,
    reanudar_conversacion,
)
from agent.providers import obtener_proveedor

router = APIRouter(prefix="/admin")
seguridad = HTTPBasic()

ADMIN_USER = os.getenv("ADMIN_USER", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def _verificar(credenciales: HTTPBasicCredentials = Depends(seguridad)) -> str:
    """
    Compara usuario y contraseña con secrets.compare_digest (a prueba de timing
    attacks) — mismo criterio que las firmas de webhook en providers/.
    """
    if not ADMIN_USER or not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_USER / ADMIN_PASSWORD no configurados en el .env",
        )
    usuario_ok = secrets.compare_digest(credenciales.username, ADMIN_USER)
    clave_ok = secrets.compare_digest(credenciales.password, ADMIN_PASSWORD)
    if not (usuario_ok and clave_ok):
        raise HTTPException(
            status_code=401,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credenciales.username


ESTILO = """
<style>
  body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }
  a { color: #0a7d3c; text-decoration: none; }
  .conversacion { display: block; padding: 0.75rem; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 0.5rem; }
  .conversacion:hover { background: #f7f7f7; }
  .pausado { color: #b45309; font-weight: 600; }
  .mensaje { padding: 0.5rem 0.75rem; border-radius: 8px; margin-bottom: 0.5rem; max-width: 80%; white-space: pre-wrap; }
  .mensaje.user { background: #e5e7eb; }
  .mensaje.assistant { background: #d1fae5; margin-left: auto; }
  form { margin-top: 1rem; }
  textarea { width: 100%; padding: 0.5rem; box-sizing: border-box; font-family: inherit; }
  button { padding: 0.5rem 1rem; margin-top: 0.5rem; cursor: pointer; }
</style>
"""


@router.get("/", response_class=HTMLResponse)
async def panel(usuario: str = Depends(_verificar)) -> str:
    """Lista de conversaciones, la mas reciente primero."""
    conversaciones = await listar_conversaciones()

    if not conversaciones:
        filas = "<p>Todavía no hay conversaciones.</p>"
    else:
        filas = ""
        for c in conversaciones:
            marca = (
                ' <span class="pausado">⏸ atendida por una persona</span>'
                if c["pausado"]
                else ""
            )
            vista_previa = escape(c["ultimo_mensaje"][:80])
            filas += f"""
            <a class="conversacion" href="/admin/chat/{escape(c['telefono'])}">
              <b>{escape(c['telefono'])}</b>{marca}<br>
              <span style="color:#666">{vista_previa}</span>
            </a>
            """

    return f"<html><head><title>Conversaciones</title>{ESTILO}</head><body><h1>Conversaciones</h1>{filas}</body></html>"


@router.get("/chat/{telefono}", response_class=HTMLResponse)
async def chat(telefono: str, usuario: str = Depends(_verificar)) -> str:
    """Historial completo de una conversacion + formulario para responder."""
    historial = await obtener_historial(telefono, limite=100)
    pausado = await esta_pausado(telefono)

    mensajes_html = "".join(
        f'<div class="mensaje {m["role"]}">{escape(m["content"])}</div>' for m in historial
    )
    if not mensajes_html:
        mensajes_html = "<p>Sin mensajes todavía.</p>"

    boton_pausa = (
        f'<form method="post" action="/admin/chat/{telefono}/reanudar">'
        f"<button type=\"submit\">▶ Reanudar al bot</button></form>"
        if pausado
        else '<p style="color:#666">El bot sigue respondiendo automáticamente en esta conversación.</p>'
    )

    return f"""
    <html><head><title>{escape(telefono)}</title>{ESTILO}</head><body>
      <p><a href="/admin/">&larr; Todas las conversaciones</a></p>
      <h1>{escape(telefono)}</h1>
      {mensajes_html}
      {boton_pausa}
      <form method="post" action="/admin/chat/{telefono}/enviar">
        <textarea name="mensaje" rows="3" placeholder="Escribe una respuesta..." required></textarea>
        <button type="submit">Enviar (pausa al bot)</button>
      </form>
    </body></html>
    """


@router.post("/chat/{telefono}/enviar")
async def enviar(
    telefono: str, mensaje: str = Form(...), usuario: str = Depends(_verificar)
) -> RedirectResponse:
    """
    Envia un mensaje manual y pausa la conversacion — si no la pausamos, el bot le
    seguiria respondiendo al mismo cliente por encima de lo que acaba de escribir
    la persona.
    """
    try:
        proveedor = obtener_proveedor()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Proveedor no configurado: {e}")

    enviado = await proveedor.enviar_mensaje(telefono, mensaje)
    if not enviado:
        raise HTTPException(status_code=502, detail="No se pudo enviar el mensaje por WhatsApp")

    await guardar_mensaje(telefono, "assistant", mensaje)
    await pausar_conversacion(telefono)
    return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)


@router.post("/chat/{telefono}/reanudar")
async def reanudar(telefono: str, usuario: str = Depends(_verificar)) -> RedirectResponse:
    """Vuelve a dejar que el bot responda automaticamente en esta conversacion."""
    await reanudar_conversacion(telefono)
    return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)
