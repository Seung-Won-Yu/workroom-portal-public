#!/usr/bin/env python3
import argparse
from pathlib import Path

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from workroom.web.actions import PortalActionsMixin
from workroom.admin.views import AdminViewsMixin
from workroom.web.api import PortalApiMixin
from workroom.core.auth import PortalAuthMixin
from workroom.files.views import FileViewsMixin
from workroom.web.http import PortalHttpMixin
from workroom.core.model import Portal
from workroom.web.router import PortalRouterMixin
from workroom.web.user_views import UserViewsMixin


class Handler(
    PortalRouterMixin,
    PortalApiMixin,
    PortalAuthMixin,
    PortalHttpMixin,
    PortalActionsMixin,
    AdminViewsMixin,
    UserViewsMixin,
    FileViewsMixin,
    BaseHTTPRequestHandler,
):
    server_version = "WorkroomPortal/0.1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    portal = Portal(Path(args.config))
    host = portal.config.get("bind", "0.0.0.0")
    port = int(portal.config.get("port", 8787))

    class Server(ThreadingHTTPServer):
        pass

    server = Server((host, port), Handler)
    server.portal = portal
    print(f"Workroom portal listening on {host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
