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
#include "export/exr_writer.h"
#include "export/image_writer.h"

namespace {

enum class EyeMode { kLeft, kRight, kBoth };

enum class OutputFormat { kPPM, kEXR };

struct Arguments {
    std::filesystem::path clip_path;
    std::filesystem::path output_dir;  // 출력 디렉토리 (범위 모드)
    std::string output_prefix;         // 파일명 접두사
    uint32_t start_frame{0};
    uint32_t end_frame{0};
    bool range_mode{false};            // 프레임 범위 모드
    EyeMode eye_mode{EyeMode::kLeft};
    OutputFormat format{OutputFormat::kEXR};
    bool use_aces{false};
    bool apply_gamma{false};
    std::string input_colorspace{"BMDFilm WideGamut Gen5"};
    std::string output_colorspace{"ACEScg"};
    bool quiet{false};                 // 로그 최소화
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

// 프레임 범위 파싱 (예: "0-999", "100-200", "50")
bool parse_frame_range(const std::string& token, uint32_t& start, uint32_t& end) {
    auto dash_pos = token.find('-');
    if (dash_pos != std::string::npos) {
        try {
            start = static_cast<uint32_t>(std::stoul(token.substr(0, dash_pos)));
            end = static_cast<uint32_t>(std::stoul(token.substr(dash_pos + 1)));
            return start <= end;
        } catch (...) {
            return false;
        }
    } else {
        try {
            start = end = static_cast<uint32_t>(std::stoul(token));
            return true;
        } catch (...) {
            return false;
        }
    }
}

void print_usage() {
    std::cerr << "사용법:\n";
    std::cerr << "  braw_cli <clip.braw> <output_dir> <start-end> <eye> [options]\n";
    std::cerr << "  braw_cli <clip.braw> --info\n";
    std::cerr << "\n";
    std::cerr << "인자:\n";
    std::cerr << "  output_dir    출력 디렉토리 (L/R 하위 폴더 자동 생성)\n";
    std::cerr << "  start-end     프레임 범위 (예: 0-999, 100-200, 50)\n";
    std::cerr << "  eye           left, right, both 중 하나\n";
    std::cerr << "\n";
    std::cerr << "옵션:\n";
    std::cerr << "  --format=exr|ppm   출력 포맷 (기본: exr)\n";
    std::cerr << "  --prefix=NAME      파일명 접두사 (기본: 클립 이름)\n";
    std::cerr << "  --aces             ACES 색공간 변환 적용\n";
    std::cerr << "  --gamma            Rec.709 감마 적용\n";
    std::cerr << "  --quiet            진행 로그 최소화\n";
    std::cerr << "\n";
    std::cerr << "예시:\n";
    std::cerr << "  braw_cli clip.braw ./export 0-999 both --format=exr\n";
    std::cerr << "  braw_cli clip.braw ./out 0-99 left --aces --quiet\n";
}

std::optional<Arguments> parse_arguments(int argc, char** argv) {
    if (argc < 3) {
        print_usage();
        return std::nullopt;
    }

    // --info 모드 체크
    if (std::string(argv[2]) == "--info") {
        Arguments args;
        args.clip_path = argv[1];
        args.range_mode = false;
        return args;
    }

    if (argc < 5) {
        print_usage();
        return std::nullopt;
    }

    Arguments args;
    args.clip_path = argv[1];
    args.output_dir = argv[2];
    args.range_mode = true;

    // 프레임 범위 파싱
    if (!parse_frame_range(argv[3], args.start_frame, args.end_frame)) {
        std::cerr << "잘못된 프레임 범위: " << argv[3] << "\n";
        return std::nullopt;
    }

    // eye 모드 파싱
    auto mode = parse_eye_mode(argv[4]);
    if (!mode) {
        std::cerr << "알 수 없는 시야 옵션: " << argv[4] << " (left/right/both 중 하나 사용)\n";
        return std::nullopt;
    }
    args.eye_mode = *mode;

    // 기본 접두사: 클립 파일명
    args.output_prefix = args.clip_path.stem().string();

    // 플래그 파싱
    for (int i = 5; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--aces") {
            args.use_aces = true;
        } else if (arg == "--gamma") {
            args.apply_gamma = true;
        } else if (arg == "--quiet" || arg == "-q") {
            args.quiet = true;
        } else if (arg.rfind("--format=", 0) == 0) {
            std::string fmt = arg.substr(9);
            if (fmt == "ppm") {
                args.format = OutputFormat::kPPM;
            } else if (fmt == "exr") {
                args.format = OutputFormat::kEXR;
            }
        } else if (arg.rfind("--prefix=", 0) == 0) {
            args.output_prefix = arg.substr(9);
        } else if (arg.rfind("--input-cs=", 0) == 0) {
            args.input_colorspace = arg.substr(11);
        } else if (arg.rfind("--output-cs=", 0) == 0) {
            args.output_colorspace = arg.substr(12);
        }
    }

    return args;
}

// 파일명 생성: prefix_000000.exr
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
        std::cerr << "COM initialization failed: 0x" << std::hex << hr << std::dec << "\n";
        return 1;
    }
#endif

    const auto args = parse_arguments(argc, argv);
    if (!args) {
        return 1;
    }

    braw::BrawDecoder decoder(braw::ComThreadingModel::kMultiThreaded);

    if (!decoder.open_clip(args->clip_path)) {
        std::cerr << "클립을 열 수 없습니다: " << args->clip_path << "\n";
        return 1;
    }

    const auto info = decoder.clip_info();

    // --info 모드: 클립 정보만 출력하고 종료
    if (!args->range_mode) {
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

    // 스테레오 검증
    if (args->eye_mode == EyeMode::kBoth) {
        if (!info || !info->has_immersive_video || info->available_view_count < 2) {
            std::cerr << "해당 클립은 좌/우 트랙을 제공하지 않습니다.\n";
            return 1;
        }
    }

    // 프레임 범위 검증
    uint32_t end_frame = args->end_frame;
    if (info && end_frame >= info->frame_count) {
        end_frame = static_cast<uint32_t>(info->frame_count - 1);
        std::cerr << "경고: end_frame을 " << end_frame << "로 조정합니다.\n";
    }

    // 출력 디렉토리 생성
    const std::string ext = (args->format == OutputFormat::kEXR) ? ".exr" : ".ppm";
    std::filesystem::path left_dir = args->output_dir;
    std::filesystem::path right_dir = args->output_dir;

    if (args->eye_mode == EyeMode::kBoth) {
        left_dir = args->output_dir / "L";
        right_dir = args->output_dir / "R";
    } else if (args->eye_mode == EyeMode::kLeft) {
        left_dir = args->output_dir / "L";
    } else {
        right_dir = args->output_dir / "R";
    }

    std::filesystem::create_directories(left_dir);
    if (args->eye_mode == EyeMode::kBoth || args->eye_mode == EyeMode::kRight) {
        std::filesystem::create_directories(right_dir);
    }

    // 시작 정보 출력
    const uint32_t total_frames = end_frame - args->start_frame + 1;
    const uint32_t total_outputs = total_frames * (args->eye_mode == EyeMode::kBoth ? 2 : 1);

    std::cout << "=== BRAW Batch Export ===\n";
    std::cout << "클립: " << args->clip_path.filename() << "\n";
    std::cout << "프레임: " << args->start_frame << " - " << end_frame
              << " (" << total_frames << " frames)\n";
    std::cout << "출력: " << args->output_dir << "\n";
    std::cout << "포맷: " << ext << "\n";
    if (args->use_aces) {
        std::cout << "색공간: " << args->input_colorspace << " → " << args->output_colorspace << "\n";
    }
    std::cout << "\n";

    // 프레임 버퍼 재사용
    braw::FrameBuffer buffer_left;
    braw::FrameBuffer buffer_right;

    auto start_time = std::chrono::steady_clock::now();
    uint32_t completed = 0;
    uint32_t failed = 0;

    // 메인 루프: 클립 한 번 열고 모든 프레임 처리
    for (uint32_t frame_idx = args->start_frame; frame_idx <= end_frame; ++frame_idx) {
        bool frame_ok = true;

        // LEFT 또는 BOTH
        if (args->eye_mode == EyeMode::kLeft || args->eye_mode == EyeMode::kBoth) {
            auto out_path = build_output_path(left_dir, args->output_prefix, frame_idx, ext);

            if (!decoder.decode_frame(frame_idx, buffer_left, braw::StereoView::kLeft)) {
                std::cerr << "FAIL [" << frame_idx << "] LEFT 디코딩 실패\n";
                frame_ok = false;
            } else {
                bool write_ok = false;
                if (args->format == OutputFormat::kEXR) {
                    write_ok = braw::write_exr_half_dwaa(out_path, buffer_left, 45.0f,
                        args->use_aces ? args->input_colorspace : "",
                        args->use_aces ? args->output_colorspace : "",
                        args->apply_gamma);
                } else {
                    write_ok = braw::write_ppm(out_path, buffer_left);
                }

                if (!write_ok) {
                    std::cerr << "FAIL [" << frame_idx << "] LEFT 저장 실패\n";
                    frame_ok = false;
                } else {
                    ++completed;
                }
            }
        }

        // RIGHT 또는 BOTH
        if (args->eye_mode == EyeMode::kRight || args->eye_mode == EyeMode::kBoth) {
            auto out_path = build_output_path(right_dir, args->output_prefix, frame_idx, ext);

            if (!decoder.decode_frame(frame_idx, buffer_right, braw::StereoView::kRight)) {
                std::cerr << "FAIL [" << frame_idx << "] RIGHT 디코딩 실패\n";
                frame_ok = false;
            } else {
                bool write_ok = false;
                if (args->format == OutputFormat::kEXR) {
                    write_ok = braw::write_exr_half_dwaa(out_path, buffer_right, 45.0f,
                        args->use_aces ? args->input_colorspace : "",
                        args->use_aces ? args->output_colorspace : "",
                        args->apply_gamma);
                } else {
                    write_ok = braw::write_ppm(out_path, buffer_right);
                }

                if (!write_ok) {
                    std::cerr << "FAIL [" << frame_idx << "] RIGHT 저장 실패\n";
                    frame_ok = false;
                } else {
                    ++completed;
                }
            }
        }

        if (!frame_ok) {
            ++failed;
        }

        // 진행률 출력 (quiet 모드가 아닐 때)
        if (!args->quiet) {
            const uint32_t progress_frame = frame_idx - args->start_frame + 1;
            const float pct = 100.0f * static_cast<float>(progress_frame) / static_cast<float>(total_frames);

            auto now = std::chrono::steady_clock::now();
            auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now - start_time).count();
            float fps = (elapsed > 0) ? static_cast<float>(progress_frame) / static_cast<float>(elapsed) : 0.0f;

            uint32_t eta_sec = (fps > 0) ? static_cast<uint32_t>((total_frames - progress_frame) / fps) : 0;

            std::cout << "\r[" << std::setw(3) << static_cast<int>(pct) << "%] "
                      << "Frame " << frame_idx << "/" << end_frame
                      << " | " << std::fixed << std::setprecision(1) << fps << " fps"
                      << " | ETA " << (eta_sec / 60) << "m " << (eta_sec % 60) << "s"
                      << "     " << std::flush;
        }

        // 주기적으로 flush (메모리 관리)
        if ((frame_idx - args->start_frame + 1) % 50 == 0) {
            decoder.flush_jobs();
        }
    }

    decoder.flush_jobs();

    // 최종 결과
    auto end_time = std::chrono::steady_clock::now();
    auto total_sec = std::chrono::duration_cast<std::chrono::seconds>(end_time - start_time).count();

    std::cout << "\n\n=== 완료 ===\n";
    std::cout << "성공: " << completed << " / " << total_outputs << "\n";
    if (failed > 0) {
        std::cout << "실패: " << failed << " 프레임\n";
    }
    std::cout << "소요시간: " << (total_sec / 60) << "분 " << (total_sec % 60) << "초\n";
    if (total_sec > 0) {
        std::cout << "평균: " << std::fixed << std::setprecision(2)
                  << (static_cast<float>(total_frames) / static_cast<float>(total_sec)) << " fps\n";
    }

#ifdef _WIN32
    CoUninitialize();
#endif

    return (failed > 0) ? 1 : 0;
}
