#include "main_window.h"

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
#include <QSlider>
#include <QSpinBox>
#include <QString>
#include <QTimer>
#include <QVBoxLayout>
#include <algorithm>
#include <filesystem>

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

DecodeThread::DecodeThread(braw::BrawDecoder& decoder, QObject* parent)
    : QThread(parent), decoder_(decoder) {}

DecodeThread::~DecodeThread() {
    stop_decoding();
}

void DecodeThread::start_decoding(uint32_t start_frame, uint32_t frame_count, bool stereo_sbs) {
    stop_decoding();

    start_frame_ = start_frame;
    frame_count_ = frame_count;
    current_decode_frame_ = start_frame;
    stereo_sbs_ = stereo_sbs;
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
    const uint32_t scale = 4;  // 8K -> 2K 다운샘플링

    auto clamp_to_byte = [](float value) -> unsigned char {
        float clamped = std::clamp(value, 0.0f, 1.0f);
        return static_cast<unsigned char>(clamped * 255.0f + 0.5f);
    };

    if (stereo_sbs_) {
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

        return sbs_image;
    } else {
        // 모노 모드
        if (!decoder_.decode_frame(frame_index, buffer_left_, braw::StereoView::kLeft)) {
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

    // 상단 컨트롤
    auto* controls = new QHBoxLayout();
    open_button_ = new QPushButton(tr("BRAW 열기"), this);
    controls->addWidget(open_button_);

    play_button_ = new QPushButton(tr("▶ 재생"), this);
    play_button_->setEnabled(false);
    controls->addWidget(play_button_);

    export_button_ = new QPushButton(tr("내보내기"), this);
    export_button_->setEnabled(false);
    controls->addWidget(export_button_);

    stereo_button_ = new QPushButton(tr("SBS"), this);
    stereo_button_->setEnabled(false);
    stereo_button_->setCheckable(true);
    stereo_button_->setChecked(false);
    controls->addWidget(stereo_button_);

    status_label_ = new QLabel(tr("클립이 선택되지 않았습니다."), this);
    controls->addWidget(status_label_, 1);
    controls->setSpacing(12);
    layout->addLayout(controls);

    // 프레임 슬라이더
    auto* slider_layout = new QHBoxLayout();
    frame_slider_ = new QSlider(Qt::Horizontal, this);
    frame_slider_->setEnabled(false);
    frame_slider_->setMinimum(0);
    frame_slider_->setMaximum(0);
    slider_layout->addWidget(frame_slider_, 1);

    frame_label_ = new QLabel(tr("0 / 0"), this);
    frame_label_->setMinimumWidth(80);
    slider_layout->addWidget(frame_label_);
    layout->addLayout(slider_layout);

    // 클립 정보
    info_label_ = new QLabel(tr("정보 없음"), this);
    layout->addWidget(info_label_);

    // 이미지 뷰어
    image_label_ = new QLabel(this);
    image_label_->setAlignment(Qt::AlignCenter);
    image_label_->setMinimumSize(640, 360);
    image_label_->setStyleSheet("background-color: #101010; color: #ffffff;");
    image_label_->setText(tr("미리보기 없음"));
    layout->addWidget(image_label_, 1);

    setCentralWidget(central);
    setWindowTitle(tr("BRAW Viewer"));
    resize(1280, 800);

    // 타이머 설정
    playback_timer_ = new QTimer(this);

    // 디코딩 스레드 생성
    decode_thread_ = new DecodeThread(decoder_, this);

    // 시그널 연결
    connect(open_button_, &QPushButton::clicked, this, &MainWindow::handle_open_clip);
    connect(play_button_, &QPushButton::clicked, this, &MainWindow::handle_play_pause);
    connect(export_button_, &QPushButton::clicked, this, &MainWindow::handle_export);
    connect(frame_slider_, &QSlider::valueChanged, this, &MainWindow::handle_frame_slider_changed);
    connect(playback_timer_, &QTimer::timeout, this, &MainWindow::handle_playback_timer);
    connect(decode_thread_, &DecodeThread::frame_ready, this, &MainWindow::handle_frame_decoded, Qt::QueuedConnection);
    connect(stereo_button_, &QPushButton::toggled, this, [this](bool checked) {
        show_stereo_sbs_ = checked;
        if (decode_thread_) {
            decode_thread_->set_stereo_mode(checked);
        }
        if (has_clip_ && !is_playing_) {
            load_frame(current_frame_);
        }
    });
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

    // 기존 디코딩 중지
    if (decode_thread_) {
        decode_thread_->stop_decoding();
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
        frame_slider_->setMaximum(static_cast<int>(info->frame_count - 1));
        const int fps = static_cast<int>(info->frame_rate + 0.5);
        playback_timer_->setInterval(1000 / fps);

        if (info->has_immersive_video && info->available_view_count >= 2) {
            stereo_button_->setEnabled(true);
            show_stereo_sbs_ = false;
            stereo_button_->setChecked(false);
        } else {
            stereo_button_->setEnabled(false);
            show_stereo_sbs_ = false;
            stereo_button_->setChecked(false);
        }
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
        play_button_->setText(tr("⏸ 일시정지"));

        // 백그라운드 디코딩 시작
        decode_thread_->start_decoding(current_frame_, info->frame_count, show_stereo_sbs_);
        playback_timer_->start();
    } else {
        play_button_->setText(tr("▶ 재생"));
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

        const auto info = decoder_.clip_info();
        if (info) {
            frame_label_->setText(tr("%1 / %2").arg(frame_index).arg(info->frame_count - 1));
        }

        frame_slider_->blockSignals(true);
        frame_slider_->setValue(static_cast<int>(frame_index));
        frame_slider_->blockSignals(false);
    }
}

void MainWindow::load_frame(uint32_t frame_index) {
    const auto info = decoder_.clip_info();
    const bool is_stereo = info && info->has_immersive_video && info->available_view_count >= 2;

    if (show_stereo_sbs_ && is_stereo) {
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
        if (!decoder_.decode_frame(frame_index, frame_buffer_left_, braw::StereoView::kLeft)) {
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
    frame_slider_->blockSignals(true);
    frame_slider_->setValue(static_cast<int>(frame_index));
    frame_slider_->blockSignals(false);

    if (info) {
        frame_label_->setText(tr("%1 / %2").arg(frame_index).arg(info->frame_count - 1));
    }

    display_image(last_image_);
}

void MainWindow::display_image(const QImage& image) {
    if (image_label_->size().width() > 0 && image_label_->size().height() > 0) {
        image_label_->setPixmap(
            QPixmap::fromImage(image).scaled(image_label_->size(), Qt::KeepAspectRatio,
                                             Qt::FastTransformation));
    } else {
        image_label_->setPixmap(QPixmap::fromImage(image));
    }
    image_label_->setText(QString());
}

void MainWindow::update_ui_state() {
    play_button_->setEnabled(has_clip_);
    export_button_->setEnabled(has_clip_);
    frame_slider_->setEnabled(has_clip_);
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

    const uint32_t scale = 4;
    const uint32_t single_width = left.width / scale;   // 한쪽 이미지 너비
    const uint32_t out_width = single_width * 2;        // 전체 SBS 너비 (2배)
    const uint32_t out_height = left.height / scale;

    QImage sbs_image(out_width, out_height, QImage::Format_RGB888);
    const auto left_data = left.as_span();
    const auto right_data = right.as_span();

    auto clamp_to_byte = [](float value) -> unsigned char {
        float clamped = std::clamp(value, 0.0f, 1.0f);
        return static_cast<unsigned char>(clamped * 255.0f + 0.5f);
    };

    for (uint32_t y = 0; y < out_height; ++y) {
        auto* scan = sbs_image.scanLine(static_cast<int>(y));
        const uint32_t src_y = y * scale;

        // 좌측: 좌안 (원본 비율)
        for (uint32_t x = 0; x < single_width; ++x) {
            const uint32_t src_x = x * scale;
            const size_t idx = (src_y * left.width + src_x) * 3;
            *scan++ = clamp_to_byte(left_data[idx]);
            *scan++ = clamp_to_byte(left_data[idx + 1]);
            *scan++ = clamp_to_byte(left_data[idx + 2]);
        }

        // 우측: 우안 (원본 비율)
        for (uint32_t x = 0; x < single_width; ++x) {
            const uint32_t src_x = x * scale;
            const size_t idx = (src_y * right.width + src_x) * 3;
            *scan++ = clamp_to_byte(right_data[idx]);
            *scan++ = clamp_to_byte(right_data[idx + 1]);
            *scan++ = clamp_to_byte(right_data[idx + 2]);
        }
    }

    return sbs_image;
}

QImage MainWindow::convert_to_qimage(const braw::FrameBuffer& buffer) const {
    if (buffer.format != braw::FramePixelFormat::kRGBFloat32 || buffer.width == 0 ||
        buffer.height == 0) {
        return {};
    }

    const uint32_t scale = 4;
    const uint32_t out_width = buffer.width / scale;
    const uint32_t out_height = buffer.height / scale;

    QImage image(out_width, out_height, QImage::Format_RGB888);
    const auto data = buffer.as_span();

    auto clamp_to_byte = [](float value) -> unsigned char {
        float clamped = std::clamp(value, 0.0f, 1.0f);
        return static_cast<unsigned char>(clamped * 255.0f + 0.5f);
    };

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
    return image;
}

void MainWindow::resizeEvent(QResizeEvent* event) {
    QMainWindow::resizeEvent(event);
    if (last_image_.isNull()) {
        return;
    }
    display_image(last_image_);
}
