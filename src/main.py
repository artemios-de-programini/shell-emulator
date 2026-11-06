"""Emulator of a UNIX-like command line (single module build).

The module keeps the original implementation of the project: the
command line lexer, the command implementations, the in-memory
virtual file system, the shell dispatcher, the tkinter front end
and the entry point.
"""

import argparse
import base64
import json
import calendar
import datetime
import os
import re
import sys
import tkinter as tk


# ======================================================================
# state.py
# ======================================================================
# Mutable state shared by the shell and its commands.
#
# The state keeps the working directory, the environment of the host system
# and the root of the virtual file system.  Keeping it in a separate module
# lets commands and the user interface depend on the session data without
# importing each other.

DIR_SEPARATOR = "/"


class ShellState:
    """Working directory, environment and file system of one session."""

    def __init__(self, root=None, cwd=None, environ=None, vfs_path=""):
        """Create a session state with an optional virtual file system."""
        self.root = root
        self.cwd = list(cwd) if cwd else []
        self.environ = dict(environ) if environ else {}
        self.vfs_path = vfs_path
        self.home = self.environ.get("HOME", DIR_SEPARATOR)

    def cwd_path(self):
        """Return the working directory as an absolute path string."""
        return DIR_SEPARATOR + DIR_SEPARATOR.join(self.cwd)


# ======================================================================
# lexer.py
# ======================================================================
# Lexical analysis of command lines typed into the emulator.
#
# The lexer splits a command line into words the way a POSIX shell does.
# Words are separated by spaces and tabs, single quotes keep their text
# verbatim, double quotes keep the text but still expand variables, and a
# backslash escapes the next character.  Variables use the ``$NAME`` and
# ``${NAME}`` forms and are taken from the environment of the host system.

VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NOT_FOUND = -1
WORD_SEPARATORS = " \t"
SINGLE_QUOTE = "'"
DOUBLE_QUOTE = '"'
BACKSLASH = "\\"
DOLLAR = "$"
BRACE_OPEN = "{"
BRACE_CLOSE = "}"


class LexerError(Exception):
    """Raised when a command line cannot be split into words."""


def expand_variables(text, environ):
    """Replace every ``$NAME`` and ``${NAME}`` in text with its value."""
    result = []
    position = 0
    while position < len(text):
        char = text[position]
        if char != DOLLAR:
            result.append(char)
            position += 1
            continue
        name, position = _read_name(text, position + 1)
        result.append(environ.get(name, "") if name else DOLLAR)
    return "".join(result)


def split_words(line, environ=None):
    """Split one command line into words, expanding variables."""
    environment = os.environ if environ is None else environ
    words = []
    current = []
    in_word = False
    position = 0
    while position < len(line):
        char = line[position]
        if char in WORD_SEPARATORS:
            if in_word:
                words.append("".join(current))
                current = []
            in_word = False
            position += 1
            continue
        text, position = _read_word_piece(line, position, environment)
        current.append(text)
        in_word = True
    if in_word:
        words.append("".join(current))
    return words


def _read_word_piece(line, position, environ):
    """Read one piece of a word and return it with the next position."""
    char = line[position]
    if char == SINGLE_QUOTE:
        return _read_single_quoted(line, position + 1)
    if char == DOUBLE_QUOTE:
        return _read_double_quoted(line, position + 1, environ)
    if char == BACKSLASH:
        return _read_escaped(line, position)
    if char == DOLLAR:
        name, new_position = _read_name(line, position + 1)
        value = environ.get(name, "") if name else DOLLAR
        return value, new_position
    return char, position + 1


def _read_name(text, position):
    """Read a variable name at position and return it with the new index."""
    if position < len(text) and text[position] == BRACE_OPEN:
        end = text.find(BRACE_CLOSE, position + 1)
        if end == NOT_FOUND:
            raise LexerError("unterminated ${...} expression")
        return text[position + 1:end], end + 1
    match = VARIABLE_NAME.match(text, position)
    if not match:
        return "", position
    return match.group(0), match.end()


def _read_single_quoted(line, position):
    """Read a single quoted fragment, starting after the opening quote."""
    end = line.find(SINGLE_QUOTE, position)
    if end == NOT_FOUND:
        raise LexerError("unterminated single quote")
    return line[position:end], end + 1


def _read_double_quoted(line, position, environ):
    """Read a double quoted fragment, expanding variables inside it."""
    result = []
    while position < len(line):
        char = line[position]
        if char == DOUBLE_QUOTE:
            return "".join(result), position + 1
        if char == BACKSLASH:
            text, position = _read_escaped(line, position)
            result.append(text)
            continue
        if char == DOLLAR:
            name, position = _read_name(line, position + 1)
            result.append(environ.get(name, "") if name else DOLLAR)
            continue
        result.append(char)
        position += 1
    raise LexerError("unterminated double quote")


def _read_escaped(line, position):
    """Read the character protected by a backslash at position."""
    if position + 1 >= len(line):
        raise LexerError("trailing backslash")
    return line[position + 1], position + 2


# ======================================================================
# commands.py
# ======================================================================
# Command implementations of the shell emulator.
#
# Every command receives the current session state and the list of its
# arguments, and returns the text that the emulator has to display.  Errors
# are reported by raising :class:`CommandError`; the shell adds the command
# name to the message, which keeps the output close to the behaviour of
# real UNIX tools.

FILE_MODE = "-"
DIRECTORY_MODE = "d"
LONG_ENTRY = "{mode} {size:>7} {name}"
EMPTY_OUTPUT = ""
CD_MAX_ARGS = 1
ONE_ARGUMENT = 1
CAL_MAX_ARGS = 2
MONTH_MIN = 1
MONTH_MAX = 12
YEAR_MIN = 1
YEAR_MAX = 9999
BYTES_PER_KIB = 1024.0
SIZE_UNITS = ("B", "K", "M", "G")
LS_FLAGS = ("-l",)
DU_FLAGS = ("-a", "-h")
MKDIR_FLAGS = ("-p",)
NO_FLAGS = ()


class CommandError(Exception):
    """Raised when a command cannot be executed as requested."""


def cmd_ls(state, args):
    """List the content of directories."""
    flags, operands = _parse_flags(args, LS_FLAGS)
    if not operands:
        operands = [CURRENT_DIR]
    long_format = "-l" in flags
    lines = []
    for operand in operands:
        lines.extend(_list_operand(state, operand, long_format))
    return "\n".join(lines)


def cmd_cd(state, args):
    """Change the working directory of the session."""
    if len(args) > CD_MAX_ARGS:
        raise CommandError("too many arguments")
    target = args[0] if args else HOME_DIR
    try:
        parts, node = _lookup(state, target)
    except PathNotFound:
        raise CommandError(f"no such file or directory: {target}")
    except NotADirectory:
        raise CommandError(f"not a directory: {target}")
    if not node.is_dir:
        raise CommandError(f"not a directory: {target}")
    state.cwd = parts
    return EMPTY_OUTPUT


def cmd_cat(state, args):
    """Print the content of files."""
    if not args:
        raise CommandError("missing operand")
    chunks = []
    for target in args:
        chunks.append(_cat_file(state, target))
    return "".join(chunks)


def cmd_cal(state, args):
    """Print a calendar for a month, a year or the current month."""
    today = datetime.date.today()
    if not args:
        return calendar.month(today.year, today.month).rstrip()
    if len(args) == ONE_ARGUMENT:
        year = _read_number(args[0], "year")
        _check_range(year, YEAR_MIN, YEAR_MAX, "year")
        return calendar.calendar(year).rstrip()
    if len(args) > CAL_MAX_ARGS:
        raise CommandError("too many arguments")
    month = _read_number(args[0], "month")
    year = _read_number(args[1], "year")
    _check_range(month, MONTH_MIN, MONTH_MAX, "month")
    _check_range(year, YEAR_MIN, YEAR_MAX, "year")
    return calendar.month(year, month).rstrip()


def cmd_du(state, args):
    """Report the size of directories and, optionally, of files."""
    flags, operands = _parse_flags(args, DU_FLAGS)
    if not operands:
        operands = [CURRENT_DIR]
    show_files = "-a" in flags
    human = "-h" in flags
    lines = []
    for operand in operands:
        lines.extend(_du_operand(state, operand, show_files, human))
    return "\n".join(lines)


def _lookup(state, target):
    """Resolve a path inside the tree of the current session."""
    return resolve(state.root, target, state.cwd, state.home)


def cmd_mkdir(state, args):
    """Create directories in the virtual file system."""
    flags, operands = _parse_flags(args, MKDIR_FLAGS)
    if not operands:
        raise CommandError("missing operand")
    parents = "-p" in flags
    for operand in operands:
        _make_directory(state, operand, parents)
    return EMPTY_OUTPUT


def cmd_rmdir(state, args):
    """Remove empty directories from the virtual file system."""
    _, operands = _parse_flags(args, NO_FLAGS)
    if not operands:
        raise CommandError("missing operand")
    for operand in operands:
        _remove_directory(state, operand)
    return EMPTY_OUTPUT


def _parse_flags(args, allowed):
    """Split arguments into known flags and operands."""
    flags = []
    operands = []
    for argument in args:
        if argument.startswith("-") and argument not in (None, "-"):
            if argument not in allowed:
                raise CommandError(f"invalid option -- '{argument}'")
            flags.append(argument)
            continue
        operands.append(argument)
    return flags, operands


def _list_operand(state, operand, long_format):
    """Return the lines of one ls operand."""
    try:
        _, node = _lookup(state, operand)
    except PathNotFound:
        raise CommandError(
            f"cannot access '{operand}': No such file or directory")
    except NotADirectory:
        raise CommandError(f"cannot access '{operand}': Not a directory")
    if not node.is_dir:
        return [_format_entry(node, long_format)]
    return [_format_entry(node.children[name], long_format)
            for name in sorted(node.children)]


def _format_entry(node, long_format):
    """Format one directory entry of the ls command."""
    name = node.name + DIR_SEPARATOR if node.is_dir else node.name
    if not long_format:
        return name
    mode = DIRECTORY_MODE if node.is_dir else FILE_MODE
    return LONG_ENTRY.format(mode=mode, size=node.size(), name=name)


def _cat_file(state, target):
    """Return the content of one file of the cat command."""
    try:
        _, node = _lookup(state, target)
    except PathNotFound:
        raise CommandError(f"{target}: No such file or directory")
    except NotADirectory:
        raise CommandError(f"{target}: Not a directory")
    if node.is_dir:
        raise CommandError(f"{target}: Is a directory")
    return node.content


def _read_number(text, name):
    """Convert a numeric command argument to an integer."""
    try:
        return int(text)
    except ValueError:
        raise CommandError(f"invalid {name}: {text}")


def _check_range(value, low, high, name):
    """Check that a number belongs to the closed interval."""
    if value < low or value > high:
        raise CommandError(f"{name} out of range: {value}")


def _human_size(size):
    """Convert a size in bytes to a short human readable form."""
    value = float(size)
    for unit in SIZE_UNITS[:-1]:
        if value < BYTES_PER_KIB:
            return f"{value:.0f}{unit}"
        value /= BYTES_PER_KIB
    return f"{value:.0f}{SIZE_UNITS[-1]}"


def _size_line(size, path, human):
    """Format one line of the du output."""
    value = _human_size(size) if human else str(size)
    return f"{value}\t{path}"


def _du_entries(node, path, show_files, human):
    """Collect the size lines of a node and of its subdirectories."""
    lines = []
    if not node.is_dir:
        return [_size_line(node.size(), path, human)]
    for name in sorted(node.children):
        child = node.children[name]
        child_path = join_path(path, name)
        if child.is_dir:
            lines.extend(_du_entries(child, child_path, show_files, human))
        elif show_files:
            lines.append(_size_line(child.size(), child_path, human))
    lines.append(_size_line(node.size(), path, human))
    return lines


def _du_operand(state, operand, show_files, human):
    """Return the lines of one du operand."""
    try:
        parts, node = _lookup(state, operand)
    except PathNotFound:
        raise CommandError(
            f"cannot access '{operand}': No such file or directory")
    except NotADirectory:
        raise CommandError(f"cannot access '{operand}': Not a directory")
    path = DIR_SEPARATOR + DIR_SEPARATOR.join(parts)
    return _du_entries(node, path, show_files, human)


def _make_directory(state, target, parents):
    """Create one directory, optionally together with its parents."""
    if not target:
        raise CommandError(
            "cannot create directory '': No such file or directory")
    parts = split_path(target, state.cwd, state.home)
    if not parts:
        raise CommandError(
            f"cannot create directory '{target}': File exists")
    node = state.root
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        child = node.children.get(part)
        if child is None:
            if not last and not parents:
                raise CommandError(
                    f"cannot create directory '{target}': "
                    "No such file or directory")
            node = node.add_directory(part)
            continue
        if not child.is_dir:
            raise CommandError(
                f"cannot create directory '{target}': Not a directory")
        if last and not parents:
            raise CommandError(
                f"cannot create directory '{target}': File exists")
        node = child


def _remove_directory(state, target):
    """Remove one empty directory from the tree."""
    if not target:
        raise CommandError(
            "failed to remove '': No such file or directory")
    parts = split_path(target, state.cwd, state.home)
    if not parts:
        raise CommandError(
            f"failed to remove '{target}': Device or resource busy")
    try:
        parent = node_at(state.root, parts[:-1])
    except PathNotFound:
        raise CommandError(
            f"failed to remove '{target}': No such file or directory")
    child = parent.children.get(parts[-1])
    if child is None:
        raise CommandError(
            f"failed to remove '{target}': No such file or directory")
    if not child.is_dir:
        raise CommandError(
            f"failed to remove '{target}': Not a directory")
    if child.children:
        raise CommandError(
            f"failed to remove '{target}': Directory not empty")
    parent.remove_child(parts[-1])
COMMANDS = {
    "ls": cmd_ls,
    "cd": cmd_cd,
    "cat": cmd_cat,
    "cal": cmd_cal,
    "du": cmd_du,
    "mkdir": cmd_mkdir,
    "rmdir": cmd_rmdir,
}


# ======================================================================
# config.py
# ======================================================================
# Debug description of all startup parameters of the emulator.
#
# Stage 2 requires the emulator to print every given parameter at startup.
# The description is written to the standard output and is also shown in
# the window of the graphical interface, so a user always sees which
# virtual file system and which startup script were selected.

TITLE = "Emulator configuration"
PARAMETER_TEMPLATE = "  {name:<8} {value}"
NOT_SPECIFIED = "<not specified>"
ABSENT = "missing"
PRESENT = "ok"
DIRECTORY_KIND = "directory"
FILE_KIND = "file"
MODE_GUI = "GUI"
MODE_HEADLESS = "headless"
ENTRIES_TEMPLATE = "{files} files, {directories} directories"


def describe(vfs_path, script_path, headless=False, root=None):
    """Return a multi-line dump of the emulator parameters."""
    mode = MODE_HEADLESS if headless else MODE_GUI
    lines = [TITLE]
    lines.append(_parameter("vfs", _describe_vfs(vfs_path)))
    lines.append(_parameter("script", _describe_script(script_path)))
    lines.append(_parameter("mode", mode))
    if root is not None:
        lines.append(_parameter("entries", _describe_tree(root)))
    return "\n".join(lines)


def _parameter(name, value):
    """Format one parameter line of the debug dump."""
    return PARAMETER_TEMPLATE.format(name=name, value=value)


def _describe_tree(root):
    """Describe the number of files and directories of the loaded tree."""
    return ENTRIES_TEMPLATE.format(
        files=count_files(root),
        directories=count_directories(root),
    )


def _describe_vfs(vfs_path):
    """Describe the directory that is used as the virtual file system."""
    if not vfs_path:
        return NOT_SPECIFIED
    absolute = os.path.abspath(vfs_path)
    if not os.path.exists(absolute):
        return f"{absolute} [{ABSENT}]"
    if not os.path.isdir(absolute):
        return f"{absolute} [{FILE_KIND}]"
    return f"{absolute} [{DIRECTORY_KIND}]"


def _describe_script(script_path):
    """Describe the startup script of the emulator."""
    if not script_path:
        return NOT_SPECIFIED
    absolute = os.path.abspath(script_path)
    if not os.path.exists(absolute):
        return f"{absolute} [{ABSENT}]"
    if not os.path.isfile(absolute):
        return f"{absolute} [{DIRECTORY_KIND}]"
    return f"{absolute} [{PRESENT}]"


# ======================================================================
# vfs.py
# ======================================================================
# Virtual file system that lives completely in memory.
#
# The tree is built once from a directory of the host system.  After that,
# every operation works with the in-memory nodes only: the source
# directory is never modified and is never read again.  A missing or
# broken source directory is reported with :class:`VfsError`.

ROOT_NAME = "/"
PARENT_DIR = ".."
CURRENT_DIR = "."
HOME_DIR = "~"
TEXT_ENCODING = "utf-8"
JSON_EXTENSION = ".json"


class VfsError(Exception):
    """Raised when the virtual file system cannot be loaded."""


class PathError(Exception):
    """Raised when a path given by the user cannot be resolved."""


class PathNotFound(PathError):
    """Raised when a component of a path does not exist."""


class NotADirectory(PathError):
    """Raised when a component of a path is a file, not a directory."""


class VfsNode:
    """A single file or directory of the virtual file system."""

    def __init__(self, name, is_dir=False, content=""):
        """Create a node with a name, a type and optional file content."""
        self.name = name
        self.is_dir = is_dir
        self.content = content
        self.children = {}

    def size(self):
        """Return the size of the node in bytes."""
        if not self.is_dir:
            return len(self.content.encode(TEXT_ENCODING))
        return sum(child.size() for child in self.children.values())

    def add_directory(self, name):
        """Create an empty child directory and return it."""
        child = VfsNode(name, is_dir=True)
        self.children[name] = child
        return child

    def remove_child(self, name):
        """Remove a child node by name."""
        del self.children[name]


def load_tree(host_path):
    """Build the virtual file system from a directory or a JSON description."""
    if not host_path:
        raise VfsError("path to the virtual file system is empty")
    absolute = os.path.abspath(host_path)
    if not os.path.exists(absolute):
        raise VfsError(f"path not found: {absolute}")
    if is_json_path(absolute):
        return load_json_tree(absolute)
    if not os.path.isdir(absolute):
        raise VfsError(f"not a directory: {absolute}")
    root = VfsNode(ROOT_NAME, is_dir=True)
    _load_directory(root, absolute)
    return root


def is_json_path(path):
    """Tell whether the given path points to a JSON description of the tree."""
    return os.path.splitext(path)[1].lower() == JSON_EXTENSION


def load_json_tree(json_path):
    """Build the virtual file system from a JSON description of the tree."""
    try:
        with open(json_path, encoding=TEXT_ENCODING) as handle:
            data = json.load(handle)
    except OSError as exc:
        raise VfsError(f"cannot read file: {json_path} ({exc})")
    except ValueError as exc:
        raise VfsError(f"invalid JSON: {json_path} ({exc})")
    if not isinstance(data, dict):
        raise VfsError(f"JSON root must be an object: {json_path}")
    root = VfsNode(ROOT_NAME, is_dir=True)
    _load_json_directory(root, data, json_path)
    return root


def _load_json_directory(node, data, json_path):
    """Fill one directory node from an object of the JSON description."""
    for name in sorted(data):
        value = data[name]
        if isinstance(value, dict):
            child = VfsNode(name, is_dir=True)
            _load_json_directory(child, value, json_path)
        elif isinstance(value, str):
            content = _decode_content(value, json_path)
            child = VfsNode(name, is_dir=False, content=content)
        else:
            raise VfsError(f"unsupported value for '{name}' in {json_path}")
        node.children[name] = child


def _decode_content(value, json_path):
    """Decode the content of one file stored in the JSON description."""
    try:
        return base64.b64decode(value).decode(TEXT_ENCODING)
    except (ValueError, UnicodeDecodeError) as exc:
        raise VfsError(f"cannot decode content in {json_path} ({exc})")


def split_path(raw_path, cwd, home):
    """Turn a user supplied path into normalised parts from the root."""
    text = raw_path
    if text == HOME_DIR or text.startswith(HOME_DIR + DIR_SEPARATOR):
        text = home + text[len(HOME_DIR):]
    parts = [] if text.startswith(DIR_SEPARATOR) else list(cwd)
    for part in text.split(DIR_SEPARATOR):
        if part in (CURRENT_DIR, ""):
            continue
        if part == PARENT_DIR:
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return parts


def lookup(root, parts):
    """Return the node at parts and the index of a missing component."""
    node = root
    for index, part in enumerate(parts):
        if not node.is_dir:
            return node, index
        child = node.children.get(part)
        if child is None:
            return node, index
        node = child
    return node, None


def node_at(root, parts):
    """Return the node at parts or raise :class:`PathNotFound`."""
    node = root
    for part in parts:
        if not node.is_dir or part not in node.children:
            raise PathNotFound(part)
        node = node.children[part]
    return node


def resolve(root, raw_path, cwd, home):
    """Resolve a user path and return its parts together with the node."""
    parts = split_path(raw_path, cwd, home)
    node, missing = lookup(root, parts)
    if missing is None:
        return parts, node
    if not node.is_dir:
        raise NotADirectory(raw_path)
    raise PathNotFound(raw_path)


def join_path(base, name):
    """Join an absolute directory path and a name."""
    if base == DIR_SEPARATOR:
        return DIR_SEPARATOR + name
    return base + DIR_SEPARATOR + name


def count_files(node):
    """Return the number of files in the subtree of the node."""
    if not node.is_dir:
        return 1
    return sum(count_files(child) for child in node.children.values())


def count_directories(node):
    """Return the number of directories in the subtree of the node."""
    if not node.is_dir:
        return 0
    total = 0
    for child in node.children.values():
        if child.is_dir:
            total += 1 + count_directories(child)
    return total


def _load_directory(node, host_path):
    """Load the content of one directory of the host into a node."""
    try:
        names = sorted(os.listdir(host_path))
    except OSError as exc:
        raise VfsError(f"cannot read directory: {host_path} ({exc})")
    for name in names:
        child_path = os.path.join(host_path, name)
        if os.path.isdir(child_path):
            child = VfsNode(name, is_dir=True)
            _load_directory(child, child_path)
        else:
            content = _read_file(child_path)
            child = VfsNode(name, is_dir=False, content=content)
        node.children[name] = child


def _read_file(path):
    """Read a text file or raise a VFS error for invalid content."""
    try:
        with open(path, encoding=TEXT_ENCODING) as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise VfsError(f"invalid text format: {path} ({exc.reason})")
    except OSError as exc:
        raise VfsError(f"cannot read file: {path} ({exc})")


# ======================================================================
# shell.py
# ======================================================================
# Command dispatch and script execution for the shell emulator.
#
# The shell owns the command registry, turns a raw command line into words,
# runs the matching command and remembers whether the last command failed.
# The status is used by startup scripts, which must stop at the first error.

SHELL_NAME = "emulator"
USER_NAME = "user"
PROMPT_TEMPLATE = "{user}@emulator:{path}$ "
EXIT_COMMAND = "exit"
COMMENT_PREFIX = "#"
EXIT_CODE_MIN = 0
EXIT_CODE_MAX = 255
STATUS_OK = 0
STATUS_ERROR = 1


class ExitRequest(Exception):
    """Raised when the user asks to close the emulator."""

    def __init__(self, code=STATUS_OK):
        """Remember the exit code requested by the user."""
        super().__init__("exit")
        self.code = code


class Shell:
    """Dispatch command lines and keep the status of the last command."""

    def __init__(self, session):
        """Store the session state and build the command registry."""
        self.session = session
        self.status = STATUS_OK
        self.registry = dict(COMMANDS)

    def prompt(self):
        """Return the prompt string for the current working directory."""
        return PROMPT_TEMPLATE.format(user=USER_NAME,
                                      path=self.session.cwd_path())

    def execute(self, line):
        """Run one command line and return the text to display."""
        try:
            words = split_words(line, self.session.environ)
        except LexerError as exc:
            self.status = STATUS_ERROR
            return f"{SHELL_NAME}: {exc}"
        if not words:
            self.status = STATUS_OK
            return ""
        name = words[0]
        args = words[1:]
        try:
            if name == EXIT_COMMAND:
                raise ExitRequest(self._exit_code(args))
            handler = self.registry.get(name)
            if handler is None:
                raise CommandError("command not found")
            result = handler(self.session, args)
        except CommandError as exc:
            self.status = STATUS_ERROR
            return f"{name}: {exc}"
        self.status = STATUS_OK
        return result

    def run_script(self, path):
        """Yield prompt, command and output until the script ends or fails."""
        with open(path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith(COMMENT_PREFIX):
                    continue
                prompt = self.prompt()
                output = self.execute(line)
                yield prompt, line, output
                if self.status != STATUS_OK:
                    break

    def _exit_code(self, args):
        """Return the exit code requested by an exit command."""
        if not args:
            return STATUS_OK
        try:
            code = int(args[0])
        except ValueError:
            raise CommandError(f"invalid exit code: {args[0]}")
        if code < EXIT_CODE_MIN or code > EXIT_CODE_MAX:
            raise CommandError(f"exit code out of range: {code}")
        return code


# ======================================================================
# gui.py
# ======================================================================
# Tkinter front end of the shell emulator.
#
# The window shows a terminal-like transcript: the prompt, the commands
# typed by the user and the answers of the commands.  A startup script is
# played back command by command, so the window imitates a real dialogue
# with the user.  All command logic lives in :mod:`shell`, the interface
# only renders text and forwards key presses.

WINDOW_GEOMETRY = "760x520"
WINDOW_MIN_WIDTH = 640
WINDOW_MIN_HEIGHT = 400
WINDOW_TITLE = "Shell Emulator - VFS: {name}"
TEXT_FONT = ("Courier New", 12)
COLOR_BACKGROUND = "#101010"
COLOR_FOREGROUND = "#33FF66"
COLOR_CURSOR = "#FFFFFF"
SCRIPT_DELAY_MS = 250
BANNER = "UNIX-like shell emulator. Type 'exit' to quit.\n"
SCRIPT_FAILED = "script: stopped at command '{line}'"


class EmulatorWindow:
    """Graphical REPL that renders a session of :class:`shell.Shell`."""

    def __init__(self, root, session, title_name, banner="", script_path=""):
        """Create the widgets and start the initial dialogue."""
        self.root = root
        self.session = session
        self.steps = None
        self.root.title(WINDOW_TITLE.format(name=title_name))
        self.root.geometry(WINDOW_GEOMETRY)
        self.root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.text = tk.Text(
            root,
            bg=COLOR_BACKGROUND,
            fg=COLOR_FOREGROUND,
            insertbackground=COLOR_CURSOR,
            font=TEXT_FONT,
            borderwidth=0,
            highlightthickness=0,
        )
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.bind("<Return>", self.on_enter)
        self.write(BANNER)
        if banner:
            self.write(banner + "\n")
        if script_path:
            self.steps = self.session.run_script(script_path)
            self.root.after(SCRIPT_DELAY_MS, self.run_next_step)
        else:
            self.render_prompt()

    def write(self, text):
        """Append text to the transcript and scroll to the end."""
        self.text.insert(tk.END, text)
        self.text.see(tk.END)

    def write_output(self, text):
        """Append the answer of a command and end it with a new line."""
        if not text:
            return
        if text.endswith("\n"):
            self.write(text)
            return
        self.write(text + "\n")

    def render_prompt(self):
        """Show a prompt and put the caret after it."""
        self.write(self.session.prompt())
        self.text.mark_set("insert", tk.END)

    def run_next_step(self):
        """Play the next command of the startup script."""
        try:
            prompt, line, output = next(self.steps)
        except StopIteration:
            self.finish_script()
            return
        except OSError as exc:
            self.steps = None
            self.write(f"script: {exc}\n")
            self.render_prompt()
            return
        except ExitRequest as request:
            self.root.destroy()
            return
        self.write(f"{prompt}{line}\n")
        self.write_output(output)
        if self.session.status != STATUS_OK:
            self.write(SCRIPT_FAILED.format(line=line) + "\n")
            self.finish_script()
            return
        self.root.after(SCRIPT_DELAY_MS, self.run_next_step)

    def finish_script(self):
        """Stop playing the startup script and wait for the user."""
        self.steps = None
        self.render_prompt()

    def on_enter(self, event):
        """Run the command typed on the current line."""
        line = self.text.get("insert linestart", "end-1c")
        prompt = self.session.prompt()
        command = line[len(prompt):] if line.startswith(prompt) else line
        self.write("\n")
        try:
            output = self.session.execute(command)
        except ExitRequest as request:
            self.root.destroy()
            return "break"
        self.write_output(output)
        self.render_prompt()
        return "break"


# ======================================================================
# main.py
# ======================================================================
# Entry point of the UNIX-like shell emulator.
#
# The module parses the command line parameters, prints the debug dump of
# the configuration and starts either the graphical interface or the
# headless mode that is used by the automatic tests.

PROGRAM_NAME = "shell-emulator"
DEFAULT_VFS_PATH = "tests/vfs_files.json"
SCRIPT_STOPPED = "script: stopped at command '{line}'"
EXIT_OK = 0
EXIT_SCRIPT_ERROR = 1
EXIT_USAGE = 2
EXIT_VFS_ERROR = 3


def parse_args(argv=None):
    """Parse the command line parameters of the emulator."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Emulator of a UNIX-like command line.",
    )
    parser.add_argument(
        "--vfs",
        default=DEFAULT_VFS_PATH,
        help="path to the directory used as the virtual file system",
    )
    parser.add_argument(
        "--script",
        default="",
        help="path to the startup script with emulator commands",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without the graphical interface",
    )
    return parser.parse_args(argv)


def build_session(vfs_path, root=None):
    """Create the session state for the given VFS path and tree."""
    environ = dict(os.environ)
    environ.setdefault("HOME", os.path.expanduser("~"))
    return ShellState(root=root, cwd=[], environ=environ,
                            vfs_path=vfs_path)


def run_headless(session, script_path):
    """Run the emulator without a GUI and return the exit code."""
    try:
        if script_path:
            return _run_script(session, script_path)
        return _run_stdin(session)
    except ExitRequest as request:
        return request.code


def _print_output(text):
    """Write the answer of a command to the standard output."""
    if not text:
        return
    if text.endswith("\n"):
        sys.stdout.write(text)
        return
    print(text)


def _run_script(session, script_path):
    """Execute a startup script and print the whole dialogue."""
    try:
        for prompt, line, output in session.run_script(script_path):
            print(f"{prompt}{line}")
            _print_output(output)
            if session.status != STATUS_OK:
                print(SCRIPT_STOPPED.format(line=line))
                return EXIT_SCRIPT_ERROR
    except OSError as exc:
        print(f"{PROGRAM_NAME}: {exc}", file=sys.stderr)
        return EXIT_SCRIPT_ERROR
    return EXIT_OK


def _run_stdin(session):
    """Read commands from the standard input until end of file."""
    for raw_line in sys.stdin:
        command = raw_line.rstrip("\n")
        print(f"{session.prompt()}{command}")
        output = session.execute(command)
        _print_output(output)
    return EXIT_OK


def run_gui(session, title_name, description, script_path):
    """Start the graphical interface and return its exit code."""
    import tkinter as tk

    import gui

    root = tk.Tk()
    EmulatorWindow(root, session, title_name, description, script_path)
    root.mainloop()
    return EXIT_OK


def title_name(vfs_path):
    """Return the short name of the virtual file system directory."""
    normalized = os.path.normpath(vfs_path)
    return os.path.basename(normalized) or normalized


def main(argv=None):
    """Start the emulator with the given command line parameters."""
    args = parse_args(argv)
    try:
        root = load_tree(args.vfs)
    except VfsError as exc:
        print(describe(args.vfs, args.script, args.headless))
        print(f"{PROGRAM_NAME}: VFS error: {exc}", file=sys.stderr)
        return EXIT_VFS_ERROR
    description = describe(args.vfs, args.script, args.headless, root)
    print(description)
    session = Shell(build_session(args.vfs, root))
    if args.headless:
        return run_headless(session, args.script)
    return run_gui(session, title_name(args.vfs), description, args.script)
if __name__ == "__main__":
    sys.exit(main())
