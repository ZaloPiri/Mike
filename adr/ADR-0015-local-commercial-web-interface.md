# ADR-0015 — Interfaz web local supervisada de cotización MIKE–Gestar

- **Status:** Accepted
- **Date:** 2026-09-30

La aprobación humana del 2026-09-30 acepta esta arquitectura para el
alcance local, temporal y sintético descrito. Autoriza implementar el bloque
A y preparar después el bloque B; no autoriza todavía datos comerciales,
despliegue ni activación del piloto.

## Contexto

MIKE ya dispone de un flujo local supervisado por terminal: interpretación
determinista, búsqueda paginada y selección explícita mediante
`CatalogResolution`, carrito temporal con revisión y propuestas de un solo
uso en `TerminalCart`, `DemoController` y cotización validada por
`GestarCommercialClient`. El orquestador de ADR-0014 puede preparar una
copia temporal de Gestar en solo lectura y conservar la propiedad de los
procesos que inicia.

La interfaz web propuesta debe ofrecer el mismo recorrido en Chrome, sin
crear otra implementación comercial. Gestar sigue siendo la autoridad de
productos, precios, promociones, grupos mixtos, moneda y advertencias de
stock. Esta propuesta no autoriza pedidos, ventas, reservas, pagos,
persistencia conversacional, OpenAI, WhatsApp, eventos nuevos ni cambios en
Gestar.

## Decisión propuesta

### 1. Alcance y reutilización

Se propone una interfaz FastAPI local que adapte, sin duplicar reglas:

- `language_interpreter.interpret` para texto determinista;
- `CatalogResolution` y `GestarCommercialClient` para búsquedas, cursores,
  identidad y validación de respuestas;
- `TerminalCart` para líneas, límites, revisión y propuestas inmutables;
- `DemoController` como referencia de las operaciones y mensajes;
- el endpoint existente de MIKE para la cotización, o una extracción común
  mínima si la sesión web necesita invocarlo sin copiar su lógica.

La adaptación pendiente es un dueño de sesión HTTP local que contenga un
`TerminalCart`, resoluciones y la propuesta activa. No se propone mover las
reglas a JavaScript ni incorporar un framework o una cadena de compilación.
La terminal y la demo sintética seguirán funcionando con el controlador
compartido.

### 2. Acceso inicial y superficie mínima

El operador autorizado inicia MIKE explícitamente mediante el orquestador.
El orquestador genera un código de arranque aleatorio de un solo uso,
válido durante 5 minutos, lo muestra únicamente en su terminal interactiva
y lo entrega al proceso MIKE por configuración de proceso. El operador abre
`http://127.0.0.1:<puerto>/dev/web-commercial/` en Chrome, introduce ese
código en la pantalla inicial y lo envía a la ruta de bootstrap. MIKE
invalida el código después de un intento exitoso y genera una credencial
aleatoria de sesión, que conserva únicamente en memoria y entrega al
navegador mediante una cookie `HttpOnly`, sin `Secure` para el HTTP loopback
aprobado, `SameSite=Strict` y `Path=/dev/`. La cookie no se considera
aislada por puerto: su alcance es el host y path.
La cookie no contiene el Bearer de Gestar ni la clave de desarrollo de MIKE.
La sesión expira a los 30 minutos de inactividad y también al terminar el
servidor; el orquestador puede revocarla antes mediante la acción de cierre.
No se persiste ni se recupera después de un reinicio.

La navegación `GET` de la página inicial se permite sin `Origin` cuando el
`Host` es exactamente el host/puerto loopback anunciado por MIKE. Para las
rutas JSON, `GET` exige ese mismo `Host` y, si `Origin` está presente, debe
ser exactamente el origen loopback anunciado; todo `POST` exige ambos
encabezados válidos, `Content-Type: application/json` cuando corresponda,
la cookie de sesión y un token CSRF distinto almacenado solo en memoria y
entregado en el HTML/estado inicial, también después de recargar. Un
`Origin` ausente en un `POST` autenticado, un
`Host` diferente, un origen diferente, una cookie ausente o un CSRF inválido
se rechazan antes de consultar o mutar. La respuesta no habilita CORS.

Las rutas siguientes son una propuesta concreta de sesión local; no existen
todavía y deberán implementarse antes de usarse:

- `GET /dev/web-commercial/`: sirve la pantalla de bootstrap; no crea sesión
  ni acepta credenciales en query o URL.
- `POST /dev/web-commercial/bootstrap` con `{ "code": string }`: exige
  JSON, `Host` y `Origin` loopback exactos; es la única excepción a exigir
  cookie y CSRF, consume el código de un solo uso y crea la cookie y el CSRF
  inicial; código ausente, repetido o vencido
  responde `401 web_bootstrap_failed`.
- `GET /dev/web-commercial/state`: devuelve estado de la sesión autenticada:
  `session_revision`, líneas `{product_id, quantity}`, resolución,
  propuesta activa y captura; nunca secretos.
- `POST /dev/web-commercial/interpret` con `{ "text": string }`: interpreta
  sin mutar carrito; una interpretación inválida responde `422
  interpretation_invalid`.
- `POST /dev/web-commercial/search` con `{ "query": string,
  "cursor": string|null, "limit": int }`: permite búsqueda manual sin
  interpretación previa y devuelve una página con un `search_id` vigente.
  Cuando proviene de una interpretación, MIKE asocia la búsqueda a su
  mención; query y cursor no se reutilizan entre búsquedas. Un error de
  Gestar responde `502/408` y deja inválidas solo las opciones afectadas.
- `POST /dev/web-commercial/select` con `{ "search_id": string,
  "product_id": int }`: exige ID entero de la página vigente de esa
  búsqueda; una respuesta o selección vieja responde
  `409 selection_not_current`.
- `POST /dev/web-commercial/cart/add` con `{ "product_id": int,
  "quantity": int, "expected_revision": int, "selection_id": string,
  "replace": bool }`: exige una selección vigente validada en servidor;
  agrega o, con `replace=true`, reemplaza tras confirmación de la UI.
  Devuelve la nueva revisión. `cart_revision_conflict` responde `409`.
- `POST /dev/web-commercial/cart/modify` con `{ "product_id": int,
  "quantity": int, "expected_revision": int }`: modifica una línea
  existente sin depender de la página actual del catálogo.
- `POST /dev/web-commercial/cart/remove` con `{ "product_id": int,
  "expected_revision": int }`: quita una línea, preservando las demás.
- `POST /dev/web-commercial/proposals` sin líneas inventadas: prepara todas
  las menciones resueltas y devuelve `proposal_id`, `cart_id`,
  `cart_revision` y líneas `add/replace` con cantidad anterior cuando
  corresponda.
- `POST /dev/web-commercial/proposals/{proposal_id}/confirm` con
  `{ "expected_revision": int }`: exige propuesta activa, sesión, carrito
  y revisión exactos.
- `POST /dev/web-commercial/proposals/{proposal_id}/cancel` con
  `{ "expected_revision": int }`: consume la propuesta sin mutar carrito.
- `POST /dev/web-commercial/quote` con `{ "expected_revision": int }`:
  cotiza el carrito completo solo si la revisión sigue vigente; devuelve la
  cotización validada y la revisión/huella del contenido enviado. Carrito
  vacío responde `409 empty_cart` sin llamada a Gestar.

Los errores comunes serán `401 web_session_required`, `401 web_bootstrap_failed`,
`403 origin_not_allowed`,
`404 session_or_resource_not_found`, `409 cart_revision_conflict`,
`409 proposal_stale`, `409 selection_not_current`, `422 invalid_input` y
`502/408` para rechazo, indisponibilidad o timeout de Gestar. No se
retransmiten mensajes internos ni secretos.

Los cuerpos y respuestas definitivos deberán conservar los tipos y errores
de los contratos de ADR-0011/0012/0013. Toda respuesta de catálogo o
cotización será validada por MIKE, incluyendo instalación, negocio,
moneda ARS, fecha comercial, timestamp, lista, cantidades, componentes,
desglose, total y advertencias. El navegador nunca recibe el Bearer de
Gestar ni decide tenant, instalación, negocio, URL de destino, ruta de base,
precio o disponibilidad.

### 3. Seguridad de la sesión local

La interfaz solo podrá escuchar en `127.0.0.1`; loopback no se considera
autenticación. La cookie HttpOnly descrita arriba es la credencial de sesión
web; el código de bootstrap es una credencial efímera de entrada entregada
por el orquestador, no un secreto de Gestar. El token CSRF protege las
mutaciones frente a solicitudes cross-site y
el Bearer/clave de MIKE son secretos internos separados, nunca entregados al
navegador. La creación ocurre al servir la página inicial legítima, no por
un endpoint POST anónimo: solo el bootstrap de un solo uso puede crearla.
Solo el proceso MIKE puede generar, validar y revocar la sesión.

El Bearer de Gestar, la clave local, la URL y la identidad se mantienen en
configuración del proceso y nunca aparecen en HTML, JSON del navegador,
`localStorage`, URLs, logs ni mensajes de error. La habilitación seguirá
siendo explícita, solo en `development`, y usará la copia temporal de
solo lectura del orquestador cuando el piloto la administre.

### 4. Semántica temporal y concurrente

Las pestañas del mismo perfil comparten la cookie, sesión y carrito. Recargar
conserva la misma sesión mientras la cookie no haya expirado, y el estado se
vuelve a consultar desde MIKE. Sesiones autenticadas distintas permanecen
aisladas. El límite propuesto es 4 sesiones activas por proceso; para crear
otra, el orquestador solicita el código mediante `POST
/dev/web-commercial/control/bootstrap-code`, en loopback, con el encabezado
`X-MIKE-Control-Key` y una clave efímera distinta de la cookie, CSRF, Bearer
de Gestar y clave de desarrollo. Esa clave se entrega solo al proceso MIKE
al iniciar y al orquestador propietario; ningún navegador puede usarla. El
endpoint exige `Host` loopback, `Origin` ausente y no acepta cookie. Un
código consumido no permite
volver a entrar ni crear otra sesión. Una quinta creación responde `429
session_limit`. Reiniciar MIKE no promete recuperación.

Una búsqueda o error recuperable conserva el carrito, pero invalida las
opciones obsoletas de la consulta afectada. Cambiar el carrito invalida una
propuesta previa, incluso si después se vuelve al contenido anterior.
Confirmar exige propuesta activa, carrito correcto y revisión vigente; una
confirmación repetida, vieja o de otra sesión no aplica nada. Una propuesta
contiene todas las líneas y se aplica completa o se rechaza completa.

Cada sesión tiene un lock en memoria. Las mutaciones de carrito, interpretación,
búsquedas, selecciones, propuestas y confirmaciones se serializan; si no
puede adquirirse dentro de 1 segundo
responden `409 session_busy`. Una cotización captura atómicamente la
revisión, las líneas y una huella del request bajo ese lock, libera el lock
durante la llamada a Gestar y solo publica la respuesta si la revisión y la
huella siguen iguales. Si cambiaron, la respuesta tardía se descarta con
`409 quote_stale`; nunca aparece como cotización vigente. Antes de publicar
la respuesta también se verifica que la sesión siga activa; logout o
expiración descartan la respuesta aunque la revisión no haya cambiado. No
se promete coordinación entre procesos.

### 5. Ciclo de vida y propiedad

Las pestañas del mismo perfil comparten sesión. Cerrar sesión (`POST
/dev/web-commercial/logout`) revoca la cookie y descarta esa sesión para
todas sus pestañas; no afecta sesiones distintas ni detiene procesos. Solo
la credencial de esa sesión puede solicitarlo. Terminar todo el piloto se
hace con `salir` en la terminal del orquestador, no desde una ruta web. El
proceso web no puede detener Gestar externo ni asumir propiedad de procesos
que no inició.

El orquestador coordina el cierre: primero detiene MIKE, espera su proceso,
detiene y espera Gestar propio, cierra clientes/conexiones y elimina la
copia con reintentos acotados. El resultado final se confirma en la salida
del orquestador o en su registro local sin secretos; después de apagar MIKE
ninguna pestaña puede prometer una confirmación posterior. Una pestaña
cerrada por sí sola no confirma limpieza.

## Bloques verificables

### A. Sesión y operaciones web

Implementar el almacén temporal de sesiones y los adaptadores FastAPI para
interpretar, buscar, seleccionar, preparar, confirmar, cancelar y cotizar,
reutilizando las clases actuales.

Aceptación: dos sesiones autenticadas distintas no comparten carrito ni
propuesta; las pestañas de una misma sesión sí comparten ambos; la búsqueda
manual no requiere interpretación ni `mention_index`; selección requiere la
página vigente; ambigüedad, búsqueda fallida y respuestas
inválidas no producen aplicación parcial; confirmación repetida u obsoleta
es rechazada; el carrito se conserva ante error; el total y sus componentes
son los devueltos por Gestar; no se crean eventos, outbox, pedidos ni
reservas. Se prueban además Host/Origin, bootstrap sin cookie/CSRF como
única excepción, cookie/CSRF posterior, expiración, emisión de códigos
sucesivos desde el orquestador, límite de cuatro sesiones, serialización,
selección vieja, conflicto de revisión y descarte de una cotización tardía
tras logout.

### B. Pantalla y arranque/cierre del piloto

Construir una pantalla HTML mínima servida por MIKE, con nombres, IDs,
unidades, cantidades, alternativas, operaciones add/replace/remove,
propuesta antes de confirmar, total ARS, desglose, advertencias y fecha de
captura. El orquestador iniciará y cerrará únicamente sus procesos; la
prueba usará datos sintéticos, loopback y una copia de solo lectura.

Aceptación: Chrome completa texto o búsqueda, selección explícita,
confirmación y cotización; recarga y otra pestaña comparten sesión; logout
revoca ambas; `salir` confirma la limpieza desde el orquestador; Gestar
continúa separado hasta que su dueño lo cierre; no
aparecen secretos ni efectos comerciales. `salir` y EOF del orquestador se
prueban; Ctrl+C queda como revisión de código hasta ejecutar una prueba
manual específica y no se presenta como garantía ya demostrada.

## Garantías ya demostradas y límites

Ya están demostrados en terminal/cliente/orquestador el timeout total del
cliente, la validación de identidad y moneda, la selección explícita, las
propuestas de un solo uso, la revisión del carrito, la cotización de solo
lectura y la limpieza de procesos/copia con reintentos acotados. Eso no
demuestra todavía la seguridad de navegador, el aislamiento entre sesiones
web ni la limpieza confirmada mediante una pantalla.

La interfaz propuesta no convierte una captura en disponibilidad actual, no
promete recuperación tras reinicio y no cancela el cálculo de Gestar cuando
vence el timeout de MIKE. Los límites de carga del motor y la política de
sesiones concurrentes quedan sujetos a evidencia antes de habilitar el
piloto fuera de datos sintéticos.

## Implementación y validación pendientes

- confirmar que el límite de cuatro sesiones y el lock de 1 segundo son
  suficientes con datos sintéticos representativos;
- concretar el formato HTML mínimo sin añadir dependencias ni build;
- concretar los códigos y esquemas como contratos ejecutables;
- ejecutar las pruebas sintéticas del bloque A y, posteriormente, del bloque
  B. La aceptación documental no presenta esas pruebas como realizadas.

La aprobación de este ADR autoriza implementar los dos bloques y ejecutar
las pruebas sintéticas descritas. La habilitación contra datos comerciales,
el piloto real y cualquier despliegue quedan para una decisión posterior,
después de esa validación.
