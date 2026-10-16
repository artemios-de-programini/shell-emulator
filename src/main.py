import argparse
import calendar
import datetime
import os
import re
import sys
import tkinter as tk

os.environ["TK_SILENCE_DEPRECATION"] = "1"


class VFSNode:
    def __init__(self, name, is_dir=True, content=""):
        self.name = name
        self.is_dir = is_dir
        self.content = content
        self.children = {}


class VirtualFileSystem:
    def __init__(self, host_path):
        self.root = VFSNode("/", is_dir=True)
        if host_path and os.path.exists(host_path):
            self.load_from_host(host_path)

    def load_from_host(self, host_path):
        if not os.path.isdir(host_path):
            return
        for root_dir, dirs, files in os.walk(host_path):
            rel_path = os.path.relpath(root_dir, host_path)
            parent_node = self.get_node_by_rel_path(rel_path)

            for d in dirs:
                parent_node.children[d] = VFSNode(d, is_dir=True)

            for f in files:
                f_path = os.path.join(root_dir, f)
                try:
                    with open(f_path, "r", encoding="utf-8") as file_obj:
                        text = file_obj.read()
                except Exception:
                    text = "[Binary or Unreadable File]"
                parent_node.children[f] = VFSNode(f, is_dir=False, content=text)

    def get_node_by_rel_path(self, rel_path):
        if rel_path in (".", ""):
            return self.root
        parts = rel_path.strip(os.sep).split(os.sep)
        curr = self.root
        for p in parts:
            if p not in curr.children:
                curr.children[p] = VFSNode(p, is_dir=True)
            curr = curr.children[p]
        return curr


class ShellEmulatorGUI:
    def __init__(self, root, vfs_path, script_path):
        self.root = root
        self.vfs_path = vfs_path
        self.script_path = script_path

        try:
            self.vfs = VirtualFileSystem(vfs_path)
        except Exception as e:
            print(f"VFS Loading Error: {e}")
            sys.exit(1)

        self.current_path = []
        vfs_name = os.path.basename(os.path.normpath(vfs_path))
        self.root.title(f"Shell Emulator - VFS: {vfs_name}")
        self.root.geometry("750x500")

        # Основной текстовый виджет
        self.text = tk.Text(
            root, bg="black", fg="#00FF00", insertbackground="white",
            font=("Courier", 12)
        )
        self.text.pack(fill=tk.BOTH, expand=True)

        self.text.bind("<Return>", self.on_enter)
        self.render_prompt()

        if self.script_path:
            self.root.after(300, self.run_script)

    def get_current_node(self):
        curr = self.vfs.root
        for p in self.current_path:
            curr = curr.children[p]
        return curr

    def get_prompt_str(self):
        pwd = "/" + "/".join(self.current_path)
        return f"user@emulator:{pwd}$ "

    def render_prompt(self):
        self.text.insert(tk.END, self.get_prompt_str())
        self.text.see(tk.END)
        self.text.mark_set("insert", tk.END)

    def print_output(self, text):
        self.text.insert(tk.END, text)
        self.text.see(tk.END)

    def expand_env_vars(self, command_str):
        pattern = re.compile(r'\$(\w+)|\$\{(\w+)\}')

        def replace(match):
            var = match.group(1) or match.group(2)
            return os.environ.get(var, "")

        return pattern.sub(replace, command_str)

    def execute_command(self, cmd_line):
        cmd_line = self.expand_env_vars(cmd_line.strip())
        if not cmd_line:
            return True

        parts = cmd_line.split()
        cmd = parts[0]
        args = parts[1:]

        if cmd == "exit":
            sys.exit(0)
        elif cmd == "ls":
            return self.cmd_ls(args)
        elif cmd == "cd":
            return self.cmd_cd(args)
        elif cmd == "cat":
            return self.cmd_cat(args)
        elif cmd == "cal":
            return self.cmd_cal(args)
        elif cmd == "du":
            return self.cmd_du(args)
        elif cmd == "mkdir":
            return self.cmd_mkdir(args)
        elif cmd == "rmdir":
            return self.cmd_rmdir(args)
        else:
            self.print_output(f"Error: unknown command '{cmd}'\n")
            return False

    def cmd_ls(self, args):
        node = self.get_current_node()
        items = sorted(node.children.keys())
        out = [f"{name}/" if node.children[name].is_dir else name for name in items]
        self.print_output("  ".join(out) + "\n" if out else "\n")
        return True

    def cmd_cd(self, args):
        if not args or args[0] == "/":
            self.current_path = []
            return True

        target = args[0]
        if target == "..":
            if self.current_path:
                self.current_path.pop()
            return True

        node = self.get_current_node()
        if target in node.children and node.children[target].is_dir:
            self.current_path.append(target)
            return True
        else:
            self.print_output(f"cd: no such file or directory: {target}\n")
            return False

    def cmd_cat(self, args):
        if not args:
            self.print_output("cat: missing operand\n")
            return False
        node = self.get_current_node()
        target = args[0]
        if target in node.children and not node.children[target].is_dir:
            self.print_output(node.children[target].content + "\n")
            return True
        self.print_output(f"cat: {target}: No such file or directory\n")
        return False

    def cmd_cal(self, args):
        now = datetime.datetime.now()
        cal_str = calendar.month(now.year, now.month)
        self.print_output(cal_str + "\n")
        return True

    def cmd_du(self, args):
        def calculate_size(n):
            if not n.is_dir:
                return len(n.content.encode('utf-8'))
            return sum(calculate_size(c) for c in n.children.values())

        node = self.get_current_node()
        for name, child in node.children.items():
            size = calculate_size(child)
            self.print_output(f"{size}\t{name}\n")
        return True

    def cmd_mkdir(self, args):
        if not args:
            self.print_output("mkdir: missing operand\n")
            return False
        dirname = args[0]
        node = self.get_current_node()
        if dirname in node.children:
            self.print_output(f"mkdir: cannot create directory '{dirname}': File exists\n")
            return False
        node.children[dirname] = VFSNode(dirname, is_dir=True)
        return True

    def cmd_rmdir(self, args):
        if not args:
            self.print_output("rmdir: missing operand\n")
            return False
        dirname = args[0]
        node = self.get_current_node()
        if dirname not in node.children or not node.children[dirname].is_dir:
            self.print_output(f"rmdir: failed to remove '{dirname}': No such directory\n")
            return False
        if node.children[dirname].children:
            self.print_output(f"rmdir: failed to remove '{dirname}': Directory not empty\n")
            return False
        del node.children[dirname]
        return True

    def on_enter(self, event):
        # Получаем последнюю введенную строку
        line = self.text.get("insert linestart", "end-1c")
        prompt = self.get_prompt_str()
        if line.startswith(prompt):
            cmd = line[len(prompt):]
        else:
            cmd = line

        self.print_output("\n")
        self.execute_command(cmd)
        self.render_prompt()
        return "break"

    def run_script(self):
        if not os.path.exists(self.script_path):
            self.print_output(f"Error: Script '{self.script_path}' not found\n")
            return

        with open(self.script_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self.print_output(f"{self.get_prompt_str()}{line}\n")
            success = self.execute_command(line)
            if not success:
                self.print_output("Script stopped due to an error.\n")
                break


def parse_args():
    parser = argparse.ArgumentParser(description="UNIX Shell Emulator")
    parser.add_argument("--vfs", default="./vfs_root", help="Path to VFS directory")
    parser.add_argument("--script", default="", help="Path to startup script")
    return parser.parse_args()


def main():
    args = parse_args()
    root = tk.Tk()
    app = ShellEmulatorGUI(root, args.vfs, args.script)
    root.mainloop()


if __name__ == "__main__":
    main()