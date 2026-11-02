# Native texture readiness

The unreleased adapter now finishes compilation of its owned textures before
reading platform dimensions. Cold texture getters can otherwise report a 32px
placeholder for an 8K asset. Source-size metadata alone does not prove readiness.

This requires the editor-only **FramewrightNativeBridge** companion. The Python
adapter requires its active owner lease, exact texture identities and owned paths
before calling the bridge. The bridge validates the entire batch, rejects invalid
pilot namespaces, null/transient/duplicate/foreign textures, PIE and batches over
4096, then calls Unreal's targeted texture compilation API. It returns before/after
pending counts. No global asset-compilation barrier, save, import or setting change
is performed. Empty texture sets need no bridge. Missing or incomplete readiness
fails before dimensions are accepted; the adapter never silently falls back.

Successful native inspection and apply receipts include `texture_readiness`, with
scope `owned_texture_platform_data`, texture count, pending counts and ready state.
This proves CPU platform-data readiness, not complete shader compilation, GPU
residency, decoded pixel equivalence or rendered appearance. The call is synchronous;
an owned background editor needs an outer process deadline for stalled native work.

## Install or build

The current [0.2.0 Win64 companion](../artifacts/native-uv-precision-20261101/framewright-native-bridge-0.2.0-ue5.8.3-win64.zip)
includes source and the small editor DLL. It targets the installed Unreal 5.8.3
build with module build ID `55116800`. It is separate from the sealed Blender 0.9
ZIP, which is unchanged. Extract `FramewrightNativeBridge` into the intended
project's `Plugins` directory and explicitly enable it, or use these launch options
for an authorized disposable process without editing its project descriptor:

```text
-PLUGIN="<absolute-path>/FramewrightNativeBridge/FramewrightNativeBridge.uplugin"
-EnablePlugins=FramewrightNativeBridge
```

These instructions do not authorize installation into Sundown. The validation used
only the already-authorized disposable project. The descriptor uses compatibility
version `5.8.0`, which this 5.8.3 installation reports for plugin compatibility;
the adapter's actual runtime target remains 5.8.3. Other builds require rebuilding
and validation, not reuse of an incompatible DLL.

Source is under [unreal/FramewrightNativeBridge](../unreal/FramewrightNativeBridge/README.md).
Use the installed engine's `RunUAT.bat BuildPlugin -Plugin=<descriptor> -Package=<new-short-output-path>
-HostPlatforms=Win64 -NoTargetPlatforms -StrictIncludes`. Choose a new output folder:
Unreal's packaging command clears an existing destination. This machine's default
VS 2026 toolchain lacked standard headers; the successful build used the existing
VS 2022 toolchain 14.44.35207, SDK 10.0.22621.0, no PCH/unity and four compiler slots.
The retained build command records the explicit UBT toolchain override. No engine
source, global toolchain configuration or game project was edited.

## Evidence and limits

The original [0.1.0 build](../artifacts/native-readiness-20261101/framewright-native-bridge-0.1.0-ue5.8.3-win64.zip)
remains historical evidence. The current importer requires 0.2.0's additional
[full-precision pipeline helper](native-uv-precision.md), even without textures.
The empty-texture-set exemption above applies only to texture readback.

[Receipt](../artifacts/verification/native-readiness-20261101.json): 12 new focused
Python cases plus 64 affected cases pass on standalone Python 3.15.2. An initial
temporary-directory setup error was corrected; only its 31 affected cases reran.
Ruff passes. The C++ bridge compiles with strict includes. Initial path-length,
toolchain and plugin compatibility failures are retained; they are not successes.

The fresh native check took 19.79 seconds. All three original 8K textures started
at **32×32**, with **three pending** builds; production adapter inspection finished
them to **8192×8192**, with **zero pending**. The original geometry/settings gates
pass, and five invalid native batches reject before work. The empty-batch control
passes. All 208 pinned code/binary/project/asset files remain unchanged; Initial is
restored. No texture rebake, native import, render or save occurred.

The bridge's batch boundaries and targeted engine API are verified. A separate
concurrently compiling unrelated asset was not instrumented. Broader shader/GPU
readiness, lighting, full geometry/collision/LOD, runtime and
art acceptance remain open. No full suite or 8K bake was repeated.

The [six-region normal follow-up](native-normal-validation.md) now passes atlas
and direct exports with sensitive controls, using this production texture bridge.
