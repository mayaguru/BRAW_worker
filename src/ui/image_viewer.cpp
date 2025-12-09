#include "image_viewer.h"

#include <QMouseEvent>
#include <QPainter>
#include <QWheelEvent>
#include <algorithm>
#include <cmath>

ImageViewer::ImageViewer(QWidget* parent) : QWidget(parent) {
    setMouseTracking(true);
    setFocusPolicy(Qt::StrongFocus);
    setMinimumSize(320, 180);
}

void ImageViewer::setImage(const QImage& image) {
    image_ = image;
    update();
}

void ImageViewer::resetView() {
    zoom_ = 1.0f;
    offset_ = QPointF(0, 0);
    emit zoomChanged(zoom_);
    update();
}

void ImageViewer::fitToWindow() {
    if (image_.isNull() || width() == 0 || height() == 0) {
        return;
    }

    const float scale_x = static_cast<float>(width()) / image_.width();
    const float scale_y = static_cast<float>(height()) / image_.height();
    zoom_ = std::min(scale_x, scale_y);
    zoom_ = std::clamp(zoom_, MIN_ZOOM, MAX_ZOOM);
    offset_ = QPointF(0, 0);
    emit zoomChanged(zoom_);
    update();
}

void ImageViewer::setZoom(float zoom) {
    zoom_ = std::clamp(zoom, MIN_ZOOM, MAX_ZOOM);
    clampOffset();
    emit zoomChanged(zoom_);
    update();
}

void ImageViewer::paintEvent(QPaintEvent* /*event*/) {
    QPainter painter(this);
    painter.setRenderHint(QPainter::SmoothPixmapTransform, zoom_ < 2.0f);

    // 배경
    painter.fillRect(rect(), QColor(16, 16, 16));

    if (image_.isNull()) {
        painter.setPen(QColor(128, 128, 128));
        painter.drawText(rect(), Qt::AlignCenter,
                         tr("BRAW 파일을 드래그하거나 열기 버튼을 클릭하세요"));
        return;
    }

    // 이미지 크기 계산
    const float scaled_width = image_.width() * zoom_;
    const float scaled_height = image_.height() * zoom_;

    // 중앙 정렬 + 오프셋
    const float x = (width() - scaled_width) / 2.0f + offset_.x();
    const float y = (height() - scaled_height) / 2.0f + offset_.y();

    // 이미지 그리기
    QRectF target_rect(x, y, scaled_width, scaled_height);
    painter.drawImage(target_rect, image_);

    // 줌 레벨 표시 (100%가 아닐 때만)
    if (std::abs(zoom_ - 1.0f) > 0.01f) {
        QString zoom_text = QString("%1%").arg(static_cast<int>(zoom_ * 100));
        QFont font = painter.font();
        font.setPointSize(10);
        painter.setFont(font);

        QRect text_rect = painter.fontMetrics().boundingRect(zoom_text);
        text_rect.adjust(-6, -3, 6, 3);
        text_rect.moveBottomRight(QPoint(width() - 10, height() - 10));

        painter.fillRect(text_rect, QColor(0, 0, 0, 160));
        painter.setPen(QColor(200, 200, 200));
        painter.drawText(text_rect, Qt::AlignCenter, zoom_text);
    }
}

void ImageViewer::wheelEvent(QWheelEvent* event) {
    if (image_.isNull()) {
        return;
    }

    // 줌 인/아웃
    const float zoom_factor = (event->angleDelta().y() > 0) ? 1.15f : 1.0f / 1.15f;
    const float new_zoom = std::clamp(zoom_ * zoom_factor, MIN_ZOOM, MAX_ZOOM);

    if (std::abs(new_zoom - zoom_) > 0.001f) {
        // 마우스 위치를 기준으로 줌
        const QPointF mouse_pos = event->position();
        const QPointF image_center(width() / 2.0f + offset_.x(), height() / 2.0f + offset_.y());
        const QPointF delta = mouse_pos - image_center;

        // 새 오프셋 계산 (마우스 위치가 고정되도록)
        const float ratio = new_zoom / zoom_;
        offset_ = QPointF(
            offset_.x() - delta.x() * (ratio - 1.0f),
            offset_.y() - delta.y() * (ratio - 1.0f)
        );

        zoom_ = new_zoom;
        clampOffset();
        emit zoomChanged(zoom_);
        update();
    }

    event->accept();
}

void ImageViewer::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::MiddleButton) {
        // 휠 버튼으로 패닝 시작
        panning_ = true;
        last_mouse_pos_ = event->position();
        setCursor(Qt::ClosedHandCursor);
        event->accept();
    } else {
        QWidget::mousePressEvent(event);
    }
}

void ImageViewer::mouseMoveEvent(QMouseEvent* event) {
    if (panning_) {
        const QPointF delta = event->position() - last_mouse_pos_;
        offset_ += delta;
        clampOffset();
        last_mouse_pos_ = event->position();
        update();
        event->accept();
    } else {
        QWidget::mouseMoveEvent(event);
    }
}

void ImageViewer::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() == Qt::MiddleButton && panning_) {
        panning_ = false;
        setCursor(Qt::ArrowCursor);
        event->accept();
    } else {
        QWidget::mouseReleaseEvent(event);
    }
}

void ImageViewer::mouseDoubleClickEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        // 더블클릭으로 100% 줌 또는 fit 토글
        if (std::abs(zoom_ - 1.0f) < 0.01f) {
            fitToWindow();
        } else {
            // 100% 줌으로 리셋
            zoom_ = 1.0f;
            offset_ = QPointF(0, 0);
            emit zoomChanged(zoom_);
            update();
        }
        event->accept();
    } else if (event->button() == Qt::MiddleButton) {
        // 휠 더블클릭으로 fit to window
        fitToWindow();
        event->accept();
    } else {
        QWidget::mouseDoubleClickEvent(event);
    }
}

void ImageViewer::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    clampOffset();
    update();
}

void ImageViewer::clampOffset() {
    if (image_.isNull()) {
        offset_ = QPointF(0, 0);
        return;
    }

    const float scaled_width = image_.width() * zoom_;
    const float scaled_height = image_.height() * zoom_;

    // 이미지가 위젯보다 작으면 오프셋 제한 없음 (중앙에 표시)
    // 이미지가 위젯보다 크면 이미지가 위젯 밖으로 나가지 않도록 제한
    float max_offset_x = 0;
    float max_offset_y = 0;

    if (scaled_width > width()) {
        max_offset_x = (scaled_width - width()) / 2.0f;
    }
    if (scaled_height > height()) {
        max_offset_y = (scaled_height - height()) / 2.0f;
    }

    offset_.setX(std::clamp(static_cast<float>(offset_.x()), -max_offset_x, max_offset_x));
    offset_.setY(std::clamp(static_cast<float>(offset_.y()), -max_offset_y, max_offset_y));
}

QPointF ImageViewer::mapToImage(const QPointF& widget_pos) const {
    if (image_.isNull()) {
        return {};
    }

    const float scaled_width = image_.width() * zoom_;
    const float scaled_height = image_.height() * zoom_;
    const float x = (width() - scaled_width) / 2.0f + offset_.x();
    const float y = (height() - scaled_height) / 2.0f + offset_.y();

    return QPointF(
        (widget_pos.x() - x) / zoom_,
        (widget_pos.y() - y) / zoom_
    );
}
