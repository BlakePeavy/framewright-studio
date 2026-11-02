# Export identity and cold-hidden static transforms

The 0.9 candidate corrects two failures exposed by the refined cabinet handoff.
The public command remains `asset.export`; no additional command is introduced.

## FBX object identity

Blender's installed FBX importer rewrites object names exceeding 63 UTF-8 bytes.
Export staging now reserves deterministic aliases within that limit, including
multibyte names and collisions with existing Blender objects. Short available
aliases keep their previous spelling. The export receipt records the exact
source-to-export mapping; the original source names remain unchanged. GLB naming
retains its existing behavior.

This bounds object labels only. Long mesh-data and material labels can still be
rewritten on FBX import. Actual stored bone names, skin groups and material slots
survive the focused fixture; arbitrary naming behavior is not certified.

## Cold-hidden static hierarchies

A saved hidden assembly can have stale evaluated world matrices after reopening.
For complete, ordinary object-parented mesh/empty hierarchies without animation
or constraints, export now derives receipts from authored transform channels and
parent inverses. Owned staging copies retain those channels, then update after
their dependency graph exists. Original visibility, cached matrices, geometry,
UVs, materials and hierarchy stay unchanged.

Animated, skinned, constrained, mixed or bone-parented cases use the existing
export path. Their cold-hidden behavior is outside this new certification.

## Verification

Seven new regression methods and 44 existing methods passed in the isolated
repair. Tests cover UTF-8 boundaries, deterministic occupancy collisions,
receipt identity, hidden parent transforms and exact source preservation.
The retained refined 2K atlas also passed the unchanged cold FBX identity,
hierarchy, geometry and image gates without rebaking or unhiding its sources.
Its full/detail RGB MAE was 0.000000488/0.000000239, with both P95 values zero.
The [closed repair receipt](../artifacts/development09/export-repair/artifacts/final-receipt.json)
pins the retained regression evidence. The [retention manifest](../artifacts/evidence-retention-0.9.json)
also identifies externally retained reproduction inputs; historical absolute paths
have not been rewritten inside copied records.

The initial deeply nested temporary directory caused three file-open errors;
the unchanged affected suite passed with a short owned TEMP. Both outcomes are
retained in the repair evidence. `scripts/test_export_names.py` is included in
the combined 0.9 aggregate. Combined package and refined-material public-path
verification are separate gates; no engine or artistic acceptance is implied.
