#include "braw_decoder.h"

#include <cmath>
#include <filesystem>
#include <iostream>
#include <optional>

#ifdef BRAW_SDK_AVAILABLE
#include <algorithm>
#include <condition_variable>
#include <mutex>
#include <string>

#include <Windows.h>
#include <combaseapi.h>
#include <objbase.h>
#include <oleauto.h>

#ifndef INITGUID
#define INITGUID
#endif
#include "BlackmagicRawAPI.h"
#include "BlackmagicRawAPIDispatch.h"
#endif

namespace braw {

namespace {

#ifdef BRAW_SDK_AVAILABLE
void log_hresult(const char* message, HRESULT hr) {
    std::cerr << message << " (HRESULT=0x" << std::hex << hr << std::dec << ")\n";
}

class FrameDecodeCallback final : public IBlackmagicRawCallback {
  public:
    explicit FrameDecodeCallback(FrameBuffer& buffer) : buffer_(buffer) {}
    FrameDecodeCallback(const FrameDecodeCallback&) = delete;
    FrameDecodeCallback& operator=(const FrameDecodeCallback&) = delete;

    bool wait_until_completed() {
        std::unique_lock lock(mutex_);
        cv_.wait(lock, [this]() { return completed_; });
        return SUCCEEDED(result_);
    }

    void ReadComplete(IBlackmagicRawJob* job, HRESULT result, IBlackmagicRawFrame* frame) override {
        HRESULT hr = result;
        IBlackmagicRawJob* decode_job = nullptr;

        if (SUCCEEDED(hr)) {
            hr = frame->SetResourceFormat(blackmagicRawResourceFormatRGBAF32);
        }

        if (SUCCEEDED(hr)) {
            hr = frame->CreateJobDecodeAndProcessFrame(nullptr, nullptr, &decode_job);
        }

        if (SUCCEEDED(hr) && decode_job) {
            hr = decode_job->Submit();
        }

        if (decode_job) {
            decode_job->Release();
        }
        if (job) {
            job->Release();
        }

        if (FAILED(hr)) {
            finish(hr);
        }
    }

    void ProcessComplete(IBlackmagicRawJob* job, HRESULT result,
                         IBlackmagicRawProcessedImage* processedImage) override {
        HRESULT hr = result;
        uint32_t width = 0;
        uint32_t height = 0;
        void* resource = nullptr;
        BlackmagicRawResourceFormat format = blackmagicRawResourceFormatRGBAF32;

        if (SUCCEEDED(hr)) {
            hr = processedImage->GetWidth(&width);
        }
        if (SUCCEEDED(hr)) {
            hr = processedImage->GetHeight(&height);
        }
        if (SUCCEEDED(hr)) {
            hr = processedImage->GetResource(&resource);
        }
        if (SUCCEEDED(hr)) {
            hr = processedImage->GetResourceFormat(&format);
        }

        if (SUCCEEDED(hr)) {
            const size_t pixel_count = static_cast<size_t>(width) * static_cast<size_t>(height);
            buffer_.format = FramePixelFormat::kRGBFloat32;
            buffer_.resize(width, height);

            auto span = buffer_.as_span();
            float* dst = span.data();

            const float* src = static_cast<const float*>(resource);
            const uint32_t src_stride = (format == blackmagicRawResourceFormatRGBF32) ? 3u : 4u;

            for (size_t i = 0; i < pixel_count; ++i) {
                dst[i * 3 + 0] = src[i * src_stride + 0];
                dst[i * 3 + 1] = src[i * src_stride + 1];
                dst[i * 3 + 2] = src[i * src_stride + 2];
            }
        }

        if (job) {
            job->Release();
        }

        finish(hr);
    }

    void DecodeComplete(IBlackmagicRawJob*, HRESULT) override {}
    void TrimProgress(IBlackmagicRawJob*, float) override {}
    void TrimComplete(IBlackmagicRawJob*, HRESULT) override {}
    void SidecarMetadataParseWarning(IBlackmagicRawClip*, BSTR, uint32_t, BSTR) override {}
    void SidecarMetadataParseError(IBlackmagicRawClip*, BSTR, uint32_t, BSTR) override {}
    void PreparePipelineComplete(void*, HRESULT) override {}

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) override {
        if (iid == IID_IBlackmagicRawCallback || iid == IID_IUnknown) {
            *out = this;
            return S_OK;
        }
        *out = nullptr;
        return E_NOINTERFACE;
    }

    ULONG STDMETHODCALLTYPE AddRef() override { return 1; }
    ULONG STDMETHODCALLTYPE Release() override { return 1; }

  private:
    void finish(HRESULT hr) {
        {
            std::lock_guard lock(mutex_);
            if (completed_) {
                return;
            }
            completed_ = true;
            result_ = hr;
        }
        cv_.notify_all();
    }

    FrameBuffer& buffer_;
    std::mutex mutex_;
    std::condition_variable cv_;
    bool completed_{false};
    HRESULT result_{E_FAIL};
};

#endif

#ifndef BRAW_SDK_AVAILABLE
void fill_dummy_pattern(const ClipInfo& info, FrameBuffer& out_buffer) {
    const uint32_t width = info.width ? info.width : 640;
    const uint32_t height = info.height ? info.height : 360;
    out_buffer.format = FramePixelFormat::kRGBFloat32;
    out_buffer.resize(width, height);

    auto data = out_buffer.as_span();
    size_t idx = 0;
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            const float u = static_cast<float>(x) / static_cast<float>(width);
            const float v = static_cast<float>(y) / static_cast<float>(height);
            data[idx++] = u;
            data[idx++] = v;
            data[idx++] = 0.5f + 0.5f * std::sin(u * 6.28318f);
        }
    }
}
#endif

}  // namespace

struct BrawDecoder::Impl {
#ifdef BRAW_SDK_AVAILABLE
    IBlackmagicRawFactory* factory{nullptr};
    IBlackmagicRaw* codec{nullptr};
    IBlackmagicRawClip* clip{nullptr};
    IBlackmagicRawClipImmersiveVideo* immersive_clip{nullptr};
    bool com_initialized{false};
    ComThreadingModel threading_model{ComThreadingModel::kMultiThreaded};
    std::wstring sdk_library_dir;

    bool ensure_com() {
        if (com_initialized) {
            return true;
        }

        const DWORD coinit_flags = (threading_model == ComThreadingModel::kMultiThreaded)
            ? COINIT_MULTITHREADED
            : COINIT_APARTMENTTHREADED;

        const HRESULT hr = CoInitializeEx(nullptr, coinit_flags);
        if (hr == RPC_E_CHANGED_MODE || hr == S_FALSE) {
            // 이미 다른 곳에서 COM이 초기화됨 (Qt 등)
            // 문제 없으니 계속 진행
            return true;
        }
        if (FAILED(hr)) {
            log_hresult("COM 초기화 실패", hr);
            return false;
        }
        com_initialized = true;
        return true;
    }

    bool ensure_factory() {
        if (factory && codec) {
            return true;
        }
        if (!ensure_com()) {
            return false;
        }

        BSTR library_bstr = nullptr;
        if (!sdk_library_dir.empty()) {
            library_bstr = SysAllocString(sdk_library_dir.c_str());
        }

        if (!factory) {
            factory = library_bstr ? CreateBlackmagicRawFactoryInstanceFromPath(library_bstr)
                                   : CreateBlackmagicRawFactoryInstance();
        }

        if (library_bstr) {
            SysFreeString(library_bstr);
        }

        if (!factory) {
            std::cerr << "IBlackmagicRawFactory 생성 실패\n";
            return false;
        }

        if (!codec) {
            const HRESULT hr = factory->CreateCodec(&codec);
            if (FAILED(hr) || !codec) {
                log_hresult("IBlackmagicRaw 생성 실패", hr);
                return false;
            }
        }
        return true;
    }

    void release_clip() {
        if (clip) {
            clip->Release();
            clip = nullptr;
        }
        if (immersive_clip) {
            immersive_clip->Release();
            immersive_clip = nullptr;
        }
    }

    void release_all() {
        release_clip();
        if (codec) {
            codec->Release();
            codec = nullptr;
        }
        if (factory) {
            factory->Release();
            factory = nullptr;
        }
        if (com_initialized) {
            CoUninitialize();
            com_initialized = false;
        }
    }
#endif

    std::optional<ClipInfo> info;
};

BrawDecoder::BrawDecoder(ComThreadingModel model) : impl_(std::make_unique<Impl>()) {
#ifdef BRAW_SDK_AVAILABLE
    impl_->threading_model = model;
#ifdef BRAW_SDK_LIBRARY_DIR
    impl_->sdk_library_dir = std::filesystem::path(BRAW_SDK_LIBRARY_DIR).wstring();
#endif
#endif
}

BrawDecoder::~BrawDecoder() {
#ifdef BRAW_SDK_AVAILABLE
    impl_->release_all();
#endif
}

bool BrawDecoder::open_clip(const std::filesystem::path& clip_path) {
    close_clip();

    if (!std::filesystem::exists(clip_path)) {
        std::cerr << "파일이 존재하지 않습니다: " << clip_path << "\n";
        return false;
    }

#ifdef BRAW_SDK_AVAILABLE
    if (!impl_->ensure_factory()) {
        return false;
    }

    BSTR clip_bstr = SysAllocString(clip_path.wstring().c_str());
    IBlackmagicRawClip* clip = nullptr;
    const HRESULT hr = impl_->codec->OpenClip(clip_bstr, &clip);
    SysFreeString(clip_bstr);
    if (FAILED(hr) || !clip) {
        log_hresult("클립 열기 실패", hr);
        return false;
    }

    impl_->release_clip();
    impl_->clip = clip;

    ClipInfo info;
    info.source_path = clip_path;
    unsigned int width = 0;
    unsigned int height = 0;
    float frame_rate = 0.0f;
    unsigned long long frame_count = 0;

    if (SUCCEEDED(clip->GetWidth(&width))) {
        info.width = width;
    }
    if (SUCCEEDED(clip->GetHeight(&height))) {
        info.height = height;
    }
    if (SUCCEEDED(clip->GetFrameRate(&frame_rate))) {
        info.frame_rate = static_cast<double>(frame_rate);
    }
    if (SUCCEEDED(clip->GetFrameCount(&frame_count))) {
        info.frame_count = frame_count;
    }

    IBlackmagicRawClipImmersiveVideo* immersive_clip = nullptr;
    if (SUCCEEDED(clip->QueryInterface(IID_IBlackmagicRawClipImmersiveVideo,
                                       reinterpret_cast<void**>(&immersive_clip))) &&
        immersive_clip) {
        info.has_immersive_video = true;
        info.available_view_count = 2;
        impl_->immersive_clip = immersive_clip;
    } else if (immersive_clip) {
        immersive_clip->Release();
    }

    impl_->info = info;
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

void BrawDecoder::close_clip() {
#ifdef BRAW_SDK_AVAILABLE
    impl_->release_clip();
#endif
    impl_->info.reset();
}

std::optional<ClipInfo> BrawDecoder::clip_info() const { return impl_->info; }

bool BrawDecoder::decode_frame(uint32_t frame_index, FrameBuffer& out_buffer, StereoView view) {
#ifndef BRAW_SDK_AVAILABLE
    const auto info = impl_->info.value_or(ClipInfo{});
    fill_dummy_pattern(info, out_buffer);
    return true;
#else
    if (!impl_->clip || !impl_->codec) {
        std::cerr << "클립 또는 코덱이 초기화되지 않았습니다.\n";
        return false;
    }

    if (impl_->info && frame_index >= impl_->info->frame_count) {
        std::cerr << "프레임 인덱스가 범위를 벗어났습니다.\n";
        return false;
    }

    FrameDecodeCallback callback(out_buffer);
    HRESULT hr = impl_->codec->SetCallback(&callback);
    if (FAILED(hr)) {
        log_hresult("콜백 설정 실패", hr);
        return false;
    }

    IBlackmagicRawJob* read_job = nullptr;
    if (impl_->immersive_clip) {
        const BlackmagicRawImmersiveVideoTrack track =
            (view == StereoView::kRight) ? blackmagicRawImmersiveVideoTrackRight
                                         : blackmagicRawImmersiveVideoTrackLeft;
        hr = impl_->immersive_clip->CreateJobImmersiveReadFrame(track,
                                                               static_cast<unsigned long long>(frame_index),
                                                               &read_job);
    } else {
        if (view == StereoView::kRight) {
            std::cerr << "우안 트랙이 없는 클립입니다. 좌안으로 디코딩합니다.\n";
        }
        hr = impl_->clip->CreateJobReadFrame(static_cast<unsigned long long>(frame_index), &read_job);
    }
    if (FAILED(hr) || !read_job) {
        log_hresult("프레임 읽기 작업 생성 실패", hr);
        impl_->codec->SetCallback(nullptr);
        return false;
    }

    hr = read_job->Submit();
    if (FAILED(hr)) {
        log_hresult("프레임 읽기 작업 제출 실패", hr);
        read_job->Release();
        impl_->codec->SetCallback(nullptr);
        return false;
    }

    impl_->codec->FlushJobs();
    impl_->codec->SetCallback(nullptr);

    if (!callback.wait_until_completed()) {
        std::cerr << "프레임 처리 실패\n";
        return false;
    }

    return true;
#endif
}

void BrawDecoder::flush_jobs() {
#ifdef BRAW_SDK_AVAILABLE
    if (impl_->codec) {
        impl_->codec->FlushJobs();
    }
#endif
}

}  // namespace braw
