# Development environment

Everyone should use a **project-local virtual environment** and install from **`requirements.txt`** so dependencies match across laptops and OSes.

## Prerequisites

- **Python 3.10 or newer** (3.11 and 3.12 are fine). Check with:

  ```bash
  python3 --version
  ```

  On Windows, `py -3.11 --version` or `python --version` may apply depending on how Python was installed.

## One-time setup per clone

### 1. Create the virtual environment

From the repository root (`Optimization_EVCRP/`):

**macOS / Linux**

```bash
python3 -m venv .venv
```

**Windows (Command Prompt or PowerShell)**

```bash
py -3.11 -m venv .venv
```

Using **`.venv`** in the project root is conventional; the folder is gitignored and stays only on your machine.

### 2. Activate the environment

**macOS / Linux**

```bash
source .venv/bin/activate
```

**Windows CMD**

```bash
.venv\Scripts\activate.bat
```

**Windows PowerShell**

```bash
.venv\Scripts\Activate.ps1
```

Your shell prompt should show `(.venv)` when activation worked.

### 3. Install dependencies

With the venv **active**:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`--upgrade pip` avoids odd resolver issues on older Python installs.

### 4. Sanity check

Still with the venv active:

```bash
python -c "import pandas, requests, pulp; print('OK', pandas.__version__)"
```

You should see `OK` and a pandas version with no import errors.

## Daily workflow

1. Open a terminal in the repo root.
2. **Activate** `.venv` (same commands as above).
3. Run scripts with `python geocode_osm.py`, `python MILP_solverfw_test.py`, etc.

Do **not** commit `.venv` or rely on a shared copy of it; only **`requirements.txt`** is shared in Git.

## Keeping environments aligned

| Change | What to do |
|--------|------------|
| Someone adds a library | They add it to `requirements.txt` (with a pin), open a PR; everyone runs `pip install -r requirements.txt` after pulling. |
| You need stricter lockstep | After `pip install -r requirements.txt`, run `pip freeze > requirements.lock` and commit `requirements.lock`; teammates use `pip install -r requirements.lock`. Optional for this repo unless you hit solver/OS issues. |
| PuLP / solver binaries | `PuLP` is pure Python for the default usage; if you later plug in CBC/Gurobi/etc., document extra install steps in this file. |

## Optional: strict lock file

For maximum “same package versions everywhere”:

```bash
pip install -r requirements.txt
pip freeze > requirements.lock
```

Commit `requirements.lock`. Others:

```bash
pip install -r requirements.lock
```

Regenerate the lock whenever `requirements.txt` changes.

## IDE (Cursor / VS Code)

Select the interpreter at **`.venv/bin/python`** (macOS/Linux) or **`.venv\Scripts\python.exe`** (Windows) so the editor uses the same environment as the terminal.

## Related docs

- [GEOCODING.md](GEOCODING.md) — geocoding pipeline and data files.
