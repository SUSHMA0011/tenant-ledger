# AI usage

**Tool:** Claude (claude.ai chat).

**Key prompts:**
1. Walk me through the Tenant Ledger assessment step by step.
2. Which problems should I pick for a 1-hour scope, and why?
3. Build the full FastAPI project with tests.
4. Fix my Windows setup errors (Application Control policy blocking files).

**What the AI produced:** the project skeleton, data model, service layer, API endpoints, tests, and drafts of README.md and NOTES.md.

**What I corrected / rejected:**
- Windows blocked SQLAlchemy 2.1.x (`_util_cy` DLL, Application Control policy). I pinned `sqlalchemy>=2.0,<2.1` in requirements.txt and it worked.
- `pip.exe` was also blocked inside the venv, so I ran everything through `python -m pip` and `python -m pytest` instead.
- I ran the full test suite myself (34 passed) rather than trusting the AI's claim that it passed.
- I read through the code before committing each part so I can explain it.
- I questioned why reversals are dated today instead of the original date, and kept it because it avoids rewriting closed periods.