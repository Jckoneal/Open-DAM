"""py2app entry point for the packaged Collaborate.app.

A tiny shim so py2app's modulegraph has a plain script to analyze — the
real app is collaborate.menubar_app, the exact same code the `collab
menubar` CLI command runs. Nothing app-bundle-specific happens here; the
bundle-vs-CLI differences (e.g. the bundled default template) live in
collaborate.config, keyed off sys.frozen, not off which entry point ran.
"""

from collaborate.menubar_app import run

if __name__ == "__main__":
    run()
