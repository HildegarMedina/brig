# Your first project

This walkthrough creates a profile, registers an existing folder, and opens an
isolated Python terminal. The folder can contain a real project or be empty.

## 1. Prepare your machine

You need Linux, Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/). Brig also
requires Docker Engine and the Compose v2 plugin or newer. The repository
installer checks their availability, the daemon, and access for your regular user.

From the Brig repository folder:

```bash
./scripts/install.sh
brig --help
```

The installer welcomes you with a brig and shows two brief stages: preparing
Docker and installing Brig. Detailed output appears on failure, or live with
`./scripts/install.sh --verbose`. It respects `BRIG_LANG` (en, es, pt), `NO_COLOR`,
and `BRIG_NO_ANIMATION`; redirected output and CI stay plain.

If `brig` is not on your PATH, run `uv tool update-shell` and open another terminal.
After updating the code, reinstall the tool:

```bash
./scripts/install.sh
```

The installer reuses working Docker installations, including accessible remote
and rootless daemons. On Ubuntu 22.04, 24.04, 26.04 and Debian 12, 13 it installs
missing packages using Docker's official APT repository. If only Compose is
missing, it installs the plugin without reinstalling the engine. Package conflicts
stop installation without removing existing packages.

Run the installer without `sudo`; it uses `sudo` for system packages and local
service configuration. It can start and enable the standard local Docker service
on systems with systemd. If your user needs Docker access, it adds the `docker`
group and tells you to **log out and back in**. This group grants administrative
control through Docker; see [Docker's post-installation instructions](https://docs.docker.com/engine/install/linux-postinstall/).
It does not change a configured remote or rootless endpoint; if that daemon is
unreachable, start it and resolve its access before retrying.

Other Linux distributions require manually installing Docker Engine and Compose
before running the installer. Follow [Docker's distribution instructions](https://docs.docker.com/engine/install/).
The APT setup follows [Docker's Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
and [Debian](https://docs.docker.com/engine/install/debian/) documentation.

For an existing managed machine, `uv tool install --reinstall .` remains available
to install only the Python package; it does not run host dependency setup. The
development hook installer also remains separate and does not install Docker.

After setup, check Docker as your regular user:

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
version; it does not create application code.

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
`~/projects/my-api` on the host. Each agent session uses its own UID and your host
group. Shared permissions keep the code editable from the host; new files are
owned by the agent user, not root.

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
