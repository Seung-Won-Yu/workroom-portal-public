#!/usr/bin/env python3
from workroom.files.browse import FileBrowseMixin
from workroom.files.detail import FileDetailMixin
from workroom.files.streams import FileStreamMixin


class FileViewsMixin(FileBrowseMixin, FileDetailMixin, FileStreamMixin):
    pass
