#include <QApplication>

#ifdef _WIN32
#include <Windows.h>
#include <combaseapi.h>
#endif

#include "viewer_window.h"

int main(int argc, char* argv[]) {
    // Qt가 COM을 초기화하도록 놔둠
    // BrawDecoder는 이미 초기화된 COM을 감지하고 RPC_E_CHANGED_MODE 무시함
    QApplication app(argc, argv);

    MainWindow window;
    window.show();

    int result = app.exec();

#ifdef _WIN32
    CoUninitialize();
#endif

    return result;
}
