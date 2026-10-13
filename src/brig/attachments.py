"""Local context copies shared through the project's existing workspace mount."""

import shutil
import tempfile
from pathlib import Path

from brig.errors import BrigError
from brig.i18n import tr
from brig.models import Project

# Where the project folder's .brig/context appears inside the work container.
CONTEXT_PATH = "/workspace/.brig/context"
ATTACHMENTS_PATH = f"{CONTEXT_PATH}/attachments"


def _context(project: Project) -> Path:
    if not project.path or not Path(project.path).is_dir():
        raise BrigError(
            tr("Project folder is missing. Register an existing local folder.")
        )
    root = Path(project.path)
    for name in (".brig", "context", "attachments"):
        root /= name
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise BrigError(
                tr("Context folder must be a real directory: {value0}.").format(
                    value0=root
                )
            )
    return root


def attach_files(project: Project, files: list[Path]) -> str:
    if not files:
        raise BrigError(tr("Attach needs at least one file."))
    sources = [path.expanduser().absolute() for path in files]
    for source in sources:
        if not source.is_file():
            raise BrigError(
                tr("Attachment must be an existing regular file: {value0}.").format(
                    value0=source
                )
            )
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
            # Agents run as other users in the shared brig group; mkdtemp's
            # 0700 would also zero the ACL mask inherited from /workspace.
            directory.chmod(0o770)
            target = directory / source.name
            shutil.copyfile(source, target)
            target.chmod(0o660)
            paths.append(f"{ATTACHMENTS_PATH}/{directory.name}/{source.name}")
    except OSError as error:
        for directory in created:
            shutil.rmtree(directory, ignore_errors=True)
        raise BrigError(
            tr("Cannot attach files: {value0}").format(value0=error)
        ) from error
    return "\n".join(paths)


def detach_files(project: Project) -> str:
    # Stopping an old project must still work if its source folder disappeared.
    if not project.path or not Path(project.path).is_dir():
        return tr("No attachments to remove.")
    root = _context(project)
    try:
        if root.exists():
            shutil.rmtree(root)
    except OSError as error:
        raise BrigError(
            tr("Cannot remove attachments: {value0}").format(value0=error)
        ) from error
    return tr("Removed attachments for {value0}. Original files were kept.").format(
        value0=project.name
    )
