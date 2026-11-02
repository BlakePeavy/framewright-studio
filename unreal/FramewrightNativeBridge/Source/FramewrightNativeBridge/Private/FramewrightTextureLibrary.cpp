#include "FramewrightTextureLibrary.h"

#include "Editor.h"
#include "Engine/Texture2D.h"
#include "Misc/PackageName.h"
#include "Modules/ModuleManager.h"
#include "TextureCompiler.h"

IMPLEMENT_MODULE(FDefaultModuleImpl, FramewrightNativeBridge)

FFramewrightTextureReadiness UFramewrightTextureLibrary::FinishOwnedTextures(
    const TArray<UTexture2D*>& Textures, const FString& PackageRoot)
{
    FFramewrightTextureReadiness Result;
    Result.TextureCount = Textures.Num();
    const FString Prefix(TEXT("/Game/FramewrightPilots/"));
    if (!IsInGameThread() || !GEditor || GEditor->PlayWorld)
    {
        Result.Error = TEXT("Requires the editor game thread outside PIE");
        return Result;
    }
    if (!PackageRoot.StartsWith(Prefix) || PackageRoot.Len() == Prefix.Len()
        || PackageRoot.Mid(Prefix.Len()).Contains(TEXT("/"))
        || !FPackageName::IsValidLongPackageName(PackageRoot) || Textures.Num() > 4096)
    {
        Result.Error = TEXT("Invalid pilot namespace or texture budget");
        return Result;
    }
    TSet<UTexture2D*> Unique;
    TArray<UTexture*> CompileTargets;
    // Validate the complete batch before doing any compilation work.
    for (UTexture2D* Texture : Textures)
    {
        if (!IsValid(Texture) || Texture->HasAnyFlags(RF_Transient) || Unique.Contains(Texture)
            || !Texture->GetPathName().StartsWith(PackageRoot + TEXT("/Assets/")))
        {
            Result.Error = TEXT("Null, transient, duplicate or foreign texture");
            return Result;
        }
        Unique.Add(Texture);
        CompileTargets.Add(Texture);
    }
    for (UTexture* Texture : CompileTargets)
    {
        Result.PendingBefore += Texture->IsCompiling() ? 1 : 0;
    }
    if (!CompileTargets.IsEmpty())
    {
        FTextureCompilingManager::Get().FinishCompilation(CompileTargets);
    }
    for (UTexture* Texture : CompileTargets)
    {
        Result.PendingAfter += Texture->IsCompiling() ? 1 : 0;
    }
    Result.Ready = Result.PendingAfter == 0;
    if (!Result.Ready)
    {
        Result.Error = TEXT("Owned texture compilation is still pending");
    }
    return Result;
}
