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
    stereo_button_->setChecked(false);  // 기본값: OFF
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

    // 시그널 연결
    connect(open_button_, &QPushButton::clicked, this, &MainWindow::handle_open_clip);
    connect(play_button_, &QPushButton::clicked, this, &MainWindow::handle_play_pause);
    connect(export_button_, &QPushButton::clicked, this, &MainWindow::handle_export);
    connect(frame_slider_, &QSlider::valueChanged, this, &MainWindow::handle_frame_slider_changed);
    connect(playback_timer_, &QTimer::timeout, this, &MainWindow::handle_playback_timer);
    connect(stereo_button_, &QPushButton::toggled, this, [this](bool checked) {
        show_stereo_sbs_ = checked;
        if (has_clip_) {
            load_frame(current_frame_);
        }
    });
}

void MainWindow::handle_open_clip() {
    const QString file = QFileDialog::getOpenFileName(this, tr("BRAW 선택"),
                                                      QString(), tr("BRAW Files (*.braw)"));
    if (file.isEmpty()) {
        return;
    }

    const std::filesystem::path clip_path = file.toStdWString();
    if (!decoder_.open_clip(clip_path)) {
        QString error_msg = tr("클립을 열 수 없습니다.\n경로: %1").arg(file);
        QMessageBox::critical(this, tr("오류"), error_msg);

        // 콘솔에도 출력
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

        // 스테레오 버튼 활성화 (기본값: 좌안만)
        if (info->has_immersive_video && info->available_view_count >= 2) {
            stereo_button_->setEnabled(true);
            show_stereo_sbs_ = false;  // 초기 로딩은 좌안만
            stereo_button_->setChecked(false);
        } else {
            stereo_button_->setEnabled(false);
            show_stereo_sbs_ = false;
            stereo_button_->setChecked(false);
        }
    }

    update_clip_info();
    update_ui_state();
    load_frame(0);  // 첫 프레임 로드
    status_label_->setText(tr("%1 을(를) 불러왔습니다.").arg(file));
}

void MainWindow::handle_play_pause() {
    if (!has_clip_) {
        return;
    }

    is_playing_ = !is_playing_;

    if (is_playing_) {
        play_button_->setText(tr("⏸ 일시정지"));
        playback_timer_->start();
    } else {
        play_button_->setText(tr("▶ 재생"));
        playback_timer_->stop();
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
    format_combo->setCurrentIndex(1);  // 기본값 EXR
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
        eye_combo->setCurrentIndex(2);  // 기본값 양안
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

    // 출력 폴더 확인
    const QString output_folder = folder_edit->text();
    if (output_folder.isEmpty()) {
        QMessageBox::warning(this, tr("경고"), tr("출력 폴더를 선택하세요."));
        return;
    }

    const std::filesystem::path output_dir = output_folder.toStdWString();
    if (!std::filesystem::exists(output_dir)) {
        std::filesystem::create_directories(output_dir);
    }

    // 내보내기 설정
    const QString format = format_combo->currentData().toString();
    const QString eye_mode = eye_combo->currentData().toString();
    const QString ext = format == "exr" ? ".exr" : ".ppm";
    const int in_frame = in_spin->value();
    const int out_frame = out_spin->value();

    if (in_frame > out_frame) {
        QMessageBox::warning(this, tr("경고"), tr("In 포인트는 Out 포인트보다 작아야 합니다."));
        return;
    }

    // L, R 폴더 생성 (양안인 경우)
    std::filesystem::path left_dir = output_dir;
    std::filesystem::path right_dir = output_dir;

    if (eye_mode == "both") {
        left_dir = output_dir / "L";
        right_dir = output_dir / "R";
        std::filesystem::create_directories(left_dir);
        std::filesystem::create_directories(right_dir);
    }

    // 내보내기 함수
    auto export_frame = [&](uint32_t frame_idx, braw::StereoView view,
                           const std::filesystem::path& out_dir) -> bool {
        braw::FrameBuffer buffer;
        if (!decoder_.decode_frame(frame_idx, buffer, view)) {
            return false;
        }

        // 파일명: frame_0000.exr
        char filename[32];
        snprintf(filename, sizeof(filename), "frame_%04u%s", frame_idx, ext.toStdString().c_str());
        const auto output_path = out_dir / filename;

        if (format == "exr") {
            return braw::write_exr_half_dwaa(output_path, buffer, 45.0f);
        } else {
            return braw::write_ppm(output_path, buffer);
        }
    };

    // 프로그레스 다이얼로그
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
        return;  // 재생 중에는 슬라이더 변경 무시
    }
    load_frame(static_cast<uint32_t>(value));
}

void MainWindow::handle_playback_timer() {
    const auto info = decoder_.clip_info();
    if (!info) {
        return;
    }

    current_frame_++;
    if (current_frame_ >= info->frame_count) {
        current_frame_ = 0;  // 루프
    }

    load_frame(current_frame_);
}

void MainWindow::load_frame(uint32_t frame_index) {
    const auto info = decoder_.clip_info();
    const bool is_stereo = info && info->has_immersive_video && info->available_view_count >= 2;

    if (show_stereo_sbs_ && is_stereo) {
        // SBS 모드: 양안 디코딩
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
        // 모노 또는 좌안만
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

    // 이미지 표시 (FastTransformation 사용)
    if (image_label_->size().width() > 0 && image_label_->size().height() > 0) {
        image_label_->setPixmap(
            QPixmap::fromImage(last_image_).scaled(image_label_->size(), Qt::KeepAspectRatio,
                                                   Qt::FastTransformation));
    } else {
        image_label_->setPixmap(QPixmap::fromImage(last_image_));
    }
    image_label_->setText(QString());
}

void MainWindow::update_ui_state() {
    play_button_->setEnabled(has_clip_);
    export_button_->setEnabled(has_clip_);
    frame_slider_->setEnabled(has_clip_);
    // stereo_button_은 open_clip에서 스테레오 여부에 따라 설정됨
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

    // SBS: 가로로 2배, 각 이미지는 절반 너비로 축소
    const uint32_t sbs_width = left.width;  // 전체 너비 유지
    const uint32_t sbs_height = left.height;
    const uint32_t half_width = left.width / 2;

    QImage sbs_image(sbs_width, sbs_height, QImage::Format_RGB888);
    const auto left_data = left.as_span();
    const auto right_data = right.as_span();

    auto clamp_to_byte = [](float value) -> unsigned char {
        float clamped = std::clamp(value, 0.0f, 1.0f);
        return static_cast<unsigned char>(clamped * 255.0f + 0.5f);
    };

    for (uint32_t y = 0; y < sbs_height; ++y) {
        auto* scan = sbs_image.scanLine(static_cast<int>(y));

        // 좌측 절반: 좌안 이미지를 2픽셀당 1픽셀로 샘플링
        for (uint32_t x = 0; x < half_width; ++x) {
            const uint32_t src_x = x * 2;  // 2픽셀 간격으로 샘플링
            const size_t idx = (y * left.width + src_x) * 3;
            *scan++ = clamp_to_byte(left_data[idx]);
            *scan++ = clamp_to_byte(left_data[idx + 1]);
            *scan++ = clamp_to_byte(left_data[idx + 2]);
        }

        // 우측 절반: 우안 이미지를 2픽셀당 1픽셀로 샘플링
        for (uint32_t x = 0; x < half_width; ++x) {
            const uint32_t src_x = x * 2;
            const size_t idx = (y * right.width + src_x) * 3;
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

    // 8K는 너무 크므로 1/4 크기로 다운샘플링 (4픽셀당 1픽셀)
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
    if (image_label_->size().width() > 0 && image_label_->size().height() > 0) {
        image_label_->setPixmap(QPixmap::fromImage(last_image_).scaled(
            image_label_->size(), Qt::KeepAspectRatio, Qt::FastTransformation));
    }
}
