# RTKLIB Dependency Governance

## Purpose

Track RTKLIB source and build provenance for MAGRIS GNSS
processing and PPK scientific validation.

## Candidate status

The candidate source lock identifies research candidates only.
Neither candidate is approved for production use.

- Upstream RTKLIB 2.4.3 b34: comparison control.
- RTKLIB Explorer: primary multifrequency decoder candidate.
- Legacy RTKLIB 2.4.2: frozen experimental binary control.

## Legacy limitation

The exact source commit and complete build configuration
of the legacy binary have not been established.

## Build requirements

Every controlled build must record:

- Exact source repository and commit.
- Source tree and verified source archive.
- Builder image digest and target platform.
- Compiler and build dependency versions.
- Effective compiler and linker flags.
- Binary checksums.
- Regression and scientific acceptance results.

An accepted-build-lock.json must only be created after
the applicable acceptance gates have passed.

Production builds must not use floating source branches.

## Data governance

Raw GNSS measurements, coordinates, operational credentials,
field evidence and private research datasets must remain
outside the dependency repository.

Upstream license and copyright notices must be retained
in distributed derivative builds as required.

## Scientific limitations

Signal mapping is supported by official UBX specifications,
but receiver-specific firmware provenance must be verified.

Numeric phase correspondence alone does not establish
correct signal identity or absolute positioning accuracy.
