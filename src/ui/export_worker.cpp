#include "export_worker.h"

#include <QDebug>
#include <QMutexLocker>
#include <iostream>
#include <filesystem>

#include "export/exr_writer.h"
#include "export/image_writer.h"

ExportWorker::ExportWorker(QObject* parent)
    : QObject(parent) {
}

void ExportWorker::start() {
    // Worker thread entry point
    // Tasks will be processed via processTask slot
}

void ExportWorker::processTask(const ExportTask& task) {
    processTaskInternal(task);
}

void ExportWorker::processTaskInternal(const ExportTask& task) {
    bool success = false;
    
    try {
        // Ensure output directory exists
        const auto parent_dir = task.output_path.parent_path();
        if (!parent_dir.empty() && !std::filesystem::exists(parent_dir)) {
            std::filesystem::create_directories(parent_dir);
        }
        
        // Write the frame buffer to file
        if (task.is_exr) {
            success = braw::write_exr_half_dwaa(task.output_path, task.buffer, 45.0f);
        } else {
            success = braw::write_ppm(task.output_path, task.buffer);
        }
        
        if (success) {
            // Verify file was created
            if (!std::filesystem::exists(task.output_path)) {
                qDebug() << "파일이 생성되지 않았습니다:" << QString::fromStdWString(task.output_path.wstring());
                success = false;
            }
        }
        
        if (!success) {
            qDebug() << "파일 저장 실패:" << QString::fromStdWString(task.output_path.wstring());
        }
    } catch (const std::exception& e) {
        qDebug() << "예외 발생:" << e.what();
        success = false;
    } catch (...) {
        qDebug() << "알 수 없는 예외 발생";
        success = false;
    }
    
    emit taskCompleted(task.frame_index, task.eye_name, success);
}

void ExportWorker::stop() {
    QMutexLocker locker(&mutex_);
    should_stop_ = true;
    condition_.wakeAll();
}

