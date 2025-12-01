#include <QApplication>

#ifdef _WIN32
#include <Windows.h>
#include <combaseapi.h>
#endif

#include "main_window.h"

int main(int argc, char* argv[]) {
#ifdef _WIN32
    // Qt가 COM을 초기화하기 전에 먼저 초기화 시도
    // Qt는 COINIT_APARTMENTTHREADED를 사용하므로 이에 맞춤
    HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(hr)) {
        // 이미 초기화되어 있으면 무시 (Qt가 먼저 초기화했을 수 있음)
        if (hr != RPC_E_CHANGED_MODE && hr != S_FALSE) {
            return 1;
        }
    }
#endif

    QApplication app(argc, argv);

    MainWindow window;
    window.show();

    int result = app.exec();

#ifdef _WIN32
    CoUninitialize();
#endif

    return result;
}
