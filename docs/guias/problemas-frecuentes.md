# Problemas frecuentes

## Docker no está disponible

Si Brig indica que Docker no está instalado, instala Docker Engine y el plugin
de Compose según la documentación de tu distribución. Brig no instala servicios
del sistema.

Si no puede conectarse al daemon, comprueba:

```bash
docker version
docker compose version
```

El primer comando debe mostrar el servidor y el segundo la versión de Compose.
Comprueba que el daemon esté activo y que tu usuario tenga acceso a su socket.
Usa Brig como usuario habitual, sin `sudo`; el motor necesita un UID/GID distinto
de cero para crear el usuario sin privilegios del contenedor.

Puedes consultar perfiles y la configuración de los proyectos sin arrancar un
entorno. Si Docker está apagado, el estado del proyecto aparece como desconocido.

## `brig run` pide una terminal interactiva

Abrir Bash requiere una terminal real. Para un script, pipeline o tarea de CI,
especifica un programa:

```bash
brig run mi_api --command python --version
```

Pasar `--command` sin un programa es un error. Un programa que termina con un
estado distinto de cero produce un error en Brig; el entorno permanece activo.

## Brig no encuentra el proyecto

Comprueba los proyectos registrados:

```bash
brig project list
brig run mi_api
```

Sin un nombre, Brig busca una carpeta registrada que contenga el directorio
actual. `project init` registra una carpeta existente; no crea esa carpeta ni
inicializa un framework.

## El primer arranque falla al descargar o construir

Las versiones del perfil están fijadas, pero las imágenes o los paquetes pueden
no estar disponibles para tu arquitectura o haber dejado de publicarse. Brig no
sustituye la versión elegida por `latest`.

Lee la salida de Docker. Resuelve el problema de red, publicación o arquitectura
y vuelve a ejecutar `brig run mi_api`. Si necesitas otra versión, edita el perfil
y aplica su nueva revisión al proyecto detenido.

## Un servicio no llega a estar saludable

Compose espera los servicios antes de iniciar el contenedor de desarrollo. Un
fallo puede dejar algunos contenedores creados o activos. Consulta los logs del
servicio usando el nombre que muestra `brig project show mi_api`, por ejemplo:

```bash
docker logs brig-ID_DEL_PROYECTO-mysql
brig down --project mi_api
```

Sustituye el nombre del ejemplo por el real. `down` conserva los datos para poder
investigar o volver a intentar el arranque. Brig no marca el proyecto como
arrancado cuando la operación falla; las consultas posteriores verifican Docker.

## Faltan credenciales o cambió la versión mayor de una base

Restaura `credentials.json` desde una copia del directorio de ejecución del
proyecto si el archivo falta o está dañado. No borres los volúmenes como método
para resolver un problema de credenciales: contienen los datos de la base.

Si cambiaste una versión mayor, vuelve a la revisión compatible o realiza una
migración con las herramientas de la base antes de reutilizar los datos. Brig
no implementa un asistente de migración ni una opción de borrado de volúmenes.

## Las versiones no aparecen en el selector

La creación y edición de perfiles necesitan internet. Un fallo del proveedor
ofrece reintentar o cancelar. No se usan listas ficticias como alternativa.
Las versiones de herramientas se filtran por sus requisitos declarados para el
runtime seleccionado. Consulta [componentes y versiones](../referencia/componentes.md).

## Un agente no arranca

Los perfiles pueden guardar Claude Code como agente predeterminado, pero su
instalación y autenticación siguen pendientes. `brig agent` muestra ese estado.
Puedes entrar al entorno con `brig run mi_api` para trabajar en su terminal.
