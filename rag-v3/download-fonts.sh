#!/bin/bash
# download-fonts.sh
# Downloads self-hosted fonts to public/fonts/
# Run once before building: bash download-fonts.sh

set -e
mkdir -p public/fonts

echo "Downloading DM Sans..."
curl -sL "https://fonts.gstatic.com/s/dmsans/v15/rP2Hp2ywxg089UriCZa4ET-DNl0.woff2" \
  -o public/fonts/dm-sans.woff2

echo "Downloading JetBrains Mono..."
curl -sL "https://fonts.gstatic.com/s/jetbrainsmono/v18/tDbY2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKxjOV6.woff2" \
  -o public/fonts/jetbrains-mono.woff2

echo "Fonts downloaded to public/fonts/"
ls -lh public/fonts/
