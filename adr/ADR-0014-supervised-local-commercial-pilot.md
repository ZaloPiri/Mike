# ADR-0014: piloto comercial local supervisado MIKE–Gestar

Status: Accepted  
Date: 2026-09-30

## Contexto

ADR-0011 define la consulta comercial de solo lectura y ADR-0012/0013
definen la demo local, el catálogo, el carrito y el flujo supervisado de
selección. La demo actual funciona con fixtures sintéticos, SQLite temporal,
credenciales efímeras y servidores loopback. Este ADR propone la preparación
operativa mínima para consultar una instancia independiente de Gestar sin
crear ventas, pedidos, reservas, pagos ni eventos nuevos.

La revisión inspeccionada de Gestar es
`272a5bbd641b925adc3bd814ea2d486e64f15e8d`, rama
`mike-commercial-base`. Esta propuesta no fija todavía una revisión de
despliegue ni autoriza conexión a datos comerciales.

## Decisiones aceptadas

### A. Entrada comercial aislada de Gestar

Gestar tendrá una entrada de aplicación exclusivamente comercial que
reutilice el router `app/routes/commercial.py`, sus schemas, autenticación y
servicios `app/services/commercial_api.py`. No importará `app.main`, no
incluirá los routers de ventas, caja, inventario, producción, backups u otras
áreas, y no ejecutará el lifespan comercial.

La entrada no expondrá rutas de escritura. Sus únicas rutas serán las ya
existentes:

- `GET /api/v1/commercial/products`;
- `POST /api/v1/commercial/quotes`.

No se duplicarán el motor de precios, las promociones, los grupos mixtos ni
las reglas de `sales.preview()`.

### B. Base explícita y solo lectura

La ruta de la base SQLite deberá ser un parámetro obligatorio de la entrada
comercial. No habrá fallback a `data/gestar.db`, creación silenciosa de
archivos ni selección implícita de la base.

El servicio deberá abrir la base en modo SQLite de solo lectura, con una
protección efectiva contra escrituras de la conexión y sin `create_all`,
migraciones, seeds ni creación de grupos por defecto. La apertura deberá
fallar si la ruta no existe o no puede abrirse en ese modo.

Antes de servir, una comprobación de lectura deberá validar la configuración
y la compatibilidad mínima del esquema. Si falta una tabla, columna o
estructura requerida, la entrada debe fallar con un error seguro y no intentar
repararla.

La implementación deberá extraer únicamente lo necesario para inyectar el
engine y `get_db` de la entrada comercial. El acoplamiento actual concreto es
que `app/routes/commercial.py` importa `get_db` desde `app.database`, mientras
`app/database.py` construye el engine fijo sobre `data/gestar.db`. Esa
dependencia debe aislarse sin modificar las reglas comerciales ni importar el
engine fijo. La autenticación y `CommercialConfig` se reutilizarán, con su
Bearer, scopes, moneda, zona horaria e identidad configurados fuera del
código.

### C. Primera validación descartable

Una herramienta separada preparará una base sintética descartable y la
cerrará antes de eliminarla. El servicio comercial la abrirá después en modo
solo lectura. La preparación podrá crear el esquema y cargar datos sintéticos;
esa capacidad no estará disponible en el servicio que atiende consultas.

La prueba deberá verificar que una escritura directa o accidental desde la
conexión de servicio es rechazada por SQLite, que no aparecen archivos
adicionales y que ninguna inicialización automática modifica la base. No se
copiarán ni leerán bases comerciales en este bloque.

### D. Lanzador de MIKE

El lanzador del piloto reutilizará el controlador, parser, resolución,
`TerminalCart` y `GestarCommercialClient` existentes. Recibirá la URL,
credencial, scopes efectivos e identidad mediante configuración del proceso;
no importará código de Gestar, no creará catálogo y no iniciará ni detendrá
Gestar.

La confirmación del carrito y la cotización permanecerán como acciones
explícitas. La demo sintética existente seguirá siendo una herramienta
separada y conservará su preparación de fixtures.

El lanzador solo cerrará recursos que haya creado o posea. Deberá cerrar el
cliente HTTP y terminar su propio proceso ante salida normal, EOF, Ctrl+C o
error fatal, sin detener procesos ajenos.

### E. Primer entorno propuesto

La primera ejecución será en la misma computadora, con ambos servicios
ligados a `127.0.0.1`, HTTP loopback explícitamente habilitado y MIKE en modo
`development`. La habilitación comercial permanecerá desactivada por defecto
y se activará solo mediante configuración explícita.

Se conservarán Bearer, scopes de solo lectura, vinculación instalación–
negocio–tenant y clave local de desarrollo de MIKE. No se habilitará LAN ni
Internet. `Host` ni `X-Forwarded-For` podrán convertir una conexión externa en
loopback ni constituir autorización.

### F. Configuración sensible

La primera prueba usará credenciales e identidades sintéticas suministradas
al proceso. No se guardarán secretos en argumentos persistentes, logs,
documentos ni Git. La falta de cualquier valor requerido deberá impedir el
arranque o la habilitación.

Las credenciales e identidades comerciales reales, su almacenamiento,
rotación y revocación requieren autorización explícita antes de cualquier
conexión a datos reales.

### G. Límites del piloto

El alcance se limita a consulta de productos y cotizaciones. Quedan fuera
reservas, pedidos, ventas, pagos, movimientos de stock y eventos nuevos. Una
futura copia comercial debe tratarse como una instantánea: una cotización no
promete precios actuales, disponibilidad futura ni reserva.

El timeout de MIKE no implica cancelación del cálculo en Gestar. Los límites
de carga, concurrencia y operación del servidor seguirán siendo provisionales
hasta obtener evidencia con cargas representativas.

## Bloques de implementación y verificación

### Bloque A: entrada comercial de Gestar

Archivos candidatos, sujetos a la revisión de implementación:

- un módulo de entrada comercial aislada;
- una fábrica o adaptador mínimo de engine/`get_db` inyectable;
- validación de esquema de solo lectura;
- herramienta y pruebas de preparación de SQLite sintético.

No se modificará `app.main` para ejecutar una inicialización alternativa sin
una justificación adicional. La extracción mínima debe evitar que los imports
de la entrada alcancen el engine fijo o el lifespan comercial.

Criterios de aceptación:

- falla sin ruta de base, configuración o esquema compatible;
- no crea `data/gestar.db` ni otros archivos por fallback;
- rechaza efectivamente una escritura desde la conexión de servicio;
- no ejecuta `create_all`, migraciones, seeds ni grupos por defecto;
- atiende productos y cotizaciones mediante las rutas reales;
- valida Bearer, scopes, transporte e identidad;
- cierra engine, sesiones y servidor propios aun ante error.

### Bloque B: lanzador MIKE contra la instancia independiente

Archivos candidatos:

- un lanzador o configuración de desarrollo separado de `seed_gestar()`;
- pruebas del recorrido externo usando `GestarCommercialClient`;
- documentación operativa mínima y pruebas de cierre.

Criterios de aceptación:

- MIKE no importa código de Gestar ni crea catálogo;
- el recorrido HTTP real es búsqueda, selección, carrito y cotización;
- el endpoint de MIKE permanece deshabilitado por defecto;
- una credencial, scope, identidad o transporte inválidos se rechazan sin
  revelar secretos;
- confirmar no cotiza y un error de cotización conserva el carrito;
- no aparecen ventas, pagos, caja, stock, auditoría comercial, episodios,
  eventos u outbox nuevos;
- ambos procesos se cierran independientemente y se limpian solo recursos
  propios.

No es necesario repetir todas las suites históricas: deben reutilizarse las
pruebas existentes del cliente, router, catálogo, carrito y demo, agregando
solo la evidencia nueva de arranque aislado y ciclo de vida.

## Requisitos ya probados y evidencia nueva

Ya existe evidencia para el cliente HTTP, validación de respuestas,
identidad, ARS, timeout total, catálogo, carrito, propuestas, integración
sintética y ausencia de efectos comerciales dentro del arnés temporal.

Este ADR no considera probados todavía:

- apertura de una instancia de Gestar con una base explícita en solo lectura;
- ausencia de efectos del lifespan comercial sobre esa base;
- rechazo físico de escrituras por SQLite en la entrada de servicio;
- fallo seguro ante esquema incompatible;
- cierre independiente de una instancia externa no creada por MIKE.

Esas son pruebas nuevas de los bloques A y B, no una solicitud de repetir la
regresión completa.

## Decisiones pendientes antes de datos reales

- aprobar la extracción mínima de engine y dependencia `get_db`;
- fijar una revisión desplegable de Gestar y verificarla en el preflight;
- definir el propietario y procedimiento de arranque y cierre de Gestar;
- aprobar almacenamiento, rotación y revocación de credenciales reales;
- confirmar instalación, negocio y tenant autorizados;
- aprobar HTTPS o, únicamente para la primera ejecución local, la excepción
  loopback explícita;
- establecer límites operativos con evidencia de carga;
- aprobar el paso de la base sintética descartable a una copia comercial.

## Aprobación humana

El 2026-09-30 se aprobó este alcance: servicio comercial Gestar
independiente; base SQLite explícita, existente y abierta en solo lectura;
validación de configuración y esquema sin modificaciones; ausencia de
fallback, creación de tablas, migraciones o seeds; conservación del arranque
habitual de Gestar mediante la extracción mínima de dependencias; lanzador
MIKE independiente que cierre solo recursos propios; pruebas iniciales
locales con datos y credenciales sintéticos; preparación de la base sintética
separada del servicio de consulta; y fallo seguro ante configuración, base o
esquema inválidos.

La aceptación documental no autoriza despliegue, activación, conexión a datos
comerciales ni cambios en los contratos de eventos 1–12. Los pendientes
operativos relativos a datos reales se conservan en la sección anterior.
