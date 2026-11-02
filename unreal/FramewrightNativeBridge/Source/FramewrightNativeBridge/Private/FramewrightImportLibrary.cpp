#include "FramewrightImportLibrary.h"

#include "Editor.h"
#include "InterchangeGenericAssetsPipeline.h"
#include "InterchangeManager.h"
#include "UObject/Package.h"

UInterchangePipelineBase* UFramewrightImportLibrary::CreateFullPrecisionGLTFPipeline()
{
    if (!IsInGameThread() || !GEditor || GEditor->PlayWorld)
    {
        return nullptr;
    }
    const FSoftObjectPath FixedPipeline(TEXT(
        "/Interchange/Pipelines/DefaultGLTFSceneAssetsPipeline.DefaultGLTFSceneAssetsPipeline"));
    const UInterchangeGenericAssetsPipeline* Original =
        Cast<UInterchangeGenericAssetsPipeline>(FixedPipeline.TryLoad());
    if (!Original || !Original->CommonMeshesProperties)
    {
        return nullptr;
    }
    UInterchangeGenericAssetsPipeline* Copy = Cast<UInterchangeGenericAssetsPipeline>(
        UE::Interchange::GeneratePipelineInstance(FixedPipeline));
    if (!Copy || Copy == Original || Copy->GetOutermost() != GetTransientPackage()
        || !Copy->CommonMeshesProperties
        || Copy->CommonMeshesProperties == Original->CommonMeshesProperties)
    {
        return nullptr;
    }
    Copy->CommonMeshesProperties->bUseFullPrecisionUVs = true;
    return Copy;
}
