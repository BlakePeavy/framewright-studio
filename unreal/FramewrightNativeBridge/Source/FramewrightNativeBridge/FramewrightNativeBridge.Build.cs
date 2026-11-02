using UnrealBuildTool;

public class FramewrightNativeBridge : ModuleRules
{
    public FramewrightNativeBridge(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine", "InterchangeCore" });
        PrivateDependencyModuleNames.AddRange(new[] { "UnrealEd", "InterchangeEngine", "InterchangePipelines" });
    }
}
