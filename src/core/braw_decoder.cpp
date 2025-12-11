#include "braw_decoder.h"

#include <cmath>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <optional>
#include <thread>
#include <vector>

#ifdef BRAW_SDK_AVAILABLE
#include <algorithm>
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

#ifdef CUDA_AVAILABLE
#include <cuda.h>
#include <cuda_runtime.h>
#endif
#endif

namespace braw {

namespace {

#ifdef BRAW_SDK_AVAILABLE
void log_hresult(const char* message, HRESULT hr) {
    std::cerr << message << " (HRESULT=0x" << std::hex << hr << std::dec << ")" << std::endl;
}

constexpr int DECODE_TIMEOUT_MS = 30000;

#ifdef CUDA_AVAILABLE
static void* g_cuda_context = nullptr;
static bool g_gpu_pipeline_ready = false;
#endif

class SyncFrameCallback final : public IBlackmagicRawCallback {
  public:
    explicit SyncFrameCallback() = default;

    void reset() {
        std::lock_guard<std::mutex> lock(mutex_);
        completed_ = false;
        succeeded_ = false;
        result_buffer_ = nullptr;
    }

    void set_target_buffer(FrameBuffer* buffer) {
        std::lock_guard<std::mutex> lock(mutex_);
        result_buffer_ = buffer;
    }

    bool wait_for_completion(int timeout_ms = DECODE_TIMEOUT_MS) {
        std::unique_lock<std::mutex> lock(mutex_);
        return cv_.wait_for(lock, std::chrono::milliseconds(timeout_ms),
                           [this] { return completed_; });
    }

    bool succeeded() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return succeeded_;
    }

    void ReadComplete(IBlackmagicRawJob* job, HRESULT result, IBlackmagicRawFrame* frame) override {
        IBlackmagicRawJob* decode_job = nullptr;

        if (SUCCEEDED(result)) {
            result = frame->SetResourceFormat(blackmagicRawResourceFormatRGBF32);
        }

        if (SUCCEEDED(result)) {
            // GPU pipeline이 준비되면 SDK가 자동으로 GPU 사용
            result = frame->CreateJobDecodeAndProcessFrame(nullptr, nullptr, &decode_job);
        }

        if (SUCCEEDED(result) && decode_job) {
            result = decode_job->Submit();
        }

        if (FAILED(result)) {
            if (decode_job) {
                decode_job->Release();
            }
            std::lock_guard<std::mutex> lock(mutex_);
            succeeded_ = false;
            completed_ = true;
            cv_.notify_all();
        }

        job->Release();
    }

    void ProcessComplete(IBlackmagicRawJob* job, HRESULT result,
                         IBlackmagicRawProcessedImage* processedImage) override {
        bool success = false;

        if (SUCCEEDED(result)) {
            uint32_t width = 0;
            uint32_t height = 0;
            void* resource = nullptr;

            if (SUCCEEDED(processedImage->GetWidth(&width)) &&
                SUCCEEDED(processedImage->GetHeight(&height)) &&
                SUCCEEDED(processedImage->GetResource(&resource))) {

                // Check if resource is on GPU and need to copy to CPU
                BlackmagicRawResourceType resource_type = blackmagicRawResourceTypeBufferCPU;
                processedImage->GetResourceType(&resource_type);

                void* cpu_resource = resource;
#ifdef CUDA_AVAILABLE
                std::vector<float> gpu_copy_buffer;
                if (resource_type == blackmagicRawResourceTypeBufferCUDA && g_gpu_pipeline_ready) {
                    const size_t pixel_count = static_cast<size_t>(width) * static_cast<size_t>(height);
                    const size_t data_size = pixel_count * 3 * sizeof(float);
                    gpu_copy_buffer.resize(pixel_count * 3);

                    // Copy from GPU to CPU using CUDA
                    cudaError_t cuda_err = cudaMemcpy(gpu_copy_buffer.data(), resource,
                                                      data_size, cudaMemcpyDeviceToHost);
                    if (cuda_err == cudaSuccess) {
                        cpu_resource = gpu_copy_buffer.data();
                    } else {
                        std::cerr << "cudaMemcpy failed: " << cudaGetErrorString(cuda_err) << std::endl;
                        cpu_resource = nullptr;
                    }
                }
#endif

                if (cpu_resource) {
                    std::lock_guard<std::mutex> lock(mutex_);
                    if (result_buffer_) {
                        const size_t pixel_count = static_cast<size_t>(width) * static_cast<size_t>(height);
                        result_buffer_->format = FramePixelFormat::kRGBFloat32;
                        result_buffer_->resize(width, height);

                        auto span = result_buffer_->as_span();
                        std::memcpy(span.data(), cpu_resource, pixel_count * 3 * sizeof(float));
                        success = true;
                    }
                }
            }
        }

        job->Release();

        {
            std::lock_guard<std::mutex> lock(mutex_);
            succeeded_ = success;
            completed_ = true;
        }
        cv_.notify_all();
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
    mutable std::mutex mutex_;
    std::condition_variable cv_;
    bool completed_{false};
    bool succeeded_{false};
    FrameBuffer* result_buffer_{nullptr};
};

#endif  // BRAW_SDK_AVAILABLE

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

    SyncFrameCallback callback;
    bool callback_set{false};

#ifdef CUDA_AVAILABLE
    bool init_gpu_pipeline() {
        if (g_gpu_pipeline_ready) return true;

        CUresult cu_result = cuInit(0);
        if (cu_result != CUDA_SUCCESS) {
            std::cerr << "Failed to initialize CUDA driver" << std::endl;
            return false;
        }

        int device_count = 0;
        if (cuDeviceGetCount(&device_count) != CUDA_SUCCESS || device_count == 0) {
            std::cerr << "No CUDA devices found, using CPU decoding" << std::endl;
            return false;
        }

        CUdevice cuda_device;
        if (cuDeviceGet(&cuda_device, 0) != CUDA_SUCCESS) {
            std::cerr << "Failed to get CUDA device" << std::endl;
            return false;
        }

        char device_name[256];
        cuDeviceGetName(device_name, 255, cuda_device);
        std::cerr << "Using GPU: " << device_name << std::endl;

        CUcontext ctx;
        cu_result = cuCtxCreate(&ctx, CU_CTX_MAP_HOST | CU_CTX_SCHED_BLOCKING_SYNC, cuda_device);
        if (cu_result != CUDA_SUCCESS) {
            std::cerr << "Failed to create CUDA context (error: " << cu_result << ")" << std::endl;
            return false;
        }
        g_cuda_context = ctx;

        if (codec) {
            // Use IBlackmagicRawConfiguration::SetPipeline instead of PreparePipeline
            IBlackmagicRawConfiguration* config = nullptr;
            HRESULT hr = codec->QueryInterface(IID_IBlackmagicRawConfiguration,
                                                reinterpret_cast<void**>(&config));
            if (SUCCEEDED(hr) && config) {
                hr = config->SetPipeline(blackmagicRawPipelineCUDA, g_cuda_context, nullptr);
                config->Release();
                if (SUCCEEDED(hr)) {
                    g_gpu_pipeline_ready = true;
                    std::cerr << "GPU pipeline ready (CUDA)" << std::endl;
                    return true;
                } else {
                    log_hresult("SetPipeline(CUDA) failed", hr);
                }
            } else {
                log_hresult("Failed to get IBlackmagicRawConfiguration", hr);
            }
            cuCtxDestroy(ctx);
            g_cuda_context = nullptr;
        }
        return false;
    }

    void release_gpu() {
        if (g_cuda_context) {
            cuCtxDestroy(static_cast<CUcontext>(g_cuda_context));
            g_cuda_context = nullptr;
        }
        g_gpu_pipeline_ready = false;
    }
#endif

    bool ensure_com() {
        if (com_initialized) {
            return true;
        }

        const DWORD coinit_flags = (threading_model == ComThreadingModel::kMultiThreaded)
            ? COINIT_MULTITHREADED
            : COINIT_APARTMENTTHREADED;

        const HRESULT hr = CoInitializeEx(nullptr, coinit_flags);
        if (hr == RPC_E_CHANGED_MODE || hr == S_FALSE) {
            return true;
        }
        if (FAILED(hr)) {
            log_hresult("COM initialization failed", hr);
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
            std::cerr << "Failed to create IBlackmagicRawFactory" << std::endl;
            return false;
        }

        if (!codec) {
            const HRESULT hr = factory->CreateCodec(&codec);
            if (FAILED(hr) || !codec) {
                log_hresult("Failed to create IBlackmagicRaw", hr);
                return false;
            }

#ifdef CUDA_AVAILABLE
            init_gpu_pipeline();
#endif
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
        callback_set = false;
    }

    void release_all() {
        release_clip();
        if (codec) {
            codec->FlushJobs();
            codec->Release();
            codec = nullptr;
        }
#ifdef CUDA_AVAILABLE
        release_gpu();
#endif
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
        std::cerr << "File does not exist: " << clip_path << std::endl;
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
        log_hresult("Failed to open clip", hr);
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

    HRESULT cb_hr = impl_->codec->SetCallback(&impl_->callback);
    if (FAILED(cb_hr)) {
        log_hresult("Failed to set callback", cb_hr);
        return false;
    }
    impl_->callback_set = true;

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
    std::cerr << "BRAW SDK is disabled, actual decoding not available." << std::endl;
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
        std::cerr << "Clip or codec not initialized." << std::endl;
        return false;
    }

    if (!impl_->callback_set) {
        std::cerr << "Callback not set." << std::endl;
        return false;
    }

    if (impl_->info && frame_index >= impl_->info->frame_count) {
        std::cerr << "Frame index out of range." << std::endl;
        return false;
    }

    impl_->callback.reset();
    impl_->callback.set_target_buffer(&out_buffer);

    IBlackmagicRawJob* read_job = nullptr;
    HRESULT hr;

    if (impl_->immersive_clip) {
        const BlackmagicRawImmersiveVideoTrack track =
            (view == StereoView::kRight) ? blackmagicRawImmersiveVideoTrackRight
                                         : blackmagicRawImmersiveVideoTrackLeft;
        hr = impl_->immersive_clip->CreateJobImmersiveReadFrame(
            track, static_cast<unsigned long long>(frame_index), &read_job);
    } else {
        hr = impl_->clip->CreateJobReadFrame(
            static_cast<unsigned long long>(frame_index), &read_job);
    }

    if (FAILED(hr) || !read_job) {
        log_hresult("Failed to create read frame job", hr);
        return false;
    }

    hr = read_job->Submit();
    if (FAILED(hr)) {
        log_hresult("Failed to submit read frame job", hr);
        read_job->Release();
        return false;
    }

    if (!impl_->callback.wait_for_completion(DECODE_TIMEOUT_MS)) {
        std::cerr << "Frame decoding timeout" << std::endl;
        return false;
    }

    return impl_->callback.succeeded();
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
