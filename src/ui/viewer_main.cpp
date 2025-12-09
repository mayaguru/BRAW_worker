#include <QApplication>
#include <QPalette>
#include <QStyleFactory>

#ifdef _WIN32
#include <Windows.h>
#include <combaseapi.h>
#endif

#include "viewer_window.h"

void applyDarkTheme(QApplication& app) {
    app.setStyle(QStyleFactory::create("Fusion"));

    QPalette darkPalette;
    darkPalette.setColor(QPalette::Window, QColor(45, 45, 45));
    darkPalette.setColor(QPalette::WindowText, QColor(208, 208, 208));
    darkPalette.setColor(QPalette::Base, QColor(30, 30, 30));
    darkPalette.setColor(QPalette::AlternateBase, QColor(45, 45, 45));
    darkPalette.setColor(QPalette::ToolTipBase, QColor(208, 208, 208));
    darkPalette.setColor(QPalette::ToolTipText, QColor(208, 208, 208));
    darkPalette.setColor(QPalette::Text, QColor(208, 208, 208));
    darkPalette.setColor(QPalette::Button, QColor(45, 45, 45));
    darkPalette.setColor(QPalette::ButtonText, QColor(208, 208, 208));
    darkPalette.setColor(QPalette::BrightText, Qt::red);
    darkPalette.setColor(QPalette::Link, QColor(42, 130, 218));
    darkPalette.setColor(QPalette::Highlight, QColor(42, 130, 218));
    darkPalette.setColor(QPalette::HighlightedText, Qt::black);

    // Disabled colors
    darkPalette.setColor(QPalette::Disabled, QPalette::WindowText, QColor(127, 127, 127));
    darkPalette.setColor(QPalette::Disabled, QPalette::Text, QColor(127, 127, 127));
    darkPalette.setColor(QPalette::Disabled, QPalette::ButtonText, QColor(127, 127, 127));
    darkPalette.setColor(QPalette::Disabled, QPalette::Highlight, QColor(80, 80, 80));
    darkPalette.setColor(QPalette::Disabled, QPalette::HighlightedText, QColor(127, 127, 127));

    app.setPalette(darkPalette);

    // Additional stylesheet for fine-tuning
    app.setStyleSheet(R"(
        QToolTip {
            color: #d0d0d0;
            background-color: #2d2d2d;
            border: 1px solid #3d3d3d;
        }
        QGroupBox {
            border: 1px solid #3d3d3d;
            border-radius: 4px;
            margin-top: 8px;
            padding-top: 8px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 3px 0 3px;
        }
        QPushButton {
            background-color: #3d3d3d;
            border: 1px solid #505050;
            border-radius: 4px;
            padding: 5px 15px;
            min-width: 60px;
        }
        QPushButton:hover {
            background-color: #505050;
            border: 1px solid #606060;
        }
        QPushButton:pressed {
            background-color: #2a82da;
        }
        QPushButton:disabled {
            background-color: #2d2d2d;
            color: #606060;
        }
        QPushButton:checked {
            background-color: #2a82da;
            border: 1px solid #3a92ea;
        }
        QSlider::groove:horizontal {
            background: #3d3d3d;
            height: 6px;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #2a82da;
            width: 14px;
            margin: -4px 0;
            border-radius: 7px;
        }
        QProgressBar {
            border: 1px solid #3d3d3d;
            border-radius: 4px;
            text-align: center;
            background-color: #2d2d2d;
        }
        QProgressBar::chunk {
            background-color: #2a82da;
            border-radius: 3px;
        }
        QSpinBox, QComboBox, QLineEdit {
            background-color: #2d2d2d;
            border: 1px solid #3d3d3d;
            border-radius: 4px;
            padding: 3px;
        }
        QSpinBox:focus, QComboBox:focus, QLineEdit:focus {
            border: 1px solid #2a82da;
        }
        QComboBox::drop-down {
            border: none;
            width: 20px;
        }
        QComboBox::down-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 6px solid #d0d0d0;
            margin-right: 5px;
        }
        QScrollBar:vertical {
            background: #2d2d2d;
            width: 12px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #505050;
            min-height: 20px;
            border-radius: 6px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0;
        }
    )");
}

int main(int argc, char* argv[]) {
    // Qt가 COM을 초기화하도록 놔둠
    // BrawDecoder는 이미 초기화된 COM을 감지하고 RPC_E_CHANGED_MODE 무시함
    QApplication app(argc, argv);

    applyDarkTheme(app);

    MainWindow window;
    window.show();

    int result = app.exec();

#ifdef _WIN32
    CoUninitialize();
#endif

    return result;
}
