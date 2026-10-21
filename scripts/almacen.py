# -*- coding: utf-8 -*-
"""
Almacen de precios: un archivo por comercial con todos sus productos y su historial.

    data/listados/<comercial>.json
    {
      "comercial": "siman",
      "actualizado": "2026-10-20T11:30:00-06:00",
      "listados": {
        "<sku>": {
          "nombre": "...", "categoria": "tv" | "cama", "tipo": "tv" | "set" | "colchon",
          "pulgadas": 55, "medida": "matrimonial", "marca": "Samsung", "modelo": "UN55U8000HPXPA",
          "url": "...", "primera_vez": "2026-10-20", "ultima_vez": "2026-10-20",
          "observaciones": [
            {"fecha": "...", "precio": 409.0, "precio_lista": 569.0, "disponible": true,
             "fuente": "auto" | "manual", "nota": ""}
          ]
        }
      }
    }

Tambien: clasificacion de nombres (TV de N pulgadas, cama matrimonial), palabras que
filtran categoria en el buscador y estadisticas (linea base = mediana antes del corte).
La busqueda y el veredicto de la web estan en web/app.js.

Sin dependencias externas.
"""

from __future__ import annotations

import json
import re
import statistics
import threading
import time
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DIR_LISTADOS = RAIZ / "data" / "listados"

UMBRAL_OFERTA = -10.0  # % bajo la linea base para considerar la oferta "real"
UMBRAL_CAMBIO = 3.0    # % para considerar que el precio no se movio

CANDADO = threading.RLock()  # protege lecturas y escrituras cuando hay varios hilos (servidor)
_CACHE: dict[str, dict] = {}
_MTIME: dict[str, float | None] = {}
_SUCIOS: set[str] = set()  # con cambios en memoria sin guardar: no se recargan desde disco


# --------------------------------------------------------------------------- #
# Archivos
# --------------------------------------------------------------------------- #
def ruta(comercial: str) -> Path:
    return DIR_LISTADOS / f"{comercial}.json"


def _reintentar(funcion, intentos: int = 10):
    """OneDrive (o un antivirus) puede bloquear el archivo unos instantes mientras lo sincroniza."""
    for i in range(intentos):
        try:
            return funcion()
        except PermissionError:
            if i == intentos - 1:
                raise
            time.sleep(0.5)


def _leer(r: Path) -> dict:
    with r.open("r", encoding="utf-8") as f:
        return json.load(f)


def cargar(comercial: str) -> dict:
    """Lee el archivo de la tienda; si otro proceso lo cambio en disco, lo vuelve a leer."""
    with CANDADO:
        r = ruta(comercial)
        mtime = r.stat().st_mtime if r.exists() else None
        if comercial not in _CACHE or (_MTIME.get(comercial) != mtime and comercial not in _SUCIOS):
            if mtime is not None:
                _CACHE[comercial] = _reintentar(lambda: _leer(r))
            else:
                _CACHE[comercial] = {"comercial": comercial, "actualizado": None, "listados": {}}
            _MTIME[comercial] = mtime
        return _CACHE[comercial]


def guardar(comercial: str) -> None:
    with CANDADO:
        datos = cargar(comercial)
        r = ruta(comercial)
        r.parent.mkdir(parents=True, exist_ok=True)
        tmp = r.with_suffix(".tmp")

        def escribir():
            with tmp.open("w", encoding="utf-8", newline="\n") as f:
                json.dump(datos, f, ensure_ascii=False, indent=1)
                f.write("\n")
            tmp.replace(r)

        _reintentar(escribir)
        _MTIME[comercial] = r.stat().st_mtime
        _SUCIOS.discard(comercial)


def comerciales_guardados() -> list[str]:
    if not DIR_LISTADOS.exists():
        return []
    return sorted(p.stem for p in DIR_LISTADOS.glob("*.json"))


def todos():
    """Itera (comercial, sku, ficha) sobre todos los archivos."""
    for c in comerciales_guardados():
        for sku, ficha in cargar(c)["listados"].items():
            yield c, sku, ficha


def ficha(comercial: str, sku: str) -> dict | None:
    return cargar(comercial)["listados"].get(sku)


def agregar(comercial: str, sku: str, datos_ficha: dict, observacion: dict,
            forzar: bool = False, guardar_ya: bool = True) -> bool:
    """Registra una observacion. Devuelve False si ya estaba (mismo dia y mismo precio)."""
    with CANDADO:
        datos = cargar(comercial)
        f = datos["listados"].get(sku)
        dia = observacion["fecha"][:10]
        if f is None:
            f = {"nombre": "", "categoria": None, "tipo": None, "pulgadas": None, "medida": None,
                 "marca": "", "modelo": "", "url": "", "primera_vez": dia, "ultima_vez": dia,
                 "observaciones": []}
            datos["listados"][sku] = f
        for k, v in datos_ficha.items():
            if v not in (None, ""):
                f[k] = v
        f["ultima_vez"] = max(f.get("ultima_vez") or dia, dia)

        for o in f["observaciones"]:
            if o["fecha"][:10] == dia and abs(o["precio"] - observacion["precio"]) < 0.005 and not forzar:
                return False
        f["observaciones"].append(observacion)
        f["observaciones"].sort(key=lambda o: o["fecha"])
        datos["actualizado"] = max(datos.get("actualizado") or "", observacion["fecha"])
        _SUCIOS.add(comercial)
        if guardar_ya:
            guardar(comercial)
        return True


# --------------------------------------------------------------------------- #
# Texto
# --------------------------------------------------------------------------- #
def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"(\d)\s*(?:\"|''|pulgadas|pulg|in\b)", r"\1 pulg ", t)
    t = re.sub(r"\b(\d{2}(?:\.\d)?)p\b", r"\1 pulg ", t)  # Zona Digital: "27p", "24.5p"
    t = t.replace("”", " pulg ")
    return re.sub(r"[^a-z0-9.]+", " ", t).strip()


def tokens(texto: str) -> list[str]:
    return [x.strip(".") for x in normalizar(texto).split() if x.strip(".")]


TAMANOS_TV = {32, 40, 42, 43, 48, 50, 55, 58, 60, 65, 70, 75, 77, 83, 85, 86, 98, 100}
_NO_TV = re.compile(
    r"soporte|rack|mueble|mesa para|centro de entretenimiento|control remoto|cable|antena|"
    r"barra de sonido|proyector|monitor|protector|limpiador|panel para|base para|bracket|"
    r"funda|repuesto|lampara|lámpara|consola|tablet|celular|backlight|luz|tira led|smart ?band|"
    r"smartwatch|reloj|watch|roku (express|stick|ultra|streaming)|streaming (player|stick)|chromecast|"
    r"fire tv|tv box|receptor|power ?bank|"
    r"bater[ií]a|laptop|notebook|cargador|govee", re.I)
_SI_TV = re.compile(r"pantalla|televisor|\btv\b|smart tv|oled|qled|uhd|television", re.I)
_NO_CAMA = re.compile(
    r"s[aá]bana|cubrecama|edred[oó]n|almohada|protector|camarote|litera|sof[aá]|respaldo|"
    r"cabecera|inflable|mascota|fald[oó]n|frazada|cobija|cuna|beb[eé]|infantil|junior|kidz|"
    r"juego de rec[aá]mara|gavetero|mesa de noche|tocador|cojin|cojín|topper|cubre colch|"
    r"plum[oó]n|sill[oó]n|reclinable|futon|fut[oó]n|hamaca|ni[ñn][oa]\b", re.I)
_SI_CAMA = re.compile(r"\bcama\b|set de cama|colch[oó]n|box spring|\bbase\b.*colch", re.I)


def pulgadas(nombre: str) -> int | None:
    t = normalizar(nombre)
    m = re.search(r"\b(\d{2,3}) pulg", t)
    if m and int(m.group(1)) in TAMANOS_TV:
        return int(m.group(1))
    # en el codigo del modelo: UN55U8000, 55Q6Q, OLED55C6, K-55S20M2, 43LM6370...
    # (no cuenta "60hz", "60fps", "50kmah", "32gb": son unidades, no pulgadas)
    for m in re.finditer(r"(?:^|[^a-z0-9])(?:un|qn|oled|k|kd|xr|mot|hl|w|rc|dura)?\s?-?(\d{2,3})"
                         r"(?!hz|fps|kmah|mah|gb|tb|mb|mm|cm|ms|w\b|k\b|v\b)[a-z]", t):
        if int(m.group(1)) in TAMANOS_TV:
            return int(m.group(1))
    # "Samsung Smart Tv Mini Led 4k 50"
    m = re.search(r"\b(\d{2,3})$", t)
    if m and int(m.group(1)) in TAMANOS_TV:
        return int(m.group(1))
    return None


def medida_cama(nombre: str) -> str | None:
    t = normalizar(nombre)
    if re.search(r"semi ?matrimonial|semimatrimonial|1\.20|120 ?m\b", t):
        return "semi-matrimonial"
    if re.search(r"\bking\b|1\.80|1\.90|2\.00|180 m|200 m", t):
        return "king"
    if re.search(r"\bque+e?n\b|\bquenn\b|1\.60|1\.52|160 m", t):
        return "queen"
    if re.search(r"matrimonial|\bfull\b|1\.40|140 m|140 mt|1\.35|2 plazas|\bdoble\b(?! pillow)", t):
        return "matrimonial"
    if re.search(r"individual|\btwin\b|1\.00|100 m|imperial|unipersonal|1\.05", t):
        return "individual"
    # Serta en Siman: "COLCHON PERFECT BALANCE FIRM M CEL 467" (I/M/Q/K)
    m = re.search(r"\b([imqk]) cel\b", t)
    if m:
        return {"i": "individual", "m": "matrimonial", "q": "queen", "k": "king"}[m.group(1)]
    return None


def modelo_tv(nombre: str) -> str:
    """Codigo de modelo mas largo con letras y numeros: UN55U8000HPXPA, 55Q6Q, K-55S20M2."""
    candidatos = []
    for tok in re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?", nombre):
        limpio = tok.upper().replace("-", "")
        if (len(limpio) >= 5 and re.search(r"\d", limpio) and re.search(r"[A-Z]", limpio)
                and not re.fullmatch(r"HDR10|\d+K|\d+GB|\d+HZ|\d+P|\d+PULG.*|HDMI\d*|\d{3,4}X\d{3,4}|\d+[A-Z]{4,}",
                                     limpio)):
            candidatos.append(limpio)
    return max(candidatos, key=len) if candidatos else ""


def mismo_modelo(a: str, b: str) -> bool:
    """'UN55U8000' ~ 'UN55U8000HPXPA' (uno es prefijo del otro, minimo 5 caracteres)."""
    if not a or not b:
        return False
    corto, largo = sorted((a, b), key=len)
    return len(corto) >= 5 and largo.startswith(corto)


MARCAS = [
    "Samsung", "LG", "Sony", "TCL", "Hisense", "Xiaomi", "RCA", "Motorola", "Westinghouse", "Hotline",
    "Durabrand", "Dahua", "Philips", "JVC", "Panasonic", "Toshiba", "Sharp", "Vizio", "Onn", "Caixun",
    "Indufoam", "Capri", "Serta", "Simmons", "Sealy", "Therapedic", "Facenco", "Regina", "Olympia",
    "Masterbed", "Master Bed", "King Koil", "Espumar", "Healthy Bed", "Comfort Life", "Beautyrest",
    "Restonic", "Spring Air", "Tempur",
    "Acer", "Asus", "Lenovo", "MSI", "Dell", "HP", "AOC", "BenQ", "Gigabyte", "ViewSonic", "Aiwa",
    "Logitech", "Razer", "Redragon", "Xtech", "Klip Xtreme", "Argom", "Apple", "Microsoft", "Trust",
    "Primus", "HyperX", "Corsair", "SteelSeries", "JLab", "Fantech", "Meetion", "RadioShack",
    "Nintendo", "PlayStation", "Xbox",
    "Mainstays", "Politorno", "Commodity", "Moval Moveis", "Quattro", "Satisa", "Caemmun", "Poquema",
]


# Omnisport no publica la marca: se deduce del codigo de modelo
MARCA_POR_MODELO = [
    (re.compile(r"^(UN|QN)\d{2}"), "Samsung"),
    (re.compile(r"^(OLED\d{2}|\d{2}(NU|UA|UR|UT|QNED|LM|LR)\d)"), "LG"),
    (re.compile(r"^(K|KD|XR)\d{2}"), "Sony"),
    (re.compile(r"^\d{2,3}(Q\d[QSN]|S7N|U\dQ|A\dN)"), "Hisense"),
]


def marca_de(nombre: str, marca: str = "") -> str:
    if marca:
        return marca
    t = f" {normalizar(nombre)} "
    for m in MARCAS:
        if f" {normalizar(m)} " in t:
            return m
    modelo = modelo_tv(nombre)
    for patron, m in MARCA_POR_MODELO:
        if patron.search(modelo):
            return m
    return ""


def pulgadas_libres(nombre: str, minimo: float = 10, maximo: float = 100) -> float | None:
    """Pulgadas de monitores y similares, con decimales: 23.8", 27 pulgadas, 24GS60F."""
    t = normalizar(nombre)
    m = re.search(r"(?<![\d.])(\d{2}(?:\.\d{1,2})?) pulg", t)
    if not m:
        m = re.search(r"(?:^|[^a-z0-9.])(\d{2})[a-z]{1,3}\d", t)  # codigo: 24gs60f, 27u411
    if m and minimo <= float(m.group(1)) <= maximo:
        v = float(m.group(1))
        return int(v) if v.is_integer() else v
    return None


def _en_rango(valor, cfg: dict) -> bool:
    return valor is not None and cfg.get("pulgadas_min", 0) <= valor <= cfg.get("pulgadas_max", 999)


def clasificar(nombre: str, filtros: dict) -> dict | None:
    """
    Devuelve los campos de clasificacion, o None si el producto no entra en los filtros.

    'tv' y 'cama' tienen reglas propias (pulgadas validas de TV, medida de cama). Las demas
    categorias de productos.json se definen con "incluir" y "excluir" (expresiones regulares)
    y, si tienen "pulgadas_min"/"pulgadas_max", con el rango de pulgadas.
    """
    if "tv" in filtros and _SI_TV.search(nombre) and not _NO_TV.search(nombre):
        pulg = pulgadas(nombre)
        if pulg is not None:
            if not _en_rango(pulg, filtros["tv"]):
                return None
            return {"categoria": "tv", "tipo": "tv", "pulgadas": pulg, "medida": None,
                    "modelo": modelo_tv(nombre)}
    if "cama" in filtros and _SI_CAMA.search(nombre) and not _NO_CAMA.search(nombre):
        medida = medida_cama(nombre)
        if medida in filtros["cama"].get("medidas", ["matrimonial"]):
            t = normalizar(nombre)
            tipo = "colchon" if t.startswith("colchon") and "set" not in t else "set"
            return {"categoria": "cama", "tipo": tipo, "pulgadas": None, "medida": medida, "modelo": ""}
        if medida:
            return None
    for cid, cfg in filtros.items():
        if cid in ("tv", "cama") or not cfg.get("incluir"):
            continue
        if not re.search(cfg["incluir"], nombre, re.I):
            continue
        if cfg.get("excluir") and re.search(cfg["excluir"], nombre, re.I):
            continue
        pulg = None
        if "pulgadas_min" in cfg or "pulgadas_max" in cfg:
            pulg = pulgadas_libres(nombre)
            if not _en_rango(pulg, cfg):
                continue
        return {"categoria": cid, "tipo": cid, "pulgadas": pulg, "medida": None, "modelo": modelo_tv(nombre)}
    return None


# --------------------------------------------------------------------------- #
# Estadisticas y veredicto
# --------------------------------------------------------------------------- #
def clasificar_variacion(pct_base):
    """Devuelve (texto, nivel) segun la variacion contra la linea base."""
    if pct_base is None:
        return ("SIN BASE", "sin-base")
    if pct_base <= UMBRAL_OFERTA:
        return ("OFERTA REAL", "verde")
    if pct_base < -UMBRAL_CAMBIO:
        return ("DESCUENTO MENOR", "amarillo")
    if pct_base <= UMBRAL_CAMBIO:
        return ("SIN CAMBIO", "gris")
    return ("SUBIO", "rojo")


def estadisticas(observaciones: list, corte: str) -> dict:
    obs = sorted(observaciones, key=lambda o: o["fecha"])
    previas = [o for o in obs if o["fecha"][:10] < corte]
    precios = [o["precio"] for o in obs]
    listas_previas = [o["precio_lista"] for o in previas if o.get("precio_lista")]
    ultima = obs[-1] if obs else None
    base = statistics.median([o["precio"] for o in previas]) if previas else None
    pct = (ultima["precio"] / base - 1) * 100 if (ultima and base) else None
    texto, nivel = clasificar_variacion(pct)
    minimo = min(obs, key=lambda o: o["precio"]) if obs else None
    return {
        "ultimo": ultima["precio"] if ultima else None,
        "fecha": ultima["fecha"] if ultima else None,
        "lista": ultima.get("precio_lista") if ultima else None,
        "disponible": ultima.get("disponible", True) if ultima else False,
        "base": base,
        "n_base": len(previas),
        "pct_base": pct,
        "minimo": minimo["precio"] if minimo else None,
        "fecha_minimo": minimo["fecha"] if minimo else None,
        "maximo": max(precios) if precios else None,
        "max_lista_previa": max(listas_previas) if listas_previas else None,
        "n": len(obs),
        "veredicto": texto,
        "nivel": nivel,
    }




# --------------------------------------------------------------------------- #
# Busqueda
# --------------------------------------------------------------------------- #
PISTAS_FIJAS = {
    **{w: "tv" for w in ("tv", "tele", "televisor", "televisores", "pantalla", "pantallas", "smart", "television")},
    **{w: "cama" for w in ("cama", "camas", "set", "colchon", "colchones")},
}
VACIAS = {"de", "la", "el", "con", "y", "para", "en", "pulg", "un", "una"}


def pistas(filtros: dict) -> dict[str, str]:
    """Palabra -> categoria: 'teclados' filtra la categoria teclado en vez de buscarse en el nombre."""
    salida = {w: c for w, c in PISTAS_FIJAS.items() if c in filtros}
    for cid, cfg in filtros.items():
        # solo el id y las "pistas" explicitas: los terminos de busqueda traen palabras
        # ambiguas ("con" de joy-con, "gamer") que filtrarian la categoria equivocada
        for w in [cid, *cfg.get("pistas", [])]:
            # una frase ("teclado musical") gana a sus palabras sueltas en el buscador
            if len(tokens(w)) > 1:
                salida.setdefault(" ".join(tokens(w)), cid)
            for t in tokens(w):
                if len(t) < 3 or t in VACIAS:
                    continue
                for forma in (t, t + "s", t + "es"):
                    salida.setdefault(forma, cid)
    return salida
