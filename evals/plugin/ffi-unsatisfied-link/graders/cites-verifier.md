---
type: llm
---

PASS if the answer tells the user to list the dynamic exports of the `.so` with `llvm-nm -D` (or `nm -D`) and compare them with the `Java_...` names in the error.
FAIL if the answer does not list the library's exported symbols, or blames only `System.loadLibrary`.
