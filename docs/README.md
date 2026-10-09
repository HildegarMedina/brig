# Documentación de Brig

Brig crea un entorno de desarrollo para cada proyecto a partir de un perfil con
versiones concretas. `brig run mi_proyecto` prepara ese entorno y abre una terminal
Bash dentro de su contenedor de desarrollo.

## Por dónde empezar

| Necesitas… | Lee… |
| --- | --- |
| Crear y ejecutar tu primer proyecto | [Primer proyecto](tutoriales/primer-proyecto.md) |
| Arrancar, detener, actualizar o borrar una definición | [Gestionar proyectos](guias/proyectos.md) |
| Resolver un error de Docker, versiones o terminal | [Problemas frecuentes](guias/problemas-frecuentes.md) |
| Entender cómo se conectan perfiles, proyectos y Docker | [Arquitectura y flujo de ejecución](explicacion/arquitectura.md) |
| Consultar comandos y opciones | [Referencia de comandos](referencia/comandos.md) |
| Saber dónde están las definiciones, credenciales y datos | [Almacenamiento y persistencia](referencia/datos.md) |
| Consultar componentes, versiones y compatibilidad | [Componentes y versiones](referencia/componentes.md) |
| Modificar el código y ejecutar pruebas | [Desarrollo y mantenimiento](desarrollo.md) |

## Alcance actual

El motor genera Dockerfiles y Compose para PHP, Python y Node.js, solos o
combinados. Puede levantar PostgreSQL, MySQL, MariaDB, MongoDB y Redis según el
perfil, construir la imagen que falta y abrir una terminal sin privilegios.

Brig no instala Docker en la máquina, instala dependencias de la aplicación,
arranca servidores HTTP ni publica puertos de la aplicación. La instalación y
la autenticación de agentes todavía están pendientes. Los YAML de perfiles se
pueden leer y compartir; su importación no está implementada.

## Cómo mantenemos esta documentación

Usamos archivos Markdown dentro del mismo repositorio que el código. La
organización sigue [Diátaxis](https://diataxis.fr/): tutoriales para aprender con un
recorrido, guías para resolver una tarea, referencias para consultar detalles y
explicaciones para comprender el sistema.

Cuando cambie un comando, un formato o una responsabilidad del motor, se debe
actualizar su página en el mismo cambio. Los ejemplos deben distinguir versiones
ilustrativas de versiones que se consultan en vivo. Documentamos el comportamiento
implementado y señalamos las funciones pendientes.
