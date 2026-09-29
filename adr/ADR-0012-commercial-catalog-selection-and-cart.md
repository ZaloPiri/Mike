# ADR-0012 — Selección de catálogo comercial y carrito explícito

- **Status:** Accepted
- **Date:** 2026-09-29

## Contexto

ADR-0011 y el bloque B ya definen una consulta comercial de solo lectura:
Gestar es la autoridad, MIKE envía IDs y cantidades explícitos, y la
cotización se valida completa antes de presentarse. La demo local actual
(`tools/gestar_demo.py`) usa un catálogo sintético conocido por el lanzador;
no consulta todavía `GET /api/v1/commercial/products` ni mantiene un carrito.

Esta propuesta agrega únicamente la selección explícita desde catálogo y el
armado temporal de un carrito para la primera interfaz de terminal. No
interpreta lenguaje libre ni convierte la consulta en pedido.

## Decisión propuesta

### Frontera

Gestar seguirá siendo la única autoridad comercial. MIKE no importará código
de Gestar, no accederá a su base y no calculará precios. El recorrido
propuesto será:

```text
terminal -> catálogo HTTP de MIKE -> cliente MIKE ->
GET /api/v1/commercial/products de Gestar
                         |
carrito explícito -> POST /dev/commercial/quote -> POST /api/v1/commercial/quotes
```

La primera interfaz será la demo de terminal. No se propone un endpoint
comercial persistente nuevo en MIKE: la búsqueda puede ser una operación
interna de la demo y la cotización reutiliza `POST /dev/commercial/quote`.
Solo se agregaría una superficie HTTP si una futura interfaz distinta de la
terminal necesitara el mismo catálogo.

### Catálogo y búsqueda

El cliente comercial de MIKE deberá incorporar una operación de lectura para
`GET /api/v1/commercial/products` con:

- `query` opcional de 0 a 100 caracteres Unicode;
- `limit` entero de 1 a 100, por defecto 50; y
- `cursor` opaco de hasta 256 caracteres, reenviado sin interpretarlo.

La respuesta válida debe comprobar `installation_id` y `business_id` contra
el binding configurado, además de `products` y `next_cursor`. Cada producto
seleccionable conserva `product_id` entero, `name`, `code` nullable y `unit`.
El orden ascendente por `product_id` y la semántica de cursor pertenecen a
Gestar; MIKE no debe ordenar, paginar por offset ni reconstruir resultados.

Una búsqueda sin coincidencias es una página válida vacía. Un cursor inválido,
parámetro inválido, falta de scope, credencial inválida, configuración
incompatible o identidad incompatible se presenta como error seguro, no como
catálogo vacío. La búsqueda necesita exclusivamente el scope
`commercial.products.read`; la cotización conserva
`commercial.quotes.read`.

Los nombres iguales o similares nunca seleccionan silenciosamente un
producto. La terminal mostrará todas las coincidencias con ID, nombre, código
y unidad, y exigirá que el usuario elija un `product_id` exacto.

### Carrito temporal

El carrito será una estructura efímera de la sesión local de la demo:

```text
CartLine = { product_id: positive strict integer,
             quantity: positive strict integer }
Cart = ordered list[CartLine]
```

El carrito no se persiste, no se coloca en eventos, episodios, outbox ni
base de MIKE, y se descarta al salir la sesión o ante error fatal. La
implementación deberá limitarlo a las mismas 50 líneas y 10.000 unidades por
línea del contrato provisional. No aceptará booleanos, strings numéricos,
fracciones, IDs no provenientes de una página de catálogo ni cantidades cero.

Operaciones de terminal propuestas:

1. buscar por nombre o código;
2. elegir un ID mostrado;
3. agregar una línea con cantidad;
4. modificar la cantidad de un ID existente;
5. quitar un ID;
6. mostrar el carrito completo; y
7. cotizar el carrito completo.

Agregar nuevamente un producto ya presente será una decisión explícita de la
interfaz: por defecto reemplazará su cantidad después de confirmación, para
evitar sumar accidentalmente una segunda intención. La operación separada
`sumar` podrá agregarse luego; no habrá líneas duplicadas en el request.

La unidad mostrada es informativa y proviene del catálogo. MIKE no convierte
unidades, docenas, peso o packaging. La cantidad se envía como entero de
unidad de venta y Gestar decide si aplica unidad, paquete, promoción o grupo.

### Cotización y revalidación

Cotizará el carrito completo mediante el cliente de cotización existente.
Antes de enviar, MIKE comprobará límites y líneas únicas; Gestar volverá a
validar existencia, actividad, lista vigente, precios, promociones, grupos y
unidad. El catálogo no congela precio, vigencia, stock ni capacidad de
producción. Un producto puede desaparecer o cambiar entre búsqueda y
cotización y la operación completa deberá rechazarse de forma segura cuando
Gestar no pueda cotizarla.

La respuesta solo se presenta si el cliente valida identidad, ARS, fechas,
timestamp aware, lista, líneas exactas, componentes, paquetes, remanentes,
Decimal, total y flags `stock_reserved=false` y
`availability_guaranteed=false`. Las advertencias de stock siguen siendo
observaciones; su ausencia no promete reserva ni disponibilidad futura.

Se reutilizan el timeout total de cinco segundos, HTTPS fuera de loopback,
HTTP solo en desarrollo loopback con credencial, ausencia de redirects y
reintentos, y el cierre de clientes en el lifecycle. La credencial Bearer,
URL, instalación, negocio y tenant siguen viniendo de configuración confiable;
ninguno puede ser elegido por el usuario ni por el cuerpo del carrito.

### Recursos y sesión

La sesión del carrito pertenece únicamente a la ejecución local de la demo.
No se comparte entre hilos ni procesos, no se guarda en disco y se limpia al
salir normalmente, por `Ctrl+C` o por error. El cliente de catálogo puede
reutilizar el cliente HTTP comercial existente y debe cerrarse junto con él.
La demo conservará el aislamiento vigente: SQLite temporal, credenciales
efímeras, servidores loopback y journal memory.

## Código que se reutiliza y faltantes

Reutilizable sin cambiar su semántica:

- `mike_app/commercial/gestar_client.py`: configuración, Bearer, transporte,
  timeout, validación de identidad y errores; falta añadir la lectura y
  validación del esquema de productos.
- `mike_app/api/dev_commercial.py`: protección development-only y la ruta de
  cotización existente; no debe aceptar catálogo ni tenant del caller.
- `tools/gestar_demo.py`: lifecycle temporal, router real de Gestar, fixtures
  sintéticos y presentación de cotizaciones; hoy su catálogo está codificado
  para la demo y deberá reemplazarse por la consulta API.
- `Settings`: binding y credenciales ya configurados; la nueva operación no
  debe introducir configuración por request.

Falta definir e implementar el método de catálogo, el modelo estricto de
producto/página, el estado de carrito en la demo y sus pruebas. No falta un
motor de precios en MIKE: seguirá perteneciendo a Gestar.

## Errores

El cliente distinguirá:

- `401` o `403` de Gestar: credencial, scope o binding rechazado;
- `422`: query, cursor o respuesta comercial inválida;
- `503`: configuración comercial de Gestar inválida;
- timeout y transporte: errores detectados por MIKE, sin reintento; y
- identidad o esquema de respuesta incompatible: rechazo protocolario seguro.

Los mensajes de la terminal no incluirán Bearer, URL sensible, SQL, paths de
Gestar ni cuerpos comerciales no autorizados.

## Pruebas de aceptación propuestas

1. Búsqueda por nombre, código, página vacía, orden por ID y cursor válido.
2. Cursor inválido, límite/query inválidos, credencial inválida y scope
   insuficiente.
3. Identidad incompatible, código nullable y unidad preservada.
4. Selección de dos nombres similares que obliga a elegir ID; ninguna
   selección automática.
5. Agregar, reemplazar, modificar, quitar y listar líneas sin duplicados.
6. Rechazo de bool, strings, cero, cantidades sobre 10.000, más de 50 líneas
   e ID no seleccionado del catálogo.
7. Cotización del carrito completo con paquetes, promoción, grupo mixto y
   benchmark; reconciliación y ausencia de efectos comerciales.
8. Cambio o desaparición sintética del producto entre catálogo y cotización:
   Gestar rechaza la operación y MIKE no muestra una cotización parcial.
9. Cierre normal, `Ctrl+C` y error: carrito, cliente, servidor y SQLite
   temporal desaparecen; no hay eventos, episodios ni outbox.

## Secuencia mínima de implementación

### A. Cliente de catálogo

Agregar modelos y `list_products(query, limit, cursor)` al cliente existente.
Probar contrato, identidad, paginación, scopes, errores y cierre sin tocar el
pipeline conversacional.

### B. Carrito de terminal

Sustituir el catálogo fijo de la demo por la página consultada y añadir las
operaciones explícitas del carrito. Mantener la sesión en memoria y probar
límites, duplicados, ambigüedad y limpieza.

### C. Cotización integrada

Enviar el carrito completo a la operación existente, ejecutar escenarios
sintéticos y verificar que catálogo y cotización no producen efectos
comerciales. Solo después evaluar otra interfaz supervisada.

## Decisiones pendientes

- Si agregar nuevamente debe reemplazar siempre o requerir una confirmación
  visible en cada caso.
- Texto exacto de los comandos de terminal y si se permite seleccionar por
  código además de ID.
- Política de renovación de páginas si el catálogo cambia entre cursores;
  el contrato no promete snapshot estable.
- Si una sesión futura necesita persistencia explícita; esta propuesta la
  mantiene deliberadamente efímera.
- Evidencia de carga representativa antes de habilitar los límites
  provisionales.

Estas decisiones siguen propuestas. Este ADR no acepta rutas nuevas, no
activa la integración, no cambia eventos 1–12 ni Phase 24 y no autoriza
pedidos, ventas, reservas, cobros, stock o datos comerciales reales.

## Fuera de alcance

- interpretación libre mediante OpenAI;
- elección automática de productos ambiguos;
- conversación persistente o cambios a eventos 1–12;
- pedidos, ventas, reservas, cobros y movimientos comerciales; y
- activación sobre datos reales.
