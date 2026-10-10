"""Local context copies shared through the project's existing workspace mount."""

import shutil
import tempfile
from pathlib import Path

from brig.errors import BrigError
from brig.models import Project


def _context(project: Project) -> Path:
    if not project.path or not Path(project.path).is_dir():
        raise BrigError("Project folder is missing. Register an existing local folder.")
    root = Path(project.path)
    for name in (".brig", "context", "attachments"):
        root /= name
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise BrigError(f"Context folder must be a real directory: {root}.")
    return root


def attach_files(project: Project, files: list[Path]) -> str:
    if not files:
        raise BrigError("Attach needs at least one file.")
    sources = [path.expanduser().absolute() for path in files]
    for source in sources:
        if not source.is_file():
            raise BrigError(f"Attachment must be an existing regular file: {source}.")
    root = _context(project)
    created = []
    paths = []
    try:
        root.mkdir(parents=True, exist_ok=True)
        ignore = root.parent / ".gitignore"
        if not ignore.exists():
            # Ignore context without editing the project's tracked .gitignore.
            with ignore.open("x", encoding="utf-8") as stream:
                stream.write("*\n")
        for source in sources:
            directory = Path(tempfile.mkdtemp(prefix="brig-", dir=root))
            created.append(directory)
            shutil.copyfile(source, directory / source.name)
            paths.append(
                f"/workspace/.brig/context/attachments/{directory.name}/{source.name}"
            )
    except OSError as error:
        for directory in created:
            shutil.rmtree(directory, ignore_errors=True)
        raise BrigError(f"Cannot attach files: {error}") from error
    return "\n".join(paths)


def detach_files(project: Project) -> str:
    # Stopping an old project must still work if its source folder disappeared.
    if not project.path or not Path(project.path).is_dir():
        return "No attachments to remove."
    root = _context(project)
    try:
        if root.exists():
            shutil.rmtree(root)
    except OSError as error:
        raise BrigError(f"Cannot remove attachments: {error}") from error
    return f"Removed attachments for {project.name}. Original files were kept."
