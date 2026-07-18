# Release And Push Checklist

Target repository:

```text
https://github.com/AmigoAgogo/ComplianceRader
```

Before each push:

1. Run the test suite.
2. Confirm `runtime/`, `data/runtime/`, `dist/`, `build/`, logs, and evidence are not staged.
3. Update `CHANGELOG.md` with user-visible changes.
4. Update `README.md` if usage, packaging, startup, or GitHub location changed.
5. Update `docs/portable_data_layout.md` if runtime storage changed.
6. If an EXE is rebuilt, verify it launches and `/api/health` returns `ok`.

Suggested first-time git setup:

```powershell
git init
git remote add origin https://github.com/AmigoAgogo/ComplianceRader.git
git branch -M main
```

Do not push runtime user data. The repository should hold source code, tests, docs, and packaging scripts only.
