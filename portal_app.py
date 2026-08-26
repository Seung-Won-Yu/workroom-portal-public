#!/usr/bin/env python3
import argparse
from pathlib import Path

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from portal_actions import PortalActionsMixin
from portal_admin_views import AdminViewsMixin
from portal_api import PortalApiMixin
from portal_auth import PortalAuthMixin
from portal_file_views import FileViewsMixin
from portal_http import PortalHttpMixin
from portal_model import Portal
from portal_router import PortalRouterMixin
from portal_user_views import UserViewsMixin


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
