#include "braw_decoder.h"

#include <cmath>
#include <iostream>

#ifdef BRAW_SDK_AVAILABLE
#include "BlackmagicRawAPI.h"
#endif

namespace braw {

struct BrawDecoder::Impl {
#ifdef BRAW_SDK_AVAILABLE
    IBlackmagicRawFactory* factory{nullptr};
    IBlackmagicRaw* codec{nullptr};
    IBlackmagicRawClip* clip{nullptr};
    IBlackmagicRawFrameProcessingAttributes* processing_attributes{nullptr};
#endif
    std::optional<ClipInfo> info;

    void reset() {
#ifdef BRAW_SDK_AVAILABLE
        if (processing_attributes) {
            processing_attributes->Release();
            processing_attributes = nullptr;
        }
        if (clip) {
            clip->Release();
            clip = nullptr;
        }
        if (codec) {
            codec->Release();
            codec = nullptr;
        }
        if (factory) {
            factory->Release();
            factory = nullptr;
        }
#endif
        info.reset();
    }
};

BrawDecoder::BrawDecoder() : impl_(std::make_unique<Impl>()) {}

BrawDecoder::~BrawDecoder() { close_clip(); }

bool BrawDecoder::open_clip(const std::filesystem::path& clip_path) {
    close_clip();

    if (!std::filesystem::exists(clip_path)) {
        std::cerr << "파일이 존재하지 않습니다: " << clip_path << "\n";
        return false;
    }

#ifdef BRAW_SDK_AVAILABLE
    impl_->factory = CreateBlackmagicRawFactoryInstance();
    if (!impl_->factory) {
        std::cerr << "BRAW Factory 생성 실패\n";
        return false;
    }

    HRESULT result = impl_->factory->CreateCodec(&impl_->codec);
    if (FAILED(result) || !impl_->codec) {
        std::cerr << "BRAW Codec 생성 실패\n";
        impl_->reset();
        return false;
    }

    result = impl_->codec->OpenClip(clip_path.wstring().c_str(), &impl_->clip);
    if (FAILED(result) || !impl_->clip) {
        std::cerr << "클립 열기 실패\n";
        impl_->reset();
        return false;
    }

    ClipInfo info;
    info.source_path = clip_path;
    uint32_t width = 0;
    uint32_t height = 0;
    impl_->clip->GetWidth(&width);
    impl_->clip->GetHeight(&height);
    info.width = width;
    info.height = height;
    impl_->clip->GetFrameCount(&info.frame_count);
    impl_->clip->GetFrameRate(&info.frame_rate);
    impl_->info = info;

    if (FAILED(impl_->clip->CreateFrameProcessingAttributes(&impl_->processing_attributes))) {
        std::cerr << "프레임 프로세싱 속성 생성 실패\n";
        impl_->reset();
        return false;
    }
    return true;
#else
    ClipInfo info;
    info.source_path = clip_path;
    info.width = 640;
    info.height = 360;
    info.frame_count = 1;
    info.frame_rate = 24.0;
    impl_->info = info;
    std::cerr << "BRAW SDK가 비활성화되어 있으므로 실제 디코딩이 불가합니다. 샘플 데이터를 사용합니다.\n";
    return true;
#endif
}

void BrawDecoder::close_clip() { impl_->reset(); }

std::optional<ClipInfo> BrawDecoder::clip_info() const { return impl_->info; }

bool BrawDecoder::decode_frame(uint32_t frame_index, FrameBuffer& out_buffer) {
#ifndef BRAW_SDK_AVAILABLE
    (void)frame_index;
    const auto info = impl_->info.value_or(ClipInfo{});
    const uint32_t width = info.width ? info.width : 640;
    const uint32_t height = info.height ? info.height : 360;
    out_buffer.format = FramePixelFormat::kRGBFloat32;
    out_buffer.resize(width, height);

    auto data = out_buffer.as_span();
    size_t idx = 0;
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            float u = static_cast<float>(x) / static_cast<float>(width);
            float v = static_cast<float>(y) / static_cast<float>(height);
            data[idx++] = u;
            data[idx++] = v;
            data[idx++] = 0.5f + 0.5f * std::sin(u * 6.28318f);
        }
    }
    return true;
#else
    if (!impl_->clip) {
        std::cerr << "클립이 열려있지 않습니다.\n";
        return false;
    }

    // TODO: 실제 BRAW 디코딩 작업 구현 필요.
    (void)frame_index;
    (void)out_buffer;
    std::cerr << "decode_frame 구현이 필요합니다.\n";
    return false;
#endif
}

}  // namespace braw
