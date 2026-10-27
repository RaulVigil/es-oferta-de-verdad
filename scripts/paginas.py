# -*- coding: utf-8 -*-
"""
Paginas estaticas para buscadores y asistentes de IA, que no ejecutan JavaScript: sin esto,
un bot que visita el sitio solo ve el titular y el pie (la lista la dibuja web/app.js).

    web/ofertas/index.html            ofertas reales y bajas leves de hoy (con datos estructurados)
    web/categoria/<id>/index.html     todos los productos disponibles de cada categoria
    web/data/ofertas.json             las mismas ofertas, con campos con nombre
    web/llms.txt                      que es el sitio y donde estan los datos (propuesta llmstxt.org)
    web/sitemap.xml

Las genera exportar.py despues de cada captura, con los mismos datos y veredictos que la web.

Sin dependencias externas.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parents[1]
DIR_WEB = RAIZ / "web"
SITIO = "https://es-oferta-de-verdad.vercel.app"
REPO = "https://github.com/RaulVigil/es-oferta-de-verdad"

ETIQUETAS = {"verde": "oferta real", "amarillo": "baja leve", "gris": "sin cambio", "rojo": "subió",
             "sin-base": "sin base"}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MAX_OFERTAS_LD = 100  # productos en el JSON-LD de /ofertas/ (la tabla los lleva todos)

LOGO = ('<svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="currentColor"/>'
        '<path d="M7 11h6v5h6v5h6" fill="none" stroke="var(--papel)" stroke-width="2.6"/>'
        '<circle cx="25" cy="21" r="2.6" fill="var(--marca)"/></svg>')


# --------------------------------------------------------------------------- #
# Formato
# --------------------------------------------------------------------------- #
def _fecha(iso: str, hora: bool = True) -> str:
    d = datetime.fromisoformat(iso)
    texto = f"{d.day} {MESES[d.month - 1]} {d.year}"
    if hora:
        texto += f", {d.hour % 12 or 12}:{d.minute:02d} {'a. m.' if d.hour < 12 else 'p. m.'}"
    return texto


def _dinero(x) -> str:
    return f"${x:,.2f}" if x is not None else "—"


def _pct(x) -> str:
    if x is None:
        return "—"
    return ("−" if x < -0.05 else "+" if x > 0.05 else "±") + f"{abs(x):.1f} %"


def _escribir(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(texto, encoding="utf-8", newline="\n")
    tmp.replace(ruta)


def _ld(datos: dict) -> str:
    """JSON-LD dentro de <script>: '</' se escapa para que un nombre no cierre la etiqueta."""
    return json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


# --------------------------------------------------------------------------- #
# Piezas de HTML
# --------------------------------------------------------------------------- #
def _pagina(titulo: str, descripcion: str, ruta: str, cuerpo: str, ld: list[dict]) -> str:
    url = SITIO + ruta
    scripts = "".join(f'\n<script type="application/ld+json">{_ld(d)}</script>' for d in ld)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(titulo)}</title>
<meta name="description" content="{escape(descripcion)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:locale" content="es_SV">
<meta property="og:site_name" content="¿Es oferta de verdad?">
<meta property="og:title" content="{escape(titulo)}">
<meta property="og:description" content="{escape(descripcion)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITIO}/og.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#f2f5f9" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#011222" media="(prefers-color-scheme: dark)">
<link rel="icon" href="/icons/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/app.css">
<link rel="stylesheet" href="/paginas.css">{scripts}
</head>
<body>
<div class="app">
  <header class="cabecera">
    <a href="/" class="logo" aria-label="¿Es oferta de verdad?, inicio">{LOGO}<span>¿es oferta<em>?</em></span></a>
    <a class="enlace" href="/">buscar un producto →</a>
  </header>
  <main class="pagina">
{cuerpo}
  </main>
  <footer class="pie">
    <p><strong>Línea base</strong>: mediana de los precios capturados en cada tienda antes del 1 de noviembre.
       <strong>Oferta real</strong>: 10&nbsp;% o más por debajo; <strong>baja leve</strong>: entre 3 y 10&nbsp;%.
       Precios en línea, de contado, sin envío. Proyecto independiente, sin relación con las tiendas:
       verifica el precio en la tienda antes de comprar.</p>
    <p>Datos abiertos: <a href="/data/ofertas.json">ofertas.json</a> · <a href="/llms.txt">llms.txt</a> ·
       <a href="{REPO}">código en GitHub</a></p>
  </footer>
</div>
</body>
</html>
"""


def _tabla(filas: list[dict], tiendas: dict) -> str:
    """Producto, tienda, precio de hoy, linea base y veredicto; el producto abre su historial en la web."""
    cuerpo = []
    for it in filas:
        s = it["s"]
        meta = " · ".join(x for x in (f'{it["p"]}"' if it.get("p") else it.get("me") or "", it.get("ma")) if x)
        tienda = escape(tiendas.get(it["t"], it["t"]))
        if it.get("u"):
            tienda = f'<a href="{escape(it["u"])}" rel="nofollow noopener">{tienda}&nbsp;↗</a>'
        cuerpo.append(
            f'<tr><td><a href="/#/{quote(it["id"], safe="")}">{escape(it["n"])}</a>'
            + (f"<small>{escape(meta)}</small>" if meta else "") + "</td>"
            f"<td>{tienda}</td><td class=\"n\">{_dinero(s['ultimo'])}</td>"
            f"<td class=\"n\">{_dinero(s['base'])}</td><td class=\"n\">{_pct(s['pct_base'])}</td>"
            f'<td><span class="v {s["nivel"]}"><i></i>{ETIQUETAS[s["nivel"]]}</span></td></tr>')
    return ('<div class="tabla"><table><thead><tr><th>Producto</th><th>Tienda</th><th class="n">Hoy</th>'
            '<th class="n">Línea base</th><th class="n">vs base</th><th>Veredicto</th></tr></thead><tbody>'
            + "\n".join(cuerpo) + "</tbody></table></div>")


def _nav_categorias(categorias: list[tuple[str, str, int]], actual: str = "") -> str:
    enlaces = []
    for cid, nombre, n in categorias:
        marca = ' aria-current="page"' if cid == actual else ""
        enlaces.append(f'<a href="/categoria/{cid}/"{marca}>{escape(nombre.lower())}<small>{n}</small></a>')
    return (f'<section><h2>Por categoría</h2><nav class="cats" aria-label="Categorías">{"".join(enlaces)}</nav>'
            "</section>")


def _aviso_base(corte: str, generado: str) -> str:
    if generado[:10] >= corte:
        return ""
    return (f'<p class="nota">La línea base se forma con lo capturado antes del {_fecha(corte + "T12:00", False)}: por ahora, '
            "«oferta real» significa 10&nbsp;% o más por debajo de la mediana de lo capturado desde el "
            "20 de octubre.</p>")


# --------------------------------------------------------------------------- #
# Generacion
# --------------------------------------------------------------------------- #
def _producto_ld(it: dict, tiendas: dict) -> dict:
    s = it["s"]
    oferta = {"@type": "Offer", "price": f'{s["ultimo"]:.2f}', "priceCurrency": "USD",
              "availability": "https://schema.org/InStock",
              "seller": {"@type": "Organization", "name": tiendas.get(it["t"], it["t"])}}
    if it.get("u"):
        oferta["url"] = it["u"]
    producto = {"@type": "Product", "name": it["n"], "offers": oferta}
    if it.get("ma"):
        producto["brand"] = {"@type": "Brand", "name": it["ma"]}
    if it.get("im"):
        producto["image"] = it["im"]
    return producto


def _oferta_json(it: dict, tiendas: dict, categorias: dict) -> dict:
    s = it["s"]
    return {
        "producto": it["n"], "marca": it.get("ma") or None, "categoria": categorias.get(it["c"], it["c"]),
        "tienda": tiendas.get(it["t"], it["t"]), "precio": s["ultimo"], "precio_tachado": s.get("lista"),
        "linea_base": s["base"], "precios_en_linea_base": s["n_base"],
        "variacion_vs_base_pct": round(s["pct_base"], 1) if s["pct_base"] is not None else None,
        "veredicto": ETIQUETAS[s["nivel"]], "minimo_historico": s["minimo"],
        "url_tienda": it.get("u") or None, "url_historial": f'{SITIO}/#/{quote(it["id"], safe="")}',
        "imagen": it.get("im") or None,
    }


def generar(items: list[dict], catalogo: dict, dir_web: Path = DIR_WEB) -> dict:
    """items: los productos de exportar.py (antes de compactarlos), con sus estadisticas en 's'."""
    tiendas = {t["id"]: t["nombre"] for t in catalogo["tiendas"]}
    nombres_cat = {c["id"]: c["nombre"] for c in catalogo["categorias"]}
    generado, corte = catalogo["generado"], catalogo["corte"]
    hoy = generado[:10]
    disponibles = [it for it in items if it["s"]["disponible"]]
    por_baja = lambda it: (it["s"]["pct_base"] if it["s"]["pct_base"] is not None else 999, it["s"]["ultimo"])

    ofertas = sorted((it for it in disponibles if it["s"]["nivel"] == "verde"), key=por_baja)
    leves = sorted((it for it in disponibles if it["s"]["nivel"] == "amarillo"), key=por_baja)
    cuenta = {cid: sum(1 for it in disponibles if it["c"] == cid) for cid in nombres_cat}
    categorias = [(cid, nombre, cuenta[cid]) for cid, nombre in nombres_cat.items() if cuenta[cid]]
    resumen = (f"Actualizado el {_fecha(generado)} · {len(items):,} productos de {len(tiendas)} tiendas · "
               f"{len(ofertas)} ofertas reales")

    # /ofertas/
    cuerpo = f"""    <p class="miga"><a href="/">Inicio</a> / Ofertas de hoy</p>
    <h1>Ofertas <em>reales</em> de hoy</h1>
    <p class="bajada">Productos de {len(tiendas)} tiendas de El Salvador cuyo precio de hoy está por debajo de lo
      que costaban antes, no del precio tachado que anuncia la tienda.</p>
    <p class="actualizado">{resumen}</p>
    {_aviso_base(corte, generado)}
    <section><h2>Ofertas reales <small>10&nbsp;% o más bajo su línea base · {len(ofertas)}</small></h2>
    {_tabla(ofertas, tiendas) if ofertas else '<p class="nota">Hoy ningún producto está 10 % por debajo de su línea base.</p>'}</section>
    <section><h2>Bajas leves <small>entre 3 y 10&nbsp;% · {len(leves)}</small></h2>
    {_tabla(leves, tiendas) if leves else '<p class="nota">Ninguna hoy.</p>'}</section>
    {_nav_categorias(categorias)}"""
    lista_ld = {"@context": "https://schema.org", "@type": "ItemList", "name": "Ofertas reales de hoy en El Salvador",
                "itemListElement": [{"@type": "ListItem", "position": i + 1, "item": _producto_ld(it, tiendas)}
                                    for i, it in enumerate(ofertas[:MAX_OFERTAS_LD])]}
    _escribir(dir_web / "ofertas" / "index.html", _pagina(
        "Ofertas reales de hoy en El Salvador — ¿Es oferta de verdad?",
        f"{len(ofertas)} productos de {len(tiendas)} tiendas de El Salvador están hoy 10 % o más por debajo "
        "de lo que costaban antes. Comparado contra su historial, no contra el precio tachado.",
        "/ofertas/", cuerpo, [lista_ld]))

    # /categoria/<id>/
    for cid, nombre, n in categorias:
        filas = sorted((it for it in disponibles if it["c"] == cid), key=por_baja)
        n_tiendas = len({it["t"] for it in filas})
        cuerpo = f"""    <p class="miga"><a href="/">Inicio</a> / <a href="/ofertas/">Ofertas de hoy</a> / {escape(nombre)}</p>
    <h1>{escape(nombre)}: <em>¿es oferta?</em></h1>
    <p class="bajada">{n:,} productos disponibles en {n_tiendas} tiendas de El Salvador, con su precio de hoy y la
      comparación contra su línea base. Primero los que más bajaron.</p>
    <p class="actualizado">{resumen}</p>
    {_aviso_base(corte, generado)}
    <section>{_tabla(filas, tiendas)}</section>
    {_nav_categorias(categorias, cid)}"""
        migas = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Inicio", "item": SITIO + "/"},
            {"@type": "ListItem", "position": 2, "name": "Ofertas de hoy", "item": SITIO + "/ofertas/"},
            {"@type": "ListItem", "position": 3, "name": nombre, "item": f"{SITIO}/categoria/{cid}/"}]}
        _escribir(dir_web / "categoria" / cid / "index.html", _pagina(
            f"{nombre} en El Salvador: precios de hoy contra su historial — ¿Es oferta de verdad?",
            f"{n:,} productos de {nombre.lower()} en {n_tiendas} tiendas de El Salvador, con su precio de hoy, "
            "la mediana de lo que costaban antes y si la oferta es real.",
            f"/categoria/{cid}/", cuerpo, [migas]))
    # una categoria que ya no tiene productos no deja su pagina vieja
    if (dir_web / "categoria").exists():
        for d in (dir_web / "categoria").iterdir():
            if d.is_dir() and not cuenta.get(d.name):
                shutil.rmtree(d)

    # /data/ofertas.json
    _escribir(dir_web / "data" / "ofertas.json", json.dumps({
        "generado": generado,
        "fuente": SITIO,
        "metodo": (f"linea_base = mediana de los precios capturados en cada tienda antes del {corte}. "
                   f"Oferta real: {abs(catalogo['umbral_oferta']):.0f} % o más por debajo de la línea base; "
                   f"baja leve: entre {catalogo['umbral_cambio']:.0f} y {abs(catalogo['umbral_oferta']):.0f} %. "
                   "Precios en línea, de contado, sin envío, en USD. Solo productos disponibles."),
        "ofertas_reales": [_oferta_json(it, tiendas, nombres_cat) for it in ofertas],
        "bajas_leves": [_oferta_json(it, tiendas, nombres_cat) for it in leves],
    }, ensure_ascii=False, indent=1) + "\n")

    # /llms.txt
    lineas_cat = "\n".join(f"- [{nombre}]({SITIO}/categoria/{cid}/): {n:,} productos disponibles"
                           for cid, nombre, n in categorias)
    lista_tiendas = ", ".join(tiendas[t] for t in sorted(tiendas, key=lambda t: tiendas[t]))
    _escribir(dir_web / "llms.txt", f"""# ¿Es oferta de verdad?

> Historial diario de precios de {len(tiendas)} tiendas en línea de El Salvador para saber si una oferta de
> Black Friday (27 de noviembre de 2026) o Cyber Monday es real: compara el precio de hoy contra la mediana de
> lo que costó antes del 1 de noviembre (línea base), no contra el precio tachado que anuncia la tienda.

{resumen}. Tiendas: {lista_tiendas}.

## Cómo leer los datos

- Línea base: mediana de los precios capturados en esa tienda antes del {corte}.
- Oferta real: el precio de hoy está {abs(catalogo['umbral_oferta']):.0f} % o más por debajo de la línea base.
  Baja leve: entre {catalogo['umbral_cambio']:.0f} y {abs(catalogo['umbral_oferta']):.0f} %. Sin cambio: menos de {catalogo['umbral_cambio']:.0f} %.
- Precios publicados en línea, de contado, sin envío, en dólares (USD). El precio en tienda física o a crédito puede variar.
- Proyecto independiente, sin relación con las tiendas. Los datos se capturan dos veces al día.

## Páginas

- [Ofertas reales de hoy]({SITIO}/ofertas/): {len(ofertas)} ofertas reales y {len(leves)} bajas leves, con precio y línea base
{lineas_cat}

## Datos abiertos

- [ofertas.json]({SITIO}/data/ofertas.json): ofertas reales y bajas leves de hoy, con campos con nombre
- [catalogo.json]({SITIO}/data/catalogo.json): catálogo completo compacto; las estadísticas de cada producto van en
  una lista posicional cuyo orden está en "formato.s", y las URLs sin el prefijo de su tienda ("tiendas[].prefijo")
- historial/<tienda>.json ({SITIO}/data/historial/siman.json, …): historial por SKU como [fecha, precio, tachado, disponible]

## Optional

- [Código fuente y metodología]({REPO})
""")

    # /sitemap.xml
    urls = [(SITIO + "/", hoy), (SITIO + "/ofertas/", hoy)] + [(f"{SITIO}/categoria/{cid}/", hoy)
                                                               for cid, _, _ in categorias]
    _escribir(dir_web / "sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
              + "".join(f"  <url><loc>{u}</loc><lastmod>{d}</lastmod></url>\n" for u, d in urls)
              + "</urlset>\n")
    return {"ofertas": len(ofertas), "bajas_leves": len(leves), "categorias": len(categorias)}
