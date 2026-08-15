# Windows distribution builder

`build-release.ps1` creates a sanitized full friend package. It copies only application source, tests, templates, the pinned `uv` executable, and delivery docs. Runtime databases, user documents, credentials, logs, backups, virtual environments, indexes, caches, Git metadata, DeepTutor source, and NextChat source are never copied. The installer fetches the verified DeepTutor CLI commit from its official repository at install time, then removes the temporary checkout.

Run from PowerShell:

```powershell
.\packaging\windows\build-release.ps1
```

The output directory and ZIP are written to `C:\AI-PC\dist` by default. The builder refuses unsafe output paths and regenerates `manifest.json` from the staged files.
