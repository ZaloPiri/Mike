# ADR-0013 — Selección comercial y propuestas de carrito desde lenguaje natural

- **Status:** Accepted
- **Date:** 2026-09-29

## Contexto

ADR-0011 establece que Gestar es la única autoridad comercial y que MIKE
consulta productos y cotizaciones mediante un cliente HTTP validado. ADR-0012
establece la selección explícita por `product_id`, el carrito temporal, la
conservación del carrito ante búsquedas y errores recuperables, la confirmación
de reemplazos y la revalidación al cotizar.

La percepción existente normaliza intenciones y entidades genéricas, y puede
usar un cliente externo cuando está habilitada. No garantiza la asociación de
varias cantidades con varios productos. Por ello, la interpretación comercial
queda separada de la autoridad de Gestar y de la mutación del carrito.

## Decisión

El flujo se divide en interpretación, búsqueda de candidatos en Gestar,
resolución de productos y cantidades, presentación de una propuesta,
confirmación y aplicación, y cotización explícita. La interpretación no
produce IDs, precios, disponibilidad ni autoridad comercial. Solo productos
devueltos por la página vigente de Gestar pueden seleccionarse y la persona
debe elegir explícitamente por `product_id`, aun cuando haya un único
candidato visible. La paginación es explícita y no recorre automáticamente
el catálogo.

El primer bloque implementado bajo esta decisión es solo un intérprete
determinista puro. No consulta Gestar, no accede al carrito, no hace I/O y no
llama a `PerceptionService` ni a OpenAI. Conserva el texto original y genera
menciones con cantidad y expresión de unidad para validarlas posteriormente
contra el catálogo.

## Gramática determinista del primer bloque

La entrada tiene como máximo 500 caracteres y diez menciones. Se admite una
secuencia de cláusulas separadas por `;`, o por `y` únicamente cuando después
de ese `y` comienza otra cantidad explícita. Cada cláusula tiene la forma:

```text
[quiero ] cantidad [de ] nombre-del-producto
```

Se admiten cifras enteras positivas y las palabras `uno` a `doce`, además de
`media docena` y `una docena`. La expresión original de cantidad y su valor
(6 o 12) se conservan; la conversión solo podrá autorizarse después de
validar la unidad real devuelta por Gestar. No se convierten peso, volumen ni
paquetes.

Los nombres pueden contener `y`; por eso no se divide cada frase por esa
conjunción. Una asociación como “6 de jamón y queso y 6 de pollo” solo se
separa porque el segundo `y` precede a otra cantidad inequívoca. Ante
ambigüedad, fragmentos no interpretables, cantidad ausente, cero, negativa,
fraccionaria, fuera de límite o una línea inválida, se devuelve una
aclaración para la frase completa y no una interpretación parcial.

“Sumame”, “otros seis” y “seis más” no se convierten silenciosamente en una
operación. “Ese”, “el anterior”, “lo de siempre” y demás referencias entre
mensajes están fuera de este bloque y requieren una futura decisión.

## Propuestas y carrito posteriores

Los bloques posteriores usarán solo `add` y `replace`: producto ausente
produce una propuesta de agregar; producto existente produce una propuesta de
reemplazar mostrando cantidad anterior y nueva. No se aprueba `sum`. La
operación final depende del carrito y del producto resuelto, no del parser.

Habrá una única propuesta activa, identificada, de un solo uso y vinculada a
una revisión incremental del carrito. Toda modificación efectiva invalida la
propuesta anterior, aunque el contenido vuelva a coincidir. Confirmar o
cancelar consume la propuesta; repetir confirmación no aplica cambios. Todas
las líneas deben validarse antes de publicar el cambio completo. Una propuesta
desactualizada exige preparar otra explícitamente, sin regeneración ni
aplicación automática. El carrito se conserva durante interpretación,
búsqueda, paginación y errores recuperables; cotizar sigue siendo una acción
explícita separada.

## Límites y alcance

Los límites de 500 caracteres y diez menciones son funcionales y
provisionales, no garantías de carga. Se conservan los límites existentes del
carrito. El primer alcance es la demo local, datos sintéticos y estado
temporal de sesión. La sesión se limpia al salir, EOF, Ctrl+C o error fatal.

Quedan fuera WhatsApp y otros canales, pedidos, ventas, reservas, pagos,
stock, facturación, conversación persistente, referencias entre mensajes,
activación comercial real, cambios en eventos 1–12, Phase 24 y toda
integración que no sea la demostración local supervisada. Un timeout del
cliente no promete cancelar el servidor.

## Verificación futura

La implementación deberá probar los tres ejemplos aprobados, varios
productos y cantidades diferentes, nombres que contengan `y`, cifras,
palabras, docenas, entradas inválidas, expresiones de suma, referencias
contextuales, límites y ausencia de interpretación parcial. También deberá
demostrar conservación del texto y ausencia de efectos externos.

Los ejemplos soportados inicialmente son frases explícitas con nombres o
códigos que luego puedan resolverse contra una página de Gestar. La búsqueda,
selección explícita, propuestas, confirmación, huella de carrito y cotización
pertenecen a bloques posteriores B, C y D; no se implementan con este bloque.
