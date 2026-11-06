"""Emulator of a UNIX-like command line (single module build).

The module keeps the original implementation of the project: the
command line lexer, the command implementations, the in-memory
virtual file system, the shell dispatcher, the tkinter front end
and the entry point.
"""

import os
import re
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
# typed by the user and the answers of the commands.  All command logic
# lives in :mod:`shell`, so the interface only renders text and forwards
# key presses.

WINDOW_GEOMETRY = "760x500"
WINDOW_TITLE = "Shell Emulator - VFS: {name}"
TEXT_FONT = ("Courier New", 12)
COLOR_BACKGROUND = "#101010"
COLOR_FOREGROUND = "#33FF66"
COLOR_CURSOR = "#FFFFFF"
BANNER = "UNIX-like shell emulator. Type 'exit' to quit.\n"


class EmulatorWindow:
    """Graphical REPL that renders a session of :class:`shell.Shell`."""

    def __init__(self, root, session, title_name, banner=""):
        """Create the widgets and show the welcome banner."""
        self.root = root
        self.session = session
        self.root.title(WINDOW_TITLE.format(name=title_name))
        self.root.geometry(WINDOW_GEOMETRY)
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
        self.render_prompt()

    def write(self, text):
        """Append text to the transcript and scroll to the end."""
        self.text.insert(tk.END, text)
        self.text.see(tk.END)

    def render_prompt(self):
        """Show a prompt and put the caret after it."""
        self.write(self.session.prompt())
        self.text.mark_set("insert", tk.END)

    def on_enter(self, event):
        """Run the command typed on the current line."""
        line = self.text.get("insert linestart", "end-1c")
        prompt = self.session.prompt()
        command = line[len(prompt):] if line.startswith(prompt) else line
        self.write("\n")
        try:
            output = self.session.execute(command)
        except ExitRequest:
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
# Stage 1 starts the graphical REPL.  The emulator keeps the name of the
# virtual file system in the window title and expands environment
# variables of the host system in every command line.

DEFAULT_VFS_PATH = "./vfs_root"
TITLE_NAME = "vfs_root"


def build_session(vfs_path):
    """Create the session state for the given VFS path."""
    environ = dict(os.environ)
    environ.setdefault("HOME", os.path.expanduser("~"))
    return ShellState(root=None, cwd=[], environ=environ,
                            vfs_path=vfs_path)


def main():
    """Start the graphical shell emulator."""
    vfs_path = DEFAULT_VFS_PATH
    session_state = build_session(vfs_path)
    session = Shell(session_state)
    root = tk.Tk()
    EmulatorWindow(root, session, TITLE_NAME)
    root.mainloop()
    return 0
if __name__ == "__main__":
    main()
