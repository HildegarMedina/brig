# Tu primer proyecto

Este recorrido crea un perfil, registra una carpeta existente y abre una terminal
Python aislada. La carpeta puede contener un proyecto real o estar vacía.

## 1. Preparar la máquina

Necesitas Linux, Python 3.12 o superior, [uv](https://docs.astral.sh/uv/), Docker
Engine y el plugin de Docker Compose v2 o superior. Docker debe estar activo y tu
usuario debe poder acceder al daemon.

Desde la carpeta del repositorio de Brig:

```bash
uv tool install .
brig --help
```

Si `brig` no aparece en el PATH, ejecuta `uv tool update-shell` y abre otra
terminal. Después de actualizar el código, reinstala la herramienta:

```bash
uv tool install --reinstall .
```

Comprueba Docker como tu usuario habitual:

```bash
docker version
docker compose version
```

Brig prepara el contenedor para ese usuario. Ejecuta Brig sin `sudo`.

## 2. Crear un perfil

```bash
brig profile create
```

Ponle el nombre `python_dev`. Selecciona Python y una versión que aparezca en la
lista. Para este recorrido puedes dejar las herramientas y los servicios sin
seleccionar. Revisa la configuración y elige **Save**.

La lista de versiones se consulta al abrir el selector. Brig guarda la versión
concreta elegida; no cambia automáticamente cuando se publica otra.

## 3. Registrar una carpeta

```bash
mkdir -p ~/projects/mi_api
cd ~/projects/mi_api
brig project init
```

Usa `mi_api` como nombre del proyecto, la carpeta actual y el perfil `python_dev`.
El nombre debe estar en `snake_case`: minúsculas, números y guiones bajos simples
entre palabras. El asistente registra la carpeta y una copia de la revisión del
perfil; no crea el código de la aplicación.

```bash
brig project show mi_api
```

## 4. Entrar al proyecto

```bash
brig run mi_api
```

Brig genera la configuración de Docker, construye la imagen si falta, levanta
los contenedores y abre Bash en `/workspace`. El primer arranque necesita internet
para descargar las imágenes y los paquetes que falten.

Dentro de la terminal:

```bash
pwd
id -u
python --version
python -c 'from pathlib import Path; Path("hello.txt").write_text("desde Brig\n")'
exit
```

`/workspace` es la carpeta registrada. El archivo `hello.txt` también aparece en
`~/projects/mi_api` en el host. La terminal usa tu UID/GID para que los archivos
creados no queden a nombre de root.

Salir de Bash deja el entorno levantado. Puedes volver a entrar con `brig run`
desde esa carpeta o con `brig run mi_api` desde cualquier otra.

## 5. Detener y volver a arrancar

```bash
brig down --project mi_api
brig run mi_api
```

`down` elimina los contenedores y la red del proyecto, conservando el código y
los volúmenes. El siguiente `run` reutiliza la imagen local si sigue disponible.

Continúa con [gestionar proyectos](../guias/proyectos.md) para añadir servicios,
actualizar el perfil o ejecutar programas sin abrir una terminal.
