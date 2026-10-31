# Token calibration, 2026-10

Measured by this repository on 2026-10-31 at catalog commit `5d5f470`. It sets the
characters-per-token ratio that `scripts/validate-skills.py` uses for every budget.

## Method

- Install the catalog as a local plugin and read the projection of the client:
  `claude plugin details rust-skills@rust-skills` (Claude Code 2.1.316). It prints an always-on
  cost per skill (the listing entry) and an on-invoke cost (the body), rounded to two significant
  figures above 1,000.
- Compare each number with the characters of the description and of the body after the
  frontmatter.
- The per-bundle listing costs come from installing each bundle plugin of
  `.claude-plugin/marketplace.json` and reading the same command.

## Result

| Quantity | Value |
| --- | --- |
| Always-on listing, all 44 skills | ~9,328 tokens for 22,253 description characters |
| Description characters per listing token | 2.27 to 2.45, 2.37 overall (includes per-entry overhead) |
| Body characters per on-invoke token | median 2.58 |
| Bodies over 5,000 on-invoke tokens | 43 of 44 (smallest: `rust-borrow-semantics`, ~4,400) |
| Common rule of thumb, characters / 3.5 | undercounts the listing by 32 % and each body by 25 % to 27 % |

Listing cost per bundle plugin:

| Bundle | Skills | Always-on tokens | Fits ~2,000 (200K window) |
| --- | ---: | ---: | --- |
| language | 13 | ~2,717 | no |
| build | 9 | ~1,867 | yes |
| testing | 4 | ~824 | yes |
| concurrency | 6 | ~1,293 | yes |
| production | 7 | ~1,424 | yes |
| ffi | 5 | ~1,238 | yes |

Decision: the validator divides characters by **2.5**. It sits between the two measured ratios
and needs no tokenizer and no network, so CI and every contributor compute the same number. The
bundle limit of 5,000 description characters is 2,000 estimated tokens.

## Limits

- The numbers are the client's projection, not a count from the model API. The client does not
  document how it computes them. A count from the token-counting endpoint of the model provider
  needs an API key and was not run.
- One client version. Re-measure when the client or the model family changes, and before you
  change `CHARS_PER_TOKEN`.
- cl100k (tiktoken) is not the tokenizer of any Claude model; `--report budget` prints it only
  when the package is installed, and no gate reads it.

## Per-skill data

| Skill | Description chars | Listing tokens | Body chars | On-invoke tokens | Body chars / token |
| --- | ---: | ---: | ---: | ---: | ---: |
| rust-swift-ffi | 515 | 210 | 20565 | 8000 | 2.57 |
| rust-unsafe | 464 | 190 | 19806 | 7700 | 2.57 |
| rust-android-build | 395 | 170 | 19811 | 7700 | 2.57 |
| rust-event-loop-state | 475 | 200 | 19913 | 7700 | 2.59 |
| rust-panic-safety | 439 | 190 | 19908 | 7700 | 2.59 |
| rust-jni | 473 | 200 | 19865 | 7700 | 2.58 |
| rust-networking | 441 | 190 | 19670 | 7600 | 2.59 |
| rust-database | 381 | 160 | 19725 | 7600 | 2.60 |
| memory-model | 383 | 160 | 19548 | 7600 | 2.57 |
| rust-hot-path | 596 | 250 | 19558 | 7600 | 2.57 |
| rust-callback-bounds | 612 | 260 | 19567 | 7600 | 2.57 |
| rust-iterator-impl | 592 | 250 | 19411 | 7500 | 2.59 |
| rust-async-internals | 616 | 260 | 19432 | 7500 | 2.59 |
| rust-variance | 595 | 250 | 19453 | 7500 | 2.59 |
| rust-sanitizers-miri | 504 | 210 | 19370 | 7500 | 2.58 |
| rust-security | 518 | 220 | 19363 | 7500 | 2.58 |
| rust-pin-projection | 597 | 250 | 19327 | 7500 | 2.58 |
| rust-macros | 538 | 220 | 19401 | 7500 | 2.59 |
| rust-crate-release | 431 | 180 | 19330 | 7500 | 2.58 |
| rust-wasm | 449 | 190 | 19483 | 7500 | 2.60 |
| rust-serde | 589 | 240 | 19065 | 7400 | 2.58 |
| rust-crate-architecture | 511 | 220 | 19061 | 7400 | 2.58 |
| rust-compiler-errors | 804 | 330 | 19209 | 7400 | 2.60 |
| rust-observability | 461 | 200 | 19030 | 7400 | 2.57 |
| rust-embedded-no-std | 426 | 180 | 18768 | 7300 | 2.57 |
| rust-copy-on-write | 523 | 230 | 18945 | 7300 | 2.60 |
| rust-lints | 473 | 200 | 18805 | 7300 | 2.58 |
| ffi-error-progress-cancel | 560 | 240 | 18483 | 7200 | 2.57 |
| rust-type-erasure | 505 | 210 | 18480 | 7200 | 2.57 |
| rust-performance | 446 | 190 | 18485 | 7200 | 2.57 |
| rust-discipline | 348 | 150 | 18303 | 7100 | 2.58 |
| rust-test-tools | 555 | 230 | 18458 | 7100 | 2.60 |
| rust-debugging | 443 | 190 | 18233 | 7100 | 2.57 |
| rust-cli | 409 | 170 | 18314 | 7100 | 2.58 |
| rust-native-linking | 455 | 190 | 18384 | 7100 | 2.59 |
| uniffi-boundary | 638 | 260 | 18016 | 7000 | 2.57 |
| uniffi-packaging-versioning | 666 | 280 | 17913 | 6900 | 2.60 |
| rust-tdd | 411 | 170 | 17783 | 6900 | 2.58 |
| rust-send-sync | 568 | 240 | 17932 | 6900 | 2.60 |
| rust-ios-build | 631 | 260 | 17237 | 6700 | 2.57 |
| cargo-workflows | 547 | 230 | 17072 | 6600 | 2.59 |
| rust-code-style | 397 | 170 | 16331 | 6300 | 2.59 |
| rust-pattern-semantics | 388 | 170 | 14663 | 5700 | 2.57 |
| rust-borrow-semantics | 485 | 210 | 11483 | 4400 | 2.61 |
