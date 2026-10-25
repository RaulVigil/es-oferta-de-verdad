# ¿Es oferta de verdad?

**¿Esa oferta de Black Friday es real?** Historial de precios de 13 tiendas de El Salvador para
comparar lo que anuncian en noviembre contra lo que costaba antes.

**Sitio:** https://es-oferta-de-verdad.vercel.app

Las tiendas suben el precio "antes" para que el descuento se vea grande. Esta app guarda
cada día el precio publicado de miles de productos y, cuando ves una oferta, la compara contra
la **mediana de lo que costó antes del 1 de noviembre**, no contra el precio tachado.

- PWA instalable, funciona sin conexión con los últimos datos.
- Sin servidor ni base de datos: un sitio estático en Vercel con archivos JSON.
- La captura es un script de Python sin dependencias que corre a diario en GitHub Actions.
- Sin IA: consultas HTTP y reglas de texto.

## Cómo funciona

```
 GitHub Actions (6:17 a. m. diario, respaldo a la 1:47 p. m.)
   └─ scripts/precios.py capturar
        ├─ consulta 13 tiendas ─────────► data/listados/<tienda>.json   (historial completo)
        └─ scripts/exportar.py ─────────► web/data/catalogo.json        (estadísticas ya calculadas)
                                          web/data/historial/<tienda>.json
   └─ git push ──► Vercel publica web/

 Navegador (web/app.js)
   búsqueda, veredicto, gráfica y comparación entre tiendas: todo en el cliente
```

Cada producto guarda todas sus observaciones de precio; una tienda caída no detiene a las
demás, y cada tienda tiene un límite de 8 minutos. Si alguna no entrega datos, se suben las
demás y el flujo termina en rojo para que GitHub avise. La corrida completa tarda unos 17 minutos.

### Cómo se leen las tiendas

Cada tienda expone el mismo catálogo que usa su propio sitio web; no hay scraping de pantallas.

| Tienda | Fuente | Qué se toma |
|---|---|---|
| Simán, Walmart | API de catálogo VTEX | categorías de TV, camas + búsquedas de texto |
| La Curacao, RadioShack | Adobe Live Search (el buscador del sitio) | catálogo completo (~8,800 y ~3,600 productos) |
| Samsung | GraphQL de Magento de la tienda oficial (vista de El Salvador, USD) | catálogo completo (~430 productos) |
| Prado, EPA | índice público de Algolia del buscador | facetas + búsquedas |
| Vidrí | API pública de su buscador (Doofinder) | búsquedas (máx. 1,000 resultados cada una) |
| Zona Digital | API JSON de su página | catálogo completo (~1,400 productos) |
| AEON | tienda Odoo (HTML con schema.org) | categorías de cómputo |
| Omnisport | HTML de categorías y productos | TV, camas, electrodomésticos |
| COOPESA | WooCommerce Store API | catálogo completo (~600 productos) |
| Electrónica 2001 | HTML de categorías + API por código | categorías de instrumentos y audio |

Sin incluir: Freund (claves de búsqueda ofuscadas), Tropigas (desafío anti-bot).

De cada producto se guarda también la foto que publica la tienda (reducida a ~300 px donde la
tienda lo permite); la web la carga desde la tienda solo cuando la fila está a la vista.

### Qué se sigue

Las categorías se definen en `data/productos.json → barrido` sin tocar código: TV (40" a 60"),
camas de 1.40 m, teclados, monitores, sillas de escritorio, controles, consolas, laptops,
memorias RAM, SSD/M.2, repisas, escritorios, roperos, audífonos, mouse, cerámica, inodoros,
lavamanos, duchas y grifería, refrigeradoras, lavadoras, microondas, freidoras de aire,
amplificadores de instrumento, guitarras, bajos, teclados musicales y pianos, baterías,
micrófonos y ukuleles.

```json
"inodoro": {
  "nombre": "Inodoros",
  "buscar": ["inodoro", "sanitario"],
  "pistas": ["inodoros", "sanitario"],
  "incluir": "^\\s*(inodoro|sanitario|taza (de ba[nñ]o|sanitaria))",
  "excluir": "asiento|tapa|v[aá]lvula|kit|flapper|herraje|..."
}
```

| Campo | Para qué |
|---|---|
| `buscar` | términos que se buscan en cada tienda |
| `incluir` | regex: el nombre debe contenerla (anclada al inicio para evitar "Funda **para** laptop"; en instrumentos admite hasta 4 palabras antes, porque Electrónica 2001 antepone el código de modelo) |
| `excluir` | regex: accesorios, repuestos, juguetes |
| `pistas` | palabras o frases que en el buscador de la web filtran esta categoría ("teclado musical" gana a "teclado") |
| `pulgadas_min/max` | rango de tamaño (TV, monitores) |
| `omnisport` | categorías de omnisport.com a recorrer |

Al exportar, todo lo guardado se vuelve a clasificar con las reglas vigentes: corregir una
regla limpia también el historial.

## El veredicto

| Veredicto | Condición |
|---|---|
| **Oferta** | 10 % o más por debajo de la línea base |
| Baja leve | entre 3 % y 10 % abajo |
| Sin cambio | se movió menos de 3 % |
| Subió | arriba de la línea base |
| Sin base | no hay precios capturados antes del 1 de noviembre |

**Línea base** = mediana de los precios capturados antes del 1 de noviembre en esa tienda.
Se descartan los precios de relleno: menos del 20 % del tachado (50 % si está agotado), como los
que Simán publica en productos descontinuados ($0.01, una laptop de $399 a $39). Lo que no salió
en la última captura de su tienda se marca como "ya no aparece" y va al final de la lista.
Además avisa si el producto ya estuvo más barato, si el "antes" que anuncian es más alto que
el tachado que se vio en octubre, y muestra **el mismo modelo en otras tiendas** (por código de
modelo, o por las equivalencias de `productos.json → productos`).

En la web también puedes escribir el precio que viste en una tienda para obtener el veredicto
al instante; lo que guardas queda en tu dispositivo.

## Correr en local

Requiere Python 3.10 o más reciente. Sin dependencias.

```bash
python scripts/servidor.py              # http://127.0.0.1:8765 con los datos del repositorio
python scripts/precios.py capturar      # barre las tiendas y regenera web/data (~17 min)
```

Con el servidor local, la web además puede **actualizar precios** y **guardar en el historial**
el precio que viste en tienda.

| Comando | Para qué |
|---|---|
| `precios.py capturar [--categoria tv] [--comercial siman]` | Barre y guarda los precios de hoy, y exporta |
| `precios.py exportar` | Regenera `web/data/` con las reglas vigentes |
| `precios.py productos` / `lista` / `add` / `quitar` | Modelos seguidos desde la terminal |

## Estructura

```
data/
  comerciales.json         tiendas
  productos.json           categorías del barrido + modelos seguidos
  listados/<tienda>.json   cada producto con su historial
scripts/
  tiendas.py               cómo leer cada tienda
  almacen.py               almacenamiento, clasificación, estadísticas
  precios.py               línea de comandos y captura
  exportar.py              JSON compactos para la web
  servidor.py              servidor local opcional
web/                       PWA estática (index.html, app.js, app.css, sw.js)
vercel.json                publica web/ sin paso de compilación
.github/workflows/         captura diaria
```

## Límites

- Precio publicado en línea, de contado, sin envío. El de tienda física o a crédito puede variar.
- EPA muestra precios de su sucursal de Soyapango.
- AEON y Electrónica 2001 no publican existencias en el listado: se asumen disponibles.
- Los nombres de las tiendas no siempre traen el modelo exacto: la comparación entre tiendas
  es automática en TV, monitores y similares, y manual (equivalencias) en camas.
- La clasificación por reglas puede dejar pasar algún accesorio: se corrige agregando su
  palabra a `excluir`.
- Los datos son de las tiendas; este proyecto solo los consulta con pausas entre peticiones.
