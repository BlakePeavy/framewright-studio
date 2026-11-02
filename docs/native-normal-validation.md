# Native normal transport and sensitivity

The original cabinet's subtle grain could not make a corrupted normal control
fail. A stronger six-region fixture now verifies both **public atlas→GLB** and
**direct source→GLB** normal transport through cold Unreal 5.8.3. This closes the
bounded sensitivity gap; it does not grant full appearance or art acceptance.

The editable diagnostic contains six meshes / 264 triangles: regular, mirrored-U,
rotated-90° and mirrored-V flat patches, plus regular and mirrored-U smooth curved
patches. An authored 256px, 16-bit asymmetric tangent normal field has substantial
X and Y components. Atlas mode uses the public 1K/default-16 bake with declared
padding and literal-value preservation. Direct mode retains original UV layouts
and source texture, with no rebake. Both use the public `asset.export` command.

The reference is the actual source shader's world-normal field, converted into
Unreal coordinates and saved as linear EXR. Each region's mask comes from a source
object-ID render, eroded two pixels and fixed before native capture. Every region
is checked independently across **51,726** interior pixels total, using unchanged
limits of **mean ≤1° / P95 ≤3°**. No large easy region can dilute a smaller failure.

| Region | Atlas native mean / P95 | Direct native mean / P95 |
|---|---:|---:|
| Flat regular | 0.075° / 0.130° | 0.082° / 0.158° |
| Flat mirrored U | 0.084° / 0.156° | 0.084° / 0.159° |
| Flat rotated 90° | 0.078° / 0.138° | 0.083° / 0.158° |
| Flat mirrored V | 0.085° / 0.155° | 0.077° / 0.150° |
| Curved regular | 0.157° / 0.320° | 0.157° / 0.292° |
| Curved mirrored U | 0.179° / 0.332° | 0.154° / 0.295° |

Both native paths pass every region. Maximum observed error is 2.232° for the atlas
and 0.526° for direct export. Cold Blender GLB checks also preserve identities,
hierarchy, transforms and triangle counts, and pass every source-normal region.
Source→atlas worst region mean/P95 is 0.072°/0.122°; the original source is preserved.

Transient native material instances set `NormalScale` to 0, then -1. Every region
rejects both controls: disabled mean error is 34.8–35.3°, inverted mean error is
69.6–70.7°. Original bindings are restored before final inspection. The extraction
pipeline's 0.25 scalar calibration remains exact. No control or capture is saved
into the asset packages.

## Evidence and scope

[Receipt](../artifacts/verification/native-normal-20261101.json) retains the editable
fixture, source/atlas/direct GLBs, masks, raw float captures, controls, scripts,
hashes and native reports. The new acceptance helper passes five focused tests for
weak controls, a single failed region, missing/undercovered evidence and invalid
vectors. Existing angular-metric tests/evidence are reused; no full suite ran.
No production runtime code or command inventory changed in this increment.

One successful 1K bake/export took 54.83 seconds. Direct export took 2.70 seconds
and reused the same source captures. Each path has its own import and fresh cold
native worker; all four workers take about 16 seconds each. The first source
attempt stopped at the decoded-image preflight guard; explicit CPU image decoding
resolved it, and its completed source captures were reused. No 8K bake was repeated.

Both new package namespaces are inside the authorized disposable project. All 352
pinned files, including earlier fixture assets, remain unchanged after the cold
checks. Each nine-package import is retained. Production scoped texture readiness
runs before inspection. The global shader barrier is used only by the owned render
harness; production shader/GPU readiness remains open. Sundown is unchanged.

This verifies front-facing opaque static normal transport at the declared camera
and sampling. It does not cover every seam, hard edge, scale/transform, backface,
shader family, animation, distant mip or platform. The original cabinet's weak
control remains insufficient and is retained as failed evidence. Linked-map mip
behavior, physical lighting, full source→native mesh data, collision/LOD, game
performance and independently reviewed artwork remain separate requirements.

![Native atlas world-normal diagnostic](../artifacts/native-normal-20261101/native-cold/normal.png)
