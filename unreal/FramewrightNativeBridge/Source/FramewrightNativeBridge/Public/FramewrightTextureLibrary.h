#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "FramewrightTextureLibrary.generated.h"

class UTexture2D;

USTRUCT(BlueprintType)
struct FRAMEWRIGHTNATIVEBRIDGE_API FFramewrightTextureReadiness
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category="Framewright")
    bool Ready = false;

    UPROPERTY(BlueprintReadOnly, Category="Framewright")
    FString Error;

    UPROPERTY(BlueprintReadOnly, Category="Framewright")
    int32 TextureCount = 0;

    UPROPERTY(BlueprintReadOnly, Category="Framewright")
    int32 PendingBefore = 0;

    UPROPERTY(BlueprintReadOnly, Category="Framewright")
    int32 PendingAfter = 0;
};

UCLASS()
class FRAMEWRIGHTNATIVEBRIDGE_API UFramewrightTextureLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /** Blocks only on the validated pilot texture set. No import, save or setting changes. */
    UFUNCTION(BlueprintCallable, Category="Framewright")
    static FFramewrightTextureReadiness FinishOwnedTextures(
        const TArray<UTexture2D*>& Textures, const FString& PackageRoot);
};
