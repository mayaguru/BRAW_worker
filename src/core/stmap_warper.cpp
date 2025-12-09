#include "stmap_warper.h"

#include <OpenEXR/ImfInputFile.h>
#include <OpenEXR/ImfRgbaFile.h>
#include <OpenEXR/ImfArray.h>
#include <OpenEXR/ImfHeader.h>
#include <OpenEXR/ImfChannelList.h>
#include <OpenEXR/ImfFrameBuffer.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>

namespace braw {

bool STMapWarper::load_stmap(const std::filesystem::path& exr_path) {
    try {
        // 캐시 파일 확인
        auto cache_path = exr_path;
        cache_path.replace_extension(".stcache");

        // 캐시가 존재하고 원본보다 최신이면 캐시 사용
        if (std::filesystem::exists(cache_path)) {
            auto exr_time = std::filesystem::last_write_time(exr_path);
            auto cache_time = std::filesystem::last_write_time(cache_path);
            if (cache_time >= exr_time && load_cache(cache_path)) {
                return true;
            }
        }

        // EXR 파일 열기
        Imf::InputFile file(exr_path.string().c_str());
        const Imf::Header& header = file.header();
        const Imath::Box2i& dataWindow = header.dataWindow();

        const uint32_t width = dataWindow.max.x - dataWindow.min.x + 1;
        const uint32_t height = dataWindow.max.y - dataWindow.min.y + 1;

        // R, G 채널 확인
        const Imf::ChannelList& channels = header.channels();
        bool has_r = channels.findChannel("R") != nullptr;
        bool has_g = channels.findChannel("G") != nullptr;

        if (!has_r || !has_g) {
            return false;
        }

        // RGBA로 읽기 (간단하게)
        Imf::Array2D<Imf::Rgba> pixels(height, width);
        Imf::RgbaInputFile rgba_file(exr_path.string().c_str());
        rgba_file.setFrameBuffer(&pixels[0][0] - dataWindow.min.x - dataWindow.min.y * width, 1, width);
        rgba_file.readPixels(dataWindow.min.y, dataWindow.max.y);

        // RG만 추출 (ST 좌표)
        stmap_.width = width;
        stmap_.height = height;
        stmap_.data.resize(width * height * 2);

        for (uint32_t y = 0; y < height; ++y) {
            for (uint32_t x = 0; x < width; ++x) {
                const Imf::Rgba& pixel = pixels[y][x];
                const size_t idx = (y * width + x) * 2;
                stmap_.data[idx + 0] = pixel.r;  // U (S)
                stmap_.data[idx + 1] = pixel.g;  // V (T)
            }
        }

        // 캐시 저장
        save_cache(cache_path);

        return true;
    } catch (...) {
        stmap_ = {};
        return false;
    }
}

bool STMapWarper::save_cache(const std::filesystem::path& cache_path) const {
    if (!stmap_.is_valid()) {
        return false;
    }

    std::ofstream file(cache_path, std::ios::binary);
    if (!file) {
        return false;
    }

    // 매직 넘버
    const char magic[] = "STMC";
    file.write(magic, 4);

    // 버전
    const uint32_t version = 1;
    file.write(reinterpret_cast<const char*>(&version), sizeof(version));

    // 크기
    file.write(reinterpret_cast<const char*>(&stmap_.width), sizeof(stmap_.width));
    file.write(reinterpret_cast<const char*>(&stmap_.height), sizeof(stmap_.height));

    // 데이터
    file.write(reinterpret_cast<const char*>(stmap_.data.data()),
               stmap_.data.size() * sizeof(float));

    return file.good();
}

bool STMapWarper::load_cache(const std::filesystem::path& cache_path) {
    std::ifstream file(cache_path, std::ios::binary);
    if (!file) {
        return false;
    }

    // 매직 넘버 확인
    char magic[4];
    file.read(magic, 4);
    if (std::memcmp(magic, "STMC", 4) != 0) {
        return false;
    }

    // 버전 확인
    uint32_t version;
    file.read(reinterpret_cast<char*>(&version), sizeof(version));
    if (version != 1) {
        return false;
    }

    // 크기 읽기
    uint32_t width, height;
    file.read(reinterpret_cast<char*>(&width), sizeof(width));
    file.read(reinterpret_cast<char*>(&height), sizeof(height));

    // 데이터 읽기
    stmap_.width = width;
    stmap_.height = height;
    stmap_.data.resize(width * height * 2);
    file.read(reinterpret_cast<char*>(stmap_.data.data()),
              stmap_.data.size() * sizeof(float));

    return file.good();
}

void STMapWarper::sample_st(float fx, float fy, float& out_u, float& out_v) const {
    if (!stmap_.is_valid()) {
        out_u = fx / stmap_.width;
        out_v = fy / stmap_.height;
        return;
    }

    fx = std::clamp(fx, 0.0f, static_cast<float>(stmap_.width - 1));
    fy = std::clamp(fy, 0.0f, static_cast<float>(stmap_.height - 1));

    const int x0 = static_cast<int>(std::floor(fx));
    const int y0 = static_cast<int>(std::floor(fy));
    const int x1 = std::min(x0 + 1, static_cast<int>(stmap_.width - 1));
    const int y1 = std::min(y0 + 1, static_cast<int>(stmap_.height - 1));

    const float tx = fx - static_cast<float>(x0);
    const float ty = fy - static_cast<float>(y0);

    // 4개 코너 샘플링
    const float* p00 = &stmap_.data[(y0 * stmap_.width + x0) * 2];
    const float* p10 = &stmap_.data[(y0 * stmap_.width + x1) * 2];
    const float* p01 = &stmap_.data[(y1 * stmap_.width + x0) * 2];
    const float* p11 = &stmap_.data[(y1 * stmap_.width + x1) * 2];

    // Bilinear 보간
    const float u_top = p00[0] + (p10[0] - p00[0]) * tx;
    const float v_top = p00[1] + (p10[1] - p00[1]) * tx;
    const float u_bottom = p01[0] + (p11[0] - p01[0]) * tx;
    const float v_bottom = p01[1] + (p11[1] - p01[1]) * tx;

    out_u = u_top + (u_bottom - u_top) * ty;
    out_v = v_top + (v_bottom - v_top) * ty;
}

void STMapWarper::sample_source_float(const float* src_data, uint32_t width, uint32_t height,
                                       float sx, float sy, float* out_rgb) const {
    sx = std::clamp(sx, 0.0f, static_cast<float>(width - 1));
    sy = std::clamp(sy, 0.0f, static_cast<float>(height - 1));

    const int x0 = static_cast<int>(std::floor(sx));
    const int y0 = static_cast<int>(std::floor(sy));
    const int x1 = std::min(x0 + 1, static_cast<int>(width - 1));
    const int y1 = std::min(y0 + 1, static_cast<int>(height - 1));

    const float tx = sx - static_cast<float>(x0);
    const float ty = sy - static_cast<float>(y0);

    const float* p00 = src_data + (y0 * width + x0) * 3;
    const float* p10 = src_data + (y0 * width + x1) * 3;
    const float* p01 = src_data + (y1 * width + x0) * 3;
    const float* p11 = src_data + (y1 * width + x1) * 3;

    for (int c = 0; c < 3; ++c) {
        const float top = p00[c] + (p10[c] - p00[c]) * tx;
        const float bottom = p01[c] + (p11[c] - p01[c]) * tx;
        out_rgb[c] = top + (bottom - top) * ty;
    }
}

void STMapWarper::sample_source_rgb888(const uint8_t* src_data, uint32_t width, uint32_t height,
                                        float sx, float sy, uint8_t* out_rgb) const {
    sx = std::clamp(sx, 0.0f, static_cast<float>(width - 1));
    sy = std::clamp(sy, 0.0f, static_cast<float>(height - 1));

    const int x0 = static_cast<int>(std::floor(sx));
    const int y0 = static_cast<int>(std::floor(sy));
    const int x1 = std::min(x0 + 1, static_cast<int>(width - 1));
    const int y1 = std::min(y0 + 1, static_cast<int>(height - 1));

    const float tx = sx - static_cast<float>(x0);
    const float ty = sy - static_cast<float>(y0);

    const uint8_t* p00 = src_data + (y0 * width + x0) * 3;
    const uint8_t* p10 = src_data + (y0 * width + x1) * 3;
    const uint8_t* p01 = src_data + (y1 * width + x0) * 3;
    const uint8_t* p11 = src_data + (y1 * width + x1) * 3;

    for (int c = 0; c < 3; ++c) {
        const float top = static_cast<float>(p00[c]) + (static_cast<float>(p10[c]) - static_cast<float>(p00[c])) * tx;
        const float bottom = static_cast<float>(p01[c]) + (static_cast<float>(p11[c]) - static_cast<float>(p01[c])) * tx;
        const float value = top + (bottom - top) * ty;
        out_rgb[c] = static_cast<uint8_t>(std::clamp(value + 0.5f, 0.0f, 255.0f));
    }
}

void STMapWarper::apply_warp(const float* src_data, float* dst_data,
                              uint32_t width, uint32_t height) const {
    if (!enabled_ || !stmap_.is_valid()) {
        // 워핑 비활성화 시 복사만
        std::memcpy(dst_data, src_data, width * height * 3 * sizeof(float));
        return;
    }

    const float map_scale_x = static_cast<float>(stmap_.width - 1) / static_cast<float>(width - 1);
    const float map_scale_y = static_cast<float>(stmap_.height - 1) / static_cast<float>(height - 1);

    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            // 현재 픽셀의 ST 맵 좌표
            const float map_x = static_cast<float>(x) * map_scale_x;
            const float map_y = static_cast<float>(y) * map_scale_y;

            // ST 좌표 샘플링 (0~1 범위의 UV)
            float u, v;
            sample_st(map_x, map_y, u, v);

            // UV를 소스 이미지 좌표로 변환
            // V 좌표를 뒤집음 (STMAP은 OpenGL 스타일 - 아래에서 위로)
            const float src_x = u * static_cast<float>(width - 1);
            const float src_y = (1.0f - v) * static_cast<float>(height - 1);

            // 소스 샘플링
            float* dst_pixel = dst_data + (y * width + x) * 3;
            sample_source_float(src_data, width, height, src_x, src_y, dst_pixel);
        }
    }
}

void STMapWarper::apply_warp_rgb888(const uint8_t* src_data, uint8_t* dst_data,
                                     uint32_t width, uint32_t height) const {
    if (!enabled_ || !stmap_.is_valid()) {
        std::memcpy(dst_data, src_data, width * height * 3);
        return;
    }

    const float map_scale_x = static_cast<float>(stmap_.width - 1) / static_cast<float>(width - 1);
    const float map_scale_y = static_cast<float>(stmap_.height - 1) / static_cast<float>(height - 1);

    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            const float map_x = static_cast<float>(x) * map_scale_x;
            const float map_y = static_cast<float>(y) * map_scale_y;

            float u, v;
            sample_st(map_x, map_y, u, v);

            // V 좌표를 뒤집음 (STMAP은 OpenGL 스타일 - 아래에서 위로)
            const float src_x = u * static_cast<float>(width - 1);
            const float src_y = (1.0f - v) * static_cast<float>(height - 1);

            uint8_t* dst_pixel = dst_data + (y * width + x) * 3;
            sample_source_rgb888(src_data, width, height, src_x, src_y, dst_pixel);
        }
    }
}


void STMapWarper::apply_warp_rgb888_square(const uint8_t* src_data, uint32_t src_width, uint32_t src_height,
                                            uint8_t* dst_data, uint32_t out_size) const {
    if (!enabled_ || !stmap_.is_valid()) {
        // 비활성화 시 중앙 크롭하여 정사각형으로 복사
        const uint32_t offset_x = (src_width - out_size) / 2;
        const uint32_t offset_y = (src_height - out_size) / 2;
        for (uint32_t y = 0; y < out_size; ++y) {
            const uint8_t* src_row = src_data + ((y + offset_y) * src_width + offset_x) * 3;
            uint8_t* dst_row = dst_data + y * out_size * 3;
            std::memcpy(dst_row, src_row, out_size * 3);
        }
        return;
    }

    // STMAP 좌표를 정사각형 출력에 맞게 매핑
    const float map_scale_x = static_cast<float>(stmap_.width - 1) / static_cast<float>(out_size - 1);
    const float map_scale_y = static_cast<float>(stmap_.height - 1) / static_cast<float>(out_size - 1);

    for (uint32_t y = 0; y < out_size; ++y) {
        for (uint32_t x = 0; x < out_size; ++x) {
            const float map_x = static_cast<float>(x) * map_scale_x;
            const float map_y = static_cast<float>(y) * map_scale_y;

            float u, v;
            sample_st(map_x, map_y, u, v);

            // V 좌표를 뒤집음 (STMAP은 OpenGL 스타일 - 아래에서 위로)
            const float src_x = u * static_cast<float>(src_width - 1);
            const float src_y = (1.0f - v) * static_cast<float>(src_height - 1);

            uint8_t* dst_pixel = dst_data + (y * out_size + x) * 3;
            sample_source_rgb888(src_data, src_width, src_height, src_x, src_y, dst_pixel);
        }
    }
}

void STMapWarper::apply_warp_float_square(const float* src_data, uint32_t src_width, uint32_t src_height,
                                           float* dst_data, uint32_t out_size) const {
    if (!enabled_ || !stmap_.is_valid()) {
        // 비활성화 시 중앙 크롭하여 정사각형으로 복사
        const uint32_t offset_x = (src_width - out_size) / 2;
        const uint32_t offset_y = (src_height - out_size) / 2;
        for (uint32_t y = 0; y < out_size; ++y) {
            const float* src_row = src_data + ((y + offset_y) * src_width + offset_x) * 3;
            float* dst_row = dst_data + y * out_size * 3;
            std::memcpy(dst_row, src_row, out_size * 3 * sizeof(float));
        }
        return;
    }

    // STMAP 좌표를 정사각형 출력에 맞게 매핑
    const float map_scale_x = static_cast<float>(stmap_.width - 1) / static_cast<float>(out_size - 1);
    const float map_scale_y = static_cast<float>(stmap_.height - 1) / static_cast<float>(out_size - 1);

    for (uint32_t y = 0; y < out_size; ++y) {
        for (uint32_t x = 0; x < out_size; ++x) {
            const float map_x = static_cast<float>(x) * map_scale_x;
            const float map_y = static_cast<float>(y) * map_scale_y;

            float u, v;
            sample_st(map_x, map_y, u, v);

            // V 좌표를 뒤집음 (STMAP은 OpenGL 스타일 - 아래에서 위로)
            const float src_x = u * static_cast<float>(src_width - 1);
            const float src_y = (1.0f - v) * static_cast<float>(src_height - 1);

            float* dst_pixel = dst_data + (y * out_size + x) * 3;
            sample_source_float(src_data, src_width, src_height, src_x, src_y, dst_pixel);
        }
    }
}

}  // namespace braw
