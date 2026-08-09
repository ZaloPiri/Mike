\# MIKE



MIKE es el nombre interno de una plataforma SaaS multiempresa de agentes de inteligencia artificial.



Su objetivo es ayudar a comercios y empresas a atender clientes, gestionar ventas y ejecutar tareas operativas mediante canales como WhatsApp e Instagram, conectándose de forma segura con la información y los sistemas de cada negocio.



\## Cliente piloto



La primera implementación será desarrollada y validada en La Sandwichería, ubicada en Chivilcoy, Argentina.



\## Objetivo del MVP



El MVP deberá permitir:



\- Recibir mensajes desde WhatsApp.

\- Recibir mensajes desde Instagram.

\- Identificar correctamente la empresa y el cliente.

\- Responder usando información real del negocio.

\- Consultar productos, precios, promociones y horarios.

\- Guiar al cliente durante la toma de un pedido.

\- Registrar clientes, conversaciones, mensajes y pedidos.

\- Derivar la conversación a una persona cuando sea necesario.

\- Mantener los datos de cada empresa completamente aislados.



\## Principios del proyecto



\- Arquitectura multiempresa desde el inicio.

\- Separación entre canales, inteligencia artificial y lógica de negocio.

\- La IA no debe inventar datos comerciales.

\- Las acciones importantes deben validarse antes de ejecutarse.

\- Toda operación debe quedar registrada.

\- El proveedor de IA debe poder reemplazarse sin reconstruir el sistema.

\- La seguridad y el aislamiento de datos son requisitos fundamentales.

\- Cada módulo debe tener una responsabilidad clara.



\## Tecnologías iniciales



\- Python

\- FastAPI

\- PostgreSQL

\- SQLAlchemy

\- Alembic

\- OpenAI API

\- Meta Cloud API

\- Git y GitHub

\- Railway

\- Cursor



\## Canales previstos



1\. WhatsApp

2\. Instagram

3\. Webchat

4\. Otros canales futuros



\## Estado



Proyecto en etapa inicial de arquitectura y definición del MVP.


## Development environment and reproducible setup


The primary verified development environment is Windows with Python 3.14.6. The full test suite was also verified on Linux with Python 3.12.13. Compatibility with other Python versions or operating systems has not been verified.


`requirements.txt` declares the project dependencies. `constraints.txt` pins the verified versions of the project's key dependencies to provide a stable installation baseline. Create and verify that environment from PowerShell with:


```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -c constraints.txt
.\.venv\Scripts\python.exe -m pytest -q
```


The expected test result is `777 passed`. The verified runs emit one known `StarletteDeprecationWarning` concerning the use of `httpx` with `starlette.testclient`. Migration to `httpx2` is outside the scope of this stabilization.

