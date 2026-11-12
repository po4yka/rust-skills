# Runtime loading on Linux and macOS

Use this file when you make a packaged program find its shared libraries at run
time: an ELF `RUNPATH`, or a Mach-O install name and `LC_RPATH`.

## Linux ELF

Prefer a relocatable `DT_RUNPATH` such as `$ORIGIN/../lib` for an application
that ships private libraries. Quote `$ORIGIN` in shell commands so the shell
does not expand it. Remember that `DT_RUNPATH` applies only to direct
dependencies. Give each shared object a valid path to its own dependencies.

Use `LD_LIBRARY_PATH` for diagnosis, not as the installed product contract.
`SKILL.md` has the `ldd` rule.

## macOS Mach-O

Give a relocatable library an install name such as `@rpath/libfoo.dylib`.
Give the executable or loading library an `LC_RPATH` such as
`@loader_path/../Frameworks`. Inspect the result with `otool -L` and
`otool -l`. Use `install_name_tool` only as an explicit packaging step. Prefer
correct linker inputs so rebuilt artifacts do not need repair.

Embed and sign frameworks or dylibs in the final bundle. Check every required
architecture slice with `lipo -info`.
