#include "viewer_window.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDebug>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPixmap>
#include <QProgressDialog>
#include <QPushButton>
#include <QResizeEvent>
#include "timeline_slider.h"
#include "image_viewer.h"
#include <QSpinBox>
#include <QString>
#include <QTimer>
#include <QVBoxLayout>
#include <algorithm>
#include <cstring>
#include <filesystem>
#include <vector>

#include "export/exr_writer.h"
#include "export/image_writer.h"

namespace {
QString to_qstring(const std::filesystem::path& path) {
    return QString::fromStdWString(path.wstring());
}

std::filesystem::path build_stereo_path(const std::filesystem::path& base, std::string_view suffix) {
    const auto parent = base.parent_path();
    const auto stem = base.stem().string();
    const auto ext = base.extension().string();
    std::filesystem::path file_name = stem + std::string(suffix) + ext;
    return parent / file_name;
}

}  // namespace

// ============================================================================
// DecodeThread 구현
// ============================================================================

DecodeThread::DecodeThread(braw::BrawDecoder& decoder, braw::STMapWarper& stmap_warper, QObject* parent)
    : QThread(parent), decoder_(decoder), stmap_warper_(stmap_warper) {}

DecodeThread::~DecodeThread() {
    stop_decoding();
}

void DecodeThread::start_decoding(uint32_t start_frame, uint32_t frame_count, int stereo_view) {
    stop_decoding();

    start_frame_ = start_frame;
    frame_count_ = frame_count;
    current_decode_frame_ = start_frame;
    stereo_view_ = stereo_view;
    running_ = true;

    clear_buffer();
    start();
}

void DecodeThread::stop_decoding() {
    if (running_) {
        running_ = false;
        buffer_not_full_.wakeAll();
        buffer_not_empty_.wakeAll();
        wait();
    }
}

void DecodeThread::clear_buffer() {
    QMutexLocker lock(&buffer_mutex_);
    while (!frame_buffer_.empty()) {
        frame_buffer_.pop();
    }
}

bool DecodeThread::get_next_frame(QImage& out_image, uint32_t& out_frame_index) {
    QMutexLocker lock(&buffer_mutex_);

    if (frame_buffer_.empty()) {
        return false;
    }

    auto& front = frame_buffer_.front();
    out_frame_index = front.first;
    out_image = std::move(front.second);
    frame_buffer_.pop();

    buffer_not_full_.wakeOne();
    return true;
}

void DecodeThread::run() {
    while (running_) {
        // 버퍼가 가득 찼으면 대기
        {
            QMutexLocker lock(&buffer_mutex_);
            while (running_ && frame_buffer_.size() >= BUFFER_SIZE) {
                buffer_not_full_.wait(&buffer_mutex_);
            }
        }

        if (!running_) break;

        // 프레임 디코딩
        QImage image = decode_frame_to_image(current_decode_frame_);

        if (!image.isNull()) {
            QMutexLocker lock(&buffer_mutex_);
            frame_buffer_.push({current_decode_frame_, std::move(image)});
            emit frame_ready();
        }

        // 다음 프레임
        current_decode_frame_++;
        if (current_decode_frame_ >= start_frame_ + frame_count_) {
            current_decode_frame_ = start_frame_;  // 루프
        }
    }
}

QImage DecodeThread::decode_frame_to_image(uint32_t frame_index) {
    const uint32_t scale = downsample_scale_.load();

    auto clamp_to_byte = [](float value) -> unsigned char {
        float clamped = std::clamp(value, 0.0f, 1.0f);
        return static_cast<unsigned char>(clamped * 255.0f + 0.5f);
    };

    const int view = stereo_view_.load();

    if (view == 2) {
        // SBS 모드: 양안 디코딩
        if (!decoder_.decode_frame(frame_index, buffer_left_, braw::StereoView::kLeft)) {
            return {};
        }
        if (!decoder_.decode_frame(frame_index, buffer_right_, braw::StereoView::kRight)) {
            return {};
        }

        if (buffer_left_.format != braw::FramePixelFormat::kRGBFloat32 ||
            buffer_left_.width == 0 || buffer_left_.height == 0) {
            return {};
        }

        // SBS 이미지 생성 (좌우 각각 원본 비율 유지, 가로로 나란히)
        const uint32_t single_width = buffer_left_.width / scale;  // 한쪽 이미지 너비
        const uint32_t out_width = single_width * 2;               // 전체 SBS 너비 (2배)
        const uint32_t out_height = buffer_left_.height / scale;

        QImage sbs_image(out_width, out_height, QImage::Format_RGB888);
        const auto left_data = buffer_left_.as_span();
        const auto right_data = buffer_right_.as_span();

        for (uint32_t y = 0; y < out_height; ++y) {
            auto* scan = sbs_image.scanLine(static_cast<int>(y));
            const uint32_t src_y = y * scale;

            // 좌측: 좌안 (원본 비율)
            for (uint32_t x = 0; x < single_width; ++x) {
                const uint32_t src_x = x * scale;
                const size_t idx = (src_y * buffer_left_.width + src_x) * 3;
                *scan++ = clamp_to_byte(left_data[idx]);
                *scan++ = clamp_to_byte(left_data[idx + 1]);
                *scan++ = clamp_to_byte(left_data[idx + 2]);
            }

            // 우측: 우안 (원본 비율)
            for (uint32_t x = 0; x < single_width; ++x) {
                const uint32_t src_x = x * scale;
                const size_t idx = (src_y * buffer_right_.width + src_x) * 3;
                *scan++ = clamp_to_byte(right_data[idx]);
                *scan++ = clamp_to_byte(right_data[idx + 1]);
                *scan++ = clamp_to_byte(right_data[idx + 2]);
            }
        }

        // STMAP 워핑 적용 (1:1 정사각형 출력)
        if (stmap_warper_.is_enabled() && stmap_warper_.is_loaded()) {
            const uint32_t square_size = stmap_warper_.get_square_output_size(single_width, out_height);

            // 좌안 워핑
            std::vector<uint8_t> left_rgb(single_width * out_height * 3);
            for (uint32_t y = 0; y < out_height; ++y) {
                const auto* src = sbs_image.scanLine(static_cast<int>(y));
                std::memcpy(&left_rgb[y * single_width * 3], src, single_width * 3);
            }
            QImage warped_left(square_size, square_size, QImage::Format_RGB888);
            stmap_warper_.apply_warp_rgb888_square(left_rgb.data(), single_width, out_height,
                                                    warped_left.bits(), square_size);

            // 우안 워핑
            std::vector<uint8_t> right_rgb(single_width * out_height * 3);
            for (uint32_t y = 0; y < out_height; ++y) {
                const auto* src = sbs_image.scanLine(static_cast<int>(y)) + single_width * 3;
                std::memcpy(&right_rgb[y * single_width * 3], src, single_width * 3);
            }
            QImage warped_right(square_size, square_size, QImage::Format_RGB888);
            stmap_warper_.apply_warp_rgb888_square(right_rgb.data(), single_width, out_height,
                                                    warped_right.bits(), square_size);

            // SBS 이미지 재조립 (정사각형 x 2)
            QImage square_sbs(square_size * 2, square_size, QImage::Format_RGB888);
            for (uint32_t y = 0; y < square_size; ++y) {
                auto* dst = square_sbs.scanLine(static_cast<int>(y));
                std::memcpy(dst, warped_left.constScanLine(static_cast<int>(y)), square_size * 3);
                std::memcpy(dst + square_size * 3, warped_right.constScanLine(static_cast<int>(y)), square_size * 3);
            }
            return square_sbs;
        }

        return sbs_image;
    } else {
        // 단안 모드: 좌안(0) 또는 우안(1)
        const braw::StereoView stereo_eye = (view == 1) ?
            braw::StereoView::kRight : braw::StereoView::kLeft;

        if (!decoder_.decode_frame(frame_index, buffer_left_, stereo_eye)) {
            return {};
        }

        if (buffer_left_.format != braw::FramePixelFormat::kRGBFloat32 ||
            buffer_left_.width == 0 || buffer_left_.height == 0) {
            return {};
        }

        const uint32_t out_width = buffer_left_.width / scale;
        const uint32_t out_height = buffer_left_.height / scale;

        QImage image(out_width, out_height, QImage::Format_RGB888);
        const auto data = buffer_left_.as_span();

        for (uint32_t y = 0; y < out_height; ++y) {
            auto* scan = image.scanLine(static_cast<int>(y));
            const uint32_t src_y = y * scale;

            for (uint32_t x = 0; x < out_width; ++x) {
                const uint32_t src_x = x * scale;
                const size_t idx = (src_y * buffer_left_.width + src_x) * 3;
                *scan++ = clamp_to_byte(data[idx]);
                *scan++ = clamp_to_byte(data[idx + 1]);
                *scan++ = clamp_to_byte(data[idx + 2]);
            }
        }

        // STMAP 워핑 적용 (1:1 정사각형 출력)
        if (stmap_warper_.is_enabled() && stmap_warper_.is_loaded()) {
            const uint32_t square_size = stmap_warper_.get_square_output_size(out_width, out_height);

            std::vector<uint8_t> src_rgb(out_width * out_height * 3);
            for (uint32_t y = 0; y < out_height; ++y) {
                const auto* src = image.scanLine(static_cast<int>(y));
                std::memcpy(&src_rgb[y * out_width * 3], src, out_width * 3);
            }

            QImage square_image(square_size, square_size, QImage::Format_RGB888);
            stmap_warper_.apply_warp_rgb888_square(src_rgb.data(), out_width, out_height,
                                                    square_image.bits(), square_size);
            return square_image;
        }

        return image;
    }
}

// ============================================================================
// MainWindow 구현
// ============================================================================

MainWindow::MainWindow(QWidget* parent)
    : QMainWindow(parent), decoder_(braw::ComThreadingModel::kMultiThreaded) {
    auto* central = new QWidget(this);
    auto* layout = new QVBoxLayout(central);
    layout->setContentsMargins(8, 8, 8, 8);
    layout->setSpacing(6);

    // 상단: 클립 정보
    info_label_ = new QLabel(tr("정보 없음"), this);
    info_label_->setStyleSheet("color: #a0a0a0; padding: 4px;");
    layout->addWidget(info_label_);

    // 중앙: 이미지 뷰어 (가장 큰 영역) - 줌/패닝 지원
    image_viewer_ = new ImageViewer(this);
    image_viewer_->setMinimumSize(640, 360);
    layout->addWidget(image_viewer_, 1);

    // 하단: 타임라인 슬라이더
    timeline_slider_ = new TimelineSlider(this);
    timeline_slider_->setEnabled(false);
    layout->addWidget(timeline_slider_);

    // 하단: 컨트롤 버튼들
    auto* controls = new QHBoxLayout();
    controls->setSpacing(8);

    open_button_ = new QPushButton(tr("열기"), this);
    open_button_->setToolTip(tr("BRAW 파일 열기"));
    controls->addWidget(open_button_);

    play_button_ = new QPushButton(tr("재생 [S]"), this);
    play_button_->setEnabled(false);
    play_button_->setToolTip(tr("재생/일시정지 (S)"));
    controls->addWidget(play_button_);

    controls->addSpacing(20);

    // 스테레오 뷰 버튼들
    left_button_ = new QPushButton(tr("좌 [Z]"), this);
    left_button_->setEnabled(false);
    left_button_->setCheckable(true);
    left_button_->setChecked(true);
    left_button_->setToolTip(tr("좌안 보기 (Z)"));
    controls->addWidget(left_button_);

    right_button_ = new QPushButton(tr("우 [C]"), this);
    right_button_->setEnabled(false);
    right_button_->setCheckable(true);
    right_button_->setToolTip(tr("우안 보기 (C)"));
    controls->addWidget(right_button_);

    sbs_button_ = new QPushButton(tr("SBS [X]"), this);
    sbs_button_->setEnabled(false);
    sbs_button_->setCheckable(true);
    sbs_button_->setToolTip(tr("좌우 동시 보기 (X)"));
    controls->addWidget(sbs_button_);

    controls->addSpacing(20);

    // STMAP 왜곡 보정 버튼
    stmap_button_ = new QPushButton(tr("왜곡보정 [W]"), this);
    stmap_button_->setCheckable(true);
    stmap_button_->setToolTip(tr("STMAP 왜곡 보정 토글 (W)"));
    controls->addWidget(stmap_button_);

    controls->addSpacing(20);

    // 해상도 (다운샘플링) 선택
    resolution_combo_ = new QComboBox(this);
    resolution_combo_->addItem(tr("1/4 (2K)"), 4);   // 8K->2K
    resolution_combo_->addItem(tr("1/2 (4K)"), 2);   // 8K->4K
    resolution_combo_->addItem(tr("원본 (8K)"), 1);  // 8K
    resolution_combo_->setCurrentIndex(0);  // 기본값: 1/4
    resolution_combo_->setToolTip(tr("프리뷰 해상도 선택"));
    controls->addWidget(resolution_combo_);

    controls->addSpacing(20);

    export_button_ = new QPushButton(tr("내보내기"), this);
    export_button_->setEnabled(false);
    controls->addWidget(export_button_);

    controls->addStretch(1);

    status_label_ = new QLabel(tr("클립이 선택되지 않았습니다."), this);
    status_label_->setStyleSheet("color: #808080;");
    controls->addWidget(status_label_);

    layout->addLayout(controls);

    setCentralWidget(central);
    setWindowTitle(tr("AMAZE Blackmagic BRAW Player"));
    resize(1280, 800);
    setAcceptDrops(true);

    // 타이머 설정
    playback_timer_ = new QTimer(this);

    // 디코딩 스레드 생성
    decode_thread_ = new DecodeThread(decoder_, stmap_warper_, this);

    // 시그널 연결
    connect(open_button_, &QPushButton::clicked, this, &MainWindow::handle_open_clip);
    connect(play_button_, &QPushButton::clicked, this, &MainWindow::handle_play_pause);
    connect(export_button_, &QPushButton::clicked, this, &MainWindow::handle_export);
    connect(timeline_slider_, &TimelineSlider::valueChanged, this, &MainWindow::handle_frame_slider_changed);
    connect(timeline_slider_, &TimelineSlider::sliderPressed, this, [this]() {
        if (is_playing_) {
            playback_timer_->stop();
        }
    });
    connect(timeline_slider_, &TimelineSlider::sliderReleased, this, [this]() {
        if (is_playing_) {
            playback_timer_->start();
        }
    });
    connect(playback_timer_, &QTimer::timeout, this, &MainWindow::handle_playback_timer);
    connect(decode_thread_, &DecodeThread::frame_ready, this, &MainWindow::handle_frame_decoded, Qt::QueuedConnection);

    // 스테레오 뷰 버튼 연결
    connect(left_button_, &QPushButton::clicked, this, [this]() { set_stereo_view(0); });
    connect(right_button_, &QPushButton::clicked, this, [this]() { set_stereo_view(1); });
    connect(sbs_button_, &QPushButton::clicked, this, [this]() { set_stereo_view(2); });

    // STMAP 버튼 연결
    connect(stmap_button_, &QPushButton::clicked, this, &MainWindow::toggle_stmap);

    // 해상도 콤보 연결
    connect(resolution_combo_, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &MainWindow::set_downsample_scale);

    // STMAP 로드 (4K 버전 - 2K 프리뷰에 적합)
    load_stmap();
}

MainWindow::~MainWindow() {
    if (decode_thread_) {
        decode_thread_->stop_decoding();
        delete decode_thread_;
    }
}

void MainWindow::handle_open_clip() {
    const QString file = QFileDialog::getOpenFileName(this, tr("BRAW 선택"),
                                                      QString(), tr("BRAW Files (*.braw)"));
    if (file.isEmpty()) {
        return;
    }
    open_braw_file(file);
}

void MainWindow::open_braw_file(const QString& file) {
    // 기존 디코딩 중지
    if (decode_thread_) {
        decode_thread_->stop_decoding();
    }

    // 재생 중이면 정지
    if (is_playing_) {
        is_playing_ = false;
        playback_timer_->stop();
        play_button_->setText(tr("재생 [S]"));
    }

    const std::filesystem::path clip_path = file.toStdWString();
    if (!decoder_.open_clip(clip_path)) {
        QString error_msg = tr("클립을 열 수 없습니다.\n경로: %1").arg(file);
        QMessageBox::critical(this, tr("오류"), error_msg);
        qDebug() << "Failed to open clip:" << file;
        qDebug() << "Path exists:" << std::filesystem::exists(clip_path);
        return;
    }

    current_frame_ = 0;
    has_clip_ = true;
    is_playing_ = false;

    const auto info = decoder_.clip_info();
    if (info) {
        timeline_slider_->setRange(static_cast<int>(info->frame_count));
        timeline_slider_->setFrameRate(info->frame_rate);
        const int fps = static_cast<int>(info->frame_rate + 0.5);
        playback_timer_->setInterval(1000 / fps);

        // 스테레오 버튼 활성화
        const bool has_stereo = info->has_immersive_video && info->available_view_count >= 2;
        left_button_->setEnabled(has_stereo);
        right_button_->setEnabled(has_stereo);
        sbs_button_->setEnabled(has_stereo);

        // 기본값: 좌안
        stereo_view_ = 0;
        set_stereo_view(0);
    }

    update_clip_info();
    update_ui_state();
    load_frame(0);
    status_label_->setText(tr("%1 을(를) 불러왔습니다.").arg(file));
}

void MainWindow::handle_play_pause() {
    if (!has_clip_) {
        return;
    }

    const auto info = decoder_.clip_info();
    if (!info) {
        return;
    }

    is_playing_ = !is_playing_;

    if (is_playing_) {
        play_button_->setText(tr("일시정지 [S]"));

        // 백그라운드 디코딩 시작
        decode_thread_->start_decoding(current_frame_, info->frame_count, stereo_view_);
        playback_timer_->start();
    } else {
        play_button_->setText(tr("재생 [S]"));
        playback_timer_->stop();
        decode_thread_->stop_decoding();
    }
}

void MainWindow::handle_export() {
    if (!has_clip_) {
        return;
    }

    const auto info = decoder_.clip_info();
    if (!info) {
        return;
    }

    // 내보내기 다이얼로그
    QDialog dialog(this);
    dialog.setWindowTitle(tr("내보내기 설정"));
    auto* layout = new QVBoxLayout(&dialog);

    // 출력 폴더 선택
    auto* folder_group = new QGroupBox(tr("출력 폴더"), &dialog);
    auto* folder_layout = new QHBoxLayout(folder_group);
    auto* folder_edit = new QLineEdit(&dialog);
    folder_edit->setPlaceholderText(tr("출력 폴더를 선택하세요"));
    auto* folder_button = new QPushButton(tr("찾아보기..."), &dialog);
    folder_layout->addWidget(folder_edit);
    folder_layout->addWidget(folder_button);
    layout->addWidget(folder_group);

    connect(folder_button, &QPushButton::clicked, [&]() {
        QString dir = QFileDialog::getExistingDirectory(this, tr("출력 폴더 선택"));
        if (!dir.isEmpty()) {
            folder_edit->setText(dir);
        }
    });

    // 포맷 선택
    auto* format_group = new QGroupBox(tr("포맷"), &dialog);
    auto* format_layout = new QVBoxLayout(format_group);
    auto* format_combo = new QComboBox(&dialog);
    format_combo->addItem(tr("PPM (8-bit RGB)"), "ppm");
    format_combo->addItem(tr("EXR (16-bit Half Float, DWAA)"), "exr");
    format_combo->setCurrentIndex(1);
    format_layout->addWidget(format_combo);
    layout->addWidget(format_group);

    // 스테레오 옵션
    auto* stereo_group = new QGroupBox(tr("스테레오"), &dialog);
    auto* stereo_layout = new QVBoxLayout(stereo_group);
    auto* eye_combo = new QComboBox(&dialog);

    const bool has_stereo = info->has_immersive_video && info->available_view_count >= 2;

    eye_combo->addItem(tr("좌안만"), "left");
    eye_combo->addItem(tr("우안만"), "right");
    if (has_stereo) {
        eye_combo->addItem(tr("양안 (L, R 폴더)"), "both");
        eye_combo->setCurrentIndex(2);
    }
    stereo_layout->addWidget(eye_combo);
    layout->addWidget(stereo_group);

    // 프레임 범위
    auto* range_group = new QGroupBox(tr("프레임 범위"), &dialog);
    auto* range_layout = new QFormLayout(range_group);

    auto* in_spin = new QSpinBox(&dialog);
    in_spin->setRange(0, static_cast<int>(info->frame_count - 1));
    in_spin->setValue(0);
    range_layout->addRow(tr("In 포인트:"), in_spin);

    auto* out_spin = new QSpinBox(&dialog);
    out_spin->setRange(0, static_cast<int>(info->frame_count - 1));
    out_spin->setValue(static_cast<int>(info->frame_count - 1));
    range_layout->addRow(tr("Out 포인트:"), out_spin);

    layout->addWidget(range_group);

    // 버튼
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    layout->addWidget(buttons);

    if (dialog.exec() != QDialog::Accepted) {
        return;
    }

    const QString output_folder = folder_edit->text();
    if (output_folder.isEmpty()) {
        QMessageBox::warning(this, tr("경고"), tr("출력 폴더를 선택하세요."));
        return;
    }

    const std::filesystem::path output_dir = output_folder.toStdWString();
    if (!std::filesystem::exists(output_dir)) {
        std::filesystem::create_directories(output_dir);
    }

    const QString format = format_combo->currentData().toString();
    const QString eye_mode = eye_combo->currentData().toString();
    const QString ext = format == "exr" ? ".exr" : ".ppm";
    const int in_frame = in_spin->value();
    const int out_frame = out_spin->value();

    if (in_frame > out_frame) {
        QMessageBox::warning(this, tr("경고"), tr("In 포인트는 Out 포인트보다 작아야 합니다."));
        return;
    }

    std::filesystem::path left_dir = output_dir;
    std::filesystem::path right_dir = output_dir;

    if (eye_mode == "both") {
        left_dir = output_dir / "L";
        right_dir = output_dir / "R";
        std::filesystem::create_directories(left_dir);
        std::filesystem::create_directories(right_dir);
    }

    auto export_frame = [&](uint32_t frame_idx, braw::StereoView view,
                           const std::filesystem::path& out_dir) -> bool {
        braw::FrameBuffer buffer;
        if (!decoder_.decode_frame(frame_idx, buffer, view)) {
            return false;
        }

        char filename[32];
        snprintf(filename, sizeof(filename), "frame_%04u%s", frame_idx, ext.toStdString().c_str());
        const auto output_path = out_dir / filename;

        if (format == "exr") {
            return braw::write_exr_half_dwaa(output_path, buffer, 45.0f);
        } else {
            return braw::write_ppm(output_path, buffer);
        }
    };

    QProgressDialog progress(tr("내보내는 중..."), tr("취소"), in_frame, out_frame, this);
    progress.setWindowModality(Qt::WindowModal);
    progress.setMinimumDuration(0);

    bool success = true;
    for (int frame = in_frame; frame <= out_frame; ++frame) {
        if (progress.wasCanceled()) {
            success = false;
            break;
        }

        progress.setValue(frame);
        progress.setLabelText(tr("프레임 %1 / %2 내보내는 중...").arg(frame).arg(out_frame));

        if (eye_mode == "both") {
            if (!export_frame(static_cast<uint32_t>(frame), braw::StereoView::kLeft, left_dir) ||
                !export_frame(static_cast<uint32_t>(frame), braw::StereoView::kRight, right_dir)) {
                success = false;
                break;
            }
        } else {
            const braw::StereoView view = (eye_mode == "right") ?
                braw::StereoView::kRight : braw::StereoView::kLeft;
            if (!export_frame(static_cast<uint32_t>(frame), view, output_dir)) {
                success = false;
                break;
            }
        }
    }

    progress.setValue(out_frame);

    if (success) {
        QMessageBox::information(this, tr("완료"),
            tr("내보내기가 완료되었습니다.\n경로: %1").arg(output_folder));
    } else {
        QMessageBox::critical(this, tr("오류"), tr("내보내기에 실패했습니다."));
    }
}

void MainWindow::handle_frame_slider_changed(int value) {
    if (is_playing_) {
        return;
    }
    load_frame(static_cast<uint32_t>(value));
}

void MainWindow::handle_playback_timer() {
    // 타이머는 프레임 표시 타이밍만 제어
    // 실제 프레임은 handle_frame_decoded에서 버퍼에서 가져옴
}

void MainWindow::handle_frame_decoded() {
    if (!is_playing_) {
        return;
    }

    QImage image;
    uint32_t frame_index;

    if (decode_thread_->get_next_frame(image, frame_index)) {
        current_frame_ = frame_index;
        last_image_ = image;
        display_image(image);

        timeline_slider_->blockSignals(true);
        timeline_slider_->setValue(static_cast<int>(frame_index));
        timeline_slider_->blockSignals(false);
    }
}

void MainWindow::load_frame(uint32_t frame_index) {
    const auto info = decoder_.clip_info();
    const bool is_stereo = info && info->has_immersive_video && info->available_view_count >= 2;

    if (stereo_view_ == 2 && is_stereo) {
        // SBS 모드: 양안
        if (!decoder_.decode_frame(frame_index, frame_buffer_left_, braw::StereoView::kLeft)) {
            status_label_->setText(tr("좌안 프레임 %1 디코딩 실패").arg(frame_index));
            return;
        }
        if (!decoder_.decode_frame(frame_index, frame_buffer_right_, braw::StereoView::kRight)) {
            status_label_->setText(tr("우안 프레임 %1 디코딩 실패").arg(frame_index));
            return;
        }

        const QImage sbs_image = create_sbs_image(frame_buffer_left_, frame_buffer_right_);
        if (sbs_image.isNull()) {
            status_label_->setText(tr("SBS 이미지 생성 실패"));
            return;
        }

        last_image_ = sbs_image;
    } else {
        // 단안 모드: 좌안(0) 또는 우안(1)
        const braw::StereoView view = (stereo_view_ == 1 && is_stereo) ?
            braw::StereoView::kRight : braw::StereoView::kLeft;

        if (!decoder_.decode_frame(frame_index, frame_buffer_left_, view)) {
            status_label_->setText(tr("프레임 %1 디코딩 실패").arg(frame_index));
            return;
        }

        last_image_ = convert_to_qimage(frame_buffer_left_);
        if (last_image_.isNull()) {
            status_label_->setText(tr("이미지 변환 실패"));
            return;
        }
    }

    current_frame_ = frame_index;
    timeline_slider_->blockSignals(true);
    timeline_slider_->setValue(static_cast<int>(frame_index));
    timeline_slider_->blockSignals(false);

    display_image(last_image_);
}

void MainWindow::display_image(const QImage& image) {
    image_viewer_->setImage(image);
}

void MainWindow::update_ui_state() {
    play_button_->setEnabled(has_clip_);
    export_button_->setEnabled(has_clip_);
    timeline_slider_->setEnabled(has_clip_);
}

void MainWindow::update_clip_info() {
    if (const auto info = decoder_.clip_info()) {
        const QString stereo = info->has_immersive_video ?
            tr("스테레오 (Views: %1)").arg(info->available_view_count) : tr("모노");

        info_label_->setText(tr("경로: %1\n해상도: %2 x %3  |  프레임 수: %4  |  FPS: %5  |  %6")
                                 .arg(to_qstring(info->source_path))
                                 .arg(info->width)
                                 .arg(info->height)
                                 .arg(info->frame_count)
                                 .arg(info->frame_rate, 0, 'f', 3)
                                 .arg(stereo));
    } else {
        info_label_->setText(tr("정보 없음"));
    }
}

QImage MainWindow::create_sbs_image(const braw::FrameBuffer& left, const braw::FrameBuffer& right) const {
    if (left.format != braw::FramePixelFormat::kRGBFloat32 ||
        right.format != braw::FramePixelFormat::kRGBFloat32 ||
        left.width == 0 || left.height == 0 ||
        left.width != right.width || left.height != right.height) {
        return {};
    }

    const uint32_t scale = downsample_scale_;
    const uint32_t single_width = left.width / scale;   // 한쪽 이미지 너비
    const uint32_t out_width = single_width * 2;        // 전체 SBS 너비 (2배)
    const uint32_t out_height = left.height / scale;

    const auto left_data = left.as_span();
    const auto right_data = right.as_span();

    auto clamp_to_byte = [](float value) -> unsigned char {
        float clamped = std::clamp(value, 0.0f, 1.0f);
        return static_cast<unsigned char>(clamped * 255.0f + 0.5f);
    };

    // 각 눈 별로 다운샘플링
    QImage left_image(single_width, out_height, QImage::Format_RGB888);
    QImage right_image(single_width, out_height, QImage::Format_RGB888);

    for (uint32_t y = 0; y < out_height; ++y) {
        auto* left_scan = left_image.scanLine(static_cast<int>(y));
        auto* right_scan = right_image.scanLine(static_cast<int>(y));
        const uint32_t src_y = y * scale;

        for (uint32_t x = 0; x < single_width; ++x) {
            const uint32_t src_x = x * scale;
            const size_t left_idx = (src_y * left.width + src_x) * 3;
            const size_t right_idx = (src_y * right.width + src_x) * 3;

            *left_scan++ = clamp_to_byte(left_data[left_idx]);
            *left_scan++ = clamp_to_byte(left_data[left_idx + 1]);
            *left_scan++ = clamp_to_byte(left_data[left_idx + 2]);

            *right_scan++ = clamp_to_byte(right_data[right_idx]);
            *right_scan++ = clamp_to_byte(right_data[right_idx + 1]);
            *right_scan++ = clamp_to_byte(right_data[right_idx + 2]);
        }
    }

    // STMAP 워핑 적용 (각 눈에 개별 적용, 1:1 정사각형 출력)
    if (stmap_warper_.is_enabled() && stmap_warper_.is_loaded()) {
        const uint32_t square_size = stmap_warper_.get_square_output_size(single_width, out_height);

        QImage left_warped(square_size, square_size, QImage::Format_RGB888);
        QImage right_warped(square_size, square_size, QImage::Format_RGB888);
        stmap_warper_.apply_warp_rgb888_square(left_image.bits(), single_width, out_height,
                                                left_warped.bits(), square_size);
        stmap_warper_.apply_warp_rgb888_square(right_image.bits(), single_width, out_height,
                                                right_warped.bits(), square_size);

        // SBS로 합치기 (정사각형 x 2)
        QImage sbs_image(square_size * 2, square_size, QImage::Format_RGB888);
        for (uint32_t y = 0; y < square_size; ++y) {
            auto* sbs_scan = sbs_image.scanLine(static_cast<int>(y));
            const auto* left_scan = left_warped.constScanLine(static_cast<int>(y));
            const auto* right_scan = right_warped.constScanLine(static_cast<int>(y));

            std::memcpy(sbs_scan, left_scan, square_size * 3);
            std::memcpy(sbs_scan + square_size * 3, right_scan, square_size * 3);
        }
        return sbs_image;
    }

    // SBS로 합치기 (원본 비율 유지)
    QImage sbs_image(out_width, out_height, QImage::Format_RGB888);
    for (uint32_t y = 0; y < out_height; ++y) {
        auto* sbs_scan = sbs_image.scanLine(static_cast<int>(y));
        const auto* left_scan = left_image.constScanLine(static_cast<int>(y));
        const auto* right_scan = right_image.constScanLine(static_cast<int>(y));

        std::memcpy(sbs_scan, left_scan, single_width * 3);
        std::memcpy(sbs_scan + single_width * 3, right_scan, single_width * 3);
    }

    return sbs_image;
}

QImage MainWindow::convert_to_qimage(const braw::FrameBuffer& buffer) const {
    if (buffer.format != braw::FramePixelFormat::kRGBFloat32 || buffer.width == 0 ||
        buffer.height == 0) {
        return {};
    }

    const uint32_t scale = downsample_scale_;
    const uint32_t out_width = buffer.width / scale;
    const uint32_t out_height = buffer.height / scale;

    QImage image(out_width, out_height, QImage::Format_RGB888);
    const auto data = buffer.as_span();

    auto clamp_to_byte = [](float value) -> unsigned char {
        float clamped = std::clamp(value, 0.0f, 1.0f);
        return static_cast<unsigned char>(clamped * 255.0f + 0.5f);
    };

    // 다운샘플링
    for (uint32_t y = 0; y < out_height; ++y) {
        auto* scan = image.scanLine(static_cast<int>(y));
        const uint32_t src_y = y * scale;

        for (uint32_t x = 0; x < out_width; ++x) {
            const uint32_t src_x = x * scale;
            const size_t idx = (src_y * buffer.width + src_x) * 3;

            *scan++ = clamp_to_byte(data[idx]);
            *scan++ = clamp_to_byte(data[idx + 1]);
            *scan++ = clamp_to_byte(data[idx + 2]);
        }
    }

    // STMAP 워핑 적용 (1:1 정사각형 출력)
    if (stmap_warper_.is_enabled() && stmap_warper_.is_loaded()) {
        const uint32_t square_size = stmap_warper_.get_square_output_size(out_width, out_height);
        QImage warped(square_size, square_size, QImage::Format_RGB888);
        stmap_warper_.apply_warp_rgb888_square(image.bits(), out_width, out_height,
                                                warped.bits(), square_size);
        return warped;
    }

    return image;
}

void MainWindow::resizeEvent(QResizeEvent* event) {
    QMainWindow::resizeEvent(event);
    if (last_image_.isNull()) {
        return;
    }
    display_image(last_image_);
}

void MainWindow::dragEnterEvent(QDragEnterEvent* event) {
    if (event->mimeData()->hasUrls()) {
        const auto urls = event->mimeData()->urls();
        for (const auto& url : urls) {
            if (url.isLocalFile()) {
                const QString path = url.toLocalFile();
                if (path.toLower().endsWith(".braw")) {
                    event->acceptProposedAction();
                    return;
                }
            }
        }
    }
    event->ignore();
}

void MainWindow::dropEvent(QDropEvent* event) {
    if (event->mimeData()->hasUrls()) {
        const auto urls = event->mimeData()->urls();
        for (const auto& url : urls) {
            if (url.isLocalFile()) {
                const QString path = url.toLocalFile();
                if (path.toLower().endsWith(".braw")) {
                    open_braw_file(path);
                    event->acceptProposedAction();
                    return;
                }
            }
        }
    }
    event->ignore();
}

void MainWindow::set_stereo_view(int view) {
    if (stereo_view_ == view) {
        return;
    }

    stereo_view_ = view;

    // 버튼 상태 업데이트
    left_button_->setChecked(view == 0);
    right_button_->setChecked(view == 1);
    sbs_button_->setChecked(view == 2);

    // 재생 중이면 디코드 스레드 모드 변경
    if (is_playing_ && decode_thread_) {
        decode_thread_->set_stereo_mode(view);
        decode_thread_->clear_buffer();  // 버퍼 클리어하여 새 모드로 디코딩
    }

    // 현재 프레임 다시 로드
    if (has_clip_) {
        load_frame(current_frame_);
    }
}

void MainWindow::keyPressEvent(QKeyEvent* event) {
    if (!has_clip_) {
        QMainWindow::keyPressEvent(event);
        return;
    }

    const auto info = decoder_.clip_info();
    const bool has_stereo = info && info->has_immersive_video && info->available_view_count >= 2;

    switch (event->key()) {
        case Qt::Key_S:
            // 재생/일시정지
            handle_play_pause();
            break;

        case Qt::Key_A:
            // 이전 프레임
            if (!is_playing_ && current_frame_ > 0) {
                load_frame(current_frame_ - 1);
            }
            break;

        case Qt::Key_D:
            // 다음 프레임
            if (!is_playing_ && info && current_frame_ < info->frame_count - 1) {
                load_frame(current_frame_ + 1);
            }
            break;

        case Qt::Key_Z:
            // 좌안 보기
            if (has_stereo) {
                set_stereo_view(0);
            }
            break;

        case Qt::Key_C:
            // 우안 보기
            if (has_stereo) {
                set_stereo_view(1);
            }
            break;

        case Qt::Key_X:
            // SBS 모드 토글
            if (has_stereo) {
                set_stereo_view(2);
            }
            break;

        case Qt::Key_W:
            // STMAP 왜곡 보정 토글
            toggle_stmap();
            break;

        default:
            QMainWindow::keyPressEvent(event);
            break;
    }
}

void MainWindow::toggle_stmap() {
    if (!stmap_warper_.is_loaded()) {
        status_label_->setText(tr("STMAP이 로드되지 않았습니다."));
        stmap_button_->setChecked(false);
        return;
    }

    const bool enabled = !stmap_warper_.is_enabled();
    stmap_warper_.set_enabled(enabled);
    stmap_button_->setChecked(enabled);

    if (enabled) {
        status_label_->setText(tr("왜곡 보정 활성화 (%1x%2)")
            .arg(stmap_warper_.map_width())
            .arg(stmap_warper_.map_height()));
    } else {
        status_label_->setText(tr("왜곡 보정 비활성화"));
    }

    // 현재 프레임 다시 로드
    if (has_clip_) {
        load_frame(current_frame_);
    }
}

void MainWindow::load_stmap() {
    // STMAP 폴더에서 4K 맵 로드 (2K 프리뷰용)
    const std::filesystem::path stmap_path = "P:/00-GIGA/BRAW_CLI/STMAP/AVP_STmap_4k.exr";

    if (stmap_warper_.load_stmap(stmap_path)) {
        status_label_->setText(tr("STMAP 로드 완료 (%1x%2)")
            .arg(stmap_warper_.map_width())
            .arg(stmap_warper_.map_height()));
        stmap_button_->setEnabled(true);
    } else {
        status_label_->setText(tr("STMAP 로드 실패"));
        stmap_button_->setEnabled(false);
    }
}

void MainWindow::set_downsample_scale(int index) {
    // 콤보박스에서 scale 값 가져오기
    const uint32_t scale = resolution_combo_->itemData(index).toUInt();
    if (scale == downsample_scale_) {
        return;
    }

    downsample_scale_ = scale;

    // 디코드 스레드에 알림
    if (decode_thread_) {
        decode_thread_->set_downsample_scale(scale);
        if (is_playing_) {
            decode_thread_->clear_buffer();  // 버퍼 클리어하여 새 해상도로 디코딩
        }
    }

    // 해상도 표시
    const auto info = decoder_.clip_info();
    if (info) {
        const uint32_t out_width = info->width / scale;
        const uint32_t out_height = info->height / scale;
        status_label_->setText(tr("프리뷰 해상도: %1x%2").arg(out_width).arg(out_height));
    }

    // 현재 프레임 다시 로드
    if (has_clip_) {
        load_frame(current_frame_);
    }
}
