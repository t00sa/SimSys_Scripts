#!/usr/bin/env python3
# *********************************COPYRIGHT************************************
# (C) Crown copyright Met Office. All rights reserved.
# For further details please refer to the file COPYRIGHT.txt
# which you should have received as part of this distribution.
# *********************************COPYRIGHT************************************
"""
Replacement for the Perl version of check_ifdef.
"""


import sys
import os
import logging
from argparse import ArgumentParser
from pathlib import Path
from typing import List

from git_bdiff import GitInfo, GitBDiff, GitBDiffError


class IfDefChecker:
    """Class which checks files for invalid ifdefs."""

    code_extensions = (".c", ".h", ".f", ".f90", ".f95")

    def __init__(self, branch: Path) -> None:
        self.branch = Path(branch)
        self._retired = []

        # File containing wrapping ifdefs and files containing newly
        # added retired macros
        self._wrapped = []
        self._additions = set([])

    def load_retired(self, source: Path) -> None:
        """Load retired ifdefs into memory.

        Parse a file containing retired ifdef macros, one per line,
        into a list.  This can then be used to determine whether any
        retired ifdefs have been added back in to the codebase.

        :param source: path to the retired file.
        """

        self._retired = []

        for line in source.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line:
                self._retired.append(line)

        logging.debug(
            "loaded %s retired ifdefs from %r", len(self._retired), str(source)
        )

    def wrapped_files(self, diff: List[str]) -> int:
        """Find ifdefs that wrap entire Fortran files.

        Match files where the first line has been changed to insert a
        new preprocessor #if statement.  This is assumed to wrap the
        entire file.  Ignore any other #ifs in diff text.

        :param diff: text of the branch diff
        :returns: number of wrapped files
        """

        self._wrapped = []

        limit = len(diff) - 2
        i = 0

        while i < limit:
            line = diff[i].strip()
            i += 1

            if line.startswith("+++ ") and ".F90" in line:
                hunks = diff[i].split()

                if hunks[2].startswith("+1,") and diff[i + 1].startswith("+#if"):
                    # Change is to the first line and adds a
                    # preprocessor if directive
                    name = line.split()[1]
                    self._wrapped.append(name)
                    logging.debug("wrapped file %r", name)

                i += 1

        logging.info("found %s files with wrapping ifdefs", len(self._wrapped))

        return len(self._wrapped)

    def get_added_files(self, diff: List[str]) -> None:
        """Get added files by parsing git diff output.

        Examine the output from a git diff for file which have had
        lines added to them and yield the path of each file in turn.

        For this to work in a useful way, the git diff should have
        been added with the --no-prefix argument to prevetn the a/ and
        b/ directories from being included in the file paths.

        :param diff: the text output of a git diff

        """

        name = None
        code_file = False

        for line in diff:
            if line.startswith("+++"):
                # Identify the file and its type
                name = Path(line.split()[1])
                code_file = name.suffix.lower() in self.code_extensions

            elif line.startswith("+") and name and code_file:
                # Lines have been added to the current file
                yield name
                name = None
                code_file = False

    def inspect_file(self, source: Path) -> bool:
        """Inspect a file for retired ifdefs.

        Read the contents of the target file, join any cpp
        continuation lines, remove any comments, and then inspect the
        result for ifdef statements.  Check the macros in the
        statements against the retired list and add any matches to the
        global list of macros.

        :param source: path to the file being inspected.
        :return: a boolean indicating whether retired macros have been
            found
        """

        clean = self.clean_text(source.read_text())

        retired = set([])

        for macro in self.find_ifdefs(clean):
            if macro in self._retired:
                # A retired macro has been used
                retired.add(macro)
                logging.debug("found retired macro %r", macro)

        logging.info("found %s retired macros in %s", len(retired), source)

        # Append the set of retired macros in this file to the global
        # set of retired macros from other files
        self._additions |= retired

        return len(retired) == 0

    def clean_text(self, text: str) -> str:
        """Strip out comments and merge preprocessor lines.

        Examine a string containing multiple lines of text and join
        any lines linked by C pre-processor continuation characters
        into a single line.  Next, remove any single line C-style
        comments.  Finally, remove any multi-line C-style comments.

        :param text: the source text
        :return: string containing the cleaned up text
        """

        result = ""
        continuation = False
        block_comment = False

        for line in text.split("\n"):
            if line.endswith("\\"):
                # Remove continuation characters
                line = line.rstrip("\\").rstrip() + " "
                continuation = True

            elif line:
                if continuation:
                    line = line.lstrip()
                line += "\n"

            if (start := line.find("/*")) >= 0:
                # Check for the start of a block comment
                block_comment = True

                if (end := line.find("*/")) > 0:
                    # Block comment is entirely within the line, so
                    # remove the whole lot and replace whitespaces
                    # with a single space
                    line = line[:start].rstrip() + " " + line[end + 2 :].lstrip()
                    block_comment = False

                else:
                    # Remove to the end of the line
                    line = line[:start].rstrip() + "\n"

            elif block_comment:
                # In an on-going multiline block comment
                if (end := line.find("*/")) > 0:
                    # Remove everything up to the start of the block
                    # comment and any trailing whitespace
                    line = line[end + 2 :].lstrip()
                    block_comment = False

                else:
                    # Ignore the entire line
                    continue

            continuation = False
            result += line

        return result.rstrip()

    def find_ifdefs(self, text: str) -> None:
        """Locate all the ifdefs in a text.

        Find all ifdefs and if defined statements in a file and yield
        each macro name up to the caller as it is found.

        :param text: the source text being searched
        :yields: macros used in ifdefs or if defined lines
        """

        for line in text.split("\n"):
            line = line.strip()

            if line.startswith("#ifdef") or line.startswith("#ifndef"):
                # Yield the name of the item being tested
                yield line.split()[1]

            elif (
                line.startswith("#if") or line.startswith("#elif") and "defined" in line
            ):
                # This may have multiple definitions
                yield from self.defined_tokens(line)

    def defined_tokens(self, line: str) -> None:
        """Unpack a line of pre-processor defined keywords.

        Pre-processor lines may contain multiple defined() functions
        separated by boolean operators, so parse a line until all the
        macros have been found, yielding each one as it is found.

        :param line: a single line of text
        :yields: string containing a macro
        """

        definition = False

        for token in line.split():
            if token.startswith("defined"):
                definition = True
                if (start := token.find("(")) > 0:
                    token = token[start + 1 :].rstrip(")")
                    definition = False
                    yield token
            elif definition:
                if token.startswith("("):
                    definition = False
                    yield token[1:].rstrip(")")

    @property
    def errors(self):
        """Whether any error conditions have been found."""

        return self._wrapped or self._additions


def process_arguments(argv):
    """Process comamnd line arguments."""

    parser = ArgumentParser(
        usage="%(prog)s [options] branch retired", description=__doc__
    )

    parser.add_argument(
        "-v", dest="verbose", action="count", help="increase verbose output"
    )

    parser.add_argument("branch", type=Path, help="path to working copy/branch")

    parser.add_argument("retired", type=Path, help="path to file of retired ifdefs")

    args = parser.parse_args(argv)
    args.suite_mode = False

    if args.verbose == 0:
        level = logging.WARNING
    elif args.verbose == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG

    logging.basicConfig(level=level)

    if not args.retired.is_file():
        parser.error("retired ifdef file is not valid")

    if "SOURCE_UM_MIRROR" in os.environ:
        args.branch = Path(os.environ["SOURCE_UM_MIRROR"])
        args.suite_mode = True
        logging.warning("redirecting branch to %r", str(args.branch))

    try:
        info = GitInfo(args.branch)
    except GitBDiffError as err:
        parser.error(str(err))

    if info.is_main():
        # Stop if this is not a development branch
        parser.error("not a development branch")

    return args


def main(argv=None):
    """Main function."""

    args = process_arguments(argv or sys.argv[1:])

    # Create the checker
    checker = IfDefChecker(args.branch)
    checker.load_retired(args.retired)

    # Get the text of the branch diff
    diff_lines = list(GitBDiff().diff(prefix=False))

    checker.wrapped_files(diff_lines)

    for filename in checker.get_added_files(diff_lines):
        # Read the file, sort out comments and continuations
        # find any ifdefs
        checker.inspect_file(filename)

    if checker.errors:
        raise SystemExit(1)

    logging.info("no problems found")


if __name__ == "__main__":

    main()
