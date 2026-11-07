# Publication hygiene

Public GitHub publication is a separate maintainer decision. No repository is
created remotely, uploaded, or made public by these guidelines or the local audit.
Development remains within Phase 1.

## What belongs in source control

Keep original source, tests, setup scripts, project documentation, license texts,
third-party notices, and approved project assets. PNG, JPG, JPEG, SVG, ICO, and
other image formats are deliberately not globally ignored. Approval and licensing
still matter; a file being trackable is not publication approval.

Contributor-editable Python modules, type stubs, Qt styles/resources, tests,
dependency/build declarations, documentation, licenses, and approved assets are
project source. Ordinary `build/`, `dist/`, `env/`, `venv/`, and `logs/` exclusions
are scoped to the repository root so source packages with those names remain
trackable beneath `src/`, `tests/`, or `docs/`. Use `.venv/` for local Python
environments; that distinctive environment name stays excluded at any depth.
Do not add a blanket source-directory exception that could expose embedded
credentials, caches, or model weights. Review the actual editable-file inventory.

Keep virtual environments, caches, binaries/build output, IDE settings, logs,
application settings, credentials, account-recovery material, generated images,
private datasets, and model weights out of commits. Runtime application data uses
the user's local data directory by default; workspace overrides should stay under
`.local-data/`. The root `data/`, `datasets/`, `private-datasets/`, `outputs/`,
`generated/`, `gallery/`, `runs/`, preview/cache/temp directories, and related paths
listed in `.gitignore` are reserved for private or generated data. Intentional
source/fixtures belong outside these runtime directories.

Weight/checkpoint files (`.safetensors`, `.ckpt`, `.pt`, `.pth`, `.bin`, `.gguf`,
`.onnx`) are ignored anywhere, including mixed-case extensions and files inside
asset/fixture directories. Any future exception must be explicitly approved and
reviewed; force-adding a file is not approval.

Only a reviewed `.env.example` placeholder template is allowed. Secrets with
arbitrary filenames or embedded in source, images, archives, or PDFs cannot be
reliably excluded through ignore rules alone.

## Inspect before staging or publishing

From the repository root, these commands are read-only:

```powershell
git status --short --untracked-files=all
git ls-files --stage
git ls-files --cached --ignored --exclude-standard
git diff --cached --stat
git diff --cached --name-only
git for-each-ref --format='%(refname) %(objecttype)'
git remote -v
git check-ignore -v --no-index outputs/example.png models/example.safetensors
```

Review the intended file list first, then inspect staged content privately before
any commit. Do not paste raw credential matches or recovery contents into issues,
logs, audit documents, or chat. Review potential secret findings using redacted
metadata. Scan for personal paths and metadata, unexpectedly large files, and asset
rights, and review any actual history separately. Automated patterns and a clean
`git status` are not proof that a repository contains no sensitive information.

## Existing objects and private snapshots

`.gitignore` affects untracked files. It does not remove index entries, change old
commits, erase reflogs, delete tool snapshot refs, or remove loose/packed objects.
Even a repository with an unborn branch and no tracked files can contain private
snapshots and blobs. Do not assume such a repository is clean based on `HEAD`
alone. See the [official Git ignore documentation](https://git-scm.com/docs/gitignore).

Do not share/archive a private `.git` directory, create an all-ref bundle, or mirror
all refs for publication. If the object store contains private snapshots, a fresh
local repository populated only from an explicitly reviewed file list is a safer
proposal than reusing the whole private repository. That export/init step must be
reviewed separately; it is not performed by this audit. Recheck the exported files
before any upload. Never copy `.git`, ignored local data, or private audit reports
into that export.

Deleting files/refs/objects, untracking files, moving private data, garbage
collection intended to remove objects, or rewriting history requires explicit
approval. If a secret has actually left the private environment, assess revocation
or replacement through the owning service; ignore rules do not undo disclosure.

## Licensing remains part of the release review

Retain the proposed GPL-3.0-or-later declaration and official license texts. The
project owner has approved the supplied Stoneglass branding for inclusion, and
both JPEG copies and PNG reference assets have completed metadata-only cleanup.
Review rights for any
additional assets before accepting them.

The Qt wheel-notice review in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) applies before redistributing
dependency artifacts, vendored implementations, or packaged applications. It does
not itself block this source-only repository, which includes no Qt/PySide/Shiboken
implementation or binaries. Qt modules and embedded code can carry different
terms; consult [Qt's licensing documentation](https://doc.qt.io/qt-6/licensing.html).

Detailed local audit evidence belongs in the ignored
`.test-artifacts/publication-audit/` directory, not in public project documentation.
