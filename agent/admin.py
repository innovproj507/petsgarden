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

Las paginas (/admin/, /admin/chat/{telefono}) renderizan el HTML inicial y despues
se refrescan solas contra los endpoints /admin/api/* (JSON) via fetch — sin recargar
la pagina. El navegador ya manda la credencial de Basic Auth en cada fetch porque es
el mismo origen y el mismo "realm", asi que no hace falta manejar tokens aparte.
"""

import os
import secrets
from html import escape

from dotenv import load_dotenv
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

# Propio, igual que en brain.py y memory.py: este modulo se importa desde main.py
# ANTES de que main.py llame a load_dotenv() (el import va primero en el archivo),
# asi que si no se carga aca tambien, ADMIN_USER/ADMIN_PASSWORD llegan vacios sin
# importar lo que haya en el .env.
load_dotenv()

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


# ── Estilo: pensado para celular primero (los mensajes se leen desde ahi la
# mayoria de las veces), con el mismo CSS sirviendo bien en laptop. ──────────
ESTILO = """
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { box-sizing: border-box; }
  body {
    font-family: system-ui, -apple-system, sans-serif;
    max-width: 720px;
    margin: 0 auto;
    padding: 1rem;
    color: #1a1a1a;
    background: #fafafa;
  }
  h1 { font-size: 1.25rem; }
  a { color: #0a7d3c; text-decoration: none; }
  .conversacion {
    display: block;
    padding: 0.9rem;
    border: 1px solid #ddd;
    border-radius: 10px;
    margin-bottom: 0.6rem;
    background: white;
  }
  .conversacion:active, .conversacion:hover { background: #f2f2f2; }
  .pausado { color: #b45309; font-weight: 600; }
  .vacio { color: #666; }
  .mensajes { display: flex; flex-direction: column; gap: 0.5rem; margin: 1rem 0; }
  .mensaje {
    padding: 0.6rem 0.85rem;
    border-radius: 10px;
    max-width: 85%;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .mensaje.user { background: #e5e7eb; align-self: flex-start; }
  .mensaje.assistant { background: #d1fae5; align-self: flex-end; }
  form { margin-top: 1rem; }
  textarea {
    width: 100%;
    padding: 0.6rem;
    font-family: inherit;
    font-size: 1rem;
    border: 1px solid #ccc;
    border-radius: 8px;
  }
  button {
    padding: 0.7rem 1.2rem;
    margin-top: 0.5rem;
    font-size: 1rem;
    border: none;
    border-radius: 8px;
    background: #0a7d3c;
    color: white;
    cursor: pointer;
  }
  button.secundario { background: #6b7280; }
  button:active { opacity: 0.85; }
  .estado { color: #666; font-size: 0.9rem; }
  .barra { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
</style>
"""

# JS compartido: escapa texto para no reabrir un hueco de XSS al insertar
# contenido de clientes (nombres, mensajes) con innerHTML.
JS_ESCAPAR = """
function escaparHtml(texto) {
  const d = document.createElement('div');
  d.textContent = texto;
  return d.innerHTML;
}
"""


@router.get("/", response_class=HTMLResponse)
async def panel(usuario: str = Depends(_verificar)) -> str:
    """Lista de conversaciones — se refresca sola cada 5 segundos."""
    return f"""
    <html><head><title>Conversaciones</title>{ESTILO}</head><body>
      <div class="barra">
        <h1>Conversaciones</h1>
        <span class="estado" id="estado"></span>
      </div>
      <div id="lista"><p class="vacio">Cargando...</p></div>

      <script>
        {JS_ESCAPAR}

        function renderizarLista(conversaciones) {{
          const cont = document.getElementById('lista');
          if (conversaciones.length === 0) {{
            cont.innerHTML = '<p class="vacio">Todavía no hay conversaciones.</p>';
            return;
          }}
          cont.innerHTML = conversaciones.map(c => `
            <a class="conversacion" href="/admin/chat/${{encodeURIComponent(c.telefono)}}">
              <b>${{escaparHtml(c.telefono)}}</b>
              ${{c.pausado ? ' <span class="pausado">⏸ atendida por una persona</span>' : ''}}
              <br><span style="color:#666">${{escaparHtml(c.ultimo_mensaje.slice(0, 80))}}</span>
            </a>
          `).join('');
        }}

        async function actualizar() {{
          try {{
            const r = await fetch('/admin/api/conversaciones');
            if (!r.ok) throw new Error('HTTP ' + r.status);
            renderizarLista(await r.json());
            document.getElementById('estado').textContent = '';
          }} catch (e) {{
            document.getElementById('estado').textContent = 'Sin conexión, reintentando...';
          }}
        }}

        actualizar();
        setInterval(actualizar, 5000);
      </script>
    </body></html>
    """


@router.get("/chat/{telefono}", response_class=HTMLResponse)
async def chat(telefono: str, usuario: str = Depends(_verificar)) -> str:
    """Historial de una conversacion — se refresca sola y se puede responder sin recargar."""
    return f"""
    <html><head><title>{escape(telefono)}</title>{ESTILO}</head><body>
      <p><a href="/admin/">&larr; Todas las conversaciones</a></p>
      <div class="barra">
        <h1>{escape(telefono)}</h1>
        <span class="estado" id="estado"></span>
      </div>
      <div class="mensajes" id="mensajes"><p class="vacio">Cargando...</p></div>
      <div id="controlPausa"></div>
      <form id="formEnviar">
        <textarea name="mensaje" rows="3" placeholder="Escribe una respuesta..." required></textarea>
        <button type="submit">Enviar (pausa al bot)</button>
      </form>

      <script>
        {JS_ESCAPAR}
        const TELEFONO = {telefono!r};
        let ultimaCantidad = -1;

        function renderizarMensajes(mensajes) {{
          const cont = document.getElementById('mensajes');
          if (mensajes.length === 0) {{
            cont.innerHTML = '<p class="vacio">Sin mensajes todavía.</p>';
            return;
          }}
          cont.innerHTML = mensajes.map(m =>
            `<div class="mensaje ${{m.role}}">${{escaparHtml(m.content)}}</div>`
          ).join('');
        }}

        function renderizarControlPausa(pausado) {{
          const cont = document.getElementById('controlPausa');
          cont.innerHTML = pausado
            ? '<button type="button" class="secundario" id="btnReanudar">▶ Reanudar al bot</button>'
            : '<p class="estado">El bot sigue respondiendo automáticamente en esta conversación.</p>';
          if (pausado) {{
            document.getElementById('btnReanudar').addEventListener('click', reanudar);
          }}
        }}

        async function actualizar() {{
          try {{
            const r = await fetch(`/admin/api/chat/${{encodeURIComponent(TELEFONO)}}`);
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const datos = await r.json();
            // Solo se vuelve a pintar si cambio algo, para no perder el scroll
            // ni el foco del textarea mientras alguien esta escribiendo.
            if (datos.mensajes.length !== ultimaCantidad) {{
              renderizarMensajes(datos.mensajes);
              ultimaCantidad = datos.mensajes.length;
            }}
            renderizarControlPausa(datos.pausado);
            document.getElementById('estado').textContent = '';
          }} catch (e) {{
            document.getElementById('estado').textContent = 'Sin conexión, reintentando...';
          }}
        }}

        async function reanudar() {{
          await fetch(`/admin/api/chat/${{encodeURIComponent(TELEFONO)}}/reanudar`, {{ method: 'POST' }});
          actualizar();
        }}

        document.getElementById('formEnviar').addEventListener('submit', async (ev) => {{
          ev.preventDefault();
          const textarea = ev.target.mensaje;
          const mensaje = textarea.value.trim();
          if (!mensaje) return;
          const boton = ev.target.querySelector('button');
          boton.disabled = true;
          try {{
            const r = await fetch(`/admin/api/chat/${{encodeURIComponent(TELEFONO)}}/enviar`, {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
              body: 'mensaje=' + encodeURIComponent(mensaje),
            }});
            if (!r.ok) throw new Error((await r.json()).detail || ('HTTP ' + r.status));
            textarea.value = '';
            ultimaCantidad = -1;  // fuerza a repintar aunque la cantidad no calce todavia
            await actualizar();
          }} catch (e) {{
            alert('No se pudo enviar: ' + e.message);
          }} finally {{
            boton.disabled = false;
          }}
        }});

        actualizar();
        setInterval(actualizar, 4000);
      </script>
    </body></html>
    """


# ── API (JSON) — la usan las paginas de arriba via fetch ─────────────────────


@router.get("/api/conversaciones")
async def api_conversaciones(usuario: str = Depends(_verificar)) -> list[dict]:
    conversaciones = await listar_conversaciones()
    return [
        {
            "telefono": c["telefono"],
            "ultimo_mensaje": c["ultimo_mensaje"],
            "pausado": c["pausado"],
        }
        for c in conversaciones
    ]


@router.get("/api/chat/{telefono}")
async def api_chat(telefono: str, usuario: str = Depends(_verificar)) -> dict:
    return {
        "mensajes": await obtener_historial(telefono, limite=100),
        "pausado": await esta_pausado(telefono),
    }


@router.post("/api/chat/{telefono}/enviar")
async def api_enviar(
    telefono: str, mensaje: str = Form(...), usuario: str = Depends(_verificar)
) -> dict:
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
    return {"ok": True}


@router.post("/api/chat/{telefono}/reanudar")
async def api_reanudar(telefono: str, usuario: str = Depends(_verificar)) -> dict:
    await reanudar_conversacion(telefono)
    return {"ok": True}


# ── Rutas viejas sin JS, por si alguien entra con un navegador muy limitado o
# JS deshabilitado — redirigen a las paginas normales de arriba, que ya cubren
# el mismo formulario sin depender de fetch para el primer envio. ────────────


@router.post("/chat/{telefono}/enviar")
async def enviar_sin_js(
    telefono: str, mensaje: str = Form(...), usuario: str = Depends(_verificar)
) -> RedirectResponse:
    await api_enviar(telefono, mensaje, usuario)
    return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)


@router.post("/chat/{telefono}/reanudar")
async def reanudar_sin_js(telefono: str, usuario: str = Depends(_verificar)) -> RedirectResponse:
    await api_reanudar(telefono, usuario)
    return RedirectResponse(url=f"/admin/chat/{telefono}", status_code=303)
