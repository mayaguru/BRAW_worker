#include "main_window.h"

#include <QFileDialog>
#include <QHBoxLayout>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QResizeEvent>
#include <QString>
#include <QVBoxLayout>
#include <QPixmap>
#include <algorithm>
#include <filesystem>

namespace {
QString to_qstring(const std::filesystem::path& path) {
    return QString::fromStdWString(path.wstring());
}

}  // namespace

MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent) {
    auto* central = new QWidget(this);
    auto* layout = new QVBoxLayout(central);

    auto* controls = new QHBoxLayout();
    open_button_ = new QPushButton(tr("BRAW 열기"), this);
    controls->addWidget(open_button_);

    status_label_ = new QLabel(tr("클립이 선택되지 않았습니다."), this);
    controls->addWidget(status_label_, 1);
    controls->setSpacing(12);
    layout->addLayout(controls);

    info_label_ = new QLabel(tr("정보 없음"), this);
    layout->addWidget(info_label_);

    image_label_ = new QLabel(this);
    image_label_->setAlignment(Qt::AlignCenter);
    image_label_->setMinimumSize(640, 360);
    image_label_->setStyleSheet("background-color: #101010; color: #ffffff;");
    image_label_->setText(tr("미리보기 없음"));
    layout->addWidget(image_label_, 1);

    setCentralWidget(central);
    setWindowTitle(tr("BRAW Viewer (Prototype)"));
    resize(960, 600);

    connect(open_button_, &QPushButton::clicked, this, &MainWindow::handle_open_clip);
}

void MainWindow::handle_open_clip() {
    const QString file = QFileDialog::getOpenFileName(this, tr("BRAW 선택"),
                                                      QString(), tr("BRAW Files (*.braw)"));
    if (file.isEmpty()) {
        return;
    }

    const std::filesystem::path clip_path = file.toStdWString();
    if (!decoder_.open_clip(clip_path)) {
        QMessageBox::critical(this, tr("오류"), tr("클립을 열 수 없습니다."));
        return;
    }

    if (!decoder_.decode_frame(0, frame_buffer_)) {
        QMessageBox::critical(this, tr("오류"), tr("프레임 디코딩에 실패했습니다."));
        return;
    }

    update_clip_info();
    render_to_label(frame_buffer_);
    status_label_->setText(tr("%1 을(를) 불러왔습니다.").arg(file));
}

void MainWindow::update_clip_info() {
    if (const auto info = decoder_.clip_info()) {
        info_label_->setText(tr("경로: %1\n해상도: %2 x %3\n프레임 수: %4  FPS: %5")
                                 .arg(to_qstring(info->source_path))
                                 .arg(info->width)
                                 .arg(info->height)
                                 .arg(info->frame_count)
                                 .arg(info->frame_rate, 0, 'f', 3));
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
