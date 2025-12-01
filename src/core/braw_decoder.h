#pragma once

#include <filesystem>
#include <memory>
#include <optional>
#include <string>

#include "frame_buffer.h"

namespace braw {

struct DecoderSettings {
    float white_balance_temperature{5600.0f};
    float white_balance_tint{10.0f};
    float iso{800.0f};
    float exposure_adjust{0.0f};
    bool use_gpu{true};
};

enum class StereoView {
    kLeft = 0,
    kRight = 1
};

struct ClipInfo {
    std::filesystem::path source_path;
    uint32_t width{0};
    uint32_t height{0};
    uint64_t frame_count{0};
    double frame_rate{0.0};
    uint32_t available_view_count{1};
    bool has_immersive_video{false};
};

class BrawDecoder {
  public:
    BrawDecoder();
    ~BrawDecoder();

    BrawDecoder(const BrawDecoder&) = delete;
    BrawDecoder& operator=(const BrawDecoder&) = delete;

    bool open_clip(const std::filesystem::path& clip_path);
    void close_clip();

    [[nodiscard]] std::optional<ClipInfo> clip_info() const;
    [[nodiscard]] DecoderSettings& settings() { return settings_; }

    bool decode_frame(uint32_t frame_index, FrameBuffer& out_buffer, StereoView view = StereoView::kLeft);

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    DecoderSettings settings_;
};

}  // namespace braw
