# Fresh setup and launch check

Verified 31 October 2026 on Windows with Python 3.12.14 already installed and working internet access. This measures recipient setup/startup time, not application performance.

An isolated source copy contained no existing virtual environment, local database or saved settings. Dependencies were installed with pip caching disabled. The copied model was then independently retrained, all tests ran, and the actual launcher served both the webpage and a freshly seeded dashboard.

| Step | Measured time |
|---|---:|
| Create new Python environment | 12.77 seconds |
| Download/install locked dependencies without cache | 127.43 seconds |
| Validate dependencies | 1.43 seconds |
| Train model | 20.73 seconds |
| Run tests | 5.98 seconds |
| Start server and successfully load dashboard | 2.67 seconds |
| **Total, including source-copy overhead** | **171.06 seconds (2 minutes 51 seconds)** |

Results: 89 tests passed; no broken dependencies; webpage HTTP 200; dashboard contained 16 eligible demo orders with matching bucket totals. The test server was stopped afterwards; the user's original running app was untouched.

Conclusion: the tested source/dependency setup meets the under-10-minute setup-and-run target on this machine/network, even including optional training and tests. Python installation time is excluded. Slower connections or different operating systems may change the time; macOS/Linux instructions are provided but were not executed here.

The README was corrected to remove references to the deleted launcher and documents and to put fresh-machine instructions first. Sharing must preserve the source folder structure, CSV, config and requirements. Exclude .venv, .setup-check, caches, secrets and local SQLite databases from the shared copy. A recipient gets a fresh demo database automatically.

Machine-readable results: clean-setup-result.json. To repeat locally: `python reports/check_clean_setup.py` from the project folder with Python 3.12. The script creates an isolated environment under .setup-check and leaves its detailed logs there.
