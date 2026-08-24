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

## Companion Dogs Linux aliases

On Linux, Project Zomboid can resolve Companion Dogs assets through the
lowercase `mods/companiondogs` path. The Companion Dogs fix creates only the
required lowercase `42/media` aliases: `lua`, `animsets`, `scripts`, and
`models_X`, plus the existing `defaultpathfind.xml` case alias. This keeps
model scripts visible without replacing the whole lowercase mod root. Do not
make `mods/companiondogs` a symlink to `CompanionDogs`: that causes a WorldGen
startup failure.
