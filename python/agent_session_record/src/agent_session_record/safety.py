"""Bound local input reads and keep recorder directories private."""
import os
from pathlib import Path
import stat


def private_directory(path):
    path = Path(path).absolute()
    for directory in reversed([path, *path.parents]):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("storage_directory_must_not_be_a_symlink")
    info = path.lstat()
    if info.st_mode & 0o077 or hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise ValueError("storage_directory_must_be_private")
    return path


def read_bounded(path, limit):
    """Refuse links and special files, then cap the actual descriptor read."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("input_byte_limit_or_file_type")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("input_byte_limit_or_file_type")
    return data
