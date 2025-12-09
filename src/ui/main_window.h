#pragma once

#include <QImage>
#include <QMainWindow>
#include <QThread>
#include <QMutex>
#include <QWaitCondition>
#include <atomic>
#include <queue>

#include "core/braw_decoder.h"

class QLabel;
class QPushButton;
class QSlider;
class QTimer;
class MainWindow;

// 백그라운드 디코딩 스레드
class DecodeThread : public QThread {
    Q_OBJECT

  public:
    explicit DecodeThread(braw::BrawDecoder& decoder, QObject* parent = nullptr);
    ~DecodeThread() override;

    void start_decoding(uint32_t start_frame, uint32_t frame_count, bool stereo_sbs);
    void stop_decoding();
    bool get_next_frame(QImage& out_image, uint32_t& out_frame_index);
    void clear_buffer();
    void set_stereo_mode(bool sbs) { stereo_sbs_ = sbs; }

  signals:
    void frame_ready();

  protected:
    void run() override;

  private:
    QImage decode_frame_to_image(uint32_t frame_index);

    braw::BrawDecoder& decoder_;
    braw::FrameBuffer buffer_left_;
    braw::FrameBuffer buffer_right_;

    std::atomic<bool> running_{false};
    std::atomic<bool> stereo_sbs_{false};
    uint32_t start_frame_{0};
    uint32_t frame_count_{0};
    uint32_t current_decode_frame_{0};

    // 프레임 버퍼 큐
    static constexpr size_t BUFFER_SIZE = 8;  // 8프레임 버퍼
    QMutex buffer_mutex_;
    QWaitCondition buffer_not_full_;
    QWaitCondition buffer_not_empty_;
    std::queue<std::pair<uint32_t, QImage>> frame_buffer_;
};

class MainWindow : public QMainWindow {
    Q_OBJECT

  public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

  private slots:
    void handle_open_clip();
    void handle_play_pause();
    void handle_export();
    void handle_frame_slider_changed(int value);
    void handle_playback_timer();
    void handle_frame_decoded();

  private:
    void update_clip_info();
    void load_frame(uint32_t frame_index);
    void update_ui_state();
    void display_image(const QImage& image);
    void resizeEvent(QResizeEvent* event) override;

    braw::BrawDecoder decoder_;
    braw::FrameBuffer frame_buffer_left_;
    braw::FrameBuffer frame_buffer_right_;
    QImage last_image_;

    // 백그라운드 디코딩
    DecodeThread* decode_thread_{nullptr};

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
