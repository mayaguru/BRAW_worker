#include "exr_writer.h"

#include <iostream>
#include <vector>

#if OPENEXR_AVAILABLE
#include <Imath/half.h>
#include <OpenEXR/ImfChannelList.h>
#include <OpenEXR/ImfFrameBuffer.h>
#include <OpenEXR/ImfOutputFile.h>
#include <OpenEXR/ImfStandardAttributes.h>
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

bool write_exr_half_dwaa(const std::filesystem::path& output_path,
                         const FrameBuffer& buffer,
                         float dwa_compression) {
#if !OPENEXR_AVAILABLE
    (void)output_path;
    (void)buffer;
    (void)dwa_compression;
    std::cerr << "OpenEXR 라이브러리가 구성되지 않았습니다.\n";
    return false;
#else
    if (!validate_buffer(buffer)) {
        return false;
    }

    try {
        const size_t pixel_count = static_cast<size_t>(buffer.width) * static_cast<size_t>(buffer.height);
        std::vector<Imath::half> channels[3];
        for (auto& ch : channels) {
            ch.resize(pixel_count);
        }

        const auto data = buffer.as_span();
        for (size_t i = 0; i < pixel_count; ++i) {
            channels[0][i] = Imath::half(data[i * 3 + 0]);
            channels[1][i] = Imath::half(data[i * 3 + 1]);
            channels[2][i] = Imath::half(data[i * 3 + 2]);
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
