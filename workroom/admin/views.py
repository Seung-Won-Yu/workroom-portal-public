#!/usr/bin/env python3
from workroom.admin.archive import AdminArchiveMixin
from workroom.admin.common import AdminCommonMixin
from workroom.admin.search import AdminSearchMixin


class AdminViewsMixin(
    AdminCommonMixin,
    AdminArchiveMixin,
    AdminSearchMixin,
):
    pass
