#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor local de la web (web/) con las dos cosas que un sitio estatico no puede hacer:
guardar un precio en los JSON del proyecto y correr una captura.

    python scripts/servidor.py              abre http://127.0.0.1:8765
    python scripts/servidor.py --puerto 9000 --no-abrir

Solo escucha en 127.0.0.1. La busqueda y el veredicto corren en el navegador
(web/app.js) con web/data/, igual que en la version publicada.

API:
    GET  /api/estado      {local: true, captura: {activa, lineas}}
    POST /api/registrar   {comercial, sku, precio, precio_lista?}
    POST /api/capturar    barrido completo en segundo plano y exportacion al terminar

Sin dependencias externas.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import almacen  # noqa: E402
import exportar  # noqa: E402
import precios  # noqa: E402

DIR_WEB = precios.RAIZ / "web"
TIPOS = {".webmanifest": "application/manifest+json", ".js": "text/javascript", ".svg": "image/svg+xml"}

CAPTURA = {"activa": False, "lineas": [], "inicio": None, "fin": None}


def api_estado(_cuerpo) -> dict:
    return {"local": True, "captura": CAPTURA}


def api_registrar(cuerpo: dict) -> dict:
    catalogo = precios.cargar_comerciales()
    cid = precios.resolver_comercial(cuerpo.get("comercial", ""), catalogo)
    sku = str(cuerpo.get("sku") or "").strip()
    if not cid or not almacen.ficha(cid, sku):
        raise LookupError("Ese producto no está guardado.")
    precio = precios.parsear_precio(cuerpo["precio"])
    if precio <= 0:
        raise ValueError("El precio debe ser mayor que cero.")
    lista = precios.parsear_precio(cuerpo["precio_lista"]) if cuerpo.get("precio_lista") else None
    obs = {"fecha": precios.ahora_iso(), "precio": precio, "precio_lista": lista, "disponible": True,
           "fuente": "manual", "nota": (cuerpo.get("nota") or "visto en tienda").strip()}
    nuevo = almacen.agregar(cid, sku, {}, obs)
    if nuevo:
        exportar.exportar(avisar=lambda _: None)
    return {"guardado": nuevo, "mensaje": "Guardado en el historial." if nuevo else "Ese precio ya estaba guardado hoy."}


def api_capturar(_cuerpo) -> dict:
    if CAPTURA["activa"]:
        return {"iniciada": False, "mensaje": "Ya hay una captura en curso."}

    def avisar(linea: str) -> None:
        CAPTURA["lineas"].append(linea)

    def correr() -> None:
        try:
            precios.capturar(avisar=avisar)
            exportar.exportar(avisar=avisar)
        except Exception as e:  # que el error se vea en la pagina
            avisar(f"ERROR: {type(e).__name__}: {e}")
        finally:
            CAPTURA["activa"] = False
            CAPTURA["fin"] = precios.ahora_iso()

    CAPTURA.update(activa=True, lineas=[], inicio=precios.ahora_iso(), fin=None)
    threading.Thread(target=correr, daemon=True).start()
    return {"iniciada": True}


RUTAS = {("GET", "/api/estado"): api_estado, ("POST", "/api/registrar"): api_registrar,
         ("POST", "/api/capturar"): api_capturar}


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, formato, *args):  # silencioso: solo errores
        pass

    def _enviar(self, codigo: int, cuerpo: bytes, tipo: str, cache: str = "no-cache") -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, codigo: int, datos) -> None:
        self._enviar(codigo, json.dumps(datos, ensure_ascii=False).encode("utf-8"),
                     "application/json; charset=utf-8", "no-store")

    def _api(self, metodo: str, ruta: str) -> bool:
        funcion = RUTAS.get((metodo, ruta))
        if not funcion:
            return False
        cuerpo = {}
        if metodo == "POST":
            largo = int(self.headers.get("Content-Length") or 0)
            try:
                cuerpo = json.loads(self.rfile.read(largo) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "JSON inválido."})
                return True
        try:
            if funcion is api_capturar:
                self._json(200, funcion(cuerpo))
            else:
                with almacen.CANDADO:
                    self._json(200, funcion(cuerpo))
        except (LookupError, ValueError, KeyError, SystemExit) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": f"{type(e).__name__}: {e}"})
        return True

    def _estatico(self, ruta: str) -> None:
        relativo = urllib.parse.unquote(ruta).lstrip("/") or "index.html"
        archivo = (DIR_WEB / relativo).resolve()
        if DIR_WEB.resolve() not in archivo.parents and archivo != DIR_WEB.resolve():
            self._json(404, {"error": "No existe."})
            return
        if archivo.is_dir():
            archivo = archivo / "index.html"
        if not archivo.is_file():
            self._json(404, {"error": "No existe."})
            return
        tipo = TIPOS.get(archivo.suffix) or mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo.endswith(("json", "javascript")):
            tipo += "; charset=utf-8"
        self._enviar(200, archivo.read_bytes(), tipo)

    def do_GET(self):
        ruta = urllib.parse.urlsplit(self.path).path
        if not self._api("GET", ruta):
            self._estatico(ruta)

    def do_POST(self):
        ruta = urllib.parse.urlsplit(self.path).path
        if not self._api("POST", ruta):
            self._json(404, {"error": "No existe."})


def main() -> int:
    parser = argparse.ArgumentParser(description="Servidor local de la web de precios.")
    parser.add_argument("--puerto", type=int, default=8765)
    parser.add_argument("--no-abrir", action="store_true", help="No abrir el navegador")
    args = parser.parse_args()

    if not (DIR_WEB / "data" / "catalogo.json").exists():
        print("Generando web/data por primera vez...")
        exportar.exportar()

    servidor = ThreadingHTTPServer(("127.0.0.1", args.puerto), Manejador)
    url = f"http://127.0.0.1:{args.puerto}"
    print(f"Web lista en {url}  (Ctrl+C para cerrar)")
    if not args.no_abrir:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
