#pragma once

#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace braw {

// ST Map 데이터 (float RG 채널로 UV 좌표 저장)
struct STMapData {
    std::vector<float> data;  // RG 채널만 (2 floats per pixel)
    uint32_t width{0};
    uint32_t height{0};

    bool is_valid() const { return !data.empty() && width > 0 && height > 0; }
};

// ST Map Warper - 왜곡 보정 처리
class STMapWarper {
  public:
    STMapWarper() = default;
    ~STMapWarper() = default;

    // STMAP EXR 파일 로드 (RG 채널)
    bool load_stmap(const std::filesystem::path& exr_path);

    // 바이너리 캐시 저장/로드 (빠른 로딩용)
    bool save_cache(const std::filesystem::path& cache_path) const;
    bool load_cache(const std::filesystem::path& cache_path);

    // 워핑 적용 (RGB float32 버퍼)
    // src_data: RGB float32 소스 이미지
    // dst_data: RGB float32 출력 버퍼 (미리 할당 필요)
    // width, height: 이미지 크기
    void apply_warp(const float* src_data, float* dst_data, uint32_t width, uint32_t height) const;

    // QImage에 워핑 적용 (RGB888)
    void apply_warp_rgb888(const uint8_t* src_data, uint8_t* dst_data, uint32_t width, uint32_t height) const;

    bool is_loaded() const { return stmap_.is_valid(); }
    uint32_t map_width() const { return stmap_.width; }
    uint32_t map_height() const { return stmap_.height; }

    // 활성화 상태
    void set_enabled(bool enabled) { enabled_ = enabled; }
    bool is_enabled() const { return enabled_; }

  private:
    // Bilinear 샘플링으로 ST 좌표 가져오기
    void sample_st(float fx, float fy, float& out_u, float& out_v) const;

    // Bilinear 샘플링으로 소스 픽셀 가져오기 (float RGB)
    void sample_source_float(const float* src_data, uint32_t width, uint32_t height,
                              float sx, float sy, float* out_rgb) const;

    // Bilinear 샘플링으로 소스 픽셀 가져오기 (RGB888)
    void sample_source_rgb888(const uint8_t* src_data, uint32_t width, uint32_t height,
                               float sx, float sy, uint8_t* out_rgb) const;

    STMapData stmap_;
    bool enabled_{false};
};

}  // namespace braw
