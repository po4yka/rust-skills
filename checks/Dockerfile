# Development-only environment. Run from the repository root; see checks/README.md.
FROM node:26-trixie-slim AS node
FROM rust:1.100.0-slim-trixie

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates git python3 \
    gcc-x86-64-linux-gnu g++-x86-64-linux-gnu \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# The container can run natively on ARM64. Only example type checks target x86_64.
# Debian trixie supplies Python 3.13. PyO3 needs the target version when HOST differs.
ENV CC_x86_64_unknown_linux_gnu=x86_64-linux-gnu-gcc \
    CXX_x86_64_unknown_linux_gnu=x86_64-linux-gnu-g++ \
    AR_x86_64_unknown_linux_gnu=x86_64-linux-gnu-ar \
    PYO3_CROSS_PYTHON_VERSION=3.13 \
    CARGO_TARGET_DIR=/tmp/rust-skills-target
COPY checks/rust-toolchain.toml /tmp/toolchain/rust-toolchain.toml
RUN cd /tmp/toolchain && rustup show active-toolchain \
    && rustup toolchain install 1.99.1 --profile minimal \
    && git config --system --add safe.directory /work
WORKDIR /work
CMD ["bash", "checks/check.sh"]
