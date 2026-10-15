"""Build the immutable files uploaded to a Brig GitHub Release; never publish."""

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile

from brig import __version__
from brig.releases import REQUIREMENTS, stable_version

ROOT = Path(__file__).resolve().parent.parent


def render_installer(version):
    helpers = "\n".join(
        (ROOT / "scripts" / name).read_text()
        for name in ("install_ui.sh", "docker_dependencies.sh", "uv_dependencies.sh")
    )
    template = (ROOT / "scripts/release_installer.sh.in").read_text()
    return template.replace("# @BRIG_HELPERS@", helpers).replace(
        "@BRIG_VERSION@", stable_version(version)
    )


def build(output, tag=None):
    if tag is not None and stable_version(tag) != __version__:
        raise ValueError("The release tag must match brig.__version__")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    constraints = output / REQUIREMENTS
    subprocess.run(
        [
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--no-annotate",
            "--no-header",
            "--format",
            "requirements.txt",
            "--output-file",
            str(constraints),
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    if (
        constraints.read_bytes()
        != (ROOT / "src/brig/release/requirements.txt").read_bytes()
    ):
        raise ValueError(
            "Runtime dependency constraints are stale. Re-export uv.lock into src/brig/release/requirements.txt"
        )
    # Build from a clean staging tree so stale build directories and local
    # generated files cannot leak into an immutable release.
    with tempfile.TemporaryDirectory(prefix="brig-build-") as temporary:
        staging = Path(temporary)
        for name in ("pyproject.toml", "README.md"):
            shutil.copyfile(ROOT / name, staging / name)
        shutil.copytree(
            ROOT / "src/brig",
            staging / "src/brig",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        subprocess.run(
            ["uv", "build", str(staging), "--wheel", "--out-dir", str(output)],
            cwd=ROOT,
            check=True,
        )
    wheel = output / f"brig-{__version__}-py3-none-any.whl"
    with ZipFile(wheel) as archive:
        metadata = archive.read(f"brig-{__version__}.dist-info/METADATA").decode()
        if (
            f"\nVersion: {__version__}\n" not in metadata
            or archive.read("brig/release/requirements.txt") != constraints.read_bytes()
        ):
            raise ValueError(
                "Wheel version or packaged dependency lock does not match the release"
            )
    installer = output / "install.sh"
    installer.write_text(render_installer(__version__))
    installer.chmod(0o755)
    version_file = output / "VERSION"
    version_file.write_text(__version__ + "\n")
    assets = (wheel, constraints, installer, version_file)
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in assets
        )
    )
    return (*assets, output / "SHA256SUMS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Expected release tag, e.g. v1.0.0")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist/release")
    args = parser.parse_args()
    # Artifact timestamps follow the source commit when CI supplies this value.
    os.environ.setdefault("SOURCE_DATE_EPOCH", "0")
    try:
        for path in build(args.out_dir, args.tag):
            print(path)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Release build failed: {error}\n")


if __name__ == "__main__":
    main()
