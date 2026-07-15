"""CLI commands for explicit AgentEra platform control enrollment."""

from __future__ import annotations

import asyncio

from hermes_cli.config import read_raw_config, save_config
from hermes_cli.platform_control import enroll, identity_path, load_identity


def platform_command(args) -> int:
    action = getattr(args, "platform_action", None)
    if action == "enroll":
        identity = asyncio.run(enroll(args.url, args.code))
        print(f"Runtime registered as instance {identity.instance_id}.")
        return 0
    if action == "disable":
        config = read_raw_config()
        current = config.get("platform_control")
        section = dict(current) if isinstance(current, dict) else {}
        section["enabled"] = False
        config["platform_control"] = section
        save_config(config, preserve_keys={("platform_control",)})
        try:
            identity_path().unlink()
        except FileNotFoundError:
            pass
        print("Platform control disabled. Re-enroll to enable it again.")
        return 0
    if action == "status":
        identity = load_identity()
        print(f"Platform control: {'enrolled' if identity else 'disabled'}")
        if identity:
            print(f"Instance: {identity.instance_id}")
        return 0
    print("Usage: hermes platform {enroll|status|disable}")
    return 1
