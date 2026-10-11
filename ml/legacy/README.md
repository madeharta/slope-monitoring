# Legacy ML Artifacts

This directory contains historical ML implementations retained only for
reproducibility, audit, and research comparison.

Code under `ml/legacy/` MUST NOT be used as the active production or
real-data training path unless explicitly restored through a reviewed change.

## gcn_v2_6_0

Original/static GCN v2.6.0 implementation and its checkpoint.

Status:

- historical/reproducibility artifact;
- feature schema is incompatible with the current real ITB sensor contract;
- not a starting checkpoint for the new GAT model;
- not production prediction evidence;
- not operational alarm input.

The current real-data research baseline is `ml/models/gcn_slope_v1/`.
The proposed research model is the new real-data GAT pipeline.
