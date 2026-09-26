"""
Give the frozen app a ``distutils``, because NodeGraphQt still imports one.

``NodeGraphQt/base/menu.py`` and ``NodeGraphQt/widgets/viewer.py`` both
do ``from distutils.version import LooseVersion``. Python 3.12 removed
``distutils`` from the standard library; in an ordinary environment
setuptools quietly puts it back through a ``.pth`` import hook, and
``.pth`` files do not run in a frozen application -- so the packaged
app died on the first NodeGraphQt import while the source tree was
perfectly happy.

Rather than hand-write a version class, this points ``distutils`` at
setuptools' own copy of it: the real implementation, the same one that
would have been used outside the bundle.

Drop this when NodeGraphQt stops importing distutils (its 0.6.44 still
does, and emits a DeprecationWarning about it).
"""

import sys


def _install_distutils_alias() -> None:
    try:
        import distutils.version  # noqa: F401 - a real one is already there
    except ImportError:
        pass
    else:
        return

    try:
        import setuptools._distutils as distutils_pkg
        import setuptools._distutils.version as version_mod
    except ImportError:
        # Nothing we can do; let the import that needs it raise, with
        # its own traceback, rather than hiding the cause here.
        return

    sys.modules.setdefault("distutils", distutils_pkg)
    sys.modules.setdefault("distutils.version", version_mod)


_install_distutils_alias()
