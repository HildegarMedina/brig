# Referencia de comandos

## Opciones generales

```text
brig [--data-dir DIRECTORIO] [comando]
brig --help
brig --version
```

Sin un comando, abre la interfaz de terminal. `--data-dir` debe aparecer antes del
comando y cambia el directorio de definiciones, revisiones y artefactos del motor.

## Perfiles

| Comando | Efecto |
| --- | --- |
| `brig profile create` | Asistente para guardar la primera revisión |
| `brig profile list` | Lista nombres y última revisión |
| `brig profile edit NOMBRE` | Asistente que crea otra revisión |
| `brig profile delete NOMBRE [--yes]` | Borra un perfil sin proyectos asociados y sus YAML |

Crear y editar requieren una terminal interactiva e internet para consultar los
componentes seleccionados. Los guardados empiezan con **Save** seleccionado.
Los borrados empiezan con **Cancel**; `--yes` confirma directamente.

## Proyectos

| Comando | Efecto |
| --- | --- |
| `brig project init` | Registra una carpeta existente con nombre y perfil |
| `brig project list` | Lista proyectos y consulta su estado en Docker |
| `brig project show NOMBRE` | Muestra snapshot, carpeta y recursos del entorno |
| `brig project update NOMBRE` | Adopta la última revisión del perfil si el entorno está detenido |
| `brig project delete NOMBRE [--yes]` | Elimina el registro de un proyecto detenido |
| `brig project dockerfile [NOMBRE] [--output ARCHIVO]` | Muestra o exporta su Dockerfile |

`project init` es interactivo. Crear perfiles o proyectos exige nombres de 1–64
caracteres ASCII en `snake_case`: empiezan con una letra minúscula y admiten
minúsculas, números y guiones bajos simples entre palabras. Los registros antiguos
siguen siendo legibles.

La exportación del Dockerfile no consulta Docker ni proveedores de versiones y
no sobrescribe un archivo existente. Sin nombre, resuelve la carpeta actual.

## Ejecutar un proyecto

```text
brig run [NOMBRE] [--project NOMBRE] [--command PROGRAMA ARGUMENTOS...]
brig up [--project NOMBRE]
brig shell [--project NOMBRE] [--command PROGRAMA ARGUMENTOS...]
brig down [--project NOMBRE]
```

| Comando | Preparación | Resultado |
| --- | --- | --- |
| `run` | Construye si falta y arranca | Abre Bash o ejecuta `--command` |
| `up` | Construye si falta y arranca | Deja el entorno activo en segundo plano |
| `shell` | Construye si falta y arranca | Abre Bash o ejecuta `--command` |
| `down` | Usa la configuración administrada existente | Retira contenedores y red; conserva volúmenes |

`run NOMBRE` y `--project NOMBRE` seleccionan un único proyecto. Es un error
indicar nombres diferentes con ambos. Si no se especifica uno, la carpeta actual
debe estar dentro de un proyecto registrado.

Después de `--command`, todas las opciones pertenecen al programa, por ejemplo:

```bash
brig run mi_api --command python -m unittest -v
```

Abrir Bash necesita stdin y stdout conectados a una terminal. Ejecutar un programa
con `--command` no necesita TTY. Brig no interpreta esos argumentos con una shell;
si la necesitas, indícala como programa.

## Agentes

```text
brig agent [AGENTE] [--project NOMBRE]
```

La instalación y autenticación de agentes están pendientes. El comando informa
de esa situación. El antiguo `brig run AGENTE` de la simulación se sustituyó por
`brig run PROYECTO`; el nombre `run` ahora corresponde a ejecutar un proyecto.

## Interfaz de terminal

Las flechas navegan; Enter selecciona; Space alterna opciones múltiples; Esc
vuelve; Ctrl+C sale. Los selectores de versiones permiten buscar con `/`. Ctrl+U
limpia un campo de texto. La terminal requiere al menos 45 columnas y 12 filas;
90 × 28 o más facilita leer detalles. Las vistas largas se desplazan con flechas.

Los errores de validación aparecen resaltados en rojo. **Shell** prepara el
proyecto y abre la terminal; al salir, vuelves al menú. **View Dockerfile** muestra
la definición sin arrancar Docker.

## Estados de salida

| Código | Significado |
| --- | --- |
| 0 | Operación completada o asistente cerrado sin error |
| 1 | Error de aplicación, Docker o programa ejecutado |
| 2 | Uso incorrecto de argumentos o falta de terminal para un asistente |
| 130 | Interrupción con Ctrl+C |

El código de error de un programa ejecutado se muestra en el mensaje de Brig;
la CLI devuelve 1 para esa operación fallida, no necesariamente el código del
programa. Cerrar Bash deja el entorno activo.
