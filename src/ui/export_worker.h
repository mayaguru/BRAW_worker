#pragma once

#include <QObject>
#include <QMutex>
#include <QQueue>
#include <QWaitCondition>
#include <filesystem>

#include "core/frame_buffer.h"

namespace braw {
    class FrameBuffer;
}

// Export task for worker threads
struct ExportTask {
    braw::FrameBuffer buffer;
    std::filesystem::path output_path;
    bool is_exr;
    int frame_index;
    QString eye_name;
    
    ExportTask() = default;
    ExportTask(const braw::FrameBuffer& buf, const std::filesystem::path& path, bool exr, int frame, const QString& eye)
        : buffer(buf), output_path(path), is_exr(exr), frame_index(frame), eye_name(eye) {}
};

Q_DECLARE_METATYPE(ExportTask)

// Worker thread that writes frames to files
class ExportWorker : public QObject {
    Q_OBJECT

public:
    explicit ExportWorker(QObject* parent = nullptr);
    ~ExportWorker() = default;

    // Start the worker (must be called from worker thread)
    void start();

public slots:
    void processTask(const ExportTask& task);
    void stop();

signals:
    void taskCompleted(int frame_index, const QString& eye_name, bool success);
    void allTasksCompleted();

private:
    QMutex mutex_;
    QQueue<ExportTask> task_queue_;
    QWaitCondition condition_;
    bool should_stop_{false};
    
    void processTaskInternal(const ExportTask& task);
};

