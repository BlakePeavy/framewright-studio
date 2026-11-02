# Framewright Native Bridge

Editor-only companion 0.2.0 for Framewright's Unreal integration. Tested on Windows
with Unreal 5.8.3, module build ID `55116800`. It completes compilation for a
validated owned texture set and creates a transient copy of the fixed installed
GLTF mesh pipeline with full-precision UVs. Neither helper imports or saves assets.
The installed engine pipeline and existing assets remain unchanged.

Enable this plugin in an authorized Unreal project before using the current native
adapter. It is separate from the Blender extension and disabled by default.
The descriptor's `5.8.0` is this engine's compatibility version, not an additional
tested application target. Rebuild and validate against a different engine build.

See [installation and texture readiness](../../docs/native-texture-readiness.md)
and [full-precision import evidence](../../docs/native-uv-precision.md).
Source is GPL-3.0-or-later, as documented in the repository LICENSE.
