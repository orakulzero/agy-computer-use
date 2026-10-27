# AGY Computer Use & GUI Grounding Operational Rules

1. Maintain 100% English-only source, documentation, and commit messages.
2. Normalize all pointer coordinates through the `[0, 1000] x [0, 1000]` bijective grid (`normalize_to_grid_1000` / `denormalize_from_grid_1000`) and preserve the `(0, 0)` top-left fail-safe abort guard.
3. Verify GUI state transitions via the 64-bit perceptual dHash `VisualActionOracle` (`[FACT]` for Hamming delta `>= 2` bits, `[NO_EFFECT]` for `< 2` bits) and record RFC 6962 Merkle audit receipts.
4. Route lifecycle hooks through the single-process `agy-golden-stack` / `agy-doctor-mux` dispatcher.
