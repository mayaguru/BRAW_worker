#include "exr_writer.h"

#include <cmath>
#include <iostream>
#include <vector>

#if OPENEXR_AVAILABLE
#include <Imath/half.h>
#include <OpenEXR/ImfChannelList.h>
#include <OpenEXR/ImfFrameBuffer.h>
#include <OpenEXR/ImfOutputFile.h>
#include <OpenEXR/ImfStandardAttributes.h>
#endif

#if OCIO_AVAILABLE
#include <OpenColorIO/OpenColorIO.h>
namespace OCIO = OCIO_NAMESPACE;
#endif

namespace braw {

namespace {

#if OPENEXR_AVAILABLE
bool validate_buffer(const FrameBuffer& buffer) {
    if (buffer.format != FramePixelFormat::kRGBFloat32) {
        std::cerr << "EXR 출력은 RGB float32 버퍼만 지원합니다.\n";
        return false;
    }
    if (buffer.width == 0 || buffer.height == 0) {
        std::cerr << "잘못된 해상도입니다.\n";
        return false;
    }
    return true;
}
#endif

}  // namespace

// Rec.709 감마 커브 적용 (linear → gamma 2.4)
static float apply_rec709_gamma(float linear) {
    if (linear < 0.0f) return 0.0f;
    if (linear < 0.018f) {
        return linear * 4.5f;
    }
    return 1.099f * std::pow(linear, 0.45f) - 0.099f;
}

bool write_exr_half_dwaa(const std::filesystem::path& output_path,
                         const FrameBuffer& buffer,
                         float dwa_compression,
                         const std::string& input_colorspace,
                         const std::string& output_colorspace,
                         bool apply_gamma) {
#if !OPENEXR_AVAILABLE
    (void)output_path;
    (void)buffer;
    (void)dwa_compression;
    (void)input_colorspace;
    (void)output_colorspace;
    (void)apply_gamma;
    std::cerr << "OpenEXR 라이브러리가 구성되지 않았습니다.\n";
    return false;
#else
    if (!validate_buffer(buffer)) {
        return false;
    }

    try {
        const size_t pixel_count = static_cast<size_t>(buffer.width) * static_cast<size_t>(buffer.height);

        // 색공간 변환 (옵션)
        std::vector<float> transformed_data;
        const float* source_data = buffer.as_span().data();

        // 색공간 변환 (OCIO 사용)
#if OCIO_AVAILABLE
        if (!input_colorspace.empty() && !output_colorspace.empty()) {
            try {
                // 외부 config 파일 사용 (절대 경로)
                const char* config_file = "P:/00-GIGA/BRAW_CLI/studio-config-v2.1.0_aces-v1.3_ocio-v2.1.ocio";
                std::cout << "[INFO] OCIO config 로드: " << config_file << "\n";
                auto config = OCIO::Config::CreateFromFile(config_file);

                std::cout << "[INFO] 색공간 변환: " << input_colorspace << " → " << output_colorspace << "\n";
                auto processor = config->getProcessor(input_colorspace.c_str(), output_colorspace.c_str());
                auto cpu = processor->getDefaultCPUProcessor();

                // 변환 데이터 준비
                transformed_data.resize(pixel_count * 3);
                std::copy(source_data, source_data + pixel_count * 3, transformed_data.begin());

                // OCIO 변환 적용
                OCIO::PackedImageDesc img(
                    transformed_data.data(),
                    static_cast<long>(buffer.width),
                    static_cast<long>(buffer.height),
                    OCIO::ChannelOrdering::CHANNEL_ORDERING_RGB,
                    OCIO::BitDepth::BIT_DEPTH_F32,
                    sizeof(float),
                    sizeof(float) * 3,
                    sizeof(float) * 3 * buffer.width
                );
                cpu->apply(img);

                source_data = transformed_data.data();
                std::cout << "[INFO] 색공간 변환 완료\n";
            } catch (const std::exception& e) {
                std::cerr << "[ERROR] OCIO 색공간 변환 실패: " << e.what() << "\n";
            }
        }
#else
        if (!input_colorspace.empty()) {
            std::cerr << "[WARNING] OCIO 미설치 - 색공간 변환 불가\n";
        }
#endif

        // 뷰포트 감마 적용 (Rec.709)
        std::vector<float> gamma_data;
        if (apply_gamma) {
            const size_t total_floats = pixel_count * 3;
            gamma_data.reserve(total_floats);
            gamma_data.resize(total_floats);
            // 새 버퍼에 감마 적용된 값 복사
            for (size_t i = 0; i < total_floats; ++i) {
                gamma_data[i] = apply_rec709_gamma(source_data[i]);
            }
            source_data = gamma_data.data();
            std::cout << "[INFO] Rec.709 감마 커브 적용 완료\n";
        }

        // float32 → half 변환
        std::vector<Imath::half> channels[3];
        for (auto& ch : channels) {
            ch.resize(pixel_count);
        }

        for (size_t i = 0; i < pixel_count; ++i) {
            channels[0][i] = Imath::half(source_data[i * 3 + 0]);
            channels[1][i] = Imath::half(source_data[i * 3 + 1]);
            channels[2][i] = Imath::half(source_data[i * 3 + 2]);
        }

        Imf::Header header(buffer.width, buffer.height);
        header.compression() = Imf::DWAA_COMPRESSION;
        Imf::addDwaCompressionLevel(header, dwa_compression);
        header.channels().insert("R", Imf::Channel(Imf::HALF));
        header.channels().insert("G", Imf::Channel(Imf::HALF));
        header.channels().insert("B", Imf::Channel(Imf::HALF));

        Imf::FrameBuffer frame_buffer;
        const size_t xStride = sizeof(Imath::half);
        const size_t yStride = xStride * buffer.width;
        frame_buffer.insert("R", Imf::Slice(Imf::HALF,
                                            reinterpret_cast<char*>(channels[0].data()),
                                            xStride,
                                            yStride));
        frame_buffer.insert("G", Imf::Slice(Imf::HALF,
                                            reinterpret_cast<char*>(channels[1].data()),
                                            xStride,
                                            yStride));
        frame_buffer.insert("B", Imf::Slice(Imf::HALF,
                                            reinterpret_cast<char*>(channels[2].data()),
                                            xStride,
                                            yStride));

        Imf::OutputFile file(output_path.string().c_str(), header);
        file.setFrameBuffer(frame_buffer);
        file.writePixels(static_cast<int>(buffer.height));
        return true;
    } catch (const std::exception& e) {
        std::cerr << "EXR 저장 실패: " << e.what() << "\n";
        return false;
    }
#endif
}

}  // namespace braw
