#include <filesystem>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

#include "core/braw_decoder.h"
#include "export/image_writer.h"

namespace {

struct Arguments {
    std::filesystem::path clip_path;
    std::filesystem::path output_path;
    uint32_t frame_index{0};
};

std::optional<Arguments> parse_arguments(int argc, char** argv) {
    if (argc < 3) {
        std::cerr << "사용법: braw_cli <clip.braw> <output.ppm> [frame_index]\n";
        return std::nullopt;
    }

    Arguments args;
    args.clip_path = argv[1];
    args.output_path = argv[2];
    if (argc >= 4) {
        args.frame_index = static_cast<uint32_t>(std::stoul(argv[3]));
    }

    return args;
}

}  // namespace

int main(int argc, char** argv) {
    const auto args = parse_arguments(argc, argv);
    if (!args) {
        return 1;
    }

    braw::BrawDecoder decoder;
    if (!decoder.open_clip(args->clip_path)) {
        std::cerr << "클립을 열 수 없습니다: " << args->clip_path << "\n";
        return 1;
    }

    braw::FrameBuffer buffer;
    if (!decoder.decode_frame(args->frame_index, buffer)) {
        std::cerr << "프레임 디코딩 실패: " << args->frame_index << "\n";
        return 1;
    }

    if (!braw::write_ppm(args->output_path, buffer)) {
        std::cerr << "이미지 저장 실패: " << args->output_path << "\n";
        return 1;
    }

    if (const auto info = decoder.clip_info()) {
        std::cout << "출력 완료: " << args->output_path << "\n"
                  << "프레임 " << args->frame_index << " / 총 " << info->frame_count << "\n"
                  << "해상도 " << info->width << "x" << info->height << "\n";
    }

    return 0;
}
