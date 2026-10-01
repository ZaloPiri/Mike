# Demostración local MIKE–Gestar

Requisitos: el `.venv` de MIKE y Gestar en `mike-commercial-base`, revisión
`1a2a7245b019eadfa1b950de5f9e82a48822be55` para el piloto independiente.

Desde PowerShell, situado en la raíz de MIKE:

```powershell
.venv\Scripts\python.exe -m tools.gestar_demo
```

La pantalla está marcada **DEMOSTRACIÓN CON DATOS FICTICIOS** y consulta el
catálogo real de Gestar antes de mostrarlo. Muestra IDs, nombres, unidad,
carrito, total ARS, desglose, promociones, grupos, advertencias, tiempos y
errores. Ejemplos predefinidos: `simple`, `paquetes`, `promocion`, `mixto` y
`benchmark`.

Comandos interactivos: `lenguaje quiero 4 de Producto A y 6 de Producto B`,
`buscar TEXTO`, `agregar ID CANTIDAD`, `modificar ID CANTIDAD`, `quitar ID`,
`carrito`, `cotizar` y `salir`. `lenguaje TEXTO` interpreta solo la gramática
determinista aprobada, busca cada mención en Gestar, exige seleccionar cada
ID mostrado, presenta una propuesta `add` o `replace` y pide `s` para
confirmarla o cualquier otra respuesta para cancelarla. Confirmar no cotiza.

Agregar un ID ya presente pide confirmación y reemplaza solo si se responde
`s`; nunca suma en silencio. Cambiar la búsqueda no borra el carrito. Un
carrito vacío no se envía. La interfaz selecciona exclusivamente IDs de la
página consultada.

Secuencia reproducible de lenguaje y cotización:

```text
lenguaje quiero 4 de Producto A y 6 de Producto B
1
2
s
carrito
cotizar
salir
```

La selección y la confirmación son explícitas; si se muestra `pagina`, se
puede escribir `pagina` antes del ID para consultar el cursor siguiente.

Para verificar todos los escenarios predefinidos sin interacción:

```powershell
.venv\Scripts\python.exe -m tools.gestar_demo --scenario simple --scenario paquetes --scenario promocion --scenario mixto --scenario benchmark
```

La terminal llama por HTTP al endpoint real de MIKE; MIKE usa su cliente HTTP
y alcanza el router y motor reales de Gestar. El lanzador no calcula precios.
Usa únicamente SQLite temporal, credenciales efímeras, loopback y journal
`memory`; no lee `.env`, bases, backups ni datos comerciales. Consultar no
crea ni reserva pedidos. Los servidores, clientes, conexiones y archivos
temporales se cierran/eliminan al salir, incluso con `Ctrl+C`.

Demuestra resolución determinista supervisada, selección por catálogo,
propuesta temporal y cotización de consulta. No demuestra continuidad
conversacional, pedidos, cobros, facturación, reservas ni disponibilidad
futura.

## Piloto local supervisado contra Gestar independiente

Este lanzador no prepara una base ni inicia Gestar. Un operador debe iniciar
por separado la entrada comercial aislada de Gestar con una SQLite existente y
descartable, por ejemplo desde el worktree de Gestar:

```powershell
.venv\Scripts\python.exe -m app.commercial_entry --database C:\ruta\a\base-sintetica.db --host 127.0.0.1 --port 8001
```

Desde la raíz de MIKE, configure los valores requeridos en el proceso, sin
poner secretos en el comando, archivos ni logs:

```powershell
$env:MIKE_ENV='development'
$env:MIKE_GESTAR_COMMERCIAL_ENABLED='true'
$env:MIKE_GESTAR_BASE_URL='http://127.0.0.1:8001'
$env:MIKE_GESTAR_BEARER_TOKEN='<token-sintetico>'
$env:MIKE_GESTAR_INSTALLATION_ID='<installation-id>'
$env:MIKE_GESTAR_BUSINESS_ID='<business-id>'
$env:MIKE_GESTAR_TENANT_ID='<tenant-id>'
$env:MIKE_GESTAR_DEV_KEY='<clave-local>'
.venv\Scripts\python.exe -m tools.gestar_pilot
```

El proceso MIKE solo inicia y cierra su servidor loopback, cliente HTTP y
carrito temporal. `salir`, EOF, Ctrl+C o un error cierran MIKE sin detener
Gestar. La consulta mantiene selección explícita, propuesta de un solo uso y
`cotizar` como acción separada. La entrada de Gestar es responsable de su
propio cierre y de eliminar únicamente recursos sintéticos de su preparación.

Este procedimiento requiere datos sintéticos hasta completar el preflight de
configuración, esquema, solo lectura, scopes e identidad. No autoriza datos
comerciales reales ni garantiza disponibilidad futura.

## Sesión sobre una copia temporal

El orquestador exige ambas rutas explícitamente, crea una copia SQLite
consistente, inicia la entrada comercial aislada de Gestar y luego ejecuta el
lanzador MIKE. No usa `app.main`, no lee `.env` y no modifica la base fuente.

Desde la raíz de MIKE:

```powershell
.venv\Scripts\python.exe -m tools.gestar_pilot_orchestrator `
  --source-db C:\Users\Ana\Desktop\GESTAR\data\gestar.db `
  --gestar-worktree C:\Users\Ana\Desktop\GESTAR-mike-base
```

La sesión muestra la fecha de captura y advierte que los precios corresponden
a esa instantánea. El operador usa los comandos normales de `gestar_pilot`,
incluido `lenguaje <texto>`, selección por ID, confirmación, `carrito`,
`cotizar` y `salir`. Salir, EOF, Ctrl+C o un fallo cierran únicamente los
procesos iniciados por el orquestador y eliminan su copia temporal.
# Piloto web local supervisado

Desde la raíz de MIKE, con una base sintética explícita y el worktree
validado de Gestar:

```powershell
.venv\Scripts\python.exe -m tools.gestar_pilot_orchestrator `
  --source-db C:\ruta\base-sintetica.sqlite3 `
  --gestar-worktree C:\Users\Ana\Desktop\GESTAR-mike-base `
  --mode web
```

El orquestador muestra una URL loopback y un código bootstrap de un solo uso.
Ábrelos en Chrome, introduce el código, interpreta la frase, busca y
selecciona IDs explícitos, prepara y confirma la propuesta, y pulsa `Cotizar`.
Para emitir otro código desde la terminal escribe `codigo` (o `bootstrap`).
La cotización usa la captura indicada y no crea pedidos ni reserva stock.

Para terminar el piloto completo escribe `salir` en la terminal del
orquestador. Cerrar la pestaña o pulsar `Cerrar sesión` solo revoca la sesión
web; no anuncia ni ejecuta la limpieza del piloto. El orquestador detiene
únicamente los procesos que inició y elimina su copia temporal.
