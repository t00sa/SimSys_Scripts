#!/usr/bin/env python3
# *********************************COPYRIGHT************************************
# (C) Crown copyright Met Office. All rights reserved.
# For further details please refer to the file COPYRIGHT.txt
# which you should have received as part of this distribution.
# *********************************COPYRIGHT************************************
"""
Dummy git repository fixture for use with pytest.
"""


import os
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest


class GitTestRepo:
    """Create a dummy git repository fixture."""

    # Always reset to this branch
    default_branch = "main"

    # Quiet mode hides output/error from git commands.  Setting this
    # to True prevents clutter in the pytest output
    quiet = True
    # quiet = False

    def __init__(self, tmpdir_factory):

        self.location = tmpdir_factory.mktemp("data")
        self._stack = []

        self.__enter__()
        self.run(["init"])
        self.add_files("README", content="Test repository")
        self.__exit__()

    def __enter__(self):
        self._stack.append(os.getcwd())
        os.chdir(self.location)
        return self

    def __exit__(self, *args):
        if os.path.isdir(".git"):
            # Reset the test repo the default branch
            self.run(["reset", "--hard"], False)
            self.run(["switch", self.default_branch], False)
        os.chdir(self._stack.pop())

    def run(self, cmd, check=True):
        """Run a git command."""

        if os.getcwd() != self.location:
            raise RuntimeError("not in repository context")

        output = subprocess.DEVNULL if self.quiet else None
        subprocess.run(["git"] + cmd, check=check, stdout=output, stderr=output)

    def create_file(self, path, content=None, mode="wt"):
        """Create and add a dummy file."""

        if content is None:
            # Dummy content
            content = "Lorem ipsum dolor sit amet"

        with path.open(mode) as fd:
            print(content, file=fd)

        self.run(["add", str(path)])

    def add_files(self, name, start=0, end=1, message=None, content=None, mode="wt"):
        """Create and commit a number of files."""

        for i in range(start, end):
            self.create_file(Path(name.format(i)), content, mode)

        if message is None:
            message = "Add some files"

        self.commit(message)

    def commit(self, message):
        """Trivial commit wrapper."""

        self.run(["commit", "--no-gpg-sign", "-m", message])

    def branch(self, branch, create=False):
        """Set the target branch."""
        cmd = ["switch"]
        if create:
            cmd.append("-c")
        cmd.append(str(branch))
        self.run(cmd)


@pytest.fixture(scope="session")
def git_repo(tmpdir_factory):
    """Create a session-wide dummy git repository."""
    return GitTestRepo(tmpdir_factory)


@pytest.fixture(scope="session")
def git_ifdef_repo(tmpdir_factory):
    """Create a session-wide dummy git repository with ifdef files."""
    repo = GitTestRepo(tmpdir_factory)

    content = dedent(
        """\
        integer :: i
        #ifdef {macro}
        integer :: j
        #endif /* {macro}
        """
    )

    wrapped = dedent(
        """\
        #ifdef WRAPPER
        integer :: i
        #endif
        """
    )

    with repo:
        repo.branch("test-mirror", True)
        repo.branch("mybranch", True)

        repo.branch("new_ifdefs", True)
        for i, macro in enumerate(["ABC", "DEF", "GHI", "JKL", "NOUSE"]):
            repo.create_file(Path(f"source{i}.F90"), content.format(macro=macro))
        repo.commit("add macro files")

        repo.branch("wrapper", True)
        repo.create_file(Path(f"wrapped.F90"), wrapped)
        repo.commit("add wrapped files")

    return repo


def test_git_repo(git_ifdef_repo):

    with git_ifdef_repo:
        assert os.path.isdir(".git")
