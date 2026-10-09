# Your first project

This walkthrough creates a profile, registers an existing folder, and opens an
isolated Python terminal. The folder can contain a real project or be empty.

## 1. Prepare your machine

You need Linux, Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), Docker Engine,
and the Docker Compose v2 plugin or newer. Docker must be running and your user
must be able to access its daemon.

From the Brig repository folder:

```bash
uv tool install .
brig --help
```

If `brig` is not on your PATH, run `uv tool update-shell` and open another terminal.
After updating the code, reinstall the tool:

```bash
uv tool install --reinstall .
```

Check Docker as your regular user:

```bash
docker version
docker compose version
```

Brig prepares the container for that user. Run Brig without `sudo`.

## 2. Create a profile

```bash
brig profile create
```

Name it `python-dev`. Select Python and a version shown in the list. For this
walkthrough, you can leave tools and services unselected. Review the configuration
and choose **Save**.

The version list is fetched when you open its selector. Brig saves the specific
version you choose; it does not change automatically when another version is
published.

## 3. Register a folder

```bash
mkdir -p ~/projects/my-api
cd ~/projects/my-api
brig project init
```

Use `my-api` as the project name, the current folder, and the `python-dev` profile.
The name must use `kebab-case`: lowercase letters, numbers, and single hyphens
between words. The wizard registers the folder and a snapshot of the profile
revision; it does not create application code.

```bash
brig project show my-api
```

## 4. Enter the project

```bash
brig run my-api
```

Brig generates the Docker configuration, builds the image if missing, starts the
containers, and opens Bash at `/workspace`. The first startup needs internet to
download missing images and packages.

Inside the terminal:

```bash
pwd
id -u
python --version
python -c 'from pathlib import Path; Path("hello.txt").write_text("from Brig\n")'
exit
```

`/workspace` is the registered folder. The `hello.txt` file also appears in
`~/projects/my-api` on the host. The terminal uses your UID/GID so newly created
files are not owned by root.

Leaving Bash keeps the environment running. You can enter again with `brig run`
from that folder or `brig run my-api` from any other folder.

## 5. Stop and restart

```bash
brig down --project my-api
brig run my-api
```

`down` removes the project's containers and network while preserving source files
and volumes. The next `run` reuses the local image if it is still available.

Continue with [manage projects](../how-to/projects.md) to add services, update a
profile, or execute programs without opening a terminal.
