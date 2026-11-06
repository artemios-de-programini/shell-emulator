"""Emulator of a UNIX-like command line (single module build).

The module keeps the original implementation of the project: the
command line lexer, the command implementations, the in-memory
virtual file system, the shell dispatcher, the tkinter front end
and the entry point.
"""

import argparse
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


class CommandError(Exception):
    """Raised when a command cannot be executed as requested."""


def stub_answer(name, args):
    """Build the answer of a placeholder command and its arguments."""
    return f"{name}: arguments {args}"


def cmd_ls(state, args):
    """Placeholder for ls: report the name and the arguments."""
    return stub_answer("ls", args)


def cmd_cd(state, args):
    """Placeholder for cd: report the name and the arguments."""
    return stub_answer("cd", args)
COMMANDS = {
    "ls": cmd_ls,
    "cd": cmd_cd,
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


def describe(vfs_path, script_path, headless=False):
    """Return a multi-line dump of the emulator parameters."""
    mode = MODE_HEADLESS if headless else MODE_GUI
    lines = [TITLE]
    lines.append(_parameter("vfs", _describe_vfs(vfs_path)))
    lines.append(_parameter("script", _describe_script(script_path)))
    lines.append(_parameter("mode", mode))
    return "\n".join(lines)


def _parameter(name, value):
    """Format one parameter line of the debug dump."""
    return PARAMETER_TEMPLATE.format(name=name, value=value)


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
        """Yield ``(line, output)`` pairs until the script ends or fails."""
        with open(path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith(COMMENT_PREFIX):
                    continue
                output = self.execute(line)
                yield line, output
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

    def render_prompt(self):
        """Show a prompt and put the caret after it."""
        self.write(self.session.prompt())
        self.text.mark_set("insert", tk.END)

    def run_next_step(self):
        """Play the next command of the startup script."""
        try:
            line, output = next(self.steps)
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
        self.write(f"{self.session.prompt()}{line}\n")
        if output:
            self.write(output + "\n")
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
        if output:
            self.write(output + "\n")
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


def build_session(vfs_path):
    """Create the session state for the given VFS path."""
    environ = dict(os.environ)
    environ.setdefault("HOME", os.path.expanduser("~"))
    return ShellState(root=None, cwd=[], environ=environ,
                            vfs_path=vfs_path)


def run_headless(session, script_path):
    """Run the emulator without a GUI and return the exit code."""
    try:
        if script_path:
            return _run_script(session, script_path)
        return _run_stdin(session)
    except ExitRequest as request:
        return request.code


def _run_script(session, script_path):
    """Execute a startup script and print the whole dialogue."""
    try:
        for line, output in session.run_script(script_path):
            print(f"{session.prompt()}{line}")
            if output:
                print(output)
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
        if output:
            print(output)
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
    description = describe(args.vfs, args.script, args.headless)
    print(description)
    session = Shell(build_session(args.vfs))
    if args.headless:
        return run_headless(session, args.script)
    return run_gui(session, title_name(args.vfs), description, args.script)
if __name__ == "__main__":
    sys.exit(main())
