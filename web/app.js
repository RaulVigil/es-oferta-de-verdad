/* ¿Es oferta de verdad? — todo corre en el navegador con data/catalogo.json.
   Si la pagina la sirve scripts/servidor.py (modo local), ademas se puede
   actualizar precios y guardar lo que ves en los JSON del proyecto. */
"use strict";

const $ = (s, raiz = document) => raiz.querySelector(s);
const VACIAS = new Set(["de", "la", "el", "con", "y", "para", "en", "pulg", "un", "una"]);
const CLAVE_MIOS = "precios.mios.v1";
const PASO = 60;
// tonos para los monogramas de tienda (no son colores de marca: solo distinguen filas)
const TONOS = [32, 200, 145, 265, 352, 88, 180, 312, 52, 230];

const E = {
  catalogo: null,
  items: [],
  porId: new Map(),
  tiendas: new Map(),
  categorias: new Map(),
  historial: new Map(),   // tienda -> {sku: [[fecha, precio, lista, disponible]]}
  local: false,
  cat: "",
  visibles: PASO,
  resultados: [],
  abierto: null,
  nivelSello: null,
};

/* ---------------- formato ---------------- */
const dinero = (x) => x == null ? "—" : "$" + Number(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (x) => x == null ? "" : (x > 0.05 ? "+" : x < -0.05 ? "−" : "±") + Math.abs(x).toFixed(1) + " %";
const fecha = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso.length === 16 ? iso + ":00" : iso);
  return d.toLocaleDateString("es-SV", { day: "numeric", month: "short" });
};
const fechaHora = (iso) => new Date(iso).toLocaleString("es-SV", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const numero = (t) => {
  const v = parseFloat(String(t).replace(/[$\s,]/g, ""));
  return Number.isFinite(v) && v > 0 ? v : null;
};
const tamano = (it) => it.p ? `${it.p}"` : (it.me || "");

function monograma(tiendaId) {
  const t = E.tiendas.get(tiendaId);
  const nombre = (t?.nombre || tiendaId).normalize("NFKD").replace(/[̀-ͯ]/g, "");
  const partes = nombre.split(/\s+/).filter(Boolean);
  const letras = partes.length > 1 ? partes[0][0] + partes[1][0] : nombre.slice(0, 2);
  return `<span class="monograma" style="--h:${t?.tono ?? 40}" aria-hidden="true">${esc(letras.toUpperCase())}</span>`;
}

const TITULOS = { verde: "Oferta real", amarillo: "Rebaja leve", gris: "No es oferta", rojo: "Más caro", "sin-base": "Sin historial" };
const CORTOS = { "OFERTA REAL": "oferta", "DESCUENTO MENOR": "baja leve", "SIN CAMBIO": "sin cambio", "SUBIO": "subió", "SIN BASE": "sin base" };

function clasificar(p) {
  const { umbral_oferta: oferta, umbral_cambio: cambio } = E.catalogo;
  if (p == null) return ["SIN BASE", "sin-base"];
  if (p <= oferta) return ["OFERTA REAL", "verde"];
  if (p < -cambio) return ["DESCUENTO MENOR", "amarillo"];
  if (p <= cambio) return ["SIN CAMBIO", "gris"];
  return ["SUBIO", "rojo"];
}

/* ---------------- busqueda (misma normalizacion que almacen.py) ---------------- */
function normalizar(t) {
  t = String(t).normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  t = t.replace(/(\d)\s*(?:"|''|pulgadas|pulg|in\b)/g, "$1 pulg ");
  t = t.replace(/\b(\d{2}(?:\.\d)?)p\b/g, "$1 pulg ");
  t = t.replace(/”/g, " pulg ");
  return t.replace(/[^a-z0-9.]+/g, " ").trim();
}
const tokens = (t) => normalizar(t).split(" ").map((x) => x.replace(/^\.+|\.+$/g, "")).filter(Boolean);

function interpretar(q) {
  let cat = null;
  const palabras = [];
  const ts = tokens(q);
  for (let i = 0; i < ts.length; i++) {
    // frases primero: "teclado musical" no es la categoria de "teclado"
    const n = [3, 2].find((k) => i + k <= ts.length && E.catalogo.pistas[ts.slice(i, i + k).join(" ")]);
    if (n) {
      cat = cat || E.catalogo.pistas[ts.slice(i, i + n).join(" ")];
      i += n - 1;
      continue;
    }
    const t = ts[i];
    if (E.catalogo.pistas[t]) cat = cat || E.catalogo.pistas[t];
    else if (!VACIAS.has(t)) palabras.push(t);
  }
  return { cat, palabras };
}

function puntaje(palabras, it) {
  if (!palabras.length) return [1, 0];
  it._w ||= new Set(it.k.split(" "));
  it._c ||= it.k.replace(/ /g, "");
  let hechos = 0, completas = 0;
  for (const q of palabras) {
    if (it._w.has(q) || (/^\d+$/.test(q) && String(it.p) === q)) { hechos++; completas++; }
    else if (q.length >= 3 && it._c.includes(q)) hechos++;  // parte de un codigo: "u8000" en "un55u8000hpxpa"
  }
  return [hechos / palabras.length, completas];
}

function filtrar() {
  const q = $("#q").value;
  document.body.classList.toggle("buscando", q.trim().length > 0);
  const { cat: catTexto, palabras } = interpretar(q);
  const cat = E.cat || catTexto;
  const tienda = $("#f-tienda").value;
  const max = numero($("#f-max").value);
  const bajas = $("#f-bajas").checked;
  const evaluar = (minimo) => {
    const salida = [];
    for (const it of E.items) {
      if (cat && it.c !== cat) continue;
      if (tienda && it.t !== tienda) continue;
      if (max && it.s.ultimo > max) continue;
      if (bajas && !(it.s.pct_base != null && it.s.pct_base < -E.catalogo.umbral_cambio)) continue;
      const [p, c] = puntaje(palabras, it);
      if (p >= minimo) salida.push({ it, p, c });
    }
    return salida;
  };
  let res = evaluar(0.99), parcial = false;
  if (!res.length && palabras.length) { res = evaluar(0.5); parcial = res.length > 0; }

  const orden = $("#f-orden").value;
  const ordenCat = new Map([...E.categorias.keys()].map((c, i) => [c, i]));
  const porPrecio = (a, b) => a.it.s.ultimo - b.it.s.ultimo;
  if (orden === "precio") res.sort(porPrecio);
  else if (orden === "baja") res.sort((a, b) => (a.it.s.pct_base ?? 999) - (b.it.s.pct_base ?? 999) || porPrecio(a, b));
  else if (orden === "nombre") res.sort((a, b) => a.it.n.localeCompare(b.it.n, "es"));
  else if (palabras.length) res.sort((a, b) => b.p - a.p || b.c - a.c || porPrecio(a, b));
  else res.sort((a, b) => ordenCat.get(a.it.c) - ordenCat.get(b.it.c) || porPrecio(a, b));

  E.resultados = res.map((r) => r.it);
  E.parcial = parcial;
  E.catEfectiva = cat;
  E.visibles = PASO;
  pintarCategorias();
  pintarLista();
  const url = new URL(location.href);
  q ? url.searchParams.set("q", q) : url.searchParams.delete("q");
  E.cat ? url.searchParams.set("cat", E.cat) : url.searchParams.delete("cat");
  history.replaceState(history.state, "", url);
}

/* ---------------- cabecera ---------------- */
function pintarCabecera() {
  const c = E.catalogo;
  const ofertas = E.items.filter((it) => it.s.nivel === "verde").length;
  $("#datos").innerHTML = [
    [E.items.length.toLocaleString("es-SV"), "productos"],
    [c.tiendas.length, "tiendas"],
    [E.categorias.size, "categorías"],
    [ofertas.toLocaleString("es-SV"), "ofertas reales hoy"],
    [fechaHora(c.generado), "última captura"],
  ].map(([v, k]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("");

  const bf = c.evento?.black_friday;
  if (bf) {
    const dias = Math.round((new Date(bf + "T00:00:00") - new Date().setHours(0, 0, 0, 0)) / 864e5);
    $("#cuenta").innerHTML = dias > 1 ? `faltan <b>${dias}</b> días para Black Friday`
      : dias === 1 ? "Black Friday es <b>mañana</b>" : dias === 0 ? "hoy es <b>Black Friday</b>" : "temporada de ofertas";
  }
  $("#pie-corte").textContent = fecha(c.corte + "T12:00");
}

/* ---------------- lista ---------------- */
function pintarCategorias() {
  const nav = $("#categorias");
  if (!nav.childElementCount) {
    const cuenta = new Map();
    for (const it of E.items) cuenta.set(it.c, (cuenta.get(it.c) || 0) + 1);
    const boton = (id, nombre, n) =>
      `<button type="button" data-cat="${id}">${esc(nombre.toLowerCase())}<small>${n}</small></button>`;
    nav.innerHTML = boton("", "todo", E.items.length) +
      [...E.categorias].filter(([id]) => cuenta.get(id)).map(([id, nombre]) => boton(id, nombre, cuenta.get(id))).join("");
    nav.addEventListener("click", (ev) => {
      const b = ev.target.closest("button");
      if (!b) return;
      E.cat = E.cat === b.dataset.cat ? "" : b.dataset.cat;
      filtrar();
    });
  }
  const activa = E.cat || E.catEfectiva || "";
  for (const b of nav.children) {
    const si = b.dataset.cat === activa;
    b.setAttribute("aria-pressed", String(si));
    if (si && b.dataset.cat) nav.scrollTo({ left: b.offsetLeft - nav.clientWidth / 3, behavior: "smooth" });
  }
}

function pintarLista() {
  const lista = $("#lista");
  const total = E.resultados.length;
  $("#conteo").innerHTML = total
    ? `<b>${total.toLocaleString("es-SV")}</b> ${total === 1 ? "producto" : "productos"}${E.parcial ? " parecidos — ninguno tiene todas las palabras" : ""}`
    : "";
  if (!total) {
    lista.innerHTML = `<li class="vacio"><b>Nada por aquí.</b>Prueba con menos palabras, otra tienda o quita “solo bajas”.</li>`;
    $("#mas").hidden = true;
    return;
  }
  const molde = $("#t-fila");
  const frag = document.createDocumentFragment();
  for (const it of E.resultados.slice(0, E.visibles)) {
    const li = molde.content.cloneNode(true);
    const b = li.querySelector(".fila");
    b.dataset.id = it.id;
    if (E.abierto === it.id) b.setAttribute("aria-current", "true");
    li.querySelector(".monograma").outerHTML = monograma(it.t);
    li.querySelector(".fila-nombre").textContent = it.n;
    li.querySelector(".fila-precio").textContent = dinero(it.s.ultimo);
    li.querySelector(".fila-meta").textContent =
      [E.tiendas.get(it.t)?.nombre, tamano(it), it.ma, it.s.disponible ? "" : "agotado"].filter(Boolean).join(" · ");
    const v = li.querySelector(".fila-var");
    const debil = it.s.base != null && it.s.n_base < 2 ? "*" : "";
    const texto = it.s.pct_base && Math.abs(it.s.pct_base) >= 0.05
      ? `${CORTOS[it.s.veredicto]} ${pct(it.s.pct_base)}` : CORTOS[it.s.veredicto] + debil;
    v.innerHTML = `<i></i>${esc(texto)}`;
    v.className = "fila-var " + it.s.nivel;
    frag.appendChild(li);
  }
  lista.replaceChildren(frag);
  $("#mas").hidden = total <= E.visibles;
}

/* ---------------- detalle ---------------- */
async function historialDe(it) {
  if (!E.historial.has(it.t)) {
    try {
      const r = await fetch(`data/historial/${it.t}.json`, { cache: "no-cache" });
      E.historial.set(it.t, r.ok ? await r.json() : {});
    } catch { E.historial.set(it.t, {}); }
  }
  const sku = it.id.slice(it.t.length + 1);
  return E.historial.get(it.t)[sku] || [];
}

function mios() {
  try { return JSON.parse(localStorage.getItem(CLAVE_MIOS)) || {}; } catch { return {}; }
}
function guardarMios(datos) {
  try { localStorage.setItem(CLAVE_MIOS, JSON.stringify(datos)); return true; } catch { return false; }
}

function evaluar(it, precio, lista) {
  const s = it.s;
  const p = s.base ? (precio / s.base - 1) * 100 : null;
  const [veredicto, nivel] = clasificar(p);
  const notas = [];
  if (s.base == null) notas.push(`No hay precios guardados antes del ${fecha(E.catalogo.corte + "T12:00")}: no se puede saber si es oferta.`);
  else if (s.n_base < 2) notas.push("La línea base tiene un solo dato: tómalo como indicativo.");
  if (s.minimo != null && precio > s.minimo + 0.005) notas.push(`Ya estuvo más barato: ${dinero(s.minimo)} el ${fecha(s.fecha_minimo)}.`);
  if (lista && s.max_lista_previa && lista > s.max_lista_previa * 1.02) {
    notas.push(`El “antes” (${dinero(lista)}) es ${Math.round((lista / s.max_lista_previa - 1) * 100)} % más alto que el tachado que mostraba la tienda (${dinero(s.max_lista_previa)}): descuento inflado.`);
  }
  if (lista && s.base) {
    notas.push(`Descuento anunciado: ${Math.round((1 - precio / lista) * 100)} %. Real, contra su línea base: ${Math.round((1 - precio / s.base) * 100)} %.`);
  }
  if (it.nt) notas.push(`Nota de la tienda: ${it.nt}.`);
  return { p, veredicto, nivel, notas };
}

function grafica(hist, base, hoy) {
  const puntos = hist.map(([f, precio]) => [new Date(f.length === 16 ? f + ":00" : f).getTime(), precio]);
  if (!puntos.length) return "";
  const ahora = Date.now();
  const W = 440, H = 160, ml = 50, mr = 10, mt = 12, mb = 22;
  const t0 = Math.min(...puntos.map((p) => p[0])), t1 = Math.max(ahora, ...puntos.map((p) => p[0]));
  const vals = puntos.map((p) => p[1]).concat(base ? [base] : [], hoy ? [hoy] : []);
  let v0 = Math.min(...vals), v1 = Math.max(...vals);
  const margen = Math.max((v1 - v0) * 0.18, v1 * 0.04);
  v0 -= margen; v1 += margen;
  const x = (t) => ml + (t1 === t0 ? (W - ml - mr) / 2 : ((t - t0) / (t1 - t0)) * (W - ml - mr));
  const y = (v) => mt + (1 - (v - v0) / (v1 - v0)) * (H - mt - mb);
  // escalones: el precio se mantiene hasta la siguiente captura
  let d = `M${x(puntos[0][0]).toFixed(1)},${y(puntos[0][1]).toFixed(1)}`;
  for (let i = 1; i < puntos.length; i++) d += `H${x(puntos[i][0]).toFixed(1)}V${y(puntos[i][1]).toFixed(1)}`;
  d += `H${x(ahora).toFixed(1)}`;
  const area = `${d}V${H - mb}H${x(puntos[0][0]).toFixed(1)}Z`;
  const etiquetas = [v1 - margen, v0 + margen].map((v) => `<text x="${ml - 8}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end">${dinero(v).replace(".00", "")}</text>`).join("");
  const ultimo = puntos[puntos.length - 1];
  return `<svg class="grafica" viewBox="0 0 ${W} ${H}" role="img" aria-label="Historial de precios">
    <defs><linearGradient id="relleno" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="currentColor" stop-opacity=".16"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/>
    </linearGradient></defs>
    ${etiquetas}
    <path d="${area}" fill="url(#relleno)"/>
    ${base ? `<line x1="${ml}" x2="${W - mr}" y1="${y(base).toFixed(1)}" y2="${y(base).toFixed(1)}" stroke="currentColor" stroke-opacity=".4" stroke-dasharray="2 5" stroke-linecap="round"/>
      <text x="${W - mr}" y="${(y(base) - 6).toFixed(1)}" text-anchor="end">línea base ${dinero(base).replace(".00", "")}</text>` : ""}
    <path d="${d}" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
    ${puntos.map(([t, v]) => `<circle cx="${x(t).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.6" fill="currentColor"><title>${fecha(new Date(t).toISOString())}: ${dinero(v)}</title></circle>`).join("")}
    <circle cx="${x(ultimo[0]).toFixed(1)}" cy="${y(ultimo[1]).toFixed(1)}" r="4.5" fill="var(--superficie)" stroke="currentColor" stroke-width="2"/>
    ${hoy ? `<g><circle cx="${x(ahora).toFixed(1)}" cy="${y(hoy).toFixed(1)}" r="7" fill="var(--marca)" stroke="currentColor" stroke-width="1.5"><title>Lo que ves: ${dinero(hoy)}</title></circle>
      <text x="${(x(ahora) - 12).toFixed(1)}" y="${(y(hoy) + 4).toFixed(1)}" text-anchor="end" style="fill:currentColor;font-weight:600">${dinero(hoy)}</text></g>` : ""}
    <text x="${ml}" y="${H - 6}">${fecha(new Date(t0).toISOString())}</text>
    <text x="${W - mr}" y="${H - 6}" text-anchor="end">hoy</text>
  </svg>`;
}

async function abrir(id, { empujar = true } = {}) {
  const it = E.porId.get(id);
  if (!it) return;
  E.abierto = id;
  E.nivelSello = null;
  if (empujar) history.pushState({ id, interno: true }, "", `#/${encodeURIComponent(id)}`);
  document.body.classList.add("con-detalle");
  $(".cuerpo").classList.remove("sin-detalle");
  const panel = $("#detalle");
  panel.hidden = false;
  $("#velo").hidden = false;
  for (const b of document.querySelectorAll(".fila")) b.toggleAttribute("aria-current", b.dataset.id === id);

  const tienda = E.tiendas.get(it.t);
  const s = it.s;
  const debil = s.base != null && s.n_base < 2 ? "*" : "";
  $("#detalle-contenido").innerHTML = `
    <div class="asa" aria-hidden="true"></div>
    <button class="volver" type="button">← volver a la lista</button>
    <div class="d-sup"><span>${esc(tienda?.nombre)} · ${esc(E.categorias.get(it.c))}</span>
      ${it.u ? `<a href="${esc(it.u)}" target="_blank" rel="noopener">ver en la tienda ↗</a>` : ""}</div>
    <h2 class="d-titulo">${esc(it.n)}</h2>
    <p class="d-meta">${[tamano(it), it.ma, it.mo, s.disponible ? "" : "agotado al último registro"].filter(Boolean).map(esc).join(" · ")}</p>

    <div class="etiqueta">
      <label>¿qué precio ves?<span class="campo"><span>$</span><input id="d-precio" inputmode="decimal" autocomplete="off" placeholder="${s.ultimo.toFixed(2)}" aria-label="Precio que ves"></span></label>
      <label>“antes”<span class="campo chico"><span>$</span><input id="d-lista" inputmode="decimal" autocomplete="off" placeholder="opcional" aria-label="Precio antes, tachado"></span></label>
    </div>
    <div class="veredicto" id="d-veredicto" aria-live="polite"></div>

    <dl class="cifras">
      <div><dt>último</dt><dd>${dinero(s.ultimo)}</dd></div>
      <div><dt>base${debil}</dt><dd>${dinero(s.base)}</dd></div>
      <div><dt>mínimo</dt><dd>${dinero(s.minimo)}</dd></div>
      <div><dt>máximo</dt><dd>${dinero(s.maximo)}</dd></div>
    </dl>
    <div id="d-grafica"></div>
    <p class="aviso">${s.n} ${s.n === 1 ? "precio registrado" : "precios registrados"} · último ${fecha(s.fecha)}${debil ? " · *base de un solo dato" : ""}</p>

    <section class="d-seccion" id="d-otras"></section>
    <section class="d-seccion" id="d-mios"></section>

    <div class="acciones">
      <button class="boton" id="d-guardar" type="button" disabled>guardar este precio</button>
      <span class="aviso" id="d-msg">${E.local ? "Queda en el historial del proyecto." : "Queda guardado en este dispositivo."}</span>
    </div>`;

  const hist = await historialDe(it);
  if (E.abierto !== id) return;
  const actualizar = () => {
    const precio = numero($("#d-precio").value);
    const lista = numero($("#d-lista").value);
    pintarVeredicto(it, precio, lista);
    $("#d-grafica").innerHTML = grafica(hist, s.base, precio);
    pintarOtras(it, precio);
    $("#d-guardar").disabled = !precio;
  };
  $("#d-precio").addEventListener("input", actualizar);
  $("#d-lista").addEventListener("input", actualizar);
  $(".volver").addEventListener("click", volver);
  $("#d-guardar").addEventListener("click", () => guardar(it));
  const inicial = new URLSearchParams(location.hash.split("?")[1] || "");
  if (inicial.get("precio")) $("#d-precio").value = inicial.get("precio");
  if (inicial.get("lista")) $("#d-lista").value = inicial.get("lista");
  actualizar();
  pintarMios(it);
  if (matchMedia("(min-width: 960px)").matches) $("#d-precio").focus({ preventScroll: true });
  else panel.scrollTop = 0;
}

function pintarVeredicto(it, precio, lista) {
  const caja = $("#d-veredicto");
  if (!precio) {
    const s = it.s;
    E.nivelSello = null;
    const estado = s.pct_base == null ? "" : ` · ${CORTOS[s.veredicto]}${Math.abs(s.pct_base) >= 0.05 ? " " + pct(s.pct_base) : ""} frente a su línea base`;
    caja.innerHTML = `<p class="pista-veredicto">Escribe el precio que ves en la tienda.
      <span class="${s.nivel}">Hoy cuesta ${dinero(s.ultimo)}${estado}.</span></p>`;
    return;
  }
  const v = evaluar(it, precio, lista);
  const estampa = E.nivelSello !== v.nivel;   // el sello solo "golpea" cuando cambia el veredicto
  E.nivelSello = v.nivel;
  caja.innerHTML = `<div class="sello ${v.nivel}${estampa ? " estampa" : ""}">
      <b>${TITULOS[v.nivel]}</b>
      <small>${v.p == null ? "sin línea base" : pct(v.p) + " vs línea base " + dinero(it.s.base)}</small>
    </div>
    ${v.notas.length ? `<ul class="notas">${v.notas.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}`;
}

function pintarOtras(it, precio) {
  const caja = $("#d-otras");
  const otras = (it.o || []).map((id) => E.porId.get(id)).filter(Boolean).sort((a, b) => a.s.ultimo - b.s.ultimo);
  if (!otras.length) { caja.innerHTML = ""; return; }
  const ref = precio || it.s.ultimo;
  caja.innerHTML = `<h3>El mismo modelo, en otras tiendas</h3><ul class="otras">${otras.map((o) => {
    const dif = (o.s.ultimo / ref - 1) * 100;
    return `<li>${monograma(o.t)}<a href="#/${encodeURIComponent(o.id)}" data-id="${esc(o.id)}"><b>${esc(E.tiendas.get(o.t)?.nombre)}</b><small>${esc(o.n)}</small></a>
      <span class="p">${dinero(o.s.ultimo)}</span><span class="v ${dif < -0.5 ? "verde" : "gris"}">${pct(dif)}</span></li>`;
  }).join("")}</ul>`;
  caja.querySelectorAll("a[data-id]").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); abrir(a.dataset.id); }));
}

function pintarMios(it) {
  const caja = $("#d-mios");
  const lista = mios()[it.id] || [];
  if (!lista.length) { caja.innerHTML = ""; return; }
  caja.innerHTML = `<h3>Lo que anotaste aquí</h3><ul class="otras">${lista.map(([f, p, l], i) =>
    `<li><span></span><span>${fechaHora(f)}${l ? `<small>“antes” ${dinero(l)}</small>` : ""}</span><span class="p">${dinero(p)}</span>
     <button class="enlace borrar" data-i="${i}" type="button">borrar</button></li>`).join("")}</ul>`;
  caja.querySelectorAll("button[data-i]").forEach((b) => b.addEventListener("click", () => {
    const datos = mios();
    datos[it.id].splice(+b.dataset.i, 1);
    if (!datos[it.id].length) delete datos[it.id];
    guardarMios(datos);
    pintarMios(it);
  }));
}

async function guardar(it) {
  const precio = numero($("#d-precio").value);
  const lista = numero($("#d-lista").value);
  if (!precio) return;
  const msg = $("#d-msg");
  $("#d-guardar").disabled = true;
  if (E.local) {
    const [comercial, ...resto] = it.id.split(":");
    try {
      const r = await fetch("api/registrar", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comercial, sku: resto.join(":"), precio, precio_lista: lista }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "error");
      msg.textContent = d.mensaje;
      E.historial.delete(it.t);
      await cargarCatalogo();
      return;
    } catch (e) { msg.textContent = "No se pudo guardar en el proyecto (" + e.message + "). Lo guardo en este dispositivo."; }
  }
  const datos = mios();
  (datos[it.id] ||= []).push([new Date().toISOString(), precio, lista]);
  msg.textContent = guardarMios(datos) ? "Guardado en este dispositivo." : "El navegador no permite guardar aquí.";
  pintarMios(it);
}

// si se entro directo a un producto (enlace compartido), "volver" no debe salir del sitio
function volver() {
  if (history.state?.interno) history.back();
  else { history.replaceState(null, "", location.pathname + location.search); cerrar(); }
}

function cerrar() {
  E.abierto = null;
  $("#detalle").hidden = true;
  $("#velo").hidden = true;
  document.body.classList.remove("con-detalle");
  $(".cuerpo").classList.add("sin-detalle");
  for (const b of document.querySelectorAll(".fila[aria-current]")) b.removeAttribute("aria-current");
}

/* ---------------- modo local: actualizar precios ---------------- */
async function detectarLocal() {
  try {
    const r = await fetch("api/estado", { cache: "no-store" });
    if (!r.ok) return;
    const d = await r.json();
    E.local = !!d.local;
    if (!E.local) return;
    const b = $("#btn-actualizar");
    b.hidden = false;
    b.addEventListener("click", async () => {
      await fetch("api/capturar", { method: "POST" });
      seguirCaptura();
    });
    if (d.captura?.activa) seguirCaptura();
  } catch { /* sitio estatico: sin servidor */ }
}

function seguirCaptura() {
  const b = $("#btn-actualizar"), log = $("#log");
  b.disabled = true;
  b.textContent = "actualizando…";
  log.hidden = false;
  const tic = async () => {
    const d = await (await fetch("api/estado", { cache: "no-store" })).json();
    log.textContent = d.captura.lineas.join("\n");
    log.scrollTop = log.scrollHeight;
    if (d.captura.activa) return setTimeout(tic, 2000);
    b.disabled = false;
    b.textContent = "actualizar precios";
    E.historial.clear();
    await cargarCatalogo();
  };
  tic();
}

/* ---------------- carga ---------------- */
// El catalogo llega compacto (scripts/exportar.py): estadisticas en lista, URLs sin el
// prefijo de la tienda, y sin la clave de busqueda ni el veredicto, que se calculan aqui.
function expandir(c) {
  const campos = c.formato.s;
  const prefijos = new Map(c.tiendas.map((t) => [t.id, t.prefijo || ""]));
  for (const it of c.items) {
    it.id = `${it.t}:${it.i}`;
    const s = Object.fromEntries(campos.map((k, i) => [k, it.s[i]]));
    s.disponible = !!s.disponible;
    s.fecha_minimo ||= s.fecha;
    [s.veredicto, s.nivel] = clasificar(s.pct_base);
    it.s = s;
    if (it.u && !/^https?:/.test(it.u)) it.u = prefijos.get(it.t) + it.u;
    it.ma ||= "";
    it.k = normalizar(`${it.n} ${it.ma} ${it.mo || ""}`);
  }
}

async function cargarCatalogo() {
  const r = await fetch("data/catalogo.json", { cache: "no-cache" });
  if (!r.ok) throw new Error("no encontré data/catalogo.json (corre scripts/exportar.py)");
  const c = await r.json();
  E.catalogo = c;
  expandir(c);
  E.items = c.items;
  E.porId = new Map(c.items.map((it) => [it.id, it]));
  E.tiendas = new Map(c.tiendas.map((t, i) => [t.id, { ...t, tono: TONOS[i % TONOS.length] }]));
  E.categorias = new Map(c.categorias.map((k) => [k.id, k.nombre]));
  const sel = $("#f-tienda");
  if (sel.options.length <= 1) for (const t of c.tiendas) sel.add(new Option(t.nombre, t.id));
  pintarCabecera();
  filtrar();
  if (E.abierto && E.porId.has(E.abierto)) abrir(E.abierto, { empujar: false });
}

function idDelHash() {
  const m = location.hash.match(/^#\/([^?]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

let espera;
$("#q").addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(filtrar, 120); });
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter" && E.resultados[0]) abrir(E.resultados[0].id); });
["#f-tienda", "#f-orden", "#f-bajas"].forEach((s) => $(s).addEventListener("change", filtrar));
$("#f-max").addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(filtrar, 200); });
$("#mas").addEventListener("click", () => { E.visibles += PASO; pintarLista(); });
$("#lista").addEventListener("click", (e) => { const b = e.target.closest(".fila"); if (b) abrir(b.dataset.id); });
$("#velo").addEventListener("click", volver);
window.addEventListener("popstate", () => { const id = idDelHash(); id ? abrir(id, { empujar: false }) : cerrar(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement?.tagName !== "INPUT") { e.preventDefault(); $("#q").focus(); }
  if (e.key === "Escape" && E.abierto) volver();
});

(async () => {
  const params = new URLSearchParams(location.search);
  $("#q").value = params.get("q") || "";
  E.cat = params.get("cat") || "";
  try {
    await cargarCatalogo();
  } catch (e) {
    $("#datos").innerHTML = `<div><dt>error</dt><dd>${esc(e.message)}</dd></div>`;
    return;
  }
  await detectarLocal();
  const id = idDelHash();
  if (id) { history.replaceState({ id }, "", location.href); abrir(id, { empujar: false }); }
  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) navigator.serviceWorker.register("sw.js");
})();
