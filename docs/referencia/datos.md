# Almacenamiento y persistencia

## Directorio de datos

El directorio predeterminado es:

```text
${XDG_DATA_HOME:-~/.local/share}/brig
```

Puedes sustituirlo para una ejecución con `brig --data-dir DIRECTORIO …`.
La primera carga crea un estado vacío si todavía no existe.

```text
brig/
├── state.json
├── profiles/
│   └── profile-NOMBRE_CODIFICADO/
│       ├── revision-1.yaml
│       └── revision-2.yaml
└── runtime/
    └── brig-ID_DEL_PROYECTO/
        ├── credentials.json
        ├── lifecycle.lock
        └── HASH_DE_IMAGEN/
            ├── Dockerfile
            ├── .dockerignore
            ├── compose.yaml
            ├── development.env
            └── SERVICIO.env
```

## Definiciones

`state.json` contiene el esquema de almacenamiento, perfiles, historial de
revisiones, registros de proyectos y sus snapshots. El ID del proyecto identifica
sus recursos; su nombre sirve para seleccionarlo desde la CLI.

Los nombres de carpeta de los perfiles están codificados y llevan el prefijo
`profile-`. Cada revisión produce un YAML separado. Sus versiones se escriben
como strings. Los YAML permiten lectura e intercambio, pero no se importan ni
se aplican ediciones manuales al estado.

La carga valida el esquema y las relaciones entre perfiles y proyectos sin
internet. Un archivo incompatible o corrupto produce un error; no se reemplaza
silenciosamente. Las escrituras del estado y de los YAML usan archivos temporales.
Si falla el guardado de una revisión, se retiran sus documentos nuevos.

## Artefactos del motor

El motor genera una carpeta por hash de Dockerfile y UID/GID. Las etiquetas del
Dockerfile incluyen el nombre del proyecto, el perfil y su revisión. Aplicar otra
revisión puede generar una imagen y una carpeta diferentes.

El contexto de construcción excluye todos los archivos salvo el Dockerfile.
`compose.yaml` utiliza rutas de montaje explícitas y no crea una carpeta fuente
inexistente. Las contraseñas no se añaden al Dockerfile ni al perfil YAML.

`credentials.json` conserva contraseñas de inicialización por servicio. Los
archivos de entorno de los servicios contienen sus variables de inicialización;
`development.env` contiene las conexiones que recibe el contenedor de desarrollo.
Los archivos generados tienen permisos 0600. Los nombres y contraseñas no se
vuelven a generar sobre datos persistentes cuando faltan las credenciales.

`lifecycle.lock` coordina arranque y parada del mismo proyecto. Las operaciones
generales de edición del estado siguen sin coordinar todos los escritores:
utiliza una sesión a la vez para crear, editar o borrar definiciones.

## Recursos de Docker

Los nombres siguen el prefijo `brig-ID_DEL_PROYECTO`:

| Recurso | Nombre o ubicación |
| --- | --- |
| Contenedor de desarrollo | `brig-ID-dev` |
| Contenedor de servicio | `brig-ID-SERVICIO` |
| Red | `brig-ID-network` |
| Volumen de home | `brig-ID-home` → `/home/brig` |
| Volumen de datos | `brig-ID-SERVICIO-data` |
| Volumen de configuración MongoDB | `brig-ID-mongodb-config` |
| Imagen de desarrollo | `brig-dev-brig-ID:HASH` |

El código vive en la carpeta registrada del host y se monta en `/workspace`.
Los volúmenes con nombre los administra Docker; no están dentro del directorio
de datos de Brig. Incluyen etiquetas de propiedad y, para los datos de un
servicio, su versión mayor. Los contenedores ajenos que ocupen el nombre del
contenedor de desarrollo no se adoptan automáticamente.

## Qué conserva cada operación

| Operación | Registro de proyecto | Código | Perfil/YAML | Contenedores/red | Volúmenes y credenciales |
| --- | --- | --- | --- | --- | --- |
| Salir de la terminal | Conserva | Conserva | Conserva | Siguen activos | Conserva |
| `down` | Conserva | Conserva | Conserva | Retira | Conserva |
| Borrar proyecto detenido | Elimina | Conserva | Conserva | No los crea ni retira | Conserva |
| Borrar perfil no referenciado | No hay proyectos asociados | Conserva | Elimina el perfil y sus YAML | Sin cambios | Sin cambios |

Una definición borrada no constituye un borrado de datos Docker. Brig no ofrece
por ahora un comando para purgar volúmenes o artefactos históricos.

## Copias de seguridad

Conserva `state.json`, `profiles/`, `runtime/` y el código del proyecto. Para
los datos de las bases, utiliza respaldos coherentes con las herramientas del
servicio: guardar los archivos de Brig no guarda los volúmenes de Docker.

Las credenciales y los datos deben restaurarse juntos. Restaurar solo los
volúmenes puede dejar la base inicializada con contraseñas que ya no están en el
estado local. Brig rechaza generar credenciales nuevas para esos volúmenes.
