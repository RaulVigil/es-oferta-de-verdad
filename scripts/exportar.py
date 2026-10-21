# -*- coding: utf-8 -*-
"""
Exporta los listados a archivos estaticos para la web (web/data/).

    web/data/catalogo.json            todos los productos con sus estadisticas ya calculadas
    web/data/historial/<tienda>.json  historial de precios por SKU (se carga al abrir un producto)

La web no necesita servidor: la busqueda, el veredicto y la comparacion entre tiendas
corren en el navegador con estos archivos. Se regenera despues de cada captura.

Uso:
    python scripts/exportar.py
    python scripts/precios.py exportar

Sin dependencias externas.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import almacen  # noqa: E402
import precios  # noqa: E402

DIR_WEB_DATOS = precios.RAIZ / "web" / "data"


def _escribir(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(ruta)


def _redondear(x):
    return round(x, 2) if isinstance(x, float) else x


# estadisticas en lista posicional (el nombre de cada campo va una sola vez, en "formato")
CAMPOS_S = ("ultimo", "base", "n_base", "pct_base", "minimo", "maximo", "max_lista_previa", "lista",
            "disponible", "n", "fecha", "fecha_minimo")


def _compacto(it: dict, prefijos: dict) -> dict:
    """
    Producto para la web sin lo que el navegador puede calcular: la clave de busqueda
    (normalizar) y el veredicto (clasificar). Fechas a minutos, campos vacios omitidos.
    """
    s = it["s"]
    fecha = (s["fecha"] or "")[:16]
    fecha_min = (s["fecha_minimo"] or "")[:16]
    valores = {**s, "fecha": fecha, "fecha_minimo": "" if fecha_min == fecha else fecha_min,
               "disponible": 1 if s["disponible"] else 0,
               "pct_base": round(s["pct_base"], 1) if s["pct_base"] is not None else None}
    salida = {"i": it["id"].split(":", 1)[1], "t": it["t"], "n": it["n"], "c": it["c"],
              "s": [valores[k] for k in CAMPOS_S]}
    for k in ("p", "me", "ma", "mo", "nt", "o"):
        if it.get(k):
            salida[k] = it[k]
    u, prefijo = it.get("u") or "", prefijos.get(it["t"], "")
    if u:
        salida["u"] = u[len(prefijo):] if prefijo and u.startswith(prefijo) else u
    return salida


def _marca(texto: str) -> str:
    """'XIAOMI' -> 'Xiaomi'; se respetan siglas cortas (LG, HP, AOC) y se ocultan las genericas."""
    t = (texto or "").strip()
    if t.lower() in ("unbranded", "generico", "genérico", "sin marca", "n/a", "otros"):
        return ""
    return t.title() if t.isupper() and len(t) > 3 else t


def _mismo_modelo(items: list[dict], grupos: list[list[str]]) -> dict[str, list[str]]:
    """id -> ids del mismo modelo en otras tiendas (por codigo de modelo o por productos.json)."""
    otros: dict[str, set[str]] = defaultdict(set)
    for grupo in grupos:
        for a in grupo:
            otros[a].update(b for b in grupo if b != a)
    # solo se comparan modelos que comparten los primeros 5 caracteres
    por_prefijo: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        if len(it["mo"]) >= 5:
            por_prefijo[it["mo"][:5]].append(it)
    for lista in por_prefijo.values():
        for i, a in enumerate(lista):
            for b in lista[i + 1:]:
                if a["t"] != b["t"] and almacen.mismo_modelo(a["mo"], b["mo"]):
                    otros[a["id"]].add(b["id"])
                    otros[b["id"]].add(a["id"])
    return {k: sorted(v) for k, v in otros.items()}


def exportar(avisar=print) -> dict:
    datos = precios.cargar_productos()
    catalogo_tiendas = precios.cargar_comerciales()
    filtros = precios.filtros_barrido(datos)
    corte = datos.get("corte_linea_base", precios.CORTE_POR_DEFECTO)

    grupos = [[f"{c['id']}:{c['sku']}" for c in p.get("comerciales", []) if c.get("sku")]
              for p in datos["productos"]]
    seguidos = {i for g in grupos for i in g}

    items: list[dict] = []
    historial: dict[str, dict] = defaultdict(dict)
    tiendas_usadas = set()
    descartados = 0
    for cid, sku, f in almacen.todos():
        obs = f.get("observaciones", [])
        if not obs:
            continue
        # se reclasifica con las reglas vigentes: una regla corregida limpia tambien lo ya guardado
        k = almacen.clasificar(f.get("nombre", ""), filtros)
        if k:
            f = {**f, **{c: v for c, v in k.items() if v not in (None, "")}}
        elif not (f"{cid}:{sku}" in seguidos or sku.startswith("manual-")):
            descartados += 1
            continue
        if f.get("categoria") not in filtros:
            continue
        est = almacen.estadisticas(obs, corte)
        if est["ultimo"] is None:
            continue
        ident = f"{cid}:{sku}"
        tiendas_usadas.add(cid)
        items.append({
            "id": ident,
            "t": cid,
            "n": f.get("nombre", ""),
            "c": f.get("categoria"),
            "p": f.get("pulgadas"),
            "me": f.get("medida"),
            "ma": _marca(f.get("marca", "")),
            "mo": f.get("modelo", ""),
            "u": f.get("url", ""),
            "s": {k: _redondear(v) for k, v in est.items()},
            "nt": (obs[-1].get("nota") or "")[:120],
        })
        historial[cid][sku] = [
            [o["fecha"][:16], o["precio"], o.get("precio_lista"), 1 if o.get("disponible", True) else 0]
            for o in obs
        ]

    otros = _mismo_modelo(items, grupos)
    ids = {it["id"] for it in items}
    for it in items:
        o = [x for x in otros.get(it["id"], []) if x in ids]
        if o:
            it["o"] = o

    # las URLs de cada tienda comparten un prefijo: se guarda una vez por tienda
    prefijos = {}
    for c in tiendas_usadas:
        urls = [it["u"] for it in items if it["t"] == c and it["u"]]
        comun = os.path.commonprefix(urls) if urls else ""
        prefijos[c] = comun[: comun.rfind("/") + 1]

    catalogo = {
        "generado": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "corte": corte,
        "evento": datos.get("evento", {}),
        "umbral_oferta": almacen.UMBRAL_OFERTA,
        "umbral_cambio": almacen.UMBRAL_CAMBIO,
        "formato": {"s": list(CAMPOS_S)},
        "tiendas": [{"id": c, "nombre": precios.nombre_comercial(c, catalogo_tiendas),
                     "url": catalogo_tiendas.get(c, {}).get("url", ""), "prefijo": prefijos[c]}
                    for c in sorted(tiendas_usadas, key=lambda c: precios.nombre_comercial(c, catalogo_tiendas))],
        "categorias": [{"id": c, "nombre": cfg.get("nombre", c)} for c, cfg in filtros.items()],
        "pistas": almacen.pistas(filtros),
        "items": [_compacto(it, prefijos) for it in items],
    }
    _escribir(DIR_WEB_DATOS / "catalogo.json", catalogo)
    for cid, por_sku in historial.items():
        _escribir(DIR_WEB_DATOS / "historial" / f"{cid}.json", por_sku)
    tam = (DIR_WEB_DATOS / "catalogo.json").stat().st_size / 1024
    avisar(f"Exportado: {len(items)} productos de {len(tiendas_usadas)} tiendas -> web/data ({tam:,.0f} KB)"
           + (f" · {descartados} descartados por las reglas actuales" if descartados else ""))
    return {"productos": len(items), "tiendas": len(tiendas_usadas)}


if __name__ == "__main__":
    exportar()
