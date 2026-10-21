# ¿Es oferta de verdad?

**¿Esa oferta de Black Friday es real?** Historial de precios de 9 tiendas de El Salvador para
comparar lo que anuncian en noviembre contra lo que costaba antes.

Las tiendas suben el precio "antes" para que el descuento se vea grande. Esta app guarda
cada día el precio publicado de miles de productos y, cuando ves una oferta, la compara contra
la **mediana de lo que costó antes del 1 de noviembre**, no contra el precio tachado.

- PWA instalable, funciona sin conexión con los últimos datos.
- Sin servidor ni base de datos: un sitio estático en Vercel con archivos JSON.
- La captura es un script de Python sin dependencias que corre a diario en GitHub Actions.
- Sin IA: consultas HTTP y reglas de texto.

## Cómo funciona

```
 GitHub Actions (7:00 a. m., diario)
   └─ scripts/precios.py capturar
        ├─ consulta 9 tiendas ──────────► data/listados/<tienda>.json   (historial completo)
        └─ scripts/exportar.py ─────────► web/data/catalogo.json        (estadísticas ya calculadas)
                                          web/data/historial/<tienda>.json
   └─ git push ──► Vercel publica web/

 Navegador (web/app.js)
   búsqueda, veredicto, gráfica y comparación entre tiendas: todo en el cliente
```

### Cómo se leen las tiendas

Cada tienda expone el mismo catálogo que usa su propio sitio web; no hay scraping de pantallas.

| Tienda | Fuente | Qué se toma |
|---|---|---|
| Simán, Walmart | API de catálogo VTEX | categorías de TV, camas + búsquedas de texto |
| La Curacao, RadioShack | GraphQL de Magento | categorías + búsquedas |
| Prado, EPA | índice público de Algolia del buscador | facetas + búsquedas |
| Zona Digital | API JSON de su página | catálogo completo (~1,400 productos) |
| AEON | tienda Odoo (HTML con schema.org) | categorías de cómputo |
| Omnisport | HTML de categorías y productos | TV, camas, electrodomésticos |

Pendientes: Vidrí (precios por JavaScript), Freund (claves de búsqueda ofuscadas),
Tropigas (desafío anti-bot), Samsung (no publica precios).

### Qué se sigue

Las categorías se definen en `data/productos.json → barrido` sin tocar código: TV (40" a 60"),
camas de 1.40 m, teclados, monitores, sillas de escritorio, controles, consolas, laptops,
memorias RAM, SSD/M.2, repisas, escritorios, roperos, audífonos, mouse, cerámica, inodoros,
lavamanos, duchas y grifería, refrigeradoras, lavadoras, microondas y freidoras de aire.

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
| `incluir` | regex: el nombre debe contenerla (anclada al inicio para evitar "Funda **para** laptop") |
| `excluir` | regex: accesorios, repuestos, juguetes |
| `pistas` | palabras que en el buscador de la web filtran esta categoría |
| `pulgadas_min/max` | rango de tamaño (TV, monitores) |
| `omnisport` | categorías de omnisport.com a recorrer |

## El veredicto

| | Condición |
|---|---|
| **Oferta real** | 10 % o más por debajo de la línea base |
| Descuento pequeño | entre 3 % y 10 % abajo |
| No es oferta | se movió menos de 3 % |
| Está más caro | arriba de la línea base |

**Línea base** = mediana de los precios capturados antes del 1 de noviembre en esa tienda.
Además avisa si el producto ya estuvo más barato, si el "antes" que anuncian es más alto que
el tachado que se vio en octubre, y muestra **el mismo modelo en otras tiendas** (por código de
modelo, o por las equivalencias de `productos.json → productos`).

## Uso local

Requiere Python 3.10 o más reciente. Sin dependencias.

```bash
python scripts/precios.py capturar      # barre las tiendas y regenera web/data (~8 min)
python scripts/servidor.py              # http://127.0.0.1:8765
```

Con el servidor local, la web además puede **actualizar precios** y **guardar en el historial**
el precio que viste en tienda. En la versión publicada, lo que guardas queda en tu dispositivo.

| Comando | Para qué |
|---|---|
| `precios.py capturar [--categoria tv] [--comercial siman]` | Barre y guarda los precios de hoy, y exporta |
| `precios.py exportar` | Regenera `web/data/` |
| `precios.py reporte` | `reportes/reporte.md` con los modelos seguidos y las bajas reales |
| `precios.py productos` / `lista` / `add` / `quitar` | Modelos seguidos desde la terminal |

## Publicar en Vercel

1. Sube el proyecto a un repositorio de GitHub.
2. En Vercel: **Add New → Project**, importa el repositorio. `vercel.json` ya indica que se
   publica la carpeta `web/` sin paso de compilación.
3. En GitHub: **Settings → Actions → General → Workflow permissions → Read and write**, para
   que la captura diaria pueda subir los JSON.
4. **Actions → Capturar precios → Run workflow** para la primera corrida.

Cada push de la captura dispara una publicación nueva en Vercel.

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
.github/workflows/         captura diaria
```

## Límites

- Precio publicado en línea, de contado, sin envío. El de tienda física o a crédito puede variar.
- EPA muestra precios de su sucursal de Soyapango.
- Los nombres de las tiendas no siempre traen el modelo exacto: la comparación entre tiendas
  es automática en TV, monitores y similares, y manual (equivalencias) en camas.
- La clasificación por reglas puede dejar pasar algún accesorio: se corrige agregando su
  palabra a `excluir`.
- Los datos son de las tiendas; este proyecto solo los consulta con pausas entre peticiones.
