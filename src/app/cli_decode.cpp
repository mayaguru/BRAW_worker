#include <algorithm>
#include <cctype>
#include <filesystem>
#include <iostream>
#include <optional>
#include <string>
#include <string_view>
#include <vector>
#include <cwctype>

#include "core/braw_decoder.h"
#include "export/exr_writer.h"
#include "export/image_writer.h"

namespace {

enum class EyeMode { kLeft, kRight, kBoth };

enum class OutputFormat { kPPM, kEXR };

struct Arguments {
    std::filesystem::path clip_path;
    std::filesystem::path output_path;
    uint32_t frame_index{0};
    EyeMode eye_mode{EyeMode::kLeft};
    OutputFormat format{OutputFormat::kPPM};
};

std::optional<EyeMode> parse_eye_mode(const std::string& token) {
    std::string lower = token;
    std::transform(lower.begin(), lower.end(), lower.begin(),
                   [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });

    if (lower == "left" || lower == "l") {
        return EyeMode::kLeft;
    }
    if (lower == "right" || lower == "r") {
        return EyeMode::kRight;
    }
    if (lower == "both" || lower == "stereo" || lower == "lr") {
        return EyeMode::kBoth;
    }
    return std::nullopt;
}

std::optional<Arguments> parse_arguments(int argc, char** argv) {
    if (argc < 3) {
        std::cerr << "사용법: braw_cli <clip.braw> <output.(ppm|exr)> [frame_index] [eye(left|right|both)]\n";
        return std::nullopt;
    }

    Arguments args;
    args.clip_path = argv[1];
    args.output_path = argv[2];
    const auto ext = args.output_path.extension().wstring();
    if (!ext.empty()) {
        std::wstring lower;
        lower.reserve(ext.size());
        for (wchar_t ch : ext) {
            lower.push_back(static_cast<wchar_t>(std::towlower(ch)));
        }
        if (lower == L".exr") {
            args.format = OutputFormat::kEXR;
        }
    }
    if (argc >= 4) {
        args.frame_index = static_cast<uint32_t>(std::stoul(argv[3]));
    }
    if (argc >= 5) {
        auto mode = parse_eye_mode(argv[4]);
        if (!mode) {
            std::cerr << "알 수 없는 시야 옵션입니다. left/right/both 중 하나를 사용하세요.\n";
            return std::nullopt;
        }
        args.eye_mode = *mode;
    }

    return args;
}

std::filesystem::path build_stereo_path(const std::filesystem::path& base, std::string_view suffix) {
    const auto parent = base.parent_path();
    const auto stem = base.stem().string();
    const auto ext = base.extension().string();
    std::filesystem::path file_name = stem + std::string(suffix) + ext;
    return parent / file_name;
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

    const auto info = decoder.clip_info();
    if (args->eye_mode == EyeMode::kBoth) {
        if (!info || !info->has_immersive_video || info->available_view_count < 2) {
            std::cerr << "해당 클립은 좌/우 트랙을 제공하지 않습니다.\n";
            return 1;
        }
    }

auto decode_and_write = [&](braw::StereoView view, const std::filesystem::path& output_path) -> bool {
        braw::FrameBuffer buffer;
        if (!decoder.decode_frame(args->frame_index, buffer, view)) {
            std::cerr << "프레임 디코딩 실패: " << args->frame_index << "\n";
            return false;
        }
        bool ok = false;
        if (args->format == OutputFormat::kEXR) {
            ok = braw::write_exr_half_dwaa(output_path, buffer, 45.0f);
        } else {
            ok = braw::write_ppm(output_path, buffer);
        }
        if (!ok) {
            std::cerr << "이미지 저장 실패: " << output_path << "\n";
            return false;
        }
        std::cout << "출력 완료 (" << (view == braw::StereoView::kRight ? "우안" : "좌안") << "): " << output_path << "\n";
        return true;
    };

    if (args->eye_mode == EyeMode::kBoth) {
        const auto left_path = build_stereo_path(args->output_path, "_L");
        const auto right_path = build_stereo_path(args->output_path, "_R");
        if (!decode_and_write(braw::StereoView::kLeft, left_path)) {
            return 1;
        }
        if (!decode_and_write(braw::StereoView::kRight, right_path)) {
            return 1;
        }
    } else {
        const braw::StereoView view =
            (args->eye_mode == EyeMode::kRight) ? braw::StereoView::kRight : braw::StereoView::kLeft;
        if (!decode_and_write(view, args->output_path)) {
            return 1;
        }
    }

    if (info) {
        const char* format = (args->format == OutputFormat::kEXR) ? "EXR (f16 DWAA45)" : "PPM";
        std::cout << "프레임 " << args->frame_index << " / 총 " << info->frame_count << "\n"
                  << "해상도 " << info->width << "x" << info->height << "  "
                  << "Views: " << info->available_view_count << " (" << (info->has_immersive_video ? "stereo" : "mono")
                  << ")  Format: " << format << "\n";
    }

    return 0;
}
