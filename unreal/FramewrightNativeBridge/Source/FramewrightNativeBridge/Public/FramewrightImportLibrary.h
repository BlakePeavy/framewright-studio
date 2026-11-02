#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "FramewrightImportLibrary.generated.h"

class UInterchangePipelineBase;

UCLASS()
class FRAMEWRIGHTNATIVEBRIDGE_API UFramewrightImportLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /** Copy the fixed installed GLTF mesh pipeline into the transient package.
     * Only full UV precision changes. No caller-selected pipeline, import or save.
     */
    UFUNCTION(BlueprintCallable, Category="Framewright")
    static UInterchangePipelineBase* CreateFullPrecisionGLTFPipeline();
};
