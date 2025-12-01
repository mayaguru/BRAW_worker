#include "image_writer.h"

#include <algorithm>
#include <fstream>
#include <iostream>

namespace braw {

namespace {
uint16_t clamp_to_uint16(float value) {
    float clamped = std::clamp(value, 0.0f, 1.0f);
    return static_cast<uint16_t>(clamped * 65535.0f + 0.5f);
}
}  // namespace

bool write_ppm(const std::filesystem::path& output_path, const FrameBuffer& buffer) {
    if (buffer.format != FramePixelFormat::kRGBFloat32) {
        std::cerr << "현재는 RGB float32 버퍼만 지원합니다.\n";
        return false;
    }

    std::ofstream stream(output_path, std::ios::binary);
    if (!stream) {
        std::cerr << "파일 열기 실패: " << output_path << "\n";
        return false;
    }

    stream << "P6\n" << buffer.width << " " << buffer.height << "\n65535\n";

    const auto data = buffer.as_span();
    for (size_t i = 0; i < data.size(); i += 3) {
        const uint16_t r = clamp_to_uint16(data[i + 0]);
        const uint16_t g = clamp_to_uint16(data[i + 1]);
        const uint16_t b = clamp_to_uint16(data[i + 2]);
        stream.put(static_cast<char>(r >> 8));
        stream.put(static_cast<char>(r & 0xFF));
        stream.put(static_cast<char>(g >> 8));
        stream.put(static_cast<char>(g & 0xFF));
        stream.put(static_cast<char>(b >> 8));
        stream.put(static_cast<char>(b & 0xFF));
    }

    return stream.good();
}

}  // namespace braw
