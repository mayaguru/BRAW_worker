#include "timeline_slider.h"
#include <algorithm>
#include <cmath>
#include <set>

TimelineSlider::TimelineSlider(QWidget* parent) : QWidget(parent) {
    setMinimumHeight(60);
    setMouseTracking(true);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
}

void TimelineSlider::setValue(int frame) {
    if (total_frames_ > 0) {
        current_frame_ = std::clamp(frame, 0, total_frames_ - 1);
    } else {
        current_frame_ = 0;
    }
    update();
}

void TimelineSlider::setRange(int total) {
    total_frames_ = std::max(1, total);
    if (current_frame_ >= total_frames_) {
        current_frame_ = total_frames_ - 1;
    }

    int timeline_width = width();
    if (timeline_width > 0) {
        min_zoom_ = 1.0f;
        zoom_factor_ = min_zoom_;
        offset_ = 0.0f;
    }
    update();
}

void TimelineSlider::setFrameRate(double fps) {
    frame_rate_ = fps > 0 ? fps : 24.0;
    update();
}

void TimelineSlider::paintEvent(QPaintEvent* event) {
    Q_UNUSED(event);
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);

    QRect rect = this->rect();
    int w = rect.width();
    int h = rect.height();

    // Background
    painter.fillRect(rect, background_color_);

    if (total_frames_ <= 0) {
        painter.setPen(QColor(150, 150, 150));
        painter.drawText(rect, Qt::AlignCenter, "No frames");
        return;
    }

    // Layout
    int top_margin = 20;
    int bottom_margin = 18;
    int timeline_top = top_margin;
    int timeline_bottom = h - bottom_margin;
    int timeline_height = timeline_bottom - timeline_top;

    if (timeline_height <= 0) return;

    // Calculate visible frame range
    float frame_width = w / static_cast<float>(total_frames_) * zoom_factor_;
    if (frame_width <= 0) return;

    int visible_start = std::max(0, static_cast<int>(offset_ / frame_width));
    int visible_end = std::min(total_frames_ - 1, static_cast<int>((offset_ + w) / frame_width));

    // Adaptive tick interval
    int tick_interval = 1;
    int text_interval = 1;

    if (zoom_factor_ < 0.5f) {
        tick_interval = std::max(1, total_frames_ / 50);
        text_interval = std::max(1, total_frames_ / 20);
    } else if (zoom_factor_ < 2.0f) {
        tick_interval = std::max(1, total_frames_ / 100);
        text_interval = std::max(1, total_frames_ / 40);
    } else if (zoom_factor_ < 10.0f) {
        tick_interval = 1;
        text_interval = std::max(1, static_cast<int>(50 / zoom_factor_));
    } else {
        tick_interval = 1;
        text_interval = std::max(1, static_cast<int>(100 / zoom_factor_));
    }

    // Round to nice numbers
    auto roundToNice = [](int val) -> int {
        int nice[] = {1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000};
        for (int n : nice) {
            if (n >= val) return n;
        }
        return val;
    };

    if (tick_interval > 1) tick_interval = roundToNice(tick_interval);
    if (text_interval > 1) text_interval = roundToNice(text_interval);
    if (text_interval < tick_interval) text_interval = tick_interval;

    int major_interval = tick_interval * 10;
    if (major_interval > total_frames_ / 5) major_interval = tick_interval;

    // Draw ticks
    int small_tick_h = std::max(3, timeline_height / 6);
    int large_tick_h = std::max(6, timeline_height / 3);

    std::set<int> drawn_text_x;
    const int MIN_TEXT_SPACING = 60;

    painter.setPen(tick_color_);

    for (int frame = visible_start; frame <= visible_end; frame += tick_interval) {
        float x = frameToPixel(frame);
        if (x < 0 || x > w) continue;

        bool is_major = (frame % major_interval == 0) || (frame == 0) || (frame == total_frames_ - 1);
        int tick_h = is_major ? large_tick_h : small_tick_h;
        int tick_y = timeline_bottom - tick_h;

        painter.drawLine(QPointF(x, tick_y), QPointF(x, timeline_bottom));

        // Draw text
        bool show_text = is_major && (frame % text_interval == 0) && zoom_factor_ >= 0.3f;
        if (show_text) {
            int px = static_cast<int>(x);
            bool overlaps = false;
            for (int drawn : drawn_text_x) {
                if (std::abs(px - drawn) < MIN_TEXT_SPACING) {
                    overlaps = true;
                    break;
                }
            }

            if (!overlaps) {
                painter.setPen(text_color_);
                QString text = QString::number(frame);
                QFontMetrics fm(painter.font());
                int text_w = fm.horizontalAdvance(text);
                int text_x = px - text_w / 2;
                text_x = std::clamp(text_x, 0, w - text_w);
                painter.drawText(text_x, timeline_bottom + 12, text);
                painter.setPen(tick_color_);
                drawn_text_x.insert(px);
            }
        }
    }

    // Draw playhead (red vertical line)
    float playhead_x = frameToPixel(current_frame_);
    if (playhead_x >= 0 && playhead_x <= w) {
        // Playhead line
        painter.setPen(QPen(playhead_color_, 2));
        painter.drawLine(QPointF(playhead_x, timeline_top), QPointF(playhead_x, timeline_bottom));

        // Playhead handle (triangle at top)
        painter.setBrush(playhead_color_);
        painter.setPen(Qt::NoPen);
        QPolygonF triangle;
        int tri_size = 6;
        triangle << QPointF(playhead_x, timeline_top)
                 << QPointF(playhead_x - tri_size, timeline_top - tri_size)
                 << QPointF(playhead_x + tri_size, timeline_top - tri_size);
        painter.drawPolygon(triangle);
    }

    // Draw frame info at top
    painter.setPen(QColor(255, 255, 255));
    painter.setFont(QFont("Arial", 10, QFont::Bold));

    QString frame_text = QString("Frame %1 / %2").arg(current_frame_).arg(maximum());
    painter.drawText(10, 14, frame_text);

    QString tc_text = QString("TC %1").arg(frameToTimecode(current_frame_));
    QFontMetrics fm(painter.font());
    int tc_width = fm.horizontalAdvance(tc_text);
    painter.drawText(w - tc_width - 10, 14, tc_text);

    // Draw current time at bottom left
    painter.setFont(QFont("Arial", 8));
    painter.setPen(text_color_);
    QString current_tc = frameToTimecode(current_frame_);
    painter.drawText(10, h - 4, current_tc);

    // Draw total time at bottom right
    QString total_tc = frameToTimecode(maximum());
    int total_w = fm.horizontalAdvance(total_tc);
    painter.drawText(w - total_w - 10, h - 4, total_tc);
}

void TimelineSlider::mousePressEvent(QMouseEvent* event) {
    if (total_frames_ <= 0) {
        event->accept();
        return;
    }

    if (event->button() == Qt::LeftButton) {
        dragging_ = true;
        last_mouse_pos_ = event->pos();
        current_frame_ = pixelToFrame(event->pos().x());
        emit valueChanged(current_frame_);
        emit sliderPressed();
        update();
    } else if (event->button() == Qt::MiddleButton) {
        panning_ = true;
        last_mouse_pos_ = event->pos();
    }
}

void TimelineSlider::mouseMoveEvent(QMouseEvent* event) {
    if (total_frames_ <= 0) {
        event->accept();
        return;
    }

    if (dragging_) {
        current_frame_ = pixelToFrame(event->pos().x());
        emit valueChanged(current_frame_);
        update();
    } else if (panning_) {
        float dx = event->pos().x() - last_mouse_pos_.x();
        offset_ -= dx;

        int timeline_width = width();
        if (timeline_width > 0 && total_frames_ > 0) {
            float total_zoomed = timeline_width * zoom_factor_;
            float max_offset = std::max(0.0f, total_zoomed - timeline_width);
            offset_ = std::clamp(offset_, 0.0f, max_offset);
        }

        last_mouse_pos_ = event->pos();
        update();
    }
}

void TimelineSlider::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton && dragging_) {
        dragging_ = false;
        emit sliderReleased();
    } else if (event->button() == Qt::MiddleButton && panning_) {
        panning_ = false;
    }
    last_mouse_pos_ = QPointF();
}

void TimelineSlider::wheelEvent(QWheelEvent* event) {
    float mouse_x = event->position().x();
    int frame_at_mouse = pixelToFrame(mouse_x);

    if (event->angleDelta().y() > 0) {
        zoom_factor_ *= 1.15f;
    } else {
        zoom_factor_ /= 1.15f;
    }
    zoom_factor_ = std::clamp(zoom_factor_, min_zoom_, max_zoom_);

    float new_mouse_x = frameToPixel(frame_at_mouse);
    offset_ += (new_mouse_x - mouse_x);

    int timeline_width = width();
    if (timeline_width > 0 && total_frames_ > 0) {
        float total_zoomed = timeline_width * zoom_factor_;
        float max_offset = std::max(0.0f, total_zoomed - timeline_width);
        offset_ = std::clamp(offset_, 0.0f, max_offset);
    }

    update();
    emit zoomChanged(zoom_factor_);
}

void TimelineSlider::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);

    int timeline_width = width();
    if (timeline_width > 0 && total_frames_ > 0) {
        if (zoom_factor_ < min_zoom_) {
            zoom_factor_ = min_zoom_;
            offset_ = 0.0f;
        }

        float total_zoomed = timeline_width * zoom_factor_;
        float max_offset = std::max(0.0f, total_zoomed - timeline_width);
        offset_ = std::clamp(offset_, 0.0f, max_offset);
    }
    update();
}

int TimelineSlider::pixelToFrame(float x) const {
    if (total_frames_ <= 0 || zoom_factor_ <= 0) return 0;

    int timeline_width = width();
    if (timeline_width <= 0) return 0;

    float frame_width = timeline_width / static_cast<float>(total_frames_) * zoom_factor_;
    if (frame_width <= 0) return 0;

    int frame = static_cast<int>((x + offset_) / frame_width);
    return std::clamp(frame, 0, total_frames_ - 1);
}

float TimelineSlider::frameToPixel(int frame) const {
    if (total_frames_ <= 0) return 0;

    int timeline_width = width();
    if (timeline_width <= 0) return 0;

    float frame_width = timeline_width / static_cast<float>(total_frames_) * zoom_factor_;
    return frame * frame_width - offset_;
}

QString TimelineSlider::frameToTimecode(int frame) const {
    if (frame_rate_ <= 0) return "00:00:00:00";

    double fps = std::clamp(frame_rate_, 1.0, 120.0);
    int fps_int = static_cast<int>(fps + 0.5);

    int frame_comp = frame % fps_int;
    int total_secs = frame / fps_int;
    int hours = total_secs / 3600;
    int mins = (total_secs % 3600) / 60;
    int secs = total_secs % 60;

    return QString("%1:%2:%3:%4")
        .arg(hours, 2, 10, QChar('0'))
        .arg(mins, 2, 10, QChar('0'))
        .arg(secs, 2, 10, QChar('0'))
        .arg(frame_comp, 2, 10, QChar('0'));
}
