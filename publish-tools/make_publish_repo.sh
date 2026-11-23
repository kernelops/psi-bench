#!/usr/bin/env bash
# Build the combined repository (psi-bench + the three protocols with their original history) in a NEW folder.
# The existing working folders are only read, never modified. Commits use your global git identity.
#
# Usage: make_publish_repo.sh <new-target-folder> <git-remote-url>
set -euo pipefail
TARGET="${1:?target folder}"
REMOTE="${2:?remote url}"
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$TOOLS/.." && pwd)"          # folder holding psi-bench, pepsi, volepsi, BZS-MPSI
HERE="$WS/psi-bench"
[ ! -e "$TARGET" ] || { echo "$TARGET already exists" >&2; exit 1; }
git config user.name  >/dev/null || { echo "git user.name is not set" >&2; exit 1; }
git config user.email >/dev/null || { echo "git user.email is not set" >&2; exit 1; }
for r in pepsi volepsi BZS-MPSI; do
  [ -z "$(git -C "$WS/$r" status --porcelain --untracked-files=no)" ] || { echo "$r has uncommitted changes to tracked files" >&2; exit 1; }
done

mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"
cd "$TARGET"
git init -q -b main .

# 1. root files
cp "$TOOLS/root/LICENSE" "$TOOLS/root/NOTICE" "$TOOLS/root/README.md" .
cp "$TOOLS/root/gitignore" .gitignore
git add -A
git commit -q -m "Add license, readme and notice"

# 2. the three protocols, each with its own history
git subtree add -q --prefix=volepsi  "$WS/volepsi"   main -m "Import volepsi from ladnir/volepsi"
git subtree add -q --prefix=BZS-MPSI "$WS/BZS-MPSI"  main -m "Import BZS-MPSI from orzcy/BZS-MPSI"
git subtree add -q --prefix=pepsi    "$WS/pepsi"     main -m "Import pepsi, based on RasoulAM/pepsi"

# 3. the harness: exactly the files git would track in psi-bench (respects psi-bench/.gitignore)
tmp="$(mktemp -d)"; git init -q "$tmp"
files="$(cd "$HERE" && git --git-dir="$tmp/.git" --work-tree=. add -A >/dev/null && git --git-dir="$tmp/.git" --work-tree=. ls-files)"
rm -rf "$tmp"
while IFS= read -r f; do mkdir -p "psi-bench/$(dirname "$f")"; cp -p "$HERE/$f" "psi-bench/$f"; done <<< "$files"
git add -A
git commit -q -m "Add psi-bench harness and web UI"

# 4. the PEPSI end-to-end driver
cp -r "$WS/pepsi/e2e" pepsi/e2e
git add -A
git commit -q -m "Add end-to-end PEPSI driver"

git remote add origin "$REMOTE"
echo "created $TARGET"
git log --oneline | head -12
