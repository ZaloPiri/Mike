# Demostración local MIKE–Gestar

Requisitos: el `.venv` de MIKE y Gestar en `mike-commercial-base`, revisión
`272a5bbd641b925adc3bd814ea2d486e64f15e8d`.

Desde PowerShell:

```powershell
.venv\Scripts\python.exe tools\gestar_demo.py
```

La pantalla está marcada **DEMOSTRACIÓN CON DATOS FICTICIOS**. Muestra el
catálogo, sus IDs, carrito, total ARS, desglose, promociones, grupos,
advertencias, tiempos y errores. Ejemplos predefinidos: `simple`, `paquetes`,
`promocion`, `mixto` y `benchmark`. También puede ingresar `id=cantidad,id=cantidad`,
por ejemplo `1=4,2=8`. Salga con `salir` o `Ctrl+C`.

Para verificar todos los recorridos sin interacción:

```powershell
.venv\Scripts\python.exe tools\gestar_demo.py --scenario simple --scenario paquetes --scenario promocion --scenario mixto --scenario benchmark
```

La terminal llama por HTTP al endpoint real de MIKE; MIKE usa su cliente HTTP
y alcanza el router y motor reales de Gestar. El lanzador no calcula precios.
Usa únicamente SQLite temporal, credenciales efímeras, loopback y journal
`memory`; no lee `.env`, bases, backups ni datos comerciales. Consultar no
crea ni reserva pedidos. Los servidores, clientes, conexiones y archivos
temporales se cierran/eliminan al salir, incluso con `Ctrl+C`.

Demuestra cotización de consulta. No demuestra resolución de lenguaje,
continuidad conversacional, pedidos, cobros, facturación, reservas ni
disponibilidad futura.
