#pragma once

#include <filesystem>

#include "core/frame_buffer.h"

namespace braw {

// Writes OpenEXR half-float image with DWAA compression (quality parameter).
// Returns false if OpenEXR support is unavailable or the write fails.
bool write_exr_half_dwaa(const std::filesystem::path& output_path,
                         const FrameBuffer& buffer,
                         float dwa_compression = 45.0f);

}  // namespace braw
