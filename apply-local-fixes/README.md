# PZ local fixes modular layout

`apply-local-fixes.py` contains only shared configuration/helpers and the loader.

`fix-scripts/*.py` contains one independent fix per file. Files are executed in
alphabetical order, so the numeric prefixes define execution order.

Each fix exports:

    FIX = {
        "name": "Readable name",
        "run": run,
    }

and `run(ctx)` returns True when it changed files, otherwise False.

Install both `apply-local-fixes.py` and the `fix-scripts` directory under:

    /home/matteo/containers/project-zomboid/

The existing exit-code contract is preserved:
- 0 = no patch changed
- 10 = one or more patches changed
- 1 = error
- 130 = interrupted
