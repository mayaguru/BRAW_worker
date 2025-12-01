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
#include <QMessageBox>
#include <QPixmap>
#include <QPushButton>
#include <QResizeEvent>
#include <QSlider>
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

MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent) {
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
    }

    load_frame(0);
    update_clip_info();
    update_ui_state();
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

    // 내보내기 다이얼로그
    QDialog dialog(this);
    dialog.setWindowTitle(tr("내보내기 설정"));
    auto* layout = new QVBoxLayout(&dialog);

    // 포맷 선택
    auto* format_group = new QGroupBox(tr("포맷"), &dialog);
    auto* format_layout = new QVBoxLayout(format_group);
    auto* format_combo = new QComboBox(&dialog);
    format_combo->addItem(tr("PPM (8-bit RGB)"), "ppm");
    format_combo->addItem(tr("EXR (16-bit Half Float, DWAA)"), "exr");
    format_layout->addWidget(format_combo);
    layout->addWidget(format_group);

    // 스테레오 옵션
    auto* stereo_group = new QGroupBox(tr("스테레오"), &dialog);
    auto* stereo_layout = new QVBoxLayout(stereo_group);
    auto* eye_combo = new QComboBox(&dialog);

    const auto info = decoder_.clip_info();
    const bool has_stereo = info && info->has_immersive_video && info->available_view_count >= 2;

    eye_combo->addItem(tr("좌안만"), "left");
    eye_combo->addItem(tr("우안만"), "right");
    if (has_stereo) {
        eye_combo->addItem(tr("양안 (별도 파일)"), "both");
    }
    stereo_layout->addWidget(eye_combo);
    layout->addWidget(stereo_group);

    // 프레임 범위
    auto* range_group = new QGroupBox(tr("프레임 범위"), &dialog);
    auto* range_layout = new QFormLayout(range_group);
    auto* export_current = new QCheckBox(tr("현재 프레임만"), &dialog);
    export_current->setChecked(true);
    range_layout->addRow(export_current);
    layout->addWidget(range_group);

    // 버튼
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    layout->addWidget(buttons);

    if (dialog.exec() != QDialog::Accepted) {
        return;
    }

    // 내보내기 실행
    const QString format = format_combo->currentData().toString();
    const QString eye_mode = eye_combo->currentData().toString();
    const QString ext = format == "exr" ? ".exr" : ".ppm";

    QString save_path = QFileDialog::getSaveFileName(
        this, tr("다른 이름으로 저장"), QString(),
        format == "exr" ? tr("OpenEXR Files (*.exr)") : tr("PPM Files (*.ppm)"));

    if (save_path.isEmpty()) {
        return;
    }

    const std::filesystem::path output_path = save_path.toStdWString();

    auto export_frame = [&](braw::StereoView view, const std::filesystem::path& path) -> bool {
        braw::FrameBuffer buffer;
        if (!decoder_.decode_frame(current_frame_, buffer, view)) {
            return false;
        }

        if (format == "exr") {
            return braw::write_exr_half_dwaa(path, buffer, 45.0f);
        } else {
            return braw::write_ppm(path, buffer);
        }
    };

    bool success = false;
    if (eye_mode == "both") {
        const auto left_path = build_stereo_path(output_path, "_L");
        const auto right_path = build_stereo_path(output_path, "_R");
        success = export_frame(braw::StereoView::kLeft, left_path) &&
                  export_frame(braw::StereoView::kRight, right_path);
    } else {
        const braw::StereoView view = (eye_mode == "right") ?
            braw::StereoView::kRight : braw::StereoView::kLeft;
        success = export_frame(view, output_path);
    }

    if (success) {
        QMessageBox::information(this, tr("완료"), tr("내보내기가 완료되었습니다."));
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
    if (!decoder_.decode_frame(frame_index, frame_buffer_)) {
        status_label_->setText(tr("프레임 %1 디코딩 실패").arg(frame_index));
        return;
    }

    current_frame_ = frame_index;
    frame_slider_->blockSignals(true);
    frame_slider_->setValue(static_cast<int>(frame_index));
    frame_slider_->blockSignals(false);

    const auto info = decoder_.clip_info();
    if (info) {
        frame_label_->setText(tr("%1 / %2").arg(frame_index).arg(info->frame_count - 1));
    }

    render_to_label(frame_buffer_);
}

void MainWindow::update_ui_state() {
    play_button_->setEnabled(has_clip_);
    export_button_->setEnabled(has_clip_);
    frame_slider_->setEnabled(has_clip_ && !is_playing_);
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

void MainWindow::render_to_label(const braw::FrameBuffer& buffer) {
    const QImage image = convert_to_qimage(buffer);
    if (image.isNull()) {
        image_label_->setText(tr("미리보기를 생성할 수 없습니다."));
        return;
    }

    last_image_ = image;
    image_label_->setPixmap(
        QPixmap::fromImage(last_image_).scaled(image_label_->size(), Qt::KeepAspectRatio,
                                               Qt::SmoothTransformation));
    image_label_->setText(QString());
}

QImage MainWindow::convert_to_qimage(const braw::FrameBuffer& buffer) const {
    if (buffer.format != braw::FramePixelFormat::kRGBFloat32 || buffer.width == 0 ||
        buffer.height == 0) {
        return {};
    }

    QImage image(buffer.width, buffer.height, QImage::Format_RGB888);
    const auto data = buffer.as_span();
    size_t idx = 0;
    for (uint32_t y = 0; y < buffer.height; ++y) {
        auto* scan = image.scanLine(static_cast<int>(y));
        for (uint32_t x = 0; x < buffer.width; ++x) {
            auto clamp_to_byte = [](float value) -> unsigned char {
                float clamped = std::clamp(value, 0.0f, 1.0f);
                return static_cast<unsigned char>(clamped * 255.0f + 0.5f);
            };

            const unsigned char r = clamp_to_byte(data[idx++]);
            const unsigned char g = clamp_to_byte(data[idx++]);
            const unsigned char b = clamp_to_byte(data[idx++]);
            *scan++ = r;
            *scan++ = g;
            *scan++ = b;
        }
    }
    return image;
}

void MainWindow::resizeEvent(QResizeEvent* event) {
    QMainWindow::resizeEvent(event);
    if (last_image_.isNull()) {
        return;
    }
    image_label_->setPixmap(QPixmap::fromImage(last_image_).scaled(
        image_label_->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
}
