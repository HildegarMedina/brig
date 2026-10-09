# Componentes, versiones y compatibilidad

## Catálogo actual

| Categoría | Componentes |
| --- | --- |
| Runtimes | PHP, Python, Node.js |
| Herramientas PHP | Composer |
| Herramientas Python | pip, uv |
| Herramientas Node.js | npm, pnpm, Yarn Classic |
| Bases relacionales | PostgreSQL, MySQL, MariaDB |
| Documentos | MongoDB |
| Caché y clave/valor | Redis |

Solo aparecen herramientas del runtime seleccionado. Es obligatorio escoger al
menos un runtime; las herramientas y los servicios son opcionales. Un perfil
puede seleccionar varios runtimes y varios servicios.

Claude Code se puede guardar como agente predeterminado, aunque su instalación y
autenticación no están implementadas. Codex y OpenCode figuran como integraciones
futuras.

## Fuentes de versiones

Las versiones no están fijadas en el catálogo del código. Se consultan al abrir
el selector y se ordenan de la más reciente a la más antigua.

| Componentes | Fuente |
| --- | --- |
| Runtimes y servicios | [Manifiestos de Docker Official Images](https://github.com/docker-library/official-images) para imágenes Linux |
| pip y uv | [API JSON de PyPI](https://docs.pypi.org/api/json/) |
| npm, pnpm y Yarn Classic | [Registro npm](https://github.com/npm/registry/blob/main/docs/responses/package-metadata.md) |
| Composer | [Feed oficial de versiones](https://getcomposer.org/versions) |

Los manifiestos de Docker representan las definiciones mantenidas actualmente;
no son un inventario de todos los releases históricos. Se excluyen aliases
móviles, variantes de imagen y prereleases. PyPI excluye releases vacíos o
completamente retirados; npm excluye versiones deprecadas. Yarn Modern no forma
parte del catálogo actual.

Una operación de creación o edición utiliza un snapshot consistente de los
metadatos consultados. Otro asistente vuelve a consultarlos. Si la fuente falla,
se ofrece reintentar o cancelar; no se inventan versiones de reemplazo.

Después de guardar, los números de versión son strings concretos. Cargar
perfiles, proyectos y generar un Dockerfile funciona offline. Construir una
imagen o descargar servicios puede necesitar internet.

## Canales de publicación

MySQL muestra **LTS** o **Innovation** según los metadatos de ramas de su
[repositorio oficial de imágenes](https://github.com/docker-library/mysql/blob/master/versions.json).
Node.js muestra **LTS** o **Current** usando el
[índice oficial de releases](https://nodejs.org/dist/index.json).

Al crear un perfil, se destaca inicialmente el LTS más reciente listado para
Node.js y MySQL. Al editar, se conserva la selección existente cuando sigue
siendo válida. Composer muestra el estado LTS que publica su propio feed.

En los demás componentes, **Stable** significa que el release no es un prerelease;
no es una afirmación de soporte LTS. Si los metadatos no identifican el canal,
se muestra como no verificado.

## Requisitos de herramientas

Antes de mostrar versiones de una herramienta, Brig filtra sus requisitos para
el runtime elegido:

| Herramienta | Requisito evaluado |
| --- | --- |
| npm, pnpm, Yarn Classic | `engines.node`, incluyendo rangos npm con `||`, caret y tilde |
| pip, uv | `Requires-Python` de archivos de distribución no retirados |
| Composer | Versión mínima de PHP declarada en el feed |

Para uv, esta comprobación se refiere al Python que instala su distribución,
no a todos los intérpretes que uv puede gestionar posteriormente. Los requisitos
que faltan o no se pueden interpretar no se consideran compatibles.

El guardado valida de nuevo con los mismos metadatos del asistente. Si ninguna
versión verificada resulta compatible, se vuelve a la selección conservando el
nombre del perfil.

Esto no valida las dependencias de la aplicación, sus extensiones adicionales,
la arquitectura de CPU o las migraciones de bases de datos. Esas comprobaciones
corresponden a la construcción y al proyecto concreto.

## Traducción al entorno Docker

Los runtimes usan variantes Bookworm con el release elegido. Las herramientas
seleccionadas se instalan con su número exacto. Las versiones incluidas de pip o
npm permanecen cuando no se selecciona una versión de esas herramientas.

PHP añade `bcmath`, `intl`, `pcntl` y `zip`. Añade `pdo_mysql` si hay MySQL o MariaDB,
y `pdo_pgsql` con las dependencias necesarias si hay PostgreSQL. Las extensiones
PHP de MongoDB y Redis no se instalan por el momento.

Compose crea un contenedor por servicio elegido y usa su versión concreta.
El entorno de desarrollo no instala por separado los servidores de bases de
datos ni inicia aplicaciones a partir del contenido de la carpeta.

## Formato de un perfil

Este ejemplo usa versiones ilustrativas; el asistente muestra las disponibles
en el momento de crear o editar el perfil:

```yaml
schema_version: 1
name: "web_dev"
revision: 1
runtimes:
  php: "8.3.15"
tools:
  composer: "2.8.5"
databases:
  postgresql: "17.2"
caches:
  redis: "7.4.2"
agent: "claude"
```

El archivo es un snapshot legible, no un archivo Docker Compose. Se crea una
revisión nueva para los cambios; no se modifica la anterior. Los proyectos
conservan su snapshot hasta una actualización explícita.
