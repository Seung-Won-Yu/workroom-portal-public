#!/usr/bin/env python3
from portal_file_browse import FileBrowseMixin
from portal_file_detail import FileDetailMixin
from portal_file_streams import FileStreamMixin


class FileViewsMixin(FileBrowseMixin, FileDetailMixin, FileStreamMixin):
    pass
