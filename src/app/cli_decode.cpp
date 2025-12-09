#include <algorithm>
#include <cctype>
#include <chrono>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>
#include <cwctype>

#ifdef _WIN32
#include <Windows.h>
#include <combaseapi.h>
#endif

#include "core/braw_decoder.h"
#include "core/frame_buffer.h"
#include "core/stmap_warper.h"
#include "export/exr_writer.h"
#include "export/image_writer.h"

namespace {

enum class EyeMode { kLeft, kRight, kBoth, kSBS };

enum class OutputFormat { kPPM, kEXR };

struct Arguments {
    std::filesystem::path clip_path;
    std::filesystem::path output_dir;
    std::string output_prefix;
    uint32_t start_frame{0};
    uint32_t end_frame{0};
    bool range_mode{false};
    EyeMode eye_mode{EyeMode::kLeft};
    OutputFormat format{OutputFormat::kEXR};
    bool use_aces{false};
    bool apply_gamma{false};
    std::string input_colorspace{"BMDFilm WideGamut Gen5"};
    std::string output_colorspace{"ACEScg"};
    bool quiet{false};
    std::filesystem::path stmap_path;  // STMAP EXR 경로 (왜곡 보정용)
    bool use_stmap{false};
};

std::optional<EyeMode> parse_eye_mode(const std::string& token) {
    std::string lower = token;
    std::transform(lower.begin(), lower.end(), lower.begin(),
                   [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });

    if (lower == "left" || lower == "l") return EyeMode::kLeft;
    if (lower == "right" || lower == "r") return EyeMode::kRight;
    if (lower == "both" || lower == "stereo" || lower == "lr") return EyeMode::kBoth;
    if (lower == "sbs" || lower == "sidebyside") return EyeMode::kSBS;
    return std::nullopt;
}

bool parse_frame_range(const std::string& token, uint32_t& start, uint32_t& end) {
    auto dash_pos = token.find('-');
    if (dash_pos != std::string::npos) {
        try {
            start = static_cast<uint32_t>(std::stoul(token.substr(0, dash_pos)));
            end = static_cast<uint32_t>(std::stoul(token.substr(dash_pos + 1)));
            return start <= end;
        } catch (...) { return false; }
    } else {
        try {
            start = end = static_cast<uint32_t>(std::stoul(token));
            return true;
        } catch (...) { return false; }
    }
}

void print_usage() {
    std::cerr << "Usage: braw_cli <clip.braw> <output_dir> <start-end> <eye> [options]\n";
    std::cerr << "  eye: left, right, both, sbs\n";
    std::cerr << "  --aces --gamma --quiet --format=exr|ppm --prefix=NAME\n";
    std::cerr << "  --stmap=<path.exr>  Apply ST Map distortion correction (outputs 1:1 square)\n";
}

std::optional<Arguments> parse_arguments(int argc, char** argv) {
    if (argc < 3) { print_usage(); return std::nullopt; }
    if (std::string(argv[2]) == "--info") {
        Arguments args; args.clip_path = argv[1]; args.range_mode = false; return args;
    }
    if (argc < 5) { print_usage(); return std::nullopt; }

    Arguments args;
    args.clip_path = argv[1];
    args.output_dir = argv[2];
    args.range_mode = true;

    if (!parse_frame_range(argv[3], args.start_frame, args.end_frame)) {
        std::cerr << "Invalid frame range: " << argv[3] << "\n"; return std::nullopt;
    }

    auto mode = parse_eye_mode(argv[4]);
    if (!mode) { std::cerr << "Unknown eye: " << argv[4] << "\n"; return std::nullopt; }
    args.eye_mode = *mode;
    args.output_prefix = args.clip_path.stem().string();

    for (int i = 5; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--aces") args.use_aces = true;
        else if (arg == "--gamma") args.apply_gamma = true;
        else if (arg == "--quiet" || arg == "-q") args.quiet = true;
        else if (arg.rfind("--format=", 0) == 0) {
            std::string fmt = arg.substr(9);
            if (fmt == "ppm") args.format = OutputFormat::kPPM;
            else if (fmt == "exr") args.format = OutputFormat::kEXR;
        }
        else if (arg.rfind("--prefix=", 0) == 0) args.output_prefix = arg.substr(9);
        else if (arg.rfind("--input-cs=", 0) == 0) args.input_colorspace = arg.substr(11);
        else if (arg.rfind("--output-cs=", 0) == 0) args.output_colorspace = arg.substr(12);
        else if (arg.rfind("--stmap=", 0) == 0) {
            args.stmap_path = arg.substr(8);
            args.use_stmap = true;
        }
    }
    return args;
}

std::filesystem::path build_output_path(const std::filesystem::path& dir,
                                         const std::string& prefix,
                                         uint32_t frame_idx,
                                         const std::string& ext) {
    std::ostringstream ss;
    ss << prefix << "_" << std::setfill('0') << std::setw(6) << frame_idx << ext;
    return dir / ss.str();
}

}  // namespace

int main(int argc, char** argv) {
#ifdef _WIN32
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr) && hr != RPC_E_CHANGED_MODE && hr != S_FALSE) {
        std::cerr << "COM init failed\n"; return 1;
    }
#endif

    const auto args = parse_arguments(argc, argv);
    if (!args) return 1;

    braw::BrawDecoder decoder(braw::ComThreadingModel::kMultiThreaded);
    if (!decoder.open_clip(args->clip_path)) {
        std::cerr << "Cannot open clip\n"; return 1;
    }

    const auto info = decoder.clip_info();
    if (!args->range_mode) {
        if (info) {
            std::cout << "FRAME_COUNT=" << info->frame_count << "\n";
            std::cout << "WIDTH=" << info->width << "\n";
            std::cout << "HEIGHT=" << info->height << "\n";
            std::cout << "FRAME_RATE=" << info->frame_rate << "\n";
            std::cout << "STEREO=" << (info->has_immersive_video ? "true" : "false") << "\n";
        }
        return 0;
    }

    if (args->eye_mode == EyeMode::kBoth || args->eye_mode == EyeMode::kSBS) {
        if (!info || !info->has_immersive_video || info->available_view_count < 2) {
            std::cerr << "No stereo tracks\n"; return 1;
        }
    }

    // STMAP warper 초기화
    braw::STMapWarper stmap_warper;
    if (args->use_stmap) {
        if (!stmap_warper.load_stmap(args->stmap_path)) {
            std::cerr << "Failed to load STMAP: " << args->stmap_path << "\n";
            return 1;
        }
        stmap_warper.set_enabled(true);
        std::cout << "STMAP loaded: " << args->stmap_path.filename() << " ("
                  << stmap_warper.map_width() << "x" << stmap_warper.map_height() << ")\n";
    }

    uint32_t end_frame = args->end_frame;
    if (info && end_frame >= info->frame_count)
        end_frame = static_cast<uint32_t>(info->frame_count - 1);

    const std::string ext = (args->format == OutputFormat::kEXR) ? ".exr" : ".ppm";
    std::filesystem::path left_dir = args->output_dir;
    std::filesystem::path right_dir = args->output_dir;
    std::filesystem::path sbs_dir = args->output_dir;

    if (args->eye_mode == EyeMode::kBoth) {
        left_dir = args->output_dir / "L"; right_dir = args->output_dir / "R";
        std::filesystem::create_directories(left_dir);
        std::filesystem::create_directories(right_dir);
    } else if (args->eye_mode == EyeMode::kLeft) {
        left_dir = args->output_dir / "L";
        std::filesystem::create_directories(left_dir);
    } else if (args->eye_mode == EyeMode::kRight) {
        right_dir = args->output_dir / "R";
        std::filesystem::create_directories(right_dir);
    } else if (args->eye_mode == EyeMode::kSBS) {
        sbs_dir = args->output_dir / "SBS";
        std::filesystem::create_directories(sbs_dir);
    }

    const uint32_t total_frames = end_frame - args->start_frame + 1;
    const uint32_t total_outputs = total_frames * (args->eye_mode == EyeMode::kBoth ? 2 : 1);

    std::cout << "=== BRAW Export ===\nMode: ";
    switch (args->eye_mode) {
        case EyeMode::kLeft:  std::cout << "LEFT\n"; break;
        case EyeMode::kRight: std::cout << "RIGHT\n"; break;
        case EyeMode::kBoth:  std::cout << "BOTH\n"; break;
        case EyeMode::kSBS:   std::cout << "SBS\n"; break;
    }
    if (args->use_stmap) {
        std::cout << "STMAP: Enabled (1:1 square output)\n";
    }

    braw::FrameBuffer buffer_left, buffer_right;
    braw::FrameBuffer warped_left, warped_right;  // STMAP 적용 결과
    auto start_time = std::chrono::steady_clock::now();
    uint32_t completed = 0, failed = 0;

    // STMAP 적용 시 출력 크기 = STMAP 크기
    uint32_t square_size = 0;
    if (args->use_stmap) {
        square_size = stmap_warper.get_output_size();
        std::cout << "Output size: " << square_size << "x" << square_size << "\n";
    }

    // STMAP 워핑 적용 헬퍼 람다
    auto apply_stmap = [&](const braw::FrameBuffer& src, braw::FrameBuffer& dst) {
        if (!args->use_stmap) {
            dst = src;
            return;
        }
        dst.resize(square_size, square_size);
        stmap_warper.apply_warp_float_square(src.data.data(), src.width, src.height,
                                              dst.data.data(), square_size);
    };

    for (uint32_t frame_idx = args->start_frame; frame_idx <= end_frame; ++frame_idx) {
        bool frame_ok = true;

        if (args->eye_mode == EyeMode::kSBS) {
            auto out_path = build_output_path(sbs_dir, args->output_prefix, frame_idx, ext);
            if (!decoder.decode_frame(frame_idx, buffer_left, braw::StereoView::kLeft)) frame_ok = false;
            else if (!decoder.decode_frame(frame_idx, buffer_right, braw::StereoView::kRight)) frame_ok = false;
            else {
                // STMAP 적용
                apply_stmap(buffer_left, warped_left);
                apply_stmap(buffer_right, warped_right);

                braw::FrameBuffer sbs_buffer = braw::merge_sbs(warped_left, warped_right);
                bool write_ok = (args->format == OutputFormat::kEXR) ?
                    braw::write_exr_half_dwaa(out_path, sbs_buffer, 45.0f,
                        args->use_aces ? args->input_colorspace : "",
                        args->use_aces ? args->output_colorspace : "", args->apply_gamma) :
                    braw::write_ppm(out_path, sbs_buffer);
                if (write_ok) ++completed; else frame_ok = false;
            }
        }
        else if (args->eye_mode == EyeMode::kLeft || args->eye_mode == EyeMode::kBoth) {
            auto out_path = build_output_path(left_dir, args->output_prefix, frame_idx, ext);
            if (!decoder.decode_frame(frame_idx, buffer_left, braw::StereoView::kLeft)) frame_ok = false;
            else {
                // STMAP 적용
                apply_stmap(buffer_left, warped_left);

                bool write_ok = (args->format == OutputFormat::kEXR) ?
                    braw::write_exr_half_dwaa(out_path, warped_left, 45.0f,
                        args->use_aces ? args->input_colorspace : "",
                        args->use_aces ? args->output_colorspace : "", args->apply_gamma) :
                    braw::write_ppm(out_path, warped_left);
                if (write_ok) ++completed; else frame_ok = false;
            }
        }

        if (args->eye_mode == EyeMode::kRight || args->eye_mode == EyeMode::kBoth) {
            auto out_path = build_output_path(right_dir, args->output_prefix, frame_idx, ext);
            if (!decoder.decode_frame(frame_idx, buffer_right, braw::StereoView::kRight)) frame_ok = false;
            else {
                // STMAP 적용
                apply_stmap(buffer_right, warped_right);

                bool write_ok = (args->format == OutputFormat::kEXR) ?
                    braw::write_exr_half_dwaa(out_path, warped_right, 45.0f,
                        args->use_aces ? args->input_colorspace : "",
                        args->use_aces ? args->output_colorspace : "", args->apply_gamma) :
                    braw::write_ppm(out_path, warped_right);
                if (write_ok) ++completed; else frame_ok = false;
            }
        }

        if (!frame_ok) ++failed;

        if (!args->quiet) {
            const uint32_t pf = frame_idx - args->start_frame + 1;
            const float pct = 100.0f * pf / total_frames;
            auto now = std::chrono::steady_clock::now();
            auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now - start_time).count();
            float fps = (elapsed > 0) ? float(pf) / float(elapsed) : 0.0f;
            std::cout << "\r[" << int(pct) << "%] Frame " << frame_idx << "/" << end_frame << std::flush;
        }
        if ((frame_idx - args->start_frame + 1) % 50 == 0) decoder.flush_jobs();
    }

    decoder.flush_jobs();
    std::cout << "\n=== Done: " << completed << "/" << total_outputs << " ===\n";

#ifdef _WIN32
    CoUninitialize();
#endif
    return (failed > 0) ? 1 : 0;
}
