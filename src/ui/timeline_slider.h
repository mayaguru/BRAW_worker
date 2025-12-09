#pragma once

#include <QWidget>
#include <QMouseEvent>
#include <QWheelEvent>
#include <QPaintEvent>
#include <QPainter>

class TimelineSlider : public QWidget {
    Q_OBJECT

  public:
    explicit TimelineSlider(QWidget* parent = nullptr);
    ~TimelineSlider() = default;

    void setValue(int frame);
    int value() const { return current_frame_; }
    void setRange(int total);
    int maximum() const { return total_frames_ > 0 ? total_frames_ - 1 : 0; }
    void setFrameRate(double fps);
    double frameRate() const { return frame_rate_; }

  signals:
    void valueChanged(int frame);
    void sliderPressed();
    void sliderReleased();
    void zoomChanged(float zoom);

  protected:
    void paintEvent(QPaintEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

  private:
    int pixelToFrame(float x) const;
    float frameToPixel(int frame) const;
    QString frameToTimecode(int frame) const;

    int total_frames_{100};
    int current_frame_{0};
    double frame_rate_{24.0};

    float zoom_factor_{1.0f};
    float min_zoom_{1.0f};
    float max_zoom_{50.0f};
    float offset_{0.0f};

    bool dragging_{false};
    bool panning_{false};
    QPointF last_mouse_pos_;

    // Colors
    QColor background_color_{50, 50, 50};
    QColor tick_color_{100, 100, 100};
    QColor text_color_{180, 180, 180};
    QColor playhead_color_{255, 50, 50};
};
