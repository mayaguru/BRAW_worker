#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace braw {

enum class FramePixelFormat {
    kRGBFloat32
};

struct FrameBuffer {
    FramePixelFormat format{FramePixelFormat::kRGBFloat32};
    uint32_t width{0};
    uint32_t height{0};
    std::vector<float> data;

    [[nodiscard]] size_t pixel_count() const noexcept {
        return static_cast<size_t>(width) * static_cast<size_t>(height);
    }

    void resize(uint32_t new_width, uint32_t new_height) {
        width = new_width;
        height = new_height;
        data.resize(pixel_count() * 3u);
    }

    [[nodiscard]] std::span<const float> as_span() const noexcept {
        return data;
    }

    [[nodiscard]] std::span<float> as_span() noexcept {
        return data;
    }
};

}  // namespace braw
