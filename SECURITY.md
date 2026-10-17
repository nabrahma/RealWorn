# Security policy

## Supported versions

Only the latest release receives fixes.

| Version | Supported |
| --- | --- |
| 3.x | Yes |
| 2.x and older | No |

## Reporting a vulnerability

Please don't report security problems in public issues.

Report them privately through this repository's **Security** tab, under **Report a
vulnerability**. Only the maintainer can read the report. Please include:

- the RealWorn and Blender versions;
- what an attacker could do, and how;
- steps or a file that reproduces it.

You can expect an acknowledgement within a week. Once a fix is released, the advisory is published
with credit to you, unless you'd rather stay anonymous.

## Scope

RealWorn runs inside Blender with the user's permissions:
- it reads texture folders the user picks;
- it writes painted masks, baked textures and exports next to the user's files;
- the add-on itself makes no network requests.

Relevant reports include path handling that writes outside the intended folders, and crafted
.blend or image files that make RealWorn misbehave.

The test helper `tests/corpus/fetch.py` downloads from Poly Haven. It's a development tool and isn't
shipped in the add-on.
