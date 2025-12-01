#pragma once

#include <QImage>
#include <QMainWindow>

#include "core/braw_decoder.h"

class QLabel;
class QPushButton;

class MainWindow : public QMainWindow {
    Q_OBJECT

  public:
    explicit MainWindow(QWidget* parent = nullptr);

  private slots:
    void handle_open_clip();

  private:
    void update_clip_info();
    void render_to_label(const braw::FrameBuffer& buffer);
    void resizeEvent(QResizeEvent* event) override;

    braw::BrawDecoder decoder_;
    braw::FrameBuffer frame_buffer_;
    QImage last_image_;

    QLabel* info_label_{nullptr};
    QLabel* image_label_{nullptr};
    QLabel* status_label_{nullptr};
    QPushButton* open_button_{nullptr};

    QImage convert_to_qimage(const braw::FrameBuffer& buffer) const;
};
