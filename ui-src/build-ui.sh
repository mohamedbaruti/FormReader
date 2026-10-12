#!/bin/sh
# Builds the phone app's screens from the portal sources (../portal) into the app.
# Needs esbuild, react and react-dom (npm install -g esbuild react react-dom, or a local node_modules).
set -e
cd "$(dirname "$0")"
OUT=../android/app/src/main/python/nidamobile/ui
mkdir -p "$OUT"
esbuild main.tsx --bundle --minify --outfile="$OUT/bundle.js" --jsx=automatic \
  --alias:@=../portal --alias:next/link=./stubs/next-link.tsx --alias:next/navigation=./stubs/next-navigation.ts \
  --define:process.env.NEXT_PUBLIC_API_URL='"/api"' --define:process.env.NODE_ENV='"production"'
cp ../portal/app/globals.css "$OUT/globals.css"
cp ../portal/public/*.png "$OUT/"
cp index.html "$OUT/index.html"
echo "screens built into $OUT"
