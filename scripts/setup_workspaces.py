#!/usr/bin/env python3
import json
from pathlib import Path
import secrets

from workroom.core.scopes import hash_password


PORTAL_DIR = Path("/home/portal/workspaces/admin/portal")
CONFIG_PATH = PORTAL_DIR / "portal_config.json"
PASSWORDS_PATH = Path("/home/portal/workspaces/admin/portal_initial_passwords.txt")

USERS = {
    "admin": {
        "name": "관리자",
        "roots": [
            {"id": "personal", "label": "관리자 작업공간", "path": "/home/portal/workspaces/admin/workroom"},
            {"id": "all", "label": "전체 작업공간", "path": "/home/portal/workspaces"},
        ],
    },
    "user1": {
        "name": "사용자1",
        "roots": [
            {"id": "personal", "label": "사용자1 개인 작업공간", "path": "/home/portal/workspaces/team-alpha/user1"},
            {"id": "team_shared", "label": "team-alpha 팀 공유", "path": "/home/portal/workspaces/team-alpha/shared"},
        ],
    },
    "user2": {
        "name": "사용자2",
        "roots": [
            {"id": "personal", "label": "사용자2 개인 작업공간", "path": "/home/portal/workspaces/team-alpha/user2"},
            {"id": "team_shared", "label": "team-alpha 팀 공유", "path": "/home/portal/workspaces/team-alpha/shared"},
        ],
    },
    "user3": {
        "name": "사용자3",
        "roots": [
            {"id": "personal", "label": "사용자3 개인 작업공간", "path": "/home/portal/workspaces/team-alpha/user3"},
            {"id": "team_shared", "label": "team-alpha 팀 공유", "path": "/home/portal/workspaces/team-alpha/shared"},
        ],
    },
    "user4": {
        "name": "사용자4",
        "roots": [
            {"id": "personal", "label": "사용자4 개인 작업공간", "path": "/home/portal/workspaces/team-alpha/user4"},
            {"id": "team_shared", "label": "team-alpha 팀 공유", "path": "/home/portal/workspaces/team-alpha/shared"},
        ],
    },
    "user5": {
        "name": "사용자5",
        "roots": [
            {"id": "personal", "label": "사용자5 개인 작업공간", "path": "/home/portal/workspaces/team-beta/user5"},
            {"id": "team_shared", "label": "team-beta 팀 공유", "path": "/home/portal/workspaces/team-beta/shared"},
        ],
    },
    "user6": {
        "name": "사용자6",
        "roots": [
            {"id": "personal", "label": "사용자6 개인 작업공간", "path": "/home/portal/workspaces/team-beta/user6"},
            {"id": "team_shared", "label": "team-beta 팀 공유", "path": "/home/portal/workspaces/team-beta/shared"},
        ],
    },
    "user7": {
        "name": "사용자7",
        "roots": [
            {"id": "personal", "label": "사용자7 개인 작업공간", "path": "/home/portal/workspaces/team-beta/user7"},
            {"id": "team_shared", "label": "team-beta 팀 공유", "path": "/home/portal/workspaces/team-beta/shared"},
        ],
    },
}

DEFAULT_PERSONAL_DIRS = ("dev", "research", "summary")


def main():
    PORTAL_DIR.mkdir(parents=True, exist_ok=True)
    existing = {}
    if CONFIG_PATH.exists():
        existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    config = {
        "bind": "0.0.0.0",
        "port": 8787,
        "secret_key": existing.get("secret_key") or secrets.token_urlsafe(48),
        "users": {},
    }

    new_passwords = []
    existing_users = existing.get("users", {})
    for username, meta in USERS.items():
        old = existing_users.get(username, {})
        password_hash = old.get("password_hash")
        if not password_hash:
            password = secrets.token_urlsafe(9)
            password_hash = hash_password(password)
            new_passwords.append((username, meta["name"], password))
        config["users"][username] = {
            "name": meta["name"],
            "password_hash": password_hash,
            "roots": meta["roots"],
        }
        for root in meta["roots"]:
            root_path = Path(root["path"])
            root_path.mkdir(parents=True, exist_ok=True)
            if root["id"] == "personal":
                folder_names = DEFAULT_PERSONAL_DIRS + (("admin",) if username == "admin" else ())
                for folder_name in folder_names:
                    (root_path / folder_name).mkdir(parents=True, exist_ok=True)

    for username, old in existing_users.items():
        if username in config["users"]:
            continue
        roots = old.get("roots", [])
        if not roots or not old.get("password_hash"):
            continue
        config["users"][username] = {
            "name": old.get("name", username),
            "password_hash": old["password_hash"],
            "roots": roots,
            **({"disabled": True} if old.get("disabled") else {}),
        }
        for root in roots:
            root_path = Path(root["path"])
            root_path.mkdir(parents=True, exist_ok=True)
            if root.get("id") == "personal":
                for folder_name in DEFAULT_PERSONAL_DIRS:
                    (root_path / folder_name).mkdir(parents=True, exist_ok=True)

    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONFIG_PATH.chmod(0o600)

    if new_passwords:
        lines = [
            "Workroom Portal Portal initial passwords",
            "Change these after rollout if needed.",
            "",
        ]
        for username, name, password in new_passwords:
            lines.append(f"{username}\t{name}\t{password}")
        PASSWORDS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        PASSWORDS_PATH.chmod(0o600)

    print(f"config: {CONFIG_PATH}")
    print(f"users: {', '.join(config['users'])}")
    if new_passwords:
        print(f"initial passwords: {PASSWORDS_PATH}")
    else:
        print("initial passwords: unchanged")


if __name__ == "__main__":
    main()
