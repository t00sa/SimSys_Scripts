#!/usr/bin/env python3
# *********************************COPYRIGHT************************************
# (C) Crown copyright Met Office. All rights reserved.
# For further details please refer to the file COPYRIGHT.txt
# which you should have received as part of this distribution.
# *********************************COPYRIGHT************************************
"""
Unit tests for check_ifdef.
"""

import os
import logging
import subprocess
from pathlib import Path
from textwrap import dedent
from check_ifdef import IfDefChecker, main, process_arguments


import pytest


class TestCheckerWrap:
    """Test wrapped file functionality."""

    def test_present(self):
        """Testcase where a wrapping ifdef is present."""

        checker = IfDefChecker(".")

        diff = dedent(
            """
            diff --git a/test.F90 b/test.F90
            index bd4cee1..d396c50 100644
            --- a/test.F90
            +++ b/test.F90
            @@ -1,2 +1,4 @@
            +#ifdef FOO
             program test
             end program test
            +#endif
            """
        )

        assert checker.wrapped_files(diff.split("\n")) == 1
        assert checker._wrapped == ["b/test.F90"]

    def test_not_if(self):
        """Test where a wrapping ifdef is not present."""

        checker = IfDefChecker(".")

        diff = dedent(
            """
            Index: test.F90
            ===================================================================
            --- test.F90	(revision 123456)
            +++ test.F90	(working copy)
            @@ -1,3 +1,4 @@
            +if something foobar
            line1
            line2
            line3
            """
        )

        assert checker.wrapped_files(diff.split("\n")) == 0

    def test_second_if(self):
        """Test where ifdef does not wrap the entire file."""

        checker = IfDefChecker(".")

        diff = dedent(
            """
            Index: test.F90
            ===================================================================
            --- test.F90	(revision 123456)
            +++ test.F90	(working copy)
            @@ -1,3 +1,5 @@
            abc
            #ifdef foobar
            line1
            line2
            line3
            """
        )

        assert checker.wrapped_files(diff.split("\n")) == 0

    def test_empty(self):
        """Test when the diff text is empty."""

        checker = IfDefChecker(".")

        diff = dedent(
            """
            """
        )

        assert checker.wrapped_files(diff.split("\n")) == 0


class TestCheckerCleaner:
    """Test functions which clean up the input text."""

    def test_continuation(self):
        """Test cpp continuation lines are joined."""

        checker = IfDefChecker(".")

        text = dedent(
            """
            abc 123 \\
            def 456 \\
            xyz 789
            """
        )

        result = checker.clean_text(text)
        lines = result.split("\n")

        assert len(lines) == 1
        assert lines[0] == "abc 123 def 456 xyz 789"

        text += "\nline 2"

        result = checker.clean_text(text)
        lines = result.split("\n")

        assert len(lines) == 2
        assert lines[0] == "abc 123 def 456 xyz 789"
        assert lines[1] == "line 2"

    def test_simple_comment(self):
        """Test removal of a simple single-line cpp comment."""

        checker = IfDefChecker(".")

        text = "abc /* comment */ 123"

        result = checker.clean_text(text)
        assert result == "abc 123"

    def test_block_comment(self):
        """Test removal of a multi-line cpp comment."""

        checker = IfDefChecker(".")

        text = "abc /* comment */ 123"

        text = dedent(
            """
            abc /* first line
                 * second line
                 */
            123
            """
        )

        result = checker.clean_text(text)
        assert result == "abc\n123"


class TestCheckerFinder:
    """Test functions which locate macros."""

    @pytest.mark.parametrize(
        "line,expected",
        [
            ("#if defined (ABC)", ["ABC"]),
            ("#if defined (ABC) || defined (EFG)", ["ABC", "EFG"]),
            ("#if defined(ABC)", ["ABC"]),
            ("#if defined(ABC) && defined(EFG)", ["ABC", "EFG"]),
            ("#elif defined (ABC)", ["ABC"]),
        ],
        ids=["basic", "double", "joined", "double joined", "elif"],
    )
    def test_defined_tokens(self, line, expected):
        """Test to find various defined tokens."""

        checker = IfDefChecker(".")
        assert list(checker.defined_tokens(line)) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("#ifdef ABC", ["ABC"]),
            ("#ifndef ABC", ["ABC"]),
            ("#ifdef ABC\n#if defined (EFG)", ["ABC", "EFG"]),
            (
                "#if defined (EFG)\n#elif defined (HIJ)",
                ["EFG", "HIJ"],
            ),
        ],
        ids=[
            "basic ifdef",
            "basic ifndef",
            "ifdef + if",
            "if + elif",
        ],
    )
    def test_find_ifdefs(self, text, expected):
        """Test to find different types of definition."""

        checker = IfDefChecker(".")
        assert list(checker.find_ifdefs(text)) == expected


class TestCheckerCore:
    """Test core checker features."""

    def test_create(self):
        """Test the creation of a new checker."""

        checker = IfDefChecker(".")
        assert checker.branch == Path(".")

    def test_retired(self, tmp_path):
        """Test parsing of a retired macro file."""

        retired = tmp_path / "retired.txt"

        retired.write_text(
            dedent(
                """
                HP
                IBM
                LINUX
                LINUX_PORTLAND_COMPILER
                ATMOS
                GLOBAL
                FLUME
                """
            )
        )

        checker = IfDefChecker(".")
        checker.load_retired(retired)

        assert len(checker._retired) == 7

    def test_inspect_file(self, tmp_path):
        """Test ability to inspect a file for retired macros."""

        checker = IfDefChecker(".")
        checker._retired.append("ABC")

        test_file = tmp_path / "example.F90"

        test_file.write_text(
            dedent(
                """
                program example
                #ifdef ABC
                integer :: i
                #endif
                #ifdef CDE
                integer :: j
                #endif
                #ifdef ABC
                integer :: k
                #endif
                end program example
                """
            )
        )

        result = checker.inspect_file(test_file)
        assert not result
        assert len(checker._additions) == 1
        assert checker._additions == set(["ABC"])



class TestArguments:
    """Test command line argument handling."""

    def test_help(self, capsys):
        """Trivial test of help option."""

        with pytest.raises(SystemExit) as err:
            process_arguments(["--help"])
        assert err.value.code == 0

        captured = capsys.readouterr()
        assert "path to working copy" in captured.out
        assert "path to file of retired ifdefs" in captured.out

    def test_parameters(self, tmp_path):
        """Test branch and retired file arguments."""

        retired = tmp_path / "retired"
        retired.write_text("ABC")

        args = process_arguments(["mybranch", str(retired)])
        assert args.branch.name == "mybranch"
        assert args.retired.name == retired.name
        assert not args.suite_mode

    def test_branch_redirect(self, tmp_path, caplog, monkeypatch):
        """Test environment variable branch redirection."""

        retired = tmp_path / "retired"
        retired.write_text("ABC")

        monkeypatch.setattr(os, "environ", {"SOURCE_UM_MIRROR": "test-mirror"})

        args = process_arguments(["mybranch", str(retired)])

        assert args.branch.name == "test-mirror"
        assert args.retired.name == retired.name
        assert args.suite_mode
        assert "redirecting branch to 'test-mirror'" in caplog.messages

    def test_no_retired(self, capsys):
        """Test error when retired file does not exist."""

        with pytest.raises(SystemExit) as err:
            process_arguments(["mybranch", "nosuch"])
        assert err.value.code != 0

        captured = capsys.readouterr()
        assert "retired ifdef file is not valid" in captured.err


def add_to_repo(start, end, message, mode="wt", content=None, extension=""):
    """Add and commit dummy files to a repo."""

    if content is None:
        content = "Lorem ipsum dolor sit amet {}"

    for i in range(start, end):
        with open(f"file{i}{extension}", mode, encoding="utf-8") as fd:
            print(content.format(i), file=fd)

    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "--no-gpg-sign", "-m", message], check=True)


@pytest.fixture(scope="session")
def git_repo(tmpdir_factory):
    """Create and populate a test git repo."""

    location = tmpdir_factory.mktemp("data")
    os.chdir(location)

    # Create the repo and add some files
    subprocess.run(["git", "init"], check=True)
    add_to_repo(0, 10, "Testing")

    # Create a branch and add some files
    subprocess.run(["git", "checkout", "-b", "wrapper"], check=True)
    add_to_repo(20, 30, "Commit to wrapper branch")
    add_to_repo(
        100,
        105,
        "Commit wrapped ifdef files",
        extension=".F90",
        content=dedent(
            """\
                #ifdef MYIFDEF
                abc {}
                #endif
                """
        ),
    )

    subprocess.run(["git", "checkout", "main"], check=True)

    subprocess.run(["git", "checkout", "-b", "new_ifdefs"], check=True)

    # Add something that uses a retired ifdef
    add_to_repo(
        110,
        115,
        "Commit new ifdefs",
        extension=".F90",
        content=dedent(
            """\
                    /* Program */
                    #ifdef NOUSE
                    abc {}
                    #endif
                """
        ),
    )

    # Create a branch from main and overwrite some things
    subprocess.run(["git", "checkout", "main"], check=True)
    subprocess.run(["git", "checkout", "-b", "overwrite"], check=True)
    add_to_repo(0, 10, "Overwriting", "at")

    # Switch back to the main branch
    subprocess.run(["git", "checkout", "main"], check=True)

    # Add other trunk-like branches, finishing back in main
    for branch in ("stable", "master", "trunk"):
        subprocess.run(["git", "checkout", "-b", branch], check=True)
        subprocess.run(["git", "checkout", "main"], check=True)

    return location


class TestMain:
    """Test the main check_idef program."""

    def test_not_dev_branch(self, git_repo, capsys):
        """Test error if not on a development branch."""

        subprocess.run(["git", "checkout", "main"], check=True)

        with pytest.raises(SystemExit) as err:
            main([".", "file1"])
        assert err.value.code == 10

        captured = capsys.readouterr()
        assert "Not a development branch" in captured.out

    def test_wrapped_ifdef_branch(self, git_repo, caplog):
        """Test command with a wrapped file."""

        subprocess.run(["git", "checkout", "wrapper"], check=True)

        caplog.clear()

        with pytest.raises(SystemExit) as err:
            with caplog.at_level(logging.INFO):
                main([".", "file1"])
        assert err.value.code == 1

        assert "found 5 files with wrapping ifdefs" in " ".join(caplog.messages)

        subprocess.run(["git", "checkout", "main"], check=True)

    def test_ifdef_branch(self, git_repo, caplog):
        """Test command with a valid ifdef."""

        subprocess.run(["git", "checkout", "new_ifdefs"], check=True)

        caplog.clear()

        with caplog.at_level(logging.INFO):
            main([".", "file1"])

        assert "no problems found" in " ".join(caplog.messages)

        subprocess.run(["git", "checkout", "main"], check=True)

    def test_retired_ifdefs(self, git_repo, caplog):
        """Test command with an retired ifdef."""

        with open("retired.txt", "wt", encoding="utf-8") as fd:
            print("NOUSE", file=fd)

        subprocess.run(["git", "checkout", "new_ifdefs"], check=True)

        caplog.clear()

        with pytest.raises(SystemExit) as err:
            with caplog.at_level(logging.INFO):
                main([".", "retired.txt"])
        assert err.value.code == 1

        assert "found 1 retired macros in" in " ".join(caplog.messages)

        subprocess.run(["git", "checkout", "main"], check=True)
