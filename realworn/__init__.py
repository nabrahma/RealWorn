# SPDX-License-Identifier: GPL-3.0-or-later
"""RealWorn: one-click weathering with scene-level weather for Blender 5.2+.

This file only registers and unregisters; see core/ for the logic.
"""

from . import props, operators, ui, handlers

_modules = (props, operators, ui, handlers)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
