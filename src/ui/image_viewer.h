#pragma once

#include <QImage>
#include <QPointF>
#include <QWidget>

class ImageViewer : public QWidget {
    Q_OBJECT

  public:
    explicit ImageViewer(QWidget* parent = nullptr);

    void setImage(const QImage& image);
    void resetView();
    void fitToWindow();

    float zoom() const { return zoom_; }
    void setZoom(float zoom);

  signals:
    void zoomChanged(float zoom);

  protected:
    void paintEvent(QPaintEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void mouseDoubleClickEvent(QMouseEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

  private:
    void clampOffset();
    QPointF mapToImage(const QPointF& widget_pos) const;

    QImage image_;
    float zoom_{1.0f};
    QPointF offset_{0, 0};  // 이미지 오프셋 (패닝용)

    bool panning_{false};
    QPointF last_mouse_pos_;

    static constexpr float MIN_ZOOM = 0.1f;
    static constexpr float MAX_ZOOM = 10.0f;
};
