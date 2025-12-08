#include <algorithm>
#include <cctype>
#include <filesystem>
#include <iostream>
#include <optional>
#include <string>
#include <string_view>
#include <vector>
#include <cwctype>

#ifdef _WIN32
#include <Windows.h>
#include <combaseapi.h>
#endif

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
    bool use_aces{false};  // 색공간 변환 사용 여부
    bool apply_gamma{false};  // 뷰포트 감마 (Rec.709) 적용 여부
    std::string input_colorspace{"BMDFilm WideGamut Gen5"};  // 고정값
    std::string output_colorspace{"ACEScg"};
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
    // --info 모드 체크
    if (argc >= 3 && std::string(argv[2]) == "--info") {
        Arguments args;
        args.clip_path = argv[1];
        args.output_path = "--info";  // 특수 마커
        return args;
    }

    if (argc < 3) {
        std::cerr << "사용법: braw_cli <clip.braw> <output.(ppm|exr)> [frame_index] [eye(left|right|both)]\n";
        std::cerr << "또는:   braw_cli <clip.braw> --info\n";
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

    // 플래그 파싱 (모든 인자 검사)
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--aces") {
            args.use_aces = true;
        } else if (arg == "--gamma") {
            args.apply_gamma = true;
        } else if (arg.rfind("--input-cs=", 0) == 0) {
            args.input_colorspace = arg.substr(11);
        } else if (arg.rfind("--output-cs=", 0) == 0) {
            args.output_colorspace = arg.substr(12);
        }
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
#ifdef _WIN32
    // Initialize COM explicitly before anything else (SDK pattern)
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr) && hr != RPC_E_CHANGED_MODE && hr != S_FALSE) {
        std::cerr << "COM initialization failed: 0x" << std::hex << hr << std::dec << "\n";
        return 1;
    }
    std::cout << "[DEBUG] 0. COM initialized\n";
#endif

    const auto args = parse_arguments(argc, argv);
    if (!args) {
        return 1;
    }

    std::cout << "[DEBUG] 1. Arguments parsed\n";

    braw::BrawDecoder decoder(braw::ComThreadingModel::kMultiThreaded);
    std::cout << "[DEBUG] 2. Decoder created\n";

    if (!decoder.open_clip(args->clip_path)) {
        std::cerr << "클립을 열 수 없습니다: " << args->clip_path << "\n";
        return 1;
    }

    std::cout << "[DEBUG] 3. Clip opened\n";

    const auto info = decoder.clip_info();
    std::cout << "[DEBUG] 4. Clip info retrieved\n";

    // --info 모드: 클립 정보만 출력하고 종료
    if (args->output_path == "--info") {
        if (info) {
            std::cout << "FRAME_COUNT=" << info->frame_count << "\n";
            std::cout << "WIDTH=" << info->width << "\n";
            std::cout << "HEIGHT=" << info->height << "\n";
            std::cout << "FRAME_RATE=" << info->frame_rate << "\n";
            std::cout << "STEREO=" << (info->has_immersive_video ? "true" : "false") << "\n";
        } else {
            std::cerr << "클립 정보를 가져올 수 없습니다.\n";
            return 1;
        }
        return 0;
    }

    if (args->eye_mode == EyeMode::kBoth) {
        if (!info || !info->has_immersive_video || info->available_view_count < 2) {
            std::cerr << "해당 클립은 좌/우 트랙을 제공하지 않습니다.\n";
            return 1;
        }
    }

    std::cout << "[DEBUG] 5. Eye mode validated\n";

auto decode_and_write = [&](braw::StereoView view, const std::filesystem::path& output_path) -> bool {
        std::cout << "[DEBUG] 6. decode_and_write started for " << output_path << "\n";
        braw::FrameBuffer buffer;
        std::cout << "[DEBUG] 7. FrameBuffer created\n";

        if (!decoder.decode_frame(args->frame_index, buffer, view)) {
            std::cerr << "프레임 디코딩 실패: " << args->frame_index << "\n";
            return false;
        }
        std::cout << "[DEBUG] 8. Frame decoded successfully\n";
        bool ok = false;
        if (args->format == OutputFormat::kEXR) {
            std::cout << "[DEBUG] 9. Writing EXR...";
            if (args->use_aces) {
                std::cout << " (색공간 변환: " << args->input_colorspace << " → " << args->output_colorspace << ")";
            }
            if (args->apply_gamma) {
                std::cout << " (Rec.709 감마 적용)";
            }
            std::cout << "\n";
            ok = braw::write_exr_half_dwaa(output_path, buffer, 45.0f,
                args->use_aces ? args->input_colorspace : "",
                args->use_aces ? args->output_colorspace : "",
                args->apply_gamma);
        } else {
            std::cout << "[DEBUG] 9. Writing PPM...\n";
            ok = braw::write_ppm(output_path, buffer);
        }
        std::cout << "[DEBUG] 10. Write returned: " << (ok ? "success" : "failure") << "\n";
        if (!ok) {
            std::cerr << "이미지 저장 실패: " << output_path << "\n";
            return false;
        }
        std::cout << "출력 완료 (" << (view == braw::StereoView::kRight ? "우안" : "좌안") << "): " << output_path << "\n";
        return true;
    };

    if (args->eye_mode == EyeMode::kBoth) {
        std::cout << "[DEBUG] 11. Processing Both eyes (sequential)\n";
        const auto left_path = build_stereo_path(args->output_path, "_L");
        const auto right_path = build_stereo_path(args->output_path, "_R");
        std::cout << "[DEBUG] 12. Paths: L=" << left_path << ", R=" << right_path << "\n";

        // Process LEFT first
        std::cout << "[DEBUG] 13. Processing LEFT eye...\n";
        if (!decode_and_write(braw::StereoView::kLeft, left_path)) {
            return 1;
        }
        std::cout << "[DEBUG] 14. LEFT eye completed\n";

        // Flush jobs before processing RIGHT
        std::cout << "[DEBUG] 15. Flushing jobs before RIGHT eye...\n";
        decoder.flush_jobs();
        std::cout << "[DEBUG] 16. Jobs flushed, starting RIGHT eye...\n";

        // Process RIGHT
        if (!decode_and_write(braw::StereoView::kRight, right_path)) {
            return 1;
        }
        std::cout << "[DEBUG] 17. RIGHT eye completed\n";
    } else {
        std::cout << "[DEBUG] 11. Processing single eye\n";
        const braw::StereoView view =
            (args->eye_mode == EyeMode::kRight) ? braw::StereoView::kRight : braw::StereoView::kLeft;
        if (!decode_and_write(view, args->output_path)) {
            return 1;
        }
    }

    std::cout << "[DEBUG] 18. Final flush...\n";
    decoder.flush_jobs();
    std::cout << "[DEBUG] 19. Final flush completed\n";

    if (info) {
        const char* format = (args->format == OutputFormat::kEXR) ? "EXR (f16 DWAA45)" : "PPM";
        std::cout << "프레임 " << args->frame_index << " / 총 " << info->frame_count << "\n"
                  << "해상도 " << info->width << "x" << info->height << "  "
                  << "Views: " << info->available_view_count << " (" << (info->has_immersive_video ? "stereo" : "mono")
                  << ")  Format: " << format << "\n";
    }

#ifdef _WIN32
    CoUninitialize();
#endif

    return 0;
}
