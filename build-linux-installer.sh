#!/bin/bash
# Build a self-contained AnkiGPT Linux package into release/.
# Usage: ./build-linux-installer.sh [--upload] [owner/repository]

set -euo pipefail
cd "$(dirname "$(realpath "$0")")"

upload=0
if [ "${1:-}" = "--upload" ]; then
    upload=1
    shift
fi
repository="${1:-mando1967/ankigpt}"

version="${ANKIGPT_INSTALLER_VERSION:-$(tr -d '[:space:]' < .version)}"
if [ -z "$version" ]; then
    echo "Error: .version is empty." >&2
    exit 1
fi
export RELEASE="${RELEASE:-1}"

echo "Building AnkiGPT $version for Linux..."
./ninja wheels
aqt_wheel=$(ls -t out/wheels/aqt-*.whl | head -n 1)
anki_wheel=$(ls -t out/wheels/anki-*.whl | head -n 1)

# The fcitx5 input-method plugin can only be bundled when fcitx5-qt6 and
# patchelf are installed; CI builds them as upstream Anki's release does.
fcitx_plugin=""
for candidate in /usr/{,local/}lib/{,*-linux-gnu/}qt6/plugins/platforminputcontexts/libfcitx5platforminputcontextplugin.so; do
    [ -f "$candidate" ] && fcitx_plugin="$candidate"
done
fcitx_args=()
if [ -z "$fcitx_plugin" ] || ! command -v patchelf >/dev/null; then
    echo "Warning: fcitx5-qt6 plugin or patchelf not found; building without fcitx5 input-method support."
    fcitx_args=(--skip_fcitx)
fi

out/pyenv/bin/python qt/tools/build_installer.py --version "$version" \
    build --aqt_wheel "$aqt_wheel" --anki_wheel "$anki_wheel" "${fcitx_args[@]}"

echo "Packaging Linux installer..."
out/pyenv/bin/python qt/tools/build_installer.py --version "$version" package

package=$(ls -t out/installer/dist/*.tar.zst | head -n 1)
mkdir -p release
mv -f "$package" release/
package="release/$(basename "$package")"
sha256sum "$package"
echo "Installer ready: $PWD/$package"

if [ "$upload" = 1 ]; then
    tag="ankigpt-v$version"
    echo "Uploading $package to $tag in $repository..."
    gh release view "$tag" --repo "$repository" >/dev/null 2>&1 \
        || gh release create "$tag" --repo "$repository" \
            --title "AnkiGPT $version" --generate-notes
    gh release upload "$tag" "$package" --clobber --repo "$repository"
fi
