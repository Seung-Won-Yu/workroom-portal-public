#!/usr/bin/env python3
import urllib.parse


def portal_url(route: str, params: dict[str, str]) -> str:
    cleaned = {key: value for key, value in params.items() if value not in (None, "")}
    if not cleaned:
        return route
    return route + "?" + urllib.parse.urlencode(cleaned)


def app_folder_url(root_id: str, path: str = "", params: dict[str, str] | None = None) -> str:
    return portal_url("/app", {"root": root_id, "path": path, **(params or {})})


def app_file_url(root_id: str, path: str, params: dict[str, str] | None = None) -> str:
    return portal_url("/app", {"root": root_id, "file": path, **(params or {})})
