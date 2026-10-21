#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registro y comparacion de precios por comercial (temporada de ofertas).

Comandos:
    python scripts/precios.py capturar [--solo-modelos] [--comercial siman] [--categoria cama]
    python scripts/precios.py productos [--categoria tv]
    python scripts/precios.py add <producto> --comercial siman --precio 379.99 --lista 499.99
    python scripts/precios.py lista [--producto <id>]
    python scripts/precios.py quitar <producto> --comercial siman [--fecha AAAA-MM-DD] [--todos]
    python scripts/precios.py reporte [--corte 2026-11-01] [--salida reportes/reporte.md]
    python scripts/precios.py exportar              (regenera web/data para la web)
    python scripts/servidor.py                      (web local con guardado y actualizacion)

Datos:
    data/comerciales.json           tiendas (id, nombre, sitio)
    data/productos.json             modelos seguidos (el mismo modelo en varias tiendas) y filtros del barrido
    data/listados/<comercial>.json  todos los productos de cada tienda con su historial de precios
    reportes/reporte.md             comparacion generada

Sin dependencias externas.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import almacen  # noqa: E402

for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        try:
            _flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

RAIZ = Path(__file__).resolve().parents[1]
DIR_DATOS = RAIZ / "data"
ARCHIVO_PRODUCTOS = DIR_DATOS / "productos.json"
ARCHIVO_COMERCIALES = DIR_DATOS / "comerciales.json"
DIR_REPORTES = RAIZ / "reportes"

CORTE_POR_DEFECTO = "2026-11-01"
FILTROS_POR_DEFECTO = {"tv": {"pulgadas_min": 40, "pulgadas_max": 60}, "cama": {"medidas": ["matrimonial"]}}


# --------------------------------------------------------------------------- #
# Utilidades de archivos
# --------------------------------------------------------------------------- #
def cargar_json(ruta: Path, defecto):
    if not ruta.exists():
        return defecto
    with ruta.open("r", encoding="utf-8") as f:
        return json.load(f)


def guardar_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")


def cargar_productos() -> dict:
    datos = cargar_json(ARCHIVO_PRODUCTOS, None)
    if not datos:
        raise SystemExit(f"No encontre el catalogo: {ARCHIVO_PRODUCTOS}")
    # presupuesto y objetivo se definen por categoria; un producto puede sobrescribirlos
    categorias = datos.get("categorias", {})
    for p in datos["productos"]:
        cat = categorias.get(p.get("categoria"), {})
        for campo in ("presupuesto_max", "precio_objetivo"):
            if p.get(campo) is None and cat.get(campo) is not None:
                p[campo] = cat[campo]
    return datos


def filtrar_categoria(productos: list, categoria: str | None) -> list:
    if not categoria:
        return productos
    elegidos = [p for p in productos if p.get("categoria") == categoria]
    if not elegidos:
        raise SystemExit(f"No hay productos en la categoria '{categoria}'.")
    return elegidos


def cargar_comerciales() -> dict:
    datos = cargar_json(ARCHIVO_COMERCIALES, {"comerciales": []})
    return {c["id"]: c for c in datos.get("comerciales", [])}


def buscar_producto(datos: dict, pid: str) -> dict:
    for p in datos["productos"]:
        if p["id"] == pid:
            return p
    opciones = ", ".join(p["id"] for p in datos["productos"])
    raise SystemExit(f"El producto '{pid}' no existe. Opciones: {opciones}")


def observaciones_de(producto: dict) -> list:
    """Historial del modelo en todas sus tiendas, leido de data/listados/<comercial>.json."""
    obs = []
    for c in producto.get("comerciales", []):
        f = almacen.ficha(c["id"], c["sku"]) if c.get("sku") else None
        for o in (f or {}).get("observaciones", []):
            obs.append({**o, "comercial": c["id"]})
    return sorted(obs, key=lambda o: o["fecha"])


def filtros_barrido(datos: dict) -> dict:
    return datos.get("barrido") or FILTROS_POR_DEFECTO


# --------------------------------------------------------------------------- #
# Utilidades de texto y formato
# --------------------------------------------------------------------------- #
def slug(texto: str) -> str:
    """'La Curacao' -> 'la-curacao' (sin acentos, sin espacios)."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    t = "".join(ch if ch.isalnum() else "-" for ch in t.lower())
    return "-".join(parte for parte in t.split("-") if parte)


def resolver_comercial(valor: str, catalogo: dict) -> str:
    """Acepta id, nombre ('La Curacao') o variantes con acentos."""
    buscado = slug(valor)
    if buscado in catalogo:
        return buscado
    for cid, c in catalogo.items():
        if slug(c.get("nombre", "")) == buscado:
            return cid
    return buscado


def nombre_comercial(cid: str, catalogo: dict) -> str:
    return catalogo.get(cid, {}).get("nombre", cid)


def ahora_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def parsear_fecha(texto: str | None) -> str:
    if not texto:
        return ahora_iso()
    try:
        dt = datetime.fromisoformat(texto.strip())
    except ValueError:
        raise SystemExit(
            f"Fecha invalida: {texto!r}. Ejemplos validos: 2026-10-20 o 2026-11-27T15:30"
        )
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.replace(microsecond=0).isoformat()


def parsear_precio(valor) -> float:
    t = str(valor).strip().replace("$", "").replace(" ", "").replace("\u00a0", "")
    if not t:
        raise SystemExit("Precio vacio.")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        partes = t.split(",")
        if len(partes) == 2 and len(partes[1]) == 2:
            t = t.replace(",", ".")
        else:
            t = t.replace(",", "")
    try:
        return round(float(t), 2)
    except ValueError:
        raise SystemExit(f"Precio invalido: {valor!r}")


def dinero(x) -> str:
    return f"${x:,.2f}" if x is not None else "-"


def porcentaje(x) -> str:
    return f"{x:+.1f}%" if x is not None else "-"


def mediana(valores):
    return statistics.median(valores) if valores else None


# --------------------------------------------------------------------------- #
# Analisis
# --------------------------------------------------------------------------- #
clasificar = almacen.clasificar_variacion


def resumen_por_comercial(observaciones: list, corte: str) -> list:
    grupos: dict[str, list] = {}
    for o in observaciones:
        grupos.setdefault(o["comercial"], []).append(o)

    filas = []
    for comercial, lista in grupos.items():
        lista = sorted(lista, key=lambda o: o["fecha"])
        previas = [o for o in lista if o["fecha"][:10] < corte]
        ultima = lista[-1]

        base = mediana([o["precio"] for o in previas])
        minimo = min(o["precio"] for o in lista)
        pct_base = (ultima["precio"] / base - 1) * 100 if base else None
        texto, nivel = clasificar(pct_base)

        pct_lista = None
        if ultima.get("precio_lista"):
            pct_lista = (ultima["precio"] / ultima["precio_lista"] - 1) * 100

        alerta_lista = None
        maximos_previos = [o["precio_lista"] for o in previas if o.get("precio_lista")]
        if ultima.get("precio_lista") and maximos_previos:
            max_previo = max(maximos_previos)
            if ultima["precio_lista"] > max_previo * 1.02:
                alerta_lista = (ultima["precio_lista"] / max_previo - 1) * 100

        filas.append(
            {
                "comercial": comercial,
                "ultimo": ultima["precio"],
                "fecha": ultima["fecha"],
                "disponible": ultima.get("disponible", True),
                "base": base,
                "pct_base": pct_base,
                "lista": ultima.get("precio_lista"),
                "pct_lista": pct_lista,
                "minimo": minimo,
                "alerta_lista": alerta_lista,
                "n_base": len(previas),
                "veredicto": texto,
                "nivel": nivel,
            }
        )

    filas.sort(key=lambda f: (not f["disponible"], f["ultimo"]))
    return filas


def decision_producto(producto: dict, filas: list, catalogo: dict) -> str:
    disponibles = [f for f in filas if f["disponible"]] or filas
    if not disponibles:
        return "Sin datos: registra el primer precio para empezar la linea base."
    mejor = min(disponibles, key=lambda f: f["ultimo"])
    nombre = nombre_comercial(mejor["comercial"], catalogo)
    objetivo = producto.get("precio_objetivo")
    presupuesto = producto.get("presupuesto_max")
    if not objetivo and not presupuesto:
        return (
            "Define presupuesto_max y precio_objetivo en data/productos.json. "
            f"Mejor precio hoy: {dinero(mejor['ultimo'])} en {nombre}."
        )
    if objetivo and mejor["ultimo"] <= objetivo:
        return f"COMPRAR: {nombre} a {dinero(mejor['ultimo'])} alcanza tu precio objetivo."
    if presupuesto and mejor["ultimo"] <= presupuesto:
        return (
            f"Dentro de presupuesto ({nombre} a {dinero(mejor['ultimo'])}), "
            "pero arriba del objetivo: sirve si no baja mas."
        )
    return f"ESPERAR: lo mejor hoy es {dinero(mejor['ultimo'])} en {nombre}."


# --------------------------------------------------------------------------- #
# Comandos
# --------------------------------------------------------------------------- #
def cmd_productos(args) -> None:
    datos = cargar_productos()
    print(
        f"{'ID':<36}  {'CAT.':<5} {'PRESUP.':>9} {'OBJETIVO':>9} "
        f"{'COMERC.':>7} {'OBS':>4} {'PEND.':>5}"
    )
    print("-" * 82)
    for p in filtrar_categoria(datos["productos"], args.categoria):
        obs = observaciones_de(p)
        vistos = {o["comercial"] for o in obs}
        comerciales = [c["id"] for c in p.get("comerciales", [])]
        pendientes = len([c for c in comerciales if c not in vistos])
        print(
            f"{p['id']:<36}  {p.get('categoria', ''):<5} "
            f"{dinero(p.get('presupuesto_max')):>9} {dinero(p.get('precio_objetivo')):>9} "
            f"{len(comerciales):>7} {len(obs):>4} {pendientes:>5}"
        )
    print()
    corte = datos.get("corte_linea_base", CORTE_POR_DEFECTO)
    print(f"PEND. = comerciales sin ninguna captura. Linea base: antes del {corte}.")


def agregar_comercial_a_producto(pid: str, entrada: dict) -> None:
    """Agrega una tienda a un modelo en productos.json (sin escribir los valores por categoria)."""
    crudo = cargar_json(ARCHIVO_PRODUCTOS, None)
    for p in crudo["productos"]:
        if p["id"] == pid:
            p.setdefault("comerciales", []).append(entrada)
    guardar_json(ARCHIVO_PRODUCTOS, crudo)


def registrar(producto: dict, observacion: dict, catalogo: dict, forzar: bool = False) -> bool:
    """Agrega la observacion al listado de la tienda. Devuelve False si ya estaba (mismo dia y precio)."""
    comercial = observacion["comercial"]
    precio = observacion["precio"]
    entrada = next((c for c in producto.get("comerciales", []) if c["id"] == comercial and c.get("sku")), None)
    if entrada is None:
        entrada = {"id": comercial, "sku": f"manual-{producto['id']}", "url": observacion.get("url", ""),
                   "nota": "agregado a mano"}
        agregar_comercial_a_producto(producto["id"], entrada)
        producto.setdefault("comerciales", []).append(entrada)

    previos = [o["precio"] for o in observaciones_de(producto) if o["comercial"] == comercial]
    if previos:
        habitual = statistics.median(previos)
        if precio < habitual * 0.3:
            print(
                f"Aviso: {dinero(precio)} es menos del 30% de lo habitual en "
                f"{nombre_comercial(comercial, catalogo)} ({dinero(habitual)}). "
                f"Si fue un error de tipeo: python scripts/precios.py quitar "
                f"{producto['id']} --comercial {comercial}"
            )

    datos_ficha = {"url": observacion.get("url") or entrada.get("url", "")}
    if almacen.ficha(comercial, entrada["sku"]) is None:
        datos_ficha.update(nombre=producto["nombre"], categoria=producto.get("categoria"))
    obs = {k: v for k, v in observacion.items() if k not in ("comercial", "url", "nombre_tienda")}
    return almacen.agregar(comercial, entrada["sku"], datos_ficha, obs, forzar)


def cmd_add(args) -> None:
    datos = cargar_productos()
    catalogo = cargar_comerciales()
    producto = buscar_producto(datos, args.producto)

    comercial = resolver_comercial(args.comercial, catalogo)
    if comercial not in catalogo:
        print(f"Aviso: '{args.comercial}' no esta en data/comerciales.json; se guarda como '{comercial}'.")

    precio = parsear_precio(args.precio)
    lista = parsear_precio(args.lista) if args.lista else None
    fecha = parsear_fecha(args.fecha)
    if precio <= 0:
        raise SystemExit("El precio debe ser mayor que cero.")
    if lista is not None and lista <= 0:
        raise SystemExit("El precio de lista debe ser mayor que cero.")

    observacion = {
        "fecha": fecha,
        "comercial": comercial,
        "precio": precio,
        "precio_lista": lista,
        "etiqueta": (args.etiqueta or "").strip(),
        "disponible": not args.agotado,
        "nota": (args.nota or "").strip(),
        "fuente": "manual",
    }
    if args.url:
        observacion["url"] = args.url.strip()

    if not registrar(producto, observacion, catalogo, args.forzar):
        print(f"Sin cambios: ya estaba registrado {dinero(precio)} en "
              f"{nombre_comercial(comercial, catalogo)} el {fecha[:10]}.")
        print("Usa --forzar si de verdad quieres duplicar el registro.")
        return
    extra = f" (lista {dinero(lista)})" if lista else ""
    print(
        f"Guardado: {producto['nombre']} | {nombre_comercial(comercial, catalogo)} | "
        f"{dinero(precio)}{extra} | {fecha}"
    )


def capturar(categoria: str | None = None, comercial: str | None = None, producto: str | None = None,
             solo_modelos: bool = False, pausa: float = 0.5, avisar=print) -> dict:
    """
    1. Barrido: todas las TV y camas de cada tienda que pasan los filtros de productos.json.
    2. Modelos seguidos: consulta uno por uno los SKU de productos.json que el barrido no cubrio.
    """
    import tiendas

    datos = cargar_productos()
    catalogo = cargar_comerciales()
    filtros = filtros_barrido(datos)
    solo = resolver_comercial(comercial, catalogo) if comercial else None
    tocados: set[tuple[str, str]] = set()
    total = {"nuevas": 0, "repetidas": 0, "errores": 0}

    if not solo_modelos and not producto:
        for cid in tiendas.COMERCIALES_BARRIDO:
            if solo and cid != solo:
                continue
            tienda = nombre_comercial(cid, catalogo)
            avisar(f"Barriendo {tienda}...")
            inicio = time.time()
            try:
                items = tiendas.barrer(cid, filtros)
            except Exception as e:  # una tienda caida no detiene el barrido de las demas
                total["errores"] += 1
                avisar(f"  ERROR {tienda}: {type(e).__name__}: {e}")
                continue
            ahora = ahora_iso()
            cuenta = {c: 0 for c in filtros}
            nuevas = 0
            for it in items:
                k = almacen.clasificar(it["nombre"], filtros)
                if not k or it["precio"] is None or (categoria and k["categoria"] != categoria):
                    continue
                cuenta[k["categoria"]] = cuenta.get(k["categoria"], 0) + 1
                datos_ficha = {**k, "nombre": it["nombre"], "url": it["url"],
                               "marca": almacen.marca_de(it["nombre"], it.get("marca", ""))}
                obs = {"fecha": ahora, "precio": it["precio"], "precio_lista": it["precio_lista"],
                       "disponible": it["disponible"], "fuente": "auto", "nota": it.get("nota", "")}
                if almacen.agregar(cid, it["sku"], datos_ficha, obs, guardar_ya=False):
                    nuevas += 1
                else:
                    total["repetidas"] += 1
                tocados.add((cid, it["sku"]))
            almacen.guardar(cid)
            total["nuevas"] += nuevas
            detalle = " · ".join(f"{n} {filtros.get(c, {}).get('nombre', c)}" for c, n in cuenta.items() if n)
            avisar(f"  {tienda:<11} {detalle or 'nada'} · {nuevas} precios nuevos ({time.time() - inicio:.0f} s)")

    productos = filtrar_categoria(datos["productos"], categoria)
    if producto:
        productos = [buscar_producto(datos, producto)]
    pendientes = [(p, c) for p in productos for c in p.get("comerciales", [])
                  if c.get("sku") and tiendas.soportado(c["id"]) and (not solo or c["id"] == solo)
                  and (c["id"], c["sku"]) not in tocados]
    if pendientes:
        avisar(f"Modelos seguidos fuera del barrido: {len(pendientes)}")
    for p, c in pendientes:
        tienda = nombre_comercial(c["id"], catalogo)
        try:
            r = tiendas.consultar(c["id"], c["sku"], c.get("url", ""))
        except tiendas.ErrorTienda as e:
            total["errores"] += 1
            avisar(f"  ERROR    {p['id']:<36} {tienda:<11} {e}")
            continue
        finally:
            time.sleep(pausa)
        if r["precio"] is None:
            total["errores"] += 1
            avisar(f"  SIN PRECIO {p['id']:<34} {tienda:<11} {r.get('nota') or 'no publicado'}")
            continue
        observacion = {
            "fecha": ahora_iso(),
            "comercial": c["id"],
            "precio": r["precio"],
            "precio_lista": r["precio_lista"],
            "disponible": r["disponible"],
            "fuente": "auto",
            "nota": r.get("nota", ""),
            "url": c.get("url", ""),
        }
        if registrar(p, observacion, catalogo):
            total["nuevas"] += 1
            avisar(f"  guardado {p['id']:<36} {tienda:<11} {dinero(r['precio']):>10}")
        else:
            total["repetidas"] += 1

    avisar(f"Listo. Precios nuevos: {total['nuevas']} · sin cambio hoy: {total['repetidas']} · "
           f"con error: {total['errores']}")
    return total


def cmd_capturar(args) -> None:
    total = capturar(args.categoria, args.comercial, args.producto, args.solo_modelos, args.pausa)
    if total["errores"]:
        print("Revisa los errores: puede que la tienda cambio el enlace o el SKU ya no existe.")
    if not args.sin_exportar:
        import exportar
        exportar.exportar()


def cmd_exportar(args) -> None:
    import exportar
    exportar.exportar()


def cmd_lista(args) -> None:
    datos = cargar_productos()
    catalogo = cargar_comerciales()
    if args.producto:
        productos = [buscar_producto(datos, args.producto)]
    else:
        productos = datos["productos"]

    for p in productos:
        ultimos: dict[str, dict] = {}
        for o in observaciones_de(p):
            ultimos[o["comercial"]] = o
        print()
        print(f"{p['nombre']}  ({p['id']})")
        if not ultimos:
            print("  (sin observaciones todavia)")
            continue
        for cid, o in sorted(ultimos.items(), key=lambda kv: kv[1]["precio"]):
            estado = "" if o.get("disponible", True) else "  [agotado]"
            print(f"  {nombre_comercial(cid, catalogo):<18} {dinero(o['precio']):>10}   "
                  f"{o['fecha'][:16]}{estado}")


def cmd_quitar(args) -> None:
    catalogo = cargar_comerciales()
    producto = buscar_producto(cargar_productos(), args.producto)
    comercial = resolver_comercial(args.comercial, catalogo)
    entrada = next((c for c in producto.get("comerciales", []) if c["id"] == comercial), None)
    f = almacen.ficha(comercial, entrada["sku"]) if entrada and entrada.get("sku") else None

    candidatos = list((f or {}).get("observaciones", []))
    if args.fecha:
        candidatos = [o for o in candidatos if o["fecha"][:10] == args.fecha[:10]]
    if not candidatos:
        raise SystemExit(
            f"No hay observaciones de '{nombre_comercial(comercial, catalogo)}' "
            f"para {producto['id']}."
        )

    if args.todos:
        quitadas = candidatos
    else:
        quitadas = [max(candidatos, key=lambda o: o["fecha"])]

    ids = {id(o) for o in quitadas}
    f["observaciones"] = [o for o in f["observaciones"] if id(o) not in ids]
    almacen.guardar(comercial)

    for o in quitadas:
        print(f"Quitado: {o['fecha'][:10]} | {nombre_comercial(comercial, catalogo)} | "
              f"{dinero(o['precio'])}")
    print(f"Quedan {len(f['observaciones'])} observaciones de {producto['id']} en "
          f"{nombre_comercial(comercial, catalogo)}.")


def generar_markdown(datos: dict, corte: str) -> str:
    catalogo = cargar_comerciales()
    ahora = datetime.now().astimezone().replace(microsecond=0)
    total = sum(len(observaciones_de(p)) for p in datos["productos"])
    iconos = {"verde": "🟢", "amarillo": "🟡", "gris": "⚪", "rojo": "🔴", "sin-base": "⚫"}
    productos = datos["productos"]

    L = []
    L.append("# Reporte de precios — ofertas de noviembre 2026")
    L.append("")
    L.append(
        f"Generado: **{ahora.strftime('%Y-%m-%d %H:%M')}** (hora local) · "
        f"Productos: **{len(productos)}** · Observaciones: **{total}**"
    )
    L.append("")
    L.append(f"Línea base = mediana de los precios capturados **antes del {corte}**.")
    L.append("")
    L.append("## Cómo leer el veredicto")
    L.append("")
    L.append(f"- 🟢 **OFERTA REAL**: el precio está {abs(almacen.UMBRAL_OFERTA):.0f}% o más por debajo de tu línea base.")
    L.append("- 🟡 **DESCUENTO MENOR**: baja entre 3% y 10%. Puede ser real pero es poco.")
    L.append("- ⚪ **SIN CAMBIO**: se movió menos de 3%. No es oferta.")
    L.append("- 🔴 **SUBIÓ**: está por encima de tu línea base.")
    L.append("- ⚫ **SIN BASE**: no hay capturas previas al corte; no se puede juzgar.")
    L.append("")
    L.append(
        "La columna **Alerta lista** marca el caso clásico de descuento falso: la tienda sube el "
        "«precio de lista» por encima del máximo que tú mismo observaste antes."
    )
    L.append("")

    # ---------------- resumen por categoria: un modelo por fila ----------------
    por_producto: dict[str, dict] = {}
    for p in productos:
        obs = observaciones_de(p)
        por_producto[p["id"]] = {f["comercial"]: f for f in resumen_por_comercial(obs, corte)}

    categorias = datos.get("categorias", {})
    orden_cat = list(dict.fromkeys(p.get("categoria", "otros") for p in productos))

    def mejor_de(pid: str):
        disp = [f for f in por_producto[pid].values() if f["disponible"]]
        return min(disp, key=lambda f: f["ultimo"]) if disp else None

    for cat in orden_cat if total else []:
        prods = [p for p in productos if p.get("categoria", "otros") == cat]
        info = categorias.get(cat, {})
        orden: list[str] = []
        for p in prods:
            for cid in [c["id"] for c in p.get("comerciales", [])] + list(por_producto[p["id"]]):
                if cid not in orden:
                    orden.append(cid)

        L.append(f"## Resumen: {info.get('nombre', cat)}")
        L.append("")
        if info.get("presupuesto_max") or info.get("precio_objetivo"):
            L.append(
                f"Presupuesto **{dinero(info.get('presupuesto_max'))}** · "
                f"objetivo **{dinero(info.get('precio_objetivo'))}**. "
                "En negrita, el precio más bajo del modelo."
            )
            L.append("")
        L.append(
            "| Modelo | " + " | ".join(nombre_comercial(c, catalogo) for c in orden)
            + " | Mejor | vs base | Veredicto |"
        )
        L.append("|---|" + "---:|" * len(orden) + "---:|---:|---|")
        prods.sort(key=lambda p: (mejor_de(p["id"]) or {}).get("ultimo", float("inf")))
        for p in prods:
            m = mejor_de(p["id"])
            celdas = []
            for cid in orden:
                f = por_producto[p["id"]].get(cid)
                if not f:
                    celdas.append("—")
                    continue
                txt = dinero(f["ultimo"])
                if not f["disponible"]:
                    txt += " (agot.)"
                elif m and f is m:
                    txt = f"**{txt}**"
                celdas.append(txt)
            if m:
                marca = "*" if m["base"] is not None and m["n_base"] < 2 else ""
                cola = (
                    f"{dinero(m['ultimo'])} | {porcentaje(m['pct_base'])} | "
                    f"{iconos[m['nivel']]} {m['veredicto']}{marca}"
                )
            else:
                cola = "— | — | —"
            L.append(f"| {p.get('nombre_corto') or p['nombre']} | " + " | ".join(celdas) + f" | {cola} |")
        L.append("")
        L.append("`*` = la línea base tiene un solo dato; captura más veces antes del corte.")
        L.append("")

    # ---------------- barrido global: todo lo que bajo de verdad ----------------
    bajas = []
    n_global = 0
    for cid, sku, f in almacen.todos():
        n_global += 1
        est = almacen.estadisticas(f.get("observaciones", []), corte)
        if est["disponible"] and est["pct_base"] is not None and est["pct_base"] < -almacen.UMBRAL_CAMBIO:
            bajas.append((est["pct_base"], cid, f, est))
    bajas.sort(key=lambda x: x[0])
    L.append("## Barrido global: lo que bajó contra su línea base")
    L.append("")
    L.append(f"Productos seguidos en todas las tiendas: **{n_global}**.")
    L.append("")
    if bajas:
        L.append("| Producto | Tienda | Hoy | Base | vs base | Veredicto |")
        L.append("|---|---|---:|---:|---:|---|")
        for pct, cid, f, est in bajas[:40]:
            medida = f"{f['pulgadas']}\"" if f.get("pulgadas") else (f.get("medida") or "")
            L.append(
                f"| [{f['nombre'][:70]}]({f.get('url', '')}) {medida} | {nombre_comercial(cid, catalogo)} | "
                f"{dinero(est['ultimo'])} | {dinero(est['base'])} | {porcentaje(pct)} | "
                f"{iconos[est['nivel']]} {est['veredicto']} |"
            )
    else:
        L.append("_Nada ha bajado más de 3% contra su línea base todavía._")
    L.append("")

    # ---------------- detalle por producto ----------------
    L.append("## Detalle por modelo")
    L.append("")
    for p in productos:
        obs = observaciones_de(p)
        filas = resumen_por_comercial(obs, corte)

        L.append(f"### {p['nombre']}")
        L.append("")
        detalles = [
            f"Presupuesto: **{dinero(p.get('presupuesto_max'))}**",
            f"Objetivo: **{dinero(p.get('precio_objetivo'))}**",
            f"Observaciones: **{len(obs)}**",
        ]
        L.append("- " + " · ".join(detalles))
        comerciales_p = [c["id"] for c in p.get("comerciales", [])]
        if comerciales_p:
            L.append(
                "- Comerciales: "
                + ", ".join(nombre_comercial(c, catalogo) for c in comerciales_p)
            )
        if p.get("modelo_exacto") and p["modelo_exacto"] != "por definir":
            L.append(f"- Modelo exacto: {p['modelo_exacto']}")
        for c in p.get("comerciales", []):
            if c.get("nota"):
                L.append(f"- {nombre_comercial(c['id'], catalogo)}: {c['nota']}")
        L.append("")

        if not filas:
            L.append("_Sin datos todavía. Registra el primer precio para arrancar la línea base:_")
            L.append("")
            L.append("```")
            L.append(
                f'python scripts/precios.py add {p["id"]} --comercial siman '
                f"--precio 379.99 --lista 499.99"
            )
            L.append("```")
            L.append("")
            continue

        L.append("| Comercial | Último | Fecha | Base (mediana) | vs base | Lista | vs lista | Mín. hist. | Alerta lista | Veredicto |")
        L.append("|---|---:|---|---:|---:|---:|---:|---:|---|---|")
        for f in filas:
            alerta = f"Sí, +{f['alerta_lista']:.0f}%" if f["alerta_lista"] else "—"
            estado = "" if f["disponible"] else " (agotado)"
            marca = "*" if f["base"] is not None and f["n_base"] < 2 else ""
            L.append(
                "| {comercial} | {ultimo} | {fecha} | {base} | {pct_base} | {lista} | {pct_lista} | "
                "{minimo} | {alerta} | {icono} {veredicto}{estado} |".format(
                    comercial=nombre_comercial(f["comercial"], catalogo),
                    ultimo=dinero(f["ultimo"]),
                    fecha=f["fecha"][:10],
                    base=dinero(f["base"]),
                    pct_base=porcentaje(f["pct_base"]),
                    lista=dinero(f["lista"]),
                    pct_lista=porcentaje(f["pct_lista"]),
                    minimo=dinero(f["minimo"]),
                    alerta=alerta,
                    icono=iconos[f["nivel"]],
                    veredicto=f"{f['veredicto']}{marca}",
                    estado=estado,
                )
            )
        L.append("")

        debiles = [f for f in filas if f["base"] is not None and f["n_base"] < 2]
        if debiles:
            L.append(
                "* Base de un solo dato en "
                + ", ".join(nombre_comercial(f["comercial"], catalogo) for f in debiles)
                + ": captura al menos dos veces para que el veredicto sea confiable."
            )
            L.append("")

        sin_capturas = [c for c in comerciales_p if c not in por_producto[p["id"]]]
        if sin_capturas:
            L.append(
                "_Sin capturas todavía: "
                + ", ".join(nombre_comercial(c, catalogo) for c in sin_capturas)
                + "._"
            )
            L.append("")

        viejos = []
        for f in filas:
            dias = (ahora.date() - datetime.fromisoformat(f["fecha"]).date()).days
            if dias > 7:
                viejos.append(
                    f"{nombre_comercial(f['comercial'], catalogo)} ({dias} dias)"
                )
        if viejos:
            L.append(
                f"> Aviso: hay datos con mas de 7 dias ({', '.join(viejos)}). "
                "Vuelve a capturar antes de decidir."
            )
            L.append("")

        L.append(f"**Decisión:** {decision_producto(p, filas, catalogo)}")
        L.append("")

    L.append("---")
    L.append("")
    L.append("## Siguiente paso")
    L.append("")
    L.append("1. Captura 2–3 veces por semana hasta el 31 de octubre (eso forma la línea base).")
    L.append("2. Del 20 al 30 de noviembre, captura a diario (Black Friday: 27 nov, Cyber Monday: 30 nov).")
    L.append("3. Compara con `python scripts/precios.py reporte` antes de pagar.")
    L.append("")
    return "\n".join(L)


def cmd_reporte(args) -> None:
    datos = cargar_productos()
    catalogo = cargar_comerciales()
    corte = args.corte or datos.get("corte_linea_base", CORTE_POR_DEFECTO)
    salida = Path(args.salida) if args.salida else (DIR_REPORTES / "reporte.md")
    if not salida.is_absolute():
        salida = RAIZ / salida

    texto = generar_markdown(datos, corte)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(texto, encoding="utf-8", newline="\n")

    print(f"Reporte generado: {salida}")
    print()
    for p in datos["productos"]:
        obs = observaciones_de(p)
        filas = resumen_por_comercial(obs, corte)
        if any(f["veredicto"] == "OFERTA REAL" and f["disponible"] for f in filas):
            print(f"OFERTA REAL  {p['nombre']}: {decision_producto(p, filas, catalogo)}")
    print("(Solo se listan los modelos con OFERTA REAL; el detalle completo esta en el reporte.)")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Registro y comparacion de precios por comercial (noviembre)."
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_prod = sub.add_parser("productos", help="Lista el catalogo y el estado de las capturas.")
    p_prod.add_argument("--categoria", default=None, help="Limitar a una categoria (tv, cama)")
    p_prod.set_defaults(func=cmd_productos)

    p_cap = sub.add_parser(
        "capturar", help="Barre todas las tiendas y categorias del barrido, guarda los precios de hoy y exporta la web."
    )
    p_cap.add_argument("--solo-modelos", action="store_true",
                       help="No barrer: solo consultar los modelos de productos.json")
    p_cap.add_argument("--producto", default=None, help="Solo este modelo de productos.json")
    p_cap.add_argument("--categoria", default=None, help="Solo esta categoria (tv, cama)")
    p_cap.add_argument("--comercial", "--tienda", dest="comercial", default=None, help="Solo esta tienda")
    p_cap.add_argument("--pausa", type=float, default=0.5, help="Segundos entre consultas (default 0.5)")
    p_cap.add_argument("--sin-exportar", action="store_true", help="No regenerar web/data al terminar")
    p_cap.set_defaults(func=cmd_capturar)

    p_exp = sub.add_parser("exportar", help="Regenera web/data/ (catalogo e historial para la web).")
    p_exp.set_defaults(func=cmd_exportar)

    p_add = sub.add_parser("add", help="Registra un precio observado.")
    p_add.add_argument("producto", help="id del producto (ver comando 'productos')")
    p_add.add_argument(
        "--comercial", "--tienda", dest="comercial", required=True,
        help="Comercial: id o nombre (siman, 'La Curacao', samsung...)",
    )
    p_add.add_argument("--precio", required=True, help="Precio final que pagarias (con IVA y envio)")
    p_add.add_argument("--lista", default=None, help="Precio de lista/tachado que muestra la tienda")
    p_add.add_argument("--etiqueta", default="", help="Texto de la promo: 'Black Friday', 'cyber'...")
    p_add.add_argument("--nota", default="", help="Nota libre")
    p_add.add_argument("--url", default="", help="Enlace exacto del producto")
    p_add.add_argument("--fecha", default=None, help="Fecha ISO (por defecto: ahora)")
    p_add.add_argument("--agotado", action="store_true", help="Marcar como agotado")
    p_add.add_argument("--forzar", action="store_true", help="Permitir registro duplicado del mismo dia")
    p_add.set_defaults(func=cmd_add)

    p_lista = sub.add_parser("lista", help="Muestra el ultimo precio por comercial.")
    p_lista.add_argument("--producto", default=None, help="Limitar a un producto")
    p_lista.set_defaults(func=cmd_lista)

    p_quitar = sub.add_parser(
        "quitar", help="Borra la ultima captura de un comercial (para corregir errores)."
    )
    p_quitar.add_argument("producto", help="id del producto")
    p_quitar.add_argument(
        "--comercial", "--tienda", dest="comercial", required=True,
        help="Comercial cuyas capturas se quieren borrar",
    )
    p_quitar.add_argument("--todos", action="store_true", help="Borrar todas las capturas de ese comercial")
    p_quitar.add_argument("--fecha", default=None, help="Borrar solo la captura de ese dia (AAAA-MM-DD)")
    p_quitar.set_defaults(func=cmd_quitar)

    p_rep = sub.add_parser("reporte", help="Genera el reporte Markdown de comparacion.")
    p_rep.add_argument("--corte", default=None, help="Fecha de corte de la linea base (AAAA-MM-DD)")
    p_rep.add_argument("--salida", default=None, help="Ruta del reporte (por defecto reportes/reporte.md)")
    p_rep.set_defaults(func=cmd_reporte)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
