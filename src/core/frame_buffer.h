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



// SBS(Side-by-Side) 합성: 두 버퍼를 가로로 합침
// 결과: width*2 x height
inline FrameBuffer merge_sbs(const FrameBuffer& left, const FrameBuffer& right) {
    FrameBuffer result;
    result.format = left.format;
    result.width = left.width + right.width;
    result.height = left.height;
    result.data.resize(result.pixel_count() * 3u);

    const uint32_t left_stride = left.width * 3;
    const uint32_t right_stride = right.width * 3;
    const uint32_t result_stride = result.width * 3;

    for (uint32_t y = 0; y < result.height; ++y) {
        // 왼쪽 이미지 복사
        std::copy_n(
            left.data.begin() + y * left_stride,
            left_stride,
            result.data.begin() + y * result_stride
        );
        // 오른쪽 이미지 복사
        std::copy_n(
            right.data.begin() + y * right_stride,
            right_stride,
            result.data.begin() + y * result_stride + left_stride
        );
    }

    return result;
}

}  // namespace braw
