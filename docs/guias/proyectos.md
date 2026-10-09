# Gestionar un proyecto

Los comandos actúan sobre un proyecto. No arrancan todos los proyectos
registrados. Usa su nombre con `run` o `--project` con los otros comandos.
Dentro de una carpeta registrada o una subcarpeta, Brig puede detectarlo; si hay
proyectos anidados, el padre registrado más cercano tiene prioridad.

## Arrancar y entrar

```bash
brig run mi_api
```

El comando construye la imagen si falta, inicia los servicios del perfil, espera
sus comprobaciones de salud y abre la terminal de desarrollo. Si ya existe el
entorno compatible, lo reutiliza.

Para levantarlo sin entrar:

```bash
brig up --project mi_api
```

Para volver a entrar, también puedes usar:

```bash
brig shell --project mi_api
```

`run` y `shell` preparan el entorno antes de abrir la terminal. `exit` vuelve al
host y deja los contenedores activos.

## Ejecutar un programa sin terminal interactiva

```bash
brig run mi_api --command python --version
brig run mi_api --command python -m unittest
```

Todo lo que siga a `--command` pertenece al programa. Brig pasa los argumentos
directamente a Docker, sin interpretarlos como código de shell. Para necesitar
una shell explícita, puedes usar `--command bash -lc 'tu comando'`.

El programa trabaja en `/workspace` y usa el usuario del contenedor. Terminar el
programa deja el entorno levantado.

## Usar las bases de datos del perfil

Los servicios se encuentran por su nombre dentro de la red del proyecto:

| Servicio | Host | Puerto interno | Variables del contenedor de desarrollo |
| --- | --- | --- | --- |
| PostgreSQL | `postgresql` | 5432 | `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` |
| MySQL | `mysql` | 3306 | `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD` |
| MariaDB | `mariadb` | 3306 | `MARIADB_HOST`, `MARIADB_PORT`, `MARIADB_DATABASE`, `MARIADB_USER`, `MARIADB_PASSWORD` |
| MongoDB | `mongodb` | 27017 | `MONGODB_URI` |
| Redis | `redis` | 6379 | `REDIS_HOST`, `REDIS_PORT`, `REDIS_URL` |

Brig crea las credenciales iniciales por proyecto y las conserva. PostgreSQL,
MySQL y MariaDB tienen una base inicial `brig`; MongoDB utiliza autenticación en
`admin` y una URI que apunta a `brig`. Redis no requiere contraseña en esta
configuración y no publica puertos en el host.

Adapta la configuración de tu aplicación a estas variables. Brig no modifica su
archivo `.env`. PHP recibe PDO MySQL para MySQL/MariaDB y PDO PostgreSQL para
PostgreSQL. Las extensiones PHP de MongoDB y Redis no se instalan automáticamente.

## Actualizar un perfil usado por un proyecto

```bash
brig profile edit python_dev
brig down --project mi_api
brig project update mi_api
brig run mi_api
```

Editar el perfil crea otra revisión. El proyecto conserva su revisión anterior
hasta que ejecutes `project update`, que adopta la última revisión de ese perfil.
La siguiente ejecución genera la configuración correspondiente.

Un cambio de versión mayor de un servicio con datos persistentes necesita una
migración de esos datos. Brig lo detecta por las etiquetas del volumen y rechaza
su reutilización automática. No hace migraciones ni reinicializa esos datos.

## Ver o exportar el Dockerfile

```bash
brig project dockerfile mi_api
```

Para guardar una copia, desde la carpeta del proyecto:

```bash
brig project dockerfile --output .brig/Dockerfile
```

La exportación funciona sin Docker ni internet y rechaza archivos existentes.
El motor genera su propia copia bajo el directorio de datos de Brig. Editar una
copia exportada no modifica el Dockerfile que usará `run`.

## Detener o borrar una definición

```bash
brig down --project mi_api
brig project delete mi_api
```

`down` elimina los contenedores y la red, conservando los volúmenes. Borrar el
proyecto elimina su registro de Brig, pero conserva su carpeta, perfil, artefactos
de ejecución y volúmenes. La comprobación de borrado consulta Docker e incluye
servicios que hayan quedado activos después de un arranque fallido.

Un perfil solo se puede borrar cuando ningún proyecto lo referencia:

```bash
brig profile delete python_dev
```

En ambos borrados, la confirmación empieza en **Cancel**. `--yes` omite esa
confirmación para scripts, pero mantiene las validaciones.
