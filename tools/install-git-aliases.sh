#!/bin/sh
# install-git-aliases.sh — repository-local git aliases for this clone.
#
# Aliases live in .git/config, which is not tracked, so a fresh clone has to run
# this once. Run it from anywhere inside the repository.
#
#   git snap "message"   save the whole working tree — tracked edits and
#                        untracked files — to refs/snapshots/<timestamp>.
#                        Builds the commit through a temporary index: it never
#                        touches the working tree, the index or HEAD.
#   git snaps            list the snapshots, newest first
#
# Recovering one file:      git show <ref>:docs/charter.md > docs/charter.md
# Recovering everything:    git show <ref>                  (then apply by hand)
#
# Snapshots are ordinary commits held by a ref, so gc will not collect them.
# Delete one with: git update-ref -d refs/snapshots/<timestamp>

set -e
cd "$(git rev-parse --show-toplevel)"

git config alias.snap '!f() {
  i=$(mktemp /tmp/git-snap-idx.XXXXXX); export GIT_INDEX_FILE="$i";
  git read-tree HEAD; git add -A; t=$(git write-tree);
  unset GIT_INDEX_FILE; rm -f "$i";
  if [ "$t" = "$(git rev-parse HEAD^{tree})" ]; then
    echo "working tree matches HEAD; nothing to snapshot";
  else
    c=$(echo "${1:-snapshot}" | git commit-tree "$t" -p HEAD);
    r=refs/snapshots/$(date +%Y%m%d-%H%M%S);
    git update-ref "$r" "$c";
    echo "saved working tree to $r ($(git rev-parse --short $c))";
  fi; }; f'

git config alias.snaps \
  'for-each-ref --sort=-refname --format=%(refname) %(objectname:short) %(contents:subject) refs/snapshots'

git config pull.rebase true

echo "installed: git snap, git snaps; set pull.rebase=true"
