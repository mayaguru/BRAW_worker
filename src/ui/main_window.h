#pragma once

#include <QImage>
#include <QMainWindow>

#include "core/braw_decoder.h"

class QLabel;
class QPushButton;
class QSlider;
class QTimer;

class MainWindow : public QMainWindow {
    Q_OBJECT

  public:
    explicit MainWindow(QWidget* parent = nullptr);

  private slots:
    void handle_open_clip();
    void handle_play_pause();
    void handle_export();
    void handle_frame_slider_changed(int value);
    void handle_playback_timer();

  private:
    void update_clip_info();
    void load_frame(uint32_t frame_index);
    void update_ui_state();
    void resizeEvent(QResizeEvent* event) override;

    braw::BrawDecoder decoder_;
    braw::FrameBuffer frame_buffer_left_;
    braw::FrameBuffer frame_buffer_right_;
    QImage last_image_;

    QLabel* info_label_{nullptr};
    QLabel* image_label_{nullptr};
    QLabel* status_label_{nullptr};
    QPushButton* open_button_{nullptr};
    QPushButton* play_button_{nullptr};
    QPushButton* export_button_{nullptr};
    QSlider* frame_slider_{nullptr};
    QLabel* frame_label_{nullptr};
    QTimer* playback_timer_{nullptr};
    QPushButton* stereo_button_{nullptr};

    uint32_t current_frame_{0};
    bool is_playing_{false};
    bool has_clip_{false};
    bool show_stereo_sbs_{false};  // 기본값: 좌안만

    QImage convert_to_qimage(const braw::FrameBuffer& buffer) const;
    QImage create_sbs_image(const braw::FrameBuffer& left, const braw::FrameBuffer& right) const;
};
