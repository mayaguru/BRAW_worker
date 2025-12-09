#pragma once

#include <QImage>
#include <QMainWindow>
#include <QThread>
#include <QMutex>
#include <QWaitCondition>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QMimeData>
#include <QKeyEvent>
#include <atomic>
#include <queue>

#include "core/braw_decoder.h"

class QLabel;
class QPushButton;
class QTimer;
class TimelineSlider;
class MainWindow;

// 백그라운드 디코딩 스레드
class DecodeThread : public QThread {
    Q_OBJECT

  public:
    explicit DecodeThread(braw::BrawDecoder& decoder, QObject* parent = nullptr);
    ~DecodeThread() override;

    void start_decoding(uint32_t start_frame, uint32_t frame_count, int stereo_view);
    void stop_decoding();
    bool get_next_frame(QImage& out_image, uint32_t& out_frame_index);
    void clear_buffer();
    void set_stereo_mode(int view) { stereo_view_ = view; }

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
    std::atomic<int> stereo_view_{0};  // 0=left, 1=right, 2=sbs
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
    void open_braw_file(const QString& file_path);
    void resizeEvent(QResizeEvent* event) override;
    void dragEnterEvent(QDragEnterEvent* event) override;
    void dropEvent(QDropEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;
    void set_stereo_view(int view);  // 0=left, 1=right, 2=sbs

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
    TimelineSlider* timeline_slider_{nullptr};
    QTimer* playback_timer_{nullptr};
    QPushButton* left_button_{nullptr};
    QPushButton* right_button_{nullptr};
    QPushButton* sbs_button_{nullptr};

    uint32_t current_frame_{0};
    bool is_playing_{false};
    bool has_clip_{false};
    int stereo_view_{0};  // 0=left, 1=right, 2=sbs

    QImage convert_to_qimage(const braw::FrameBuffer& buffer) const;
    QImage create_sbs_image(const braw::FrameBuffer& left, const braw::FrameBuffer& right) const;
};
