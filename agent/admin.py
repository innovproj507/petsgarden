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

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from agent.memory import (
    esta_pausado,
    guardar_mensaje,
    listar_conversaciones,
    obtener_mensajes_admin,
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

NOMBRE_NEGOCIO = "Pets Garden"


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


# ── Estilo: imita la paleta de WhatsApp (el equipo ya la reconoce de memoria) y
# ocupa toda la pantalla como una app, no como una pagina que hace scroll. ────
ESTILO = """
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --verde: #25D366;
    --verde-oscuro: #128C7E;
    --fondo-chat: #ECE5DD;
    --burbuja-cliente: #ffffff;
    --burbuja-bot: #DCF8C6;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    margin: 0;
    color: #1a1a1a;
    background: var(--fondo-chat);
    display: flex;
    flex-direction: column;
  }
  .topbar {
    background: var(--verde-oscuro);
    color: white;
    padding: 0.9rem 1rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-shrink: 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
  }
  .topbar a { color: white; text-decoration: none; font-size: 1.3rem; line-height: 1; }
  .topbar h1 { margin: 0; font-size: 1.05rem; font-weight: 600; flex: 1; }
  .topbar .subtitulo { font-size: 0.75rem; opacity: 0.85; font-weight: 400; }
  .avatar {
    width: 2.5rem; height: 2.5rem; border-radius: 50%;
    background: var(--verde); color: white;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.2rem; flex-shrink: 0;
  }
  .pausado-badge {
    background: #b45309; color: white; font-size: 0.7rem;
    padding: 0.15rem 0.5rem; border-radius: 999px; white-space: nowrap;
  }
  .atencion-badge {
    background: #dc2626; color: white; font-size: 0.7rem;
    padding: 0.15rem 0.5rem; border-radius: 999px; white-space: nowrap;
  }

  /* Buscador */
  .buscador-cont { padding: 0.6rem 1rem; background: white; border-bottom: 1px solid #eee; flex-shrink: 0; }
  #buscador {
    width: 100%; padding: 0.5rem 0.8rem; font-size: 0.95rem;
    border: 1px solid #ddd; border-radius: 20px; font-family: inherit;
  }

  /* Lista de conversaciones */
  #lista { flex: 1; overflow-y: auto; }
  .conversacion {
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.75rem 1rem;
    background: white;
    border-bottom: 1px solid #eee;
    border-left: 4px solid transparent;
    text-decoration: none; color: inherit;
  }
  .conversacion.necesita-atencion { border-left-color: #dc2626; background: #fef2f2; }
  .conversacion:active { background: #f5f5f5; }
  .conversacion .info { flex: 1; min-width: 0; }
  .conversacion .telefono { font-weight: 600; display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
  .conversacion .preview {
    color: #667781; font-size: 0.88rem;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .conversacion .hora { color: #667781; font-size: 0.75rem; flex-shrink: 0; }
  .vacio { color: #667781; text-align: center; padding: 2rem 1rem; }

  /* Chat */
  #mensajes { flex: 1; overflow-y: auto; padding: 1rem; display: flex; flex-direction: column; gap: 0.35rem; }
  .burbuja-fila { display: flex; }
  .burbuja-fila.user { justify-content: flex-start; }
  .burbuja-fila.assistant { justify-content: flex-end; }
  .mensaje {
    padding: 0.5rem 0.7rem;
    border-radius: 8px;
    max-width: 78%;
    white-space: pre-wrap;
    word-break: break-word;
    box-shadow: 0 1px 1px rgba(0,0,0,0.1);
    font-size: 0.95rem;
  }
  .mensaje.user { background: var(--burbuja-cliente); border-top-left-radius: 2px; }
  .mensaje.assistant { background: var(--burbuja-bot); border-top-right-radius: 2px; }
  .mensaje .hora {
    display: block; text-align: right; font-size: 0.68rem;
    color: #999; margin-top: 0.2rem;
  }
  .mensaje .check { color: #53bdeb; margin-left: 0.2rem; }

  .barra-inferior { flex-shrink: 0; background: #f0f0f0; padding: 0.6rem; }
  .barra-inferior .estado-pausa {
    text-align: center; font-size: 0.8rem; color: #667781;
    padding: 0.4rem; margin-bottom: 0.4rem;
  }
  .barra-inferior .estado-pausa.pausado { color: #b45309; font-weight: 600; }
  #formEnviar { display: flex; gap: 0.5rem; align-items: flex-end; }
  #formEnviar textarea {
    flex: 1; padding: 0.6rem 0.9rem; font-family: inherit; font-size: 1rem;
    border: 1px solid #ddd; border-radius: 20px; resize: none; max-height: 6rem;
  }
  #formEnviar button {
    width: 2.75rem; height: 2.75rem; border-radius: 50%; border: none;
    background: var(--verde-oscuro); color: white; font-size: 1.1rem;
    cursor: pointer; flex-shrink: 0;
  }
  #formEnviar button:disabled { opacity: 0.5; }
  #btnReanudar {
    display: block; margin: 0 auto; padding: 0.5rem 1rem;
    border: none; border-radius: 8px; background: #6b7280; color: white; cursor: pointer;
  }
  .toast {
    position: fixed; top: 0.5rem; left: 50%; transform: translateX(-50%);
    background: #b91c1c; color: white; padding: 0.4rem 0.9rem; border-radius: 8px;
    font-size: 0.8rem; opacity: 0; transition: opacity 0.3s; pointer-events: none;
  }
  .toast.visible { opacity: 1; }
</style>
"""

# JS compartido entre las dos paginas.
JS_COMUN = """
function escaparHtml(texto) {
  const d = document.createElement('div');
  d.textContent = texto;
  return d.innerHTML;
}

function horaRelativa(iso) {
  const fecha = new Date(iso);
  const diffMin = Math.round((Date.now() - fecha.getTime()) / 60000);
  if (diffMin < 1) return 'ahora';
  if (diffMin < 60) return `hace ${diffMin} min`;
  const diffHoras = Math.round(diffMin / 60);
  if (diffHoras < 24) return `hace ${diffHoras} h`;
  const diffDias = Math.round(diffHoras / 24);
  if (diffDias === 1) return 'ayer';
  if (diffDias < 7) return `hace ${diffDias} días`;
  return fecha.toLocaleDateString('es-PA', { day: 'numeric', month: 'short' });
}

function horaCorta(iso) {
  return new Date(iso).toLocaleTimeString('es-PA', { hour: 'numeric', minute: '2-digit' });
}

let _toastTimeout;
function mostrarError(msg) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add('visible');
  clearTimeout(_toastTimeout);
  _toastTimeout = setTimeout(() => toast.classList.remove('visible'), 3000);
}

const TITULO_BASE = document.title;

// Beep corto generado con Web Audio, sin archivo de sonido. Los navegadores
// bloquean audio hasta que hay una interaccion del usuario en la pagina (un
// click, un tap) -- por eso el primer aviso puede no sonar; los siguientes,
// despues de que alguien toco la pantalla una vez, si.
function reproducirSonido() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
    osc.start();
    osc.stop(ctx.currentTime + 0.3);
  } catch (e) { /* navegador sin soporte, o sin permiso todavia: no pasa nada */ }
}

function actualizarTitulo(cantidad) {
  document.title = cantidad > 0 ? `(${cantidad}) ${TITULO_BASE}` : TITULO_BASE;
}
"""


@router.get("/", response_class=HTMLResponse)
async def panel(usuario: str = Depends(_verificar)) -> str:
    """Lista de conversaciones — se refresca sola cada 5 segundos."""
    return f"""
    <html><head><title>{NOMBRE_NEGOCIO} — Conversaciones</title>{ESTILO}</head><body>
      <div class="topbar">
        <h1>{NOMBRE_NEGOCIO}<br><span class="subtitulo">Conversaciones</span></h1>
      </div>
      <div class="buscador-cont">
        <input type="search" id="buscador" placeholder="Buscar por número...">
      </div>
      <div id="lista"><p class="vacio">Cargando...</p></div>

      <script>
        {JS_COMUN}

        let conversacionesActuales = [];
        let numerosConAtencionPrevios = new Set();

        function necesitaAtencion(c) {{
          // Un humano ya tomo la conversacion (pausada) y el cliente escribio
          // de nuevo sin que nadie del equipo le haya contestado todavia.
          return c.pausado && c.ultimo_rol === 'user';
        }}

        function renderizarLista() {{
          const filtro = document.getElementById('buscador').value.trim();
          const cont = document.getElementById('lista');
          const filtradas = filtro
            ? conversacionesActuales.filter(c => c.telefono.includes(filtro))
            : conversacionesActuales;

          if (filtradas.length === 0) {{
            cont.innerHTML = `<p class="vacio">${{filtro ? 'Sin resultados.' : 'Todavía no hay conversaciones.'}}</p>`;
            return;
          }}
          cont.innerHTML = filtradas.map(c => `
            <a class="conversacion ${{necesitaAtencion(c) ? 'necesita-atencion' : ''}}" href="/admin/chat/${{encodeURIComponent(c.telefono)}}">
              <div class="avatar">🐾</div>
              <div class="info">
                <div class="telefono">
                  ${{escaparHtml(c.telefono)}}
                  ${{necesitaAtencion(c) ? '<span class="atencion-badge">necesita respuesta</span>' : (c.pausado ? '<span class="pausado-badge">⏸ persona</span>' : '')}}
                </div>
                <div class="preview">${{escaparHtml(c.ultimo_mensaje)}}</div>
              </div>
              <div class="hora">${{horaRelativa(c.fecha)}}</div>
            </a>
          `).join('');
        }}

        async function actualizar() {{
          try {{
            const r = await fetch('/admin/api/conversaciones');
            if (!r.ok) throw new Error('HTTP ' + r.status);
            conversacionesActuales = await r.json();
            renderizarLista();

            const numerosConAtencion = new Set(
              conversacionesActuales.filter(necesitaAtencion).map(c => c.telefono)
            );
            // Solo suena/parpadea si HAY un numero nuevo que antes no estaba
            // en la lista de "necesita atencion" -- si no, sonaria cada 5
            // segundos sin parar mientras algo siga pendiente.
            const hayNuevo = [...numerosConAtencion].some(t => !numerosConAtencionPrevios.has(t));
            if (hayNuevo) reproducirSonido();
            numerosConAtencionPrevios = numerosConAtencion;
            actualizarTitulo(numerosConAtencion.size);
          }} catch (e) {{
            mostrarError('Sin conexión, reintentando...');
          }}
        }}

        document.getElementById('buscador').addEventListener('input', renderizarLista);

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
      <div class="topbar">
        <a href="/admin/">&larr;</a>
        <div class="avatar">🐾</div>
        <h1 id="tituloTelefono">{escape(telefono)}</h1>
      </div>
      <div id="mensajes"><p class="vacio">Cargando...</p></div>
      <div class="barra-inferior">
        <div id="estadoPausa"></div>
        <form id="formEnviar">
          <textarea name="mensaje" rows="1" placeholder="Escribe una respuesta..." required></textarea>
          <button type="submit" title="Enviar (pausa al bot)">➤</button>
        </form>
      </div>

      <script>
        {JS_COMUN}
        const TELEFONO = {telefono!r};
        let ultimaCantidad = -1;

        function renderizarMensajes(mensajes) {{
          const cont = document.getElementById('mensajes');
          if (mensajes.length === 0) {{
            cont.innerHTML = '<p class="vacio">Sin mensajes todavía.</p>';
            return;
          }}
          cont.innerHTML = mensajes.map(m => `
            <div class="burbuja-fila ${{m.role}}">
              <div class="mensaje ${{m.role}}">
                ${{escaparHtml(m.content)}}
                <span class="hora">
                  ${{horaCorta(m.fecha)}}
                  ${{m.role === 'assistant' ? '<span class="check" title="Enviado a WhatsApp">✓</span>' : ''}}
                </span>
              </div>
            </div>
          `).join('');
          cont.scrollTop = cont.scrollHeight;
        }}

        function renderizarEstadoPausa(pausado) {{
          const cont = document.getElementById('estadoPausa');
          cont.innerHTML = pausado
            ? '<p class="estado-pausa pausado">⏸ La atiende una persona del equipo</p><button type="button" id="btnReanudar">▶ Reanudar al bot</button>'
            : '<p class="estado-pausa">El bot responde automáticamente</p>';
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
            renderizarEstadoPausa(datos.pausado);
          }} catch (e) {{
            mostrarError('Sin conexión, reintentando...');
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
            mostrarError('No se pudo enviar: ' + e.message);
          }} finally {{
            boton.disabled = false;
          }}
        }});

        // El textarea crece con el texto, hasta el max-height del CSS
        const textarea = document.querySelector('#formEnviar textarea');
        textarea.addEventListener('input', () => {{
          textarea.style.height = 'auto';
          textarea.style.height = textarea.scrollHeight + 'px';
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
            "ultimo_rol": c["ultimo_rol"],
            "pausado": c["pausado"],
            "fecha": c["fecha"].isoformat(),
        }
        for c in conversaciones
    ]


@router.get("/api/chat/{telefono}")
async def api_chat(telefono: str, usuario: str = Depends(_verificar)) -> dict:
    return {
        "mensajes": await obtener_mensajes_admin(telefono, limite=100),
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
