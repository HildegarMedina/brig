# Desarrollo y mantenimiento

## Preparar el repositorio

```bash
uv sync
uv run brig --help
uv run brig
```

El paquete vive en `src/brig` y los tests en `tests`. La CLI y la TUI utilizan los
mismos casos de uso en `Application`. Los nombres de componentes y sus categorías
viven en el catálogo; los números de versión reales pertenecen a los proveedores.

Puedes usar definiciones separadas de tus proyectos habituales:

```bash
uv run brig --data-dir /tmp/brig-development
```

Un directorio de datos separado también genera IDs propios para sus recursos de
Docker. La ejecución sigue siendo real; no es un modo de simulación.

## Comprobaciones locales

```bash
ruff check src tests
ruff format --check src tests
uv run python -m unittest discover -s tests
```

`ruff` debe estar disponible en el entorno de desarrollo. La suite predeterminada
no necesita Docker ni red: usa proveedores controlados y el motor de simulación
como dependencias de pruebas. Las pruebas del motor real sustituyen la frontera
de subprocesos, pero generan archivos reales en directorios temporales.

Las pruebas comprueban, entre otros comportamientos, los snapshots de perfiles,
las relaciones de almacenamiento, los errores de guardado, las opciones de CLI,
las validaciones del asistente, las instalaciones seleccionadas y la conservación
de datos frente a errores del motor.

## Pruebas de integración con Docker

```bash
BRIG_DOCKER_TESTS=1 uv run python -m unittest tests.integration.test_lifecycle -v
```

Las tres pruebas habilitadas realizan estas comprobaciones:

- Entrar a Bash con un pseudo-terminal real y salir al host.
- Construir una imagen faltante, reutilizar el contenedor, montar la carpeta
  correcta, escribir archivos con el UID del usuario y conservar datos de Redis.
  Arrancar otro proyecto y verificar que detener el primero no lo afecta.
- Levantar PostgreSQL, MySQL, MariaDB, MongoDB y Redis con un proyecto PHP;
  comprobar salud, conexiones PDO y autenticación en MongoDB.

Las pruebas usan perfiles y carpetas temporales. Su limpieza selecciona únicamente
recursos etiquetados con sus IDs y tags de imágenes de esos proyectos. Los primeros
arranques descargan imágenes y construyen la de desarrollo. La suite normal las
omite explícitamente; las pruebas unitarias no sustituyen estas comprobaciones.

Los fixtures tienen releases concretos para ser repetibles. `BRIG_TEST_PYTHON`,
`BRIG_TEST_PHP` y `BRIG_TEST_REDIS` permiten cambiar los runtimes y Redis para probar
otras versiones; los fixtures no alimentan el catálogo de producción.

## Añadir un componente

### Una herramienta

Declara el componente y su runtime en
[`catalog.py`](../src/brig/catalog.py). Añade o reutiliza su proveedor de versiones
y la evaluación de sus requisitos en
[`versions.py`](../src/brig/versions.py) y
[`compatibility.py`](../src/brig/compatibility.py).

Añade también la instalación al generador de Dockerfiles. Ser seleccionable en
el catálogo no instala automáticamente una herramienta nueva. Prueba su selección,
compatibilidad, versión exacta, ausencia cuando no se selecciona y ejecución real.

### Un runtime

Regístralo en el catálogo, implementa la generación de su imagen y define cómo
convive con los otros runtimes. `RUNTIME_IMAGES` en
[`dockerfile.py`](../src/brig/dockerfile.py) agrupa las plantillas actuales, pero
el montaje de cada runtime y sus bibliotecas también requiere lógica del builder.

Mantén las versiones fuera del catálogo estático. Incluye casos de perfiles con
ese runtime solo y combinado, con herramientas opcionales y con dependencias
compartidas verificadas en una construcción real.

### Un servicio

Decláralo en el catálogo y configura su imagen, datos y healthcheck en
[`compose.py`](../src/brig/compose.py). Añade sus variables de inicialización y
conexión a `service_environment`. Si necesita un driver PHP, actualiza
`DATABASE_DRIVERS` en el generador.

Comprueba el punto de montaje de la imagen y sus diferencias entre releases.
Los datos deben permanecer en un volumen propio del proyecto, sin puertos
publicados de forma predeterminada. Añade pruebas de inicialización, conexión,
persistencia y compatibilidad de los datos antes de ofrecerlo en el perfil.

## Cambiar el motor

El contrato está en [`engine.py`](../src/brig/engine.py). El motor real está en
[`docker_engine.py`](../src/brig/docker_engine.py). Separa la generación de archivos,
la ejecución de comandos y la coordinación en `Application`.

Mantén los argumentos de Docker como listas; no construyas comandos de shell con
nombres o rutas del usuario. Comprueba la propiedad de los recursos existentes,
espera un arranque exitoso antes de registrar el estado y conserva las credenciales
y volúmenes cuando falle una operación.

Al cambiar comandos o comportamiento, actualiza la página correspondiente en
[`docs/README.md`](README.md) junto con el código. Los commits siguen Conventional
Commits. Un cambio incompatible en la CLI debe señalarse con `!` o un footer
`BREAKING CHANGE` y explicar cómo utilizar los comandos nuevos.
