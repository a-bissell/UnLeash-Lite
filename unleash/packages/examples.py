"""Built-in example packages.

These ship as ready-to-deploy packages (seeded on first boot) and double as
starting templates in the Package Builder. They are deliberately benign,
sysadmin-oriented operations — the expected operator is a fleet administrator,
not a robotics developer, so the examples look like everyday fleet chores
(smoke test, diagnostics, remote-access, config) rather than robot code.

Each command runs through the robot's OTA engine as a shell command line.
Commands that redirect or chain are wrapped in `sh -c '...'` so they behave the
same regardless of how the engine invokes them.
"""

import json
import logging

logger = logging.getLogger("unleash.examples")


def _cmd(line: str) -> dict:
    return {"Cmd": line, "Delay": 0.0, "ExpectCode": [0], "IgnoreUnexpected": True}


# Single source of truth for both the seeder and the /packages/templates API.
EXAMPLE_PACKAGES: list[dict] = [
    {
        "name": "healthcheck",
        "version": "1.0.0",
        "module_name": "system_patch",
        "description": (
            "Smoke test: writes a timestamped marker to "
            "/unitree/var/unleash/healthcheck. The simplest way to confirm a "
            "package actually reaches a robot and runs — deploy this first."
        ),
        "commands": [
            _cmd("mkdir -p /unitree/var/unleash"),
            _cmd("sh -c 'date -u > /unitree/var/unleash/healthcheck'"),
        ],
    },
    {
        "name": "system-report",
        "version": "1.0.0",
        "module_name": "system_patch",
        "description": (
            "Collect basic diagnostics (kernel, uptime, disk, memory, network) "
            "into /unitree/var/unleash/system-report.txt for triage."
        ),
        "commands": [
            _cmd("mkdir -p /unitree/var/unleash"),
            _cmd(
                "sh -c '{ date -u; uname -a; uptime; df -h; free -m; ip -br addr; } "
                "> /unitree/var/unleash/system-report.txt 2>&1'"
            ),
        ],
    },
    {
        "name": "enable-ssh",
        "version": "1.0.0",
        "module_name": "system_patch",
        "description": (
            "Ensure the OpenSSH server is enabled and running for remote "
            "administration. Handles both `ssh` and `sshd` unit names; edit to "
            "match your init system if needed."
        ),
        "commands": [
            _cmd("sh -c 'systemctl enable ssh || systemctl enable sshd || true'"),
            _cmd("sh -c 'systemctl restart ssh || systemctl restart sshd || true'"),
        ],
    },
    {
        "name": "set-timezone",
        "version": "1.0.0",
        "module_name": "system_patch",
        "description": (
            "Set the system timezone. Change 'UTC' to your zone "
            "(e.g. America/Chicago) before deploying."
        ),
        "commands": [
            _cmd("sh -c 'ln -sf /usr/share/zoneinfo/UTC /etc/localtime'"),
            _cmd("sh -c 'echo UTC > /etc/timezone || true'"),
        ],
    },
]


async def seed_example_packages(session, package_dir) -> int:
    """Build and insert the example packages — but only into an empty catalog.

    Guarded on the whole table (including archived rows) so we never resurrect
    an example a user has deliberately deleted. Returns the number seeded.
    """
    from sqlalchemy import func, select

    from ..db.models import Package
    from .builder import build_package_to_file

    existing = (await session.execute(select(func.count(Package.id)))).scalar_one()
    if existing:
        return 0

    package_dir.mkdir(parents=True, exist_ok=True)
    seeded = 0
    for spec in EXAMPLE_PACKAGES:
        commands = spec["commands"]
        output = package_dir / f"{spec['name']}_{spec['version']}.upk"
        path, md5, size = build_package_to_file(
            commands=commands,
            output=output,
            module_name=spec["module_name"],
            version=spec["version"],
        )
        session.add(Package(
            name=spec["name"],
            version=spec["version"],
            description=spec["description"],
            module_name=spec["module_name"],
            commands_json=json.dumps(commands),
            file_hash=md5,
            file_size=size,
            file_path=str(path),
            created_by=None,
        ))
        seeded += 1

    await session.commit()
    logger.info("Seeded %d example packages", seeded)
    return seeded
