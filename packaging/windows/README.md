# Windows distribution builder

`build-release.ps1` creates a sanitized friend-preview package. It copies only application source, tests, templates, the pinned `uv` executable, and delivery docs. Runtime databases, user documents, credentials, logs, backups, virtual environments, indexes, caches, Git metadata, DeepTutor, and NextChat are never copied.

Run from PowerShell:

```powershell
.\packaging\windows\build-release.ps1
```

The output directory and ZIP are written to `C:\AI-PC\dist` by default. The builder refuses unsafe output paths and regenerates `manifest.json` from the staged files.
