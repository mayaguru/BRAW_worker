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
#include "core/stmap_warper.h"

class QComboBox;
class QLabel;
class QPushButton;
class QSlider;
class QTimer;
class TimelineSlider;
class ImageViewer;
class MainWindow;

// 렌더링 설정 (스레드 안전한 스냅샷용)
struct RenderSettings {
    uint32_t scale{4};
    bool color_transform{true};
    float exposure{0.0f};
    float gain{1.0f};
    float gamma{1.0f};
};

// 백그라운드 디코딩 스레드
class DecodeThread : public QThread {
    Q_OBJECT

  public:
    explicit DecodeThread(braw::BrawDecoder& decoder, braw::STMapWarper& stmap_warper, QObject* parent = nullptr);
    ~DecodeThread() override;

    void start_decoding(uint32_t start_frame, uint32_t frame_count, int stereo_view);
    void stop_decoding();
    bool get_next_frame(QImage& out_image, uint32_t& out_frame_index);
    void clear_buffer();
    void set_stereo_mode(int view) { stereo_view_ = view; }
    void set_downsample_scale(uint32_t scale) { 
        QMutexLocker lock(&settings_mutex_);
        settings_.scale = scale; 
    }
    void set_color_transform(bool enabled) { 
        QMutexLocker lock(&settings_mutex_);
        settings_.color_transform = enabled; 
    }
    void set_exposure(float ev) { 
        QMutexLocker lock(&settings_mutex_);
        settings_.exposure = ev; 
    }
    void set_gain(float gain) { 
        QMutexLocker lock(&settings_mutex_);
        settings_.gain = gain; 
    }
    void set_gamma(float gamma) { 
        QMutexLocker lock(&settings_mutex_);
        settings_.gamma = gamma; 
    }

  signals:
    void frame_ready();

  protected:
    void run() override;

  private:
    QImage decode_frame_to_image(uint32_t frame_index);

    braw::BrawDecoder& decoder_;
    braw::STMapWarper& stmap_warper_;
    braw::FrameBuffer buffer_left_;
    braw::FrameBuffer buffer_right_;

    std::atomic<bool> running_{false};
    std::atomic<int> stereo_view_{0};  // 0=left, 1=right, 2=sbs

    // 렌더링 설정 (뮤텍스로 보호, 일관성 보장)
    mutable QMutex settings_mutex_;
    RenderSettings settings_;

    // 설정 스냅샷 가져오기 (스레드 안전)
    RenderSettings get_settings() const {
        QMutexLocker lock(&settings_mutex_);
        return settings_;
    }
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
    void set_downsample_scale(int index);  // 0=1/4, 1=1/2, 2=원본
    void toggle_stmap();
    void load_stmap();
    void toggle_color_transform();
    void update_color_settings();

    braw::BrawDecoder decoder_;
    braw::STMapWarper stmap_warper_;
    braw::FrameBuffer frame_buffer_left_;
    braw::FrameBuffer frame_buffer_right_;
    QImage last_image_;

    // 백그라운드 디코딩
    DecodeThread* decode_thread_{nullptr};

    QLabel* info_label_{nullptr};
    ImageViewer* image_viewer_{nullptr};
    QLabel* status_label_{nullptr};
    QPushButton* open_button_{nullptr};
    QPushButton* play_button_{nullptr};
    QPushButton* export_button_{nullptr};
    TimelineSlider* timeline_slider_{nullptr};
    QTimer* playback_timer_{nullptr};
    QPushButton* left_button_{nullptr};
    QPushButton* right_button_{nullptr};
    QPushButton* sbs_button_{nullptr};
    QPushButton* stmap_button_{nullptr};
    QPushButton* color_button_{nullptr};  // 색변환 토글 버튼
    QSlider* exposure_slider_{nullptr};  // 익스포져 조절
    QSlider* gamma_slider_{nullptr};  // 감마 조절
    QComboBox* resolution_combo_{nullptr};

    // 색보정 슬라이더 (팝업 다이얼로그에서 사용)
    float exposure_{0.0f};  // -3 ~ +3 EV
    float gain_{1.0f};  // 0.5 ~ 2.0
    float gamma_{1.0f};  // 0.0 ~ 2.2
    bool color_transform_{true};  // BMDFilm → sRGB 변환

    uint32_t current_frame_{0};
    bool is_playing_{false};
    bool has_clip_{false};
    int stereo_view_{0};  // 0=left, 1=right, 2=sbs
    uint32_t downsample_scale_{4};  // 1=원본, 2=중간, 4=1/4
    QString current_clip_path_;  // 현재 열린 클립 경로

    QImage convert_to_qimage(const braw::FrameBuffer& buffer) const;
    QImage create_sbs_image(const braw::FrameBuffer& left, const braw::FrameBuffer& right) const;
};
