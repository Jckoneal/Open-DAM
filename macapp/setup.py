"""Builds Collaborate.app via py2app — run through
scripts/build-macapp.sh, not directly (that script sets up a clean build
venv with `collaborate` installed as a *regular*, non-editable package;
py2app's modulegraph needs real files sitting in site-packages to freeze,
not an editable-install import hook).

Unsigned build: there's no Apple Developer ID here to sign/notarize with,
so the first launch shows Gatekeeper's "can't verify developer" warning —
right-click > Open (once) clears it. See docs/menubar-app.md.
"""

from setuptools import setup

APP = ["launcher.py"]

# Landed at the top level of Contents/Resources/ (dest "") — Template.prproj
# becomes the packaged app's out-of-the-box default template; see
# collaborate.config's _bundled_resource_path for how it's discovered at
# runtime. AppIcon.icns is consumed directly via the iconfile option below,
# not listed here — py2app already copies it into the bundle for us.
DATA_FILES = [
    ("", ["resources/Template.prproj"]),
]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "resources/AppIcon.icns",
    "plist": {
        "CFBundleName": "Collaborate",
        "CFBundleDisplayName": "Collaborate",
        "CFBundleIdentifier": "com.collaborate.menubar",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "NSHumanReadableCopyright": "Collaborate",
        # Menu-bar-only app: no Dock icon, no Cmd+Tab entry. This also
        # sidesteps a whole class of workaround that the unpackaged
        # `collab menubar` needs (see menubar_app.py's _activate): a real
        # bundle's activation policy is established from this key before
        # our code even runs, rather than needing to be set at runtime
        # because we're "a bare script, not a real .app".
        "LSUIElement": True,
    },
    "packages": ["collaborate", "rumps"],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
