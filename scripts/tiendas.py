# -*- coding: utf-8 -*-
"""
Lectura de precios en cada comercial.

Cada tienda expone el mismo catalogo que usa su propio sitio web:
    siman, walmart      VTEX         /api/catalog_system/pub/products/search
    curacao, radioshack Magento      /graphql (Unicomer: comparten SKUs)
    prado, epa          Algolia      indice publico de busqueda del sitio
    omnisport           HTML         paginas de categoria y de producto
    zonadigital         API JSON     apizd.zonadigitalsv.com (la que usa su pagina Vue)
    aeon                HTML Odoo    /shop?search=... con datos schema.org
    vidri               Doofinder    API publica del buscador del sitio (por termino de busqueda)
    coopesa             WooCommerce  Store API publica /wp-json/wc/store/v1/products
    electronica2001     HTML         paginas de categoria + /api/v01/processingRequests.php por codigo

consultar(comercial, sku, url) -> precio actual de un SKU:
    {precio, precio_lista, disponible, nombre, nota}
barrer(comercial, filtros) -> todas las TV y camas de la tienda:
    [{sku, nombre, url, marca, precio, precio_lista, disponible, nota}, ...]
Ambas lanzan ErrorTienda si no se pudo leer.

Sin dependencias externas.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

AGENTE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
TIEMPO = 20
_LIMITE: float | None = None  # hora limite del barrido de la tienda actual (ver fijar_limite)
ZONA_SV = timezone(timedelta(hours=-6))

VTEX = {
    "siman": "https://sv.siman.com",
    "walmart": "https://www.walmart.com.sv",
}
# rutas de categoria (o busquedas de texto con "ft=") que cubren TV y camas
VTEX_BARRIDO = {
    "siman": ["tecnologia/pantallas?map=c,c", "muebles/camas?map=c,c", "muebles/colchones?map=c,c"],
    "walmart": [
        "electronica/televisores/pantallas?map=c,c,c",
        "articulos-para-el-hogar/colchones-y-blancos/colchones?map=c,c,c",
        "?ft=cama%20matrimonial",
        "?ft=set%20de%20cama",
    ],
}
MAGENTO = {
    "curacao": ("https://www.lacuracaonline.com/elsalvador", "lco_el_salvador_sv", [4705, 546, 618]),
    "radioshack": ("https://www.radioshackla.com/elsalvador", "rso_el_salvador_sv", [1476]),
}
CURACAO_GRAPHQL = MAGENTO["curacao"][0] + "/graphql"
CURACAO_STORE = MAGENTO["curacao"][1]
OMNISPORT_CATEGORIAS = ["smart-tv", "4k-tv-y-8k-tv", "oled-tv", "qled-tv-y-qned-tv", "camas", "colchones"]
ZD_API = "https://apizd.zonadigitalsv.com/api/"
ZD_WEB = "https://zonadigitalsv.com/product/"
AEON_WEB = "https://aeon.com.sv"
# categorias de aeon.com.sv que cubren lo que se sigue (Odoo incluye las subcategorias)
AEON_CATEGORIAS = [
    "perifericos-monitores-487", "smart-life-smart-tv-557", "muebles-sillas-553", "consola-video-juego-571",
    "componentes-memoria-ram-477", "almacenamiento-ssd-397", "almacenamiento-m-2-476", "computadoras-laptops-423",
    "perifericos-teclados-408", "perifericos-combo-teclado-y-mouse-449", "audifonos-579",
    "perifericos-headset-gaming-465", "perifericos-mouse-gaming-493", "accesorios-accesorios-para-consola-589",
]
VIDRI_BUSCAR = "https://us1-search.doofinder.com/6/b4d8961c442269cb15909f69bc6cfd6c/_search"
_VIDRI_CABECERAS = {"Origin": "https://www.vidri.com.sv", "Referer": "https://www.vidri.com.sv/"}
COOPESA_API = "https://www.coopesa.com.sv/wp-json/wc/store/v1/products"
E2001_WEB = "https://electronica2001es.com/"
# claves de catalogo.php?key=... de electronica2001es.com que cubren lo que se sigue
E2001_CATEGORIAS = [
    "GUITARRAACUSTICA", "GUITARRAELECTRICA", "GUITARRAELECTROACUSTICA", "COMBOSGUITARRA", "BAJOELECTRICO4",
    "BAJOELECTRICO5", "COMBOSBAJOS", "TECLADOSSINTETIZADORESPIANOS", "BATELECTRONICAS", "BATERIAS",
    "AMPLIFICADORGUITARRA", "AMPLIFICADORBAJO", "AMPTECLAS", "MICROFONOSALAMBRICOS", "MICROFONOSINALAMBRICOS",
    "UKELELE", "AUDIFONOS",
]
PAUSA = 0.3  # segundos entre paginas durante un barrido
PRADO_APP = "WLT832EA3J"
PRADO_KEY = "YTYwZjI3ODFjOTI3YWQ0MjJmYzQ3ZjBiNmY1Y2FiYjRhZjNiMmM3NmMxYTMyNDUwOGUxYjhkMWFhMzFlOGExNnRhZ0ZpbHRlcnM9"
PRADO_INDICE = "monge_upgrade_prod_prado_sv_products"

# VTEX marca los productos sin precio con 10,000,000
PRECIO_CENTINELA = 1_000_000


class ErrorTienda(Exception):
    pass


def soportado(comercial: str) -> bool:
    return comercial in VTEX or comercial in MAGENTO or comercial in ALGOLIA or comercial in (
        "omnisport", "zonadigital", "aeon", "vidri", "coopesa", "electronica2001")


COMERCIALES_BARRIDO = list(VTEX) + list(MAGENTO) + ["prado", "epa", "omnisport", "zonadigital", "aeon", "vidri",
                                                    "coopesa", "electronica2001"]


def fijar_limite(segundos: float | None) -> None:
    """Tiempo maximo para el barrido de una tienda: si una tienda no responde (o bloquea
    al servidor que captura), se corta y se sigue con las demas. None quita el limite."""
    global _LIMITE
    _LIMITE = time.time() + segundos if segundos else None


def _pedir(url: str, datos: dict | None = None, cabeceras: dict | None = None):
    if _LIMITE and time.time() > _LIMITE:
        raise ErrorTienda("se agoto el tiempo de la tienda")
    h = {"User-Agent": AGENTE, "Accept": "application/json, text/html"}
    h.update(cabeceras or {})
    cuerpo = None
    if datos is not None:
        cuerpo = json.dumps(datos).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=cuerpo, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIEMPO) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:  # red, HTTP, timeout
        raise ErrorTienda(f"{type(e).__name__}: {e}") from None


def _numero(texto) -> float | None:
    if texto is None:
        return None
    t = re.sub(r"[^\d.,]", "", str(texto)).replace(",", "")
    return round(float(t), 2) if t else None


# --------------------------------------------------------------------------- #
# VTEX (Siman, Walmart)
# --------------------------------------------------------------------------- #
def _vtex_item(base: str, p: dict, item: dict) -> dict:
    vendedores = item.get("sellers") or [{}]
    oferta = vendedores[0].get("commertialOffer") or {}
    precio = oferta.get("Price") or 0
    lista = oferta.get("ListPrice") or 0
    nombre = p.get("productName", "")
    variante = item.get("name", "")
    # en camas la variante dice la medida ("CAMA MATRIMONIAL ..."); se agrega si aporta algo
    if variante and variante.lower() not in nombre.lower():
        nombre = f"{nombre} — {variante}"
    # a veces la medida solo esta en el atributo de la variante ("Tamaño de cama": ["Queen"])
    tamanos = [v for k in item.get("variations", []) if "tama" in k.lower() for v in item.get(k, [])]
    if tamanos and not any(t.lower() in nombre.lower() for t in tamanos):
        nombre = f"{nombre} ({', '.join(tamanos)})"
    if precio <= 0 or precio >= PRECIO_CENTINELA:
        return {"sku": str(item["itemId"]), "nombre": nombre, "marca": p.get("brand", ""),
                "url": f"{base}/{p.get('linkText', '')}/p", "precio": None, "precio_lista": None,
                "disponible": False, "nota": "sin precio publicado"}
    return {
        "sku": str(item["itemId"]),
        "nombre": nombre,
        "marca": p.get("brand", ""),
        "url": f"{base}/{p.get('linkText', '')}/p",
        "precio": round(precio, 2),
        "precio_lista": round(lista, 2) if lista and lista < PRECIO_CENTINELA else None,
        "disponible": (oferta.get("AvailableQuantity") or 0) > 0,
        "nota": "",
    }


def _vtex(base: str, sku: str) -> dict:
    texto = _pedir(f"{base}/api/catalog_system/pub/products/search?fq=skuId:{urllib.parse.quote(sku)}")
    for p in json.loads(texto):
        for item in p.get("items", []):
            if str(item.get("itemId")) == str(sku):
                return _vtex_item(base, p, item)
    raise ErrorTienda(f"SKU {sku} no aparece en el catalogo")


def _vtex_barrer(base: str, rutas: list) -> list:
    vistos: dict[str, dict] = {}
    for ruta in rutas:
        sep = "&" if "?" in ruta else "?"
        for desde in range(0, 2500, 50):
            url = f"{base}/api/catalog_system/pub/products/search/{ruta}{sep}_from={desde}&_to={desde + 49}"
            try:
                productos = json.loads(_pedir(url))
            except ErrorTienda:  # un termino que la tienda no acepta no tumba el resto del barrido
                break
            for p in productos:
                for item in p.get("items", []):
                    vistos.setdefault(str(item["itemId"]), _vtex_item(base, p, item))
            time.sleep(PAUSA)
            if len(productos) < 50:
                break
    return list(vistos.values())


# --------------------------------------------------------------------------- #
# Magento (La Curacao, RadioShack)
# --------------------------------------------------------------------------- #
_CAMPOS_MAGENTO = """items { sku name url_key stock_status
      price_range { minimum_price { regular_price { value } final_price { value } } } }"""


def _magento_item(base: str, it: dict) -> dict:
    mp = it["price_range"]["minimum_price"]
    final = mp["final_price"]["value"]
    regular = mp["regular_price"]["value"]
    return {
        "sku": it["sku"],
        "nombre": it["name"],
        "marca": "",
        "url": f"{base}/{it['url_key']}/p" if it.get("url_key") else "",
        "precio": round(float(final), 2) if final else None,
        "precio_lista": round(float(regular), 2) if regular else None,
        "disponible": it.get("stock_status") == "IN_STOCK",
        "nota": "",
    }


def _magento_pedir(comercial: str, consulta: str, variables: dict) -> dict:
    base, tienda, _ = MAGENTO[comercial]
    datos = json.loads(_pedir(f"{base}/graphql", {"query": consulta, "variables": variables}, {"Store": tienda}))
    if datos.get("errors"):
        raise ErrorTienda(datos["errors"][0].get("message", "error GraphQL"))
    return datos["data"]["products"]


def _magento(comercial: str, sku: str) -> dict:
    consulta = "query($s:String!){ products(filter:{sku:{eq:$s}}){ " + _CAMPOS_MAGENTO + " } }"
    for it in _magento_pedir(comercial, consulta, {"s": sku})["items"]:
        if it["sku"] == sku:
            return _magento_item(MAGENTO[comercial][0], it)
    raise ErrorTienda(f"SKU {sku} no aparece en el catalogo")


def _magento_barrer(comercial: str, terminos: list) -> list:
    base, _, categorias = MAGENTO[comercial]
    por_categoria = ("query($c:String!,$p:Int!){ products(filter:{category_id:{eq:$c}}, pageSize:100, currentPage:$p)"
                     "{ total_count " + _CAMPOS_MAGENTO + " } }")
    por_texto = ("query($s:String!,$p:Int!){ products(search:$s, pageSize:100, currentPage:$p)"
                 "{ total_count " + _CAMPOS_MAGENTO + " } }")
    pedidos = [(por_categoria, {"c": str(c)}) for c in categorias] + [(por_texto, {"s": t}) for t in terminos]
    vistos: dict[str, dict] = {}
    for consulta, variables in pedidos:
        for pagina in range(1, 30):
            res = _magento_pedir(comercial, consulta, {**variables, "p": pagina})
            for it in res["items"]:
                vistos.setdefault(it["sku"], _magento_item(base, it))
            time.sleep(PAUSA)
            if pagina * 100 >= res["total_count"]:
                break
    return list(vistos.values())


# --------------------------------------------------------------------------- #
# Algolia sobre Magento (Prado, EPA): el indice publico que usa el buscador de cada sitio
# --------------------------------------------------------------------------- #
ALGOLIA = {
    "prado": {
        "app": PRADO_APP, "key": PRADO_KEY, "indice": PRADO_INDICE, "referer": "https://www.prado.com.sv/",
        "facetas": [["categoria:TV y Video", "categoria:Camas y Colchones"]],
    },
    "epa": {
        "app": "D8WPXV9MEC",
        "key": "MmIxYjA5Y2Y5ZDU5NzdlNWYyMTRiODUwN2RkOGI3NTU0ODUwOGY0Mzk4ZjgyNzY5NGNmOTZiOTdlM2QyZTMzNnRhZ0ZpbHRlcnM9",
        "indice": "prodsv_Soyapango_products",  # precios de la sucursal Soyapango (los muestra el sitio por defecto)
        "referer": "https://sv.epaenlinea.com/",
        "facetas": None,
    },
}


def _algolia_buscar(comercial: str, params: str) -> list:
    cfg = ALGOLIA[comercial]
    texto = _pedir(
        f"https://{cfg['app']}-dsn.algolia.net/1/indexes/{cfg['indice']}/query",
        {"params": params},
        {"X-Algolia-Application-Id": cfg["app"], "X-Algolia-API-Key": cfg["key"], "Referer": cfg["referer"]},
    )
    return json.loads(texto).get("hits", [])


def _algolia_item(comercial: str, h: dict) -> dict:
    usd = h.get("price", {}).get("USD", {})
    nota = ""
    fin = usd.get("special_to_date")
    if fin and str(fin).isdigit():
        # Magento guarda el fin de la promo como medianoche UTC del dia siguiente
        dia = datetime.fromtimestamp(int(fin), ZONA_SV).date()
        nota = f"promo vigente hasta {dia.isoformat()}"
    marca = h.get("marca")
    return {
        "sku": str(h.get("sku")),
        "nombre": h.get("name", ""),
        "marca": marca if isinstance(marca, str) else "",
        "url": h.get("url", ""),
        "precio": _numero(usd.get("default")),
        "precio_lista": _numero(usd.get("default_original_formated")),
        "disponible": bool(h.get("in_stock")),
        "nota": nota,
    }


def _algolia(comercial: str, sku: str) -> dict:
    for h in _algolia_buscar(comercial, f"query={urllib.parse.quote(sku)}&hitsPerPage=10"):
        if str(h.get("sku")) == str(sku):
            return _algolia_item(comercial, h)
    raise ErrorTienda(f"SKU {sku} no aparece en el indice")


def _algolia_barrer(comercial: str, terminos: list) -> list:
    hits = []
    facetas = ALGOLIA[comercial]["facetas"]
    if facetas:
        filtro = urllib.parse.quote(json.dumps(facetas))
        hits += _algolia_buscar(comercial, f"query=&hitsPerPage=1000&facetFilters={filtro}")
    for t in terminos:
        hits += _algolia_buscar(comercial, f"query={urllib.parse.quote(t)}&hitsPerPage=1000")
        time.sleep(PAUSA)
    vistos: dict[str, dict] = {}
    for h in hits:
        vistos.setdefault(str(h.get("sku")), _algolia_item(comercial, h))
    return list(vistos.values())


# --------------------------------------------------------------------------- #
# Omnisport (HTML)
# --------------------------------------------------------------------------- #
def _omnisport(url: str) -> dict:
    if not url:
        raise ErrorTienda("Omnisport necesita la url del producto")
    fuente = _pedir(url)
    titulo = re.search(r"<title>(.*?)</title>", fuente, re.S)
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", fuente, flags=re.S)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    promo = re.search(r"Promoci.n: \$ ?([\d,]+)\. ?(\d\d)", t)
    regular = re.search(r"Regular \$ ?([\d,]+\.\d\d)", t)
    simple = re.search(r"Precio:? \$ ?([\d,]+)\. ?(\d\d)", t)
    sku = re.search(r"SKU: (\d+)", t)
    if promo:
        precio = _numero(f"{promo.group(1)}.{promo.group(2)}")
    elif simple:
        precio = _numero(f"{simple.group(1)}.{simple.group(2)}")
    else:
        precio = None
    # la ficha principal esta al inicio; "Agotado" mas abajo suele ser de productos sugeridos
    cabeza = t[: t.find("Cantidad")] if "Cantidad" in t else t[:4000]
    return {
        "sku": sku.group(1) if sku else url.rstrip("/").rsplit("/", 1)[-1],
        "nombre": html.unescape(titulo.group(1)).split("| Omnisport")[0].strip() if titulo else "",
        "marca": "",
        "url": url,
        "precio": precio,
        "precio_lista": _numero(regular.group(1)) if regular else None,
        "disponible": precio is not None and "Agotado" not in cabeza,
        "nota": "",
    }


def _omnisport_slugs_140(slug: str) -> list:
    """Omnisport solo lista la medida mas chica; la de 1.40 m se deduce del enlace."""
    if re.search(r"junior|kidz|combo|nino|nina", slug):
        return []
    if re.search(r"-full|-140-m", slug):
        return [slug]
    candidatos = []
    if "twin" in slug:
        candidatos.append(slug.replace("twin", "full"))
    if "-100-mt" in slug:
        candidatos += [slug.replace("-100-mt", "-140-mt"), slug.replace("-100-mt", "-140-mts"),
                       slug.replace("-100-mt", "-140-m")]
    elif "-100-m" in slug:
        candidatos.append(slug.replace("-100-m", "-140-m"))
    if slug.endswith("-queen"):
        candidatos.append(slug[: -len("-queen")] + "-full")
    return candidatos


def _omnisport_barrer(filtros: dict) -> list:
    tv = filtros.get("tv", {})
    pmin, pmax = tv.get("pulgadas_min", 0), tv.get("pulgadas_max", 999)
    # categorias extra de productos.json ("omnisport": ["monitores"]): se toman todos sus productos
    extra = [c for cfg in filtros.values() for c in cfg.get("omnisport", [])]
    slugs: list[str] = []
    for cat in OMNISPORT_CATEGORIAS + extra:
        for pagina in range(1, 20):
            fuente = _pedir(f"https://omnisport.com/categorias/{cat}?page={pagina}")
            nuevos = sorted(set(re.findall(r"omnisport\.com/productos/([a-z0-9-]+)", fuente)))
            time.sleep(PAUSA)
            if not nuevos:
                break
            for s in nuevos:
                if cat in extra:
                    if s not in slugs:
                        slugs.append(s)
                elif cat in ("camas", "colchones"):
                    if s.startswith(("cama-", "colchon-")):
                        slugs += [c for c in _omnisport_slugs_140(s) if c not in slugs]
                else:
                    m = re.search(r"-(\d{2,3})$", s)
                    if m and pmin <= int(m.group(1)) <= pmax and s not in slugs:
                        slugs.append(s)
    salida = []
    for s in slugs:
        try:
            salida.append(_omnisport(f"https://omnisport.com/productos/{s}"))
        except ErrorTienda:
            pass  # la medida deducida no existe para ese modelo
        time.sleep(PAUSA)
    return salida


# --------------------------------------------------------------------------- #
# Zona Digital (API JSON)
# --------------------------------------------------------------------------- #
_ZD_CABECERAS = {"Origin": "https://zonadigitalsv.com", "Referer": "https://zonadigitalsv.com/"}
_ZD_FILTROS = {
    "offer_id": None, "search": "", "categorie_id": None, "show_marca": None, "min_price": None,
    "max_price": None, "marcas_selected": [], "categories_add_selected": [], "show_categorie": None,
    "size_page": 48, "tag_selected": [], "slug_tags": None, "categorie_second_id": None,
    "categorie_third_id": None, "is_marca_general": None, "marca_id": None, "is_best_sellers": None,
}


def _zd_item(p: dict, oferta: dict | None) -> dict:
    """Precio final como lo calcula su pagina: promo del producto (discount_g) o la oferta vigente."""
    general = round(float(p.get("precio_general") or 0), 2)
    promo = p.get("discount_g") or oferta
    precio, nota = general, ""
    if promo:
        info = promo.get("discount") if isinstance(promo.get("discount"), dict) else promo
        if promo.get("new_amount"):
            precio = round(float(promo["new_amount"]), 2)
        elif info.get("type_discount") == 1:
            precio = round(general * (1 - float(info.get("discount") or 0) / 100), 2)
        else:
            precio = round(general - float(info.get("discount") or 0), 2)
        fin = promo.get("date_to") or info.get("date_to") or ""
        nota = f"promo '{info.get('title', '')}' hasta {fin[:10]}".strip()
    sucursales = p.get("sucursales")
    disponible = any(float(s.get("stock") or 0) > 0 for s in sucursales) if sucursales else True
    marca = p.get("marca")
    return {
        "sku": str(p["id"]),
        "nombre": p.get("title", ""),
        "marca": marca.get("name", "") if isinstance(marca, dict) else "",
        "url": ZD_WEB + p.get("slug", ""),
        "precio": precio if precio > 0 else None,
        "precio_lista": general if precio < general else (round(float(p["old_price"]), 2) if p.get("old_price") else None),
        "disponible": disponible,
        "nota": nota,
    }


def _zonadigital(url: str) -> dict:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    if not slug:
        raise ErrorTienda("Zona Digital necesita la url del producto")
    datos = json.loads(_pedir(ZD_API + "ecommerce/show_product/" + urllib.parse.quote(slug), cabeceras=_ZD_CABECERAS))
    if not datos.get("product"):
        raise ErrorTienda("producto no encontrado")
    return _zd_item(datos["product"], datos.get("OFFER"))


def _zonadigital_barrer() -> list:
    """Su buscador corta en ~40 resultados; el catalogo completo son ~1,400 productos: se recorre entero."""
    vistos: dict[str, dict] = {}
    for pagina in range(1, 100):
        datos = json.loads(_pedir(ZD_API + f"ecommerce/filters/?page={pagina}", _ZD_FILTROS, _ZD_CABECERAS))
        ofertas = {o.get("product_id"): o for o in datos.get("productos_offers") or []}
        for p in datos["products"]["data"]:
            vistos.setdefault(str(p["id"]), _zd_item(p, ofertas.get(p["id"])))
        time.sleep(PAUSA)
        if pagina >= int(datos.get("total_pages") or 1):
            break
    return list(vistos.values())


# --------------------------------------------------------------------------- #
# AEON (Odoo)
# --------------------------------------------------------------------------- #
def _aeon_valor(texto: str) -> float | None:
    m = re.search(r'oe_currency_value">\s*([\d,]+\.?\d*)', texto)
    return _numero(m.group(1)) if m else None


def _aeon_bloques(fuente: str) -> list:
    salida = []
    for bloque in fuente.split('data-product-template-id="')[1:]:
        tid = bloque.split('"', 1)[0]
        enlace = re.search(r'itemprop="url" href="([^"]+)"', bloque)
        nombre = re.search(r'itemprop="name"[^>]*content="([^"]*)"', bloque) or \
            re.search(r'itemprop="name"[^>]*>\s*([^<]+?)\s*<', bloque)
        precio = re.search(r'itemprop="price"[^>]*>\s*([\d.]+)\s*<', bloque)
        base = re.search(r"base_price&#39;\]\"[^>]*>(.*?)</span>\s*</span>", bloque, re.S)
        if not (enlace and nombre and precio):
            continue
        p = round(float(precio.group(1)), 2)
        lista = _aeon_valor(base.group(1)) if base else None
        salida.append({
            "sku": tid,
            "nombre": html.unescape(nombre.group(1)).strip(),
            "marca": "",
            "url": AEON_WEB + enlace.group(1).split("?", 1)[0],
            "precio": p if p > 0 else None,
            "precio_lista": lista if lista and lista > p else None,
            "disponible": True,
            "nota": "",
        })
    return salida


def _aeon(url: str) -> dict:
    if not url:
        raise ErrorTienda("AEON necesita la url del producto")
    fuente = _pedir(url)
    precio = re.search(r'itemprop="price"[^>]*>\s*([\d.]+)\s*<', fuente) or \
        re.search(r'"price":\s*"?([\d.]+)', fuente)
    nombre = re.search(r'<h1[^>]*itemprop="name"[^>]*>\s*(.*?)\s*</h1>', fuente, re.S) or \
        re.search(r"<title>(.*?)</title>", fuente, re.S)
    base = re.search(r"base_price&#39;\]\"[^>]*>(.*?)</span>\s*</span>", fuente, re.S)
    if not precio:
        raise ErrorTienda("no encontre el precio en la pagina")
    p = round(float(precio.group(1)), 2)
    lista = _aeon_valor(base.group(1)) if base else None
    tid = re.search(r"-(\d+)/?$", url.split("?", 1)[0])
    return {
        "sku": tid.group(1) if tid else url,
        "nombre": html.unescape(re.sub(r"<[^>]+>", "", nombre.group(1))).split("|")[0].strip() if nombre else "",
        "marca": "",
        "url": url,
        "precio": p,
        "precio_lista": lista if lista and lista > p else None,
        "disponible": not re.search(r"Agotado|Sin existencias|Out of stock", fuente[:200000]),
        "nota": "",
    }


def _aeon_barrer() -> list:
    vistos: dict[str, dict] = {}
    for cat in AEON_CATEGORIAS:
        for pagina in range(1, 30):
            ruta = f"/shop/category/{cat}" + ("" if pagina == 1 else f"/page/{pagina}")
            items = _aeon_bloques(_pedir(f"{AEON_WEB}{ruta}?ppg=100"))
            nuevos = [i for i in items if i["sku"] not in vistos]
            for i in items:
                vistos.setdefault(i["sku"], i)
            time.sleep(PAUSA)
            if len(items) < 100 or not nuevos:
                break
    return list(vistos.values())


# --------------------------------------------------------------------------- #
# Vidri (Doofinder: el buscador del sitio)
# --------------------------------------------------------------------------- #
def _vidri_item(r: dict) -> dict:
    precio = r.get("sale_price") or r.get("price")
    lista = r.get("price")
    return {
        "sku": str(r["id"]),
        "nombre": html.unescape(r.get("title", "")).strip(),
        "marca": r.get("brand") or "",
        "url": r.get("link", ""),
        "precio": round(float(precio), 2) if precio else None,
        "precio_lista": round(float(lista), 2) if lista and precio and float(lista) > float(precio) else None,
        "disponible": r.get("availability") == "In stock",
        "nota": "",
    }


def _vidri_buscar(consulta: str, pagina: int = 1) -> dict:
    params = urllib.parse.urlencode({"query": consulta, "rpp": 100, "page": pagina})
    return json.loads(_pedir(f"{VIDRI_BUSCAR}?{params}", cabeceras=_VIDRI_CABECERAS))


def _vidri(sku: str) -> dict:
    for r in _vidri_buscar(sku).get("results", []):
        if str(r.get("id")) == str(sku):
            return _vidri_item(r)
    raise ErrorTienda(f"SKU {sku} no aparece en el buscador")


def _vidri_barrer(terminos: list) -> list:
    """Doofinder corta cada busqueda en 1,000 resultados (10 paginas de 100): se busca por termino."""
    vistos: dict[str, dict] = {}
    for t in terminos:
        for pagina in range(1, 11):
            datos = _vidri_buscar(t, pagina)
            for r in datos.get("results", []):
                vistos.setdefault(str(r["id"]), _vidri_item(r))
            time.sleep(PAUSA)
            if not datos.get("results") or pagina * 100 >= int(datos.get("total") or 0):
                break
    return list(vistos.values())


# --------------------------------------------------------------------------- #
# COOPESA (WooCommerce Store API)
# --------------------------------------------------------------------------- #
def _coopesa_item(p: dict) -> dict:
    pr = p.get("prices") or {}
    div = 10 ** int(pr.get("currency_minor_unit") or 2)
    precio = int(pr.get("price") or 0) / div
    regular = int(pr.get("regular_price") or 0) / div
    return {
        "sku": str(p["id"]),
        "nombre": html.unescape(p.get("name", "")).strip(),
        "marca": "",
        "url": p.get("permalink", ""),
        "precio": round(precio, 2) if precio > 0 else None,
        "precio_lista": round(regular, 2) if regular > precio else None,
        "disponible": bool(p.get("is_in_stock")),
        "nota": "",
    }


def _coopesa(sku: str) -> dict:
    return _coopesa_item(json.loads(_pedir(f"{COOPESA_API}/{urllib.parse.quote(sku)}")))


def _coopesa_barrer() -> list:
    """El catalogo completo son ~600 productos: se recorre entero."""
    vistos: dict[str, dict] = {}
    for pagina in range(1, 50):
        productos = json.loads(_pedir(f"{COOPESA_API}?per_page=100&page={pagina}"))
        for p in productos:
            vistos.setdefault(str(p["id"]), _coopesa_item(p))
        time.sleep(PAUSA)
        if len(productos) < 100:
            break
    return list(vistos.values())


# --------------------------------------------------------------------------- #
# Electronica 2001 (HTML de categorias; API JSON por codigo)
# --------------------------------------------------------------------------- #
def _e2001_url(codigo: str) -> str:
    # no hay pagina por producto: su buscador con el codigo muestra solo ese producto
    return f"{E2001_WEB}search2.php?js={urllib.parse.quote(codigo)}"


def _e2001_nombre(texto: str) -> str:
    """Quita el numero de parte del inicio ("0970150032 CC-60S GUIT..." -> "CC-60S GUIT...")."""
    t = re.sub(r"\s+", " ", html.unescape(texto)).strip()
    return re.sub(r"^(\d{6,}(:\w+)?( / \d{6,})?\s+)+", "", t)


def _e2001_bloques(fuente: str) -> list:
    salida = []
    for bloque in fuente.split('class="product-details"')[1:]:
        nombre = re.search(r'product-title">\s*<a[^>]*>([^<]+)', bloque)
        codigo = re.search(r'name="code" value="([^"]+)"', bloque)
        precio = re.search(r'product-price">\s*\$ ?([\d,.]+)', bloque)
        if not (nombre and codigo):
            continue
        p = _numero(precio.group(1)) if precio else None
        salida.append({
            "sku": codigo.group(1).strip(),
            "nombre": _e2001_nombre(nombre.group(1)),
            "marca": "",
            "url": _e2001_url(codigo.group(1).strip()),
            "precio": p if p else None,
            "precio_lista": None,
            "disponible": True,  # el listado no publica existencias
            "nota": "",
        })
    return salida


def _e2001(sku: str) -> dict:
    texto = _pedir(f"{E2001_WEB}api/v01/processingRequests.php?code={urllib.parse.quote(sku)}")
    # responde el JSON envuelto en <p>...</p>
    m = re.search(r"\{.*\}", html.unescape(texto), re.S)
    datos = json.loads(m.group(0)) if m else {}
    if not datos.get("code"):
        raise ErrorTienda(datos.get("error") or f"codigo {sku} no encontrado")
    precio = _numero(datos.get("price"))
    return {
        "sku": datos["code"].strip(),
        "nombre": _e2001_nombre(datos.get("description", "")),
        "marca": "",
        "url": _e2001_url(datos["code"].strip()),
        "precio": precio if precio else None,
        "precio_lista": None,
        "disponible": float(datos.get("stock") or 0) > 0,
        "nota": "",
    }


def _e2001_barrer() -> list:
    vistos: dict[str, dict] = {}
    for cat in E2001_CATEGORIAS:
        for pagina in range(1, 30):
            items = _e2001_bloques(_pedir(f"{E2001_WEB}catalogo.php?key={cat}&pagina={pagina}"))
            nuevos = [i for i in items if i["sku"] not in vistos]
            for i in nuevos:
                vistos[i["sku"]] = i
            time.sleep(PAUSA)
            if not nuevos:  # despues de la ultima pagina repite la anterior o sale vacia
                break
    return list(vistos.values())


# --------------------------------------------------------------------------- #
# Entrada publica
# --------------------------------------------------------------------------- #
def consultar(comercial: str, sku: str, url: str = "") -> dict:
    if comercial in VTEX:
        return _vtex(VTEX[comercial], sku)
    if comercial in MAGENTO:
        return _magento(comercial, sku)
    if comercial in ALGOLIA:
        return _algolia(comercial, sku)
    if comercial == "omnisport":
        return _omnisport(url)
    if comercial == "zonadigital":
        return _zonadigital(url)
    if comercial == "aeon":
        return _aeon(url)
    if comercial == "vidri":
        return _vidri(sku)
    if comercial == "coopesa":
        return _coopesa(sku)
    if comercial == "electronica2001":
        return _e2001(sku)
    raise ErrorTienda(f"no se como consultar '{comercial}' automaticamente")


def terminos_busqueda(filtros: dict) -> list:
    """Palabras que se buscan por texto en cada tienda ("buscar" de cada categoria en productos.json)."""
    salida: list[str] = []
    for cfg in filtros.values():
        for t in cfg.get("buscar", []):
            if t not in salida:
                salida.append(t)
    return salida


def barrer(comercial: str, filtros: dict | None = None) -> list:
    """TV y camas por categoria de la tienda, mas las busquedas de texto de las otras categorias."""
    filtros = filtros or {}
    terminos = terminos_busqueda(filtros)
    if comercial in VTEX:
        rutas = VTEX_BARRIDO[comercial] + [f"?ft={urllib.parse.quote(t)}" for t in terminos]
        return _vtex_barrer(VTEX[comercial], rutas)
    if comercial in MAGENTO:
        return _magento_barrer(comercial, terminos)
    if comercial in ALGOLIA:
        return _algolia_barrer(comercial, terminos)
    if comercial == "omnisport":
        return _omnisport_barrer(filtros)
    if comercial == "zonadigital":
        return _zonadigital_barrer()
    if comercial == "aeon":
        return _aeon_barrer()
    if comercial == "vidri":
        return _vidri_barrer(terminos)
    if comercial == "coopesa":
        return _coopesa_barrer()
    if comercial == "electronica2001":
        return _e2001_barrer()
    raise ErrorTienda(f"no hay barrido para '{comercial}'")
