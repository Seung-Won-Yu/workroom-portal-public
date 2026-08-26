#!/usr/bin/env python3
from portal_admin_archive import AdminArchiveMixin
from portal_admin_common import AdminCommonMixin
from portal_admin_search import AdminSearchMixin


class AdminViewsMixin(
    AdminCommonMixin,
    AdminArchiveMixin,
    AdminSearchMixin,
):
    pass
