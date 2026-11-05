# otto-m4b 0.8.0: rename and upgrade

The Python converter is now **otto-m4b**, inspired by [seanap's original auto-m4b](https://github.com/seanap/auto-m4b). The project remains MIT licensed; its conversion, metadata, chapter and archive behavior is unchanged.

## Upgrade

1. Stop the old converter and wait for any conversion to finish. Never run the old and new versions against the same inbox simultaneously.
2. Back up configuration, `~/.auto-m4b`, `/tmp/auto-m4b`, watch-source `.auto-m4b` markers, and conversion logs. Preserve the old image for rollback.
3. Use `brandonscript/otto-m4b` and the updated Compose template. Source users should update their Git remote to `https://github.com/brandonscript/otto-m4b.git`, refresh the Poetry environment, and continue using `poetry run python -m src`.
4. Keep configured inbox/archive/converted/backup paths. A directory named `#auto-m4b` does not need renaming. Explicit `WORKING_FOLDER` paths remain authoritative.
5. Start once and inspect migration messages and the converted directory's `otto-m4b.log` before resuming imports. Update log readers to that path.

The application migrates `~/.auto-m4b` to `~/.otto-m4b` and the default `/tmp/auto-m4b` to `/tmp/otto-m4b`. It preserves fatal locks and stops on live process locks or unfinished legacy temporary work. Resolve reported partial work manually; it is never resumed or deleted automatically. Fatal locks now require explicit resolution rather than expiring after 30 seconds.

Global/per-book `auto-m4b.*.log` files under configured inbox, converted, archive and failed directories become `otto-m4b.*.log`. Conflicting logs/cache files are preserved as `.legacy-backup` (numbered when necessary); current files are never overwritten. Repeated startup is safe. Watch markers migrate as source directories are encountered, preserving their recorded child names. Read-only legacy markers are still honored with a warning. Conflicting markers stop processing until resolved.

Hooks receive `OTTO_M4B_*` variables. Matching `AUTO_M4B_*` aliases remain available for existing scripts during this transition. New scripts should use the new names. `fixm4b` remains a separate command and project.

## Git history cleanup

The rename removes agent coauthor credits from repository-owned branches and tags. Human authorship and substantive commit messages remain. This changes commit IDs and invalidates affected historical signatures. Do not merge or push old history back into the renamed repository.

Save any uncommitted work privately, then reclone the repository. To retain a checkout, first back up its local work and deliberately reset each tracking branch to the rewritten remote counterpart. Rebase or cherry-pick only reviewed unpublished work; do not merge old branches wholesale. Administrators retain private pre-rewrite bundles and commit mappings for recovery.

## Rollback

Stop otto-m4b first. Restore the previous image/configuration and restore pre-upgrade state, markers and log names from the private snapshot. Preserve post-upgrade logs and newly processed-book state separately before restoring anything; rolling state back blindly can cause duplicate imports. No audiobook directories need moving. Git history rollback requires a coordinated ref restore from the private bundle and must not be mixed with normal pushes.
