# Brig

Brig prepara un entorno de desarrollo Docker para cada proyecto a partir de un
perfil con versiones concretas. Puede combinar PHP, Python y Node.js, añadir las
herramientas seleccionadas y levantar PostgreSQL, MySQL, MariaDB, MongoDB y Redis.

```bash
brig run mi_proyecto
```

Construye la imagen si falta, inicia el entorno y abre una terminal sin privilegios
en `/workspace`, montando la carpeta registrada del proyecto. Cada proyecto tiene
su red y volúmenes. Salir de la terminal deja el entorno activo.

## Instalar

Requiere Linux, Python 3.12 o superior y [uv](https://docs.astral.sh/uv/). Para ejecutar
entornos, necesitas Docker Engine activo y el plugin de Compose v2 o superior,
accesibles como tu usuario habitual.

Desde este repositorio:

```bash
uv tool install .
brig --help
```

Si el comando no aparece, ejecuta `uv tool update-shell` y abre otra terminal.
Después de actualizar el código, usa `uv tool install --reinstall .`.

## Crear y ejecutar un proyecto

```bash
brig profile create
cd /ruta/a/tu/proyecto
brig project init
brig run
```

Los asistentes consultan versiones disponibles al crear o editar el perfil. El
proyecto guarda una copia de la revisión elegida; las actualizaciones son
explícitas. Los nombres nuevos usan `snake_case`, por ejemplo `mi_proyecto`.

También puedes seleccionar un proyecto desde cualquier carpeta:

```bash
brig run mi_proyecto
brig up --project mi_proyecto
brig run mi_proyecto --command python --version
brig down --project mi_proyecto
```

`down` retira los contenedores y la red, conservando el código y los volúmenes.
Brig todavía no instala agentes, dependencias de la aplicación ni servidores HTTP,
y no publica puertos de la aplicación.

## Documentación

Empieza por el [índice de documentación](docs/README.md).

- [Tutorial: tu primer proyecto](docs/tutoriales/primer-proyecto.md).
- [Guía: gestionar proyectos](docs/guias/proyectos.md).
- [Explicación: arquitectura y flujo de ejecución](docs/explicacion/arquitectura.md).
- [Referencia: comandos](docs/referencia/comandos.md).
- [Referencia: datos y persistencia](docs/referencia/datos.md).
- [Referencia: componentes y versiones](docs/referencia/componentes.md).
- [Problemas frecuentes](docs/guias/problemas-frecuentes.md).

## Desarrollo

```bash
uv sync
ruff check src tests
ruff format --check src tests
uv run python -m unittest discover -s tests
```

La suite normal no necesita Docker; las tres pruebas de integración reales se
habilitan con:

```bash
BRIG_DOCKER_TESTS=1 uv run python -m unittest tests.integration.test_lifecycle -v
```

Consulta [desarrollo y mantenimiento](docs/desarrollo.md) para la arquitectura del
código, las pruebas y cómo añadir componentes.
