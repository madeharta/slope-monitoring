# MAGRIS RTKLIB Update Policy

## Production engine strategy

MAGRIS shall use one approved RTKLIB engine release
per supported runtime platform.

Historical and experimental engines shall not be
maintained as permanent production services.

## Current replacement candidate

- Engine: RTKLIB-EX
- Version: 2.5.1
- Tag: v2.5.1
- Commit: 62d4677ed8425a4e2748c6d390b500d1afb493fc
- Build status: PASS
- Scientific acceptance: PENDING
- Production approval: NOT GRANTED

## Upstream monitoring

- Check official releases weekly.
- Review relevant security advisories upon discovery.
- Review development changes monthly.
- Prefer official releases over development commits
  when scientific and operational acceptance is equivalent.

## Immutable dependency requirements

Record the exact source commit, source archive checksum,
builder image digest, compiler version, build configuration,
binary checksums and accepted runtime image digest.

Unpinned builds from moving branches are prohibited.

## Update acceptance gates

1. Verify source identity and review release changes.
2. Perform an isolated controlled build.
3. Verify binary integrity and runtime compatibility.
4. Run independent RAWX-to-RINEX reconciliation.
5. Validate GNSS signal identity and observation accounting.
6. Run PPK regression and repeatability tests.
7. Validate independent accuracy and uncertainty.
8. Complete application and operational regression tests.
9. Complete shadow processing without live publication.
10. Obtain explicit production approval.

Scientific acceptance criteria shall be defined before
candidate evaluation.

## Deployment policy

Automatic production engine upgrades are prohibited.

New releases may trigger candidate evaluation but shall
not modify production binaries, configuration, data or
published displacement without explicit approval.

Maintain immutable historical artifacts and rollback
procedures. Historical engine results remain associated
with their original processing provenance.

## Research data governance

Raw GNSS measurements, credentials and private field
datasets shall not be committed to the application repo.

Automated tests shall use approved synthetic fixtures
or explicitly authorized private research datasets.

## Implementation status

Upstream monitoring and automated CI validation are
planned controls and are not yet operational.
