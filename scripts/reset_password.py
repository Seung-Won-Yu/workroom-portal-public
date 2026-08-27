#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import secrets
import tempfile

from workroom.core.scopes import hash_password
from scripts.setup_workspaces import CONFIG_PATH, PASSWORDS_PATH


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.chmod(mode)
    tmp_path.replace(path)


def update_passwords_file(username: str, name: str, password: str) -> None:
    lines = []
    replaced = False
    if PASSWORDS_PATH.exists():
        lines = PASSWORDS_PATH.read_text(encoding="utf-8").splitlines()
    if not lines:
        lines = [
            "Workroom Portal Portal initial passwords",
            "Change these after rollout if needed.",
            "",
        ]
    updated = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] == username:
            updated.append(f"{username}\t{name}\t{password}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(f"{username}\t{name}\t{password}")
    atomic_write_text(PASSWORDS_PATH, "\n".join(updated).rstrip() + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset one Workroom Portal Portal password.")
    parser.add_argument("username", help="Portal username, e.g. user1 or admin")
    parser.add_argument("--dry-run", action="store_true", help="Validate the user without writing files or printing a password.")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    user = config.get("users", {}).get(args.username)
    if not user:
        users = ", ".join(sorted(config.get("users", {})))
        raise SystemExit(f"unknown user: {args.username}. Known users: {users}")

    name = str(user.get("name") or args.username)
    if args.dry_run:
        print(f"dry-run ok: {args.username} ({name})")
        return

    password = secrets.token_urlsafe(9)
    user["password_hash"] = hash_password(password)
    atomic_write_text(CONFIG_PATH, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    update_passwords_file(args.username, name, password)

    print(f"password reset: {args.username} ({name})")
    print(f"new password: {password}")
    print("restart the portal for the new password to take effect.")


if __name__ == "__main__":
    main()
