# Demostración local MIKE–Gestar

Requisitos: el `.venv` de MIKE y Gestar en `mike-commercial-base`, revisión
`272a5bbd641b925adc3bd814ea2d486e64f15e8d`.

Desde PowerShell:

```powershell
.venv\Scripts\python.exe tools\gestar_demo.py
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
.venv\Scripts\python.exe tools\gestar_demo.py --scenario simple --scenario paquetes --scenario promocion --scenario mixto --scenario benchmark
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
