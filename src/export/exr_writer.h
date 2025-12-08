#pragma once

#include <filesystem>

#include "core/frame_buffer.h"

namespace braw {

// Writes OpenEXR half-float image with DWAA compression (quality parameter).
// Returns false if OpenEXR support is unavailable or the write fails.
// If input_colorspace is not empty, applies OCIO color space transformation.
// If apply_gamma is true, applies Rec.709 gamma curve (viewport gamma).
bool write_exr_half_dwaa(const std::filesystem::path& output_path,
                         const FrameBuffer& buffer,
                         float dwa_compression = 45.0f,
                         const std::string& input_colorspace = "",
                         const std::string& output_colorspace = "",
                         bool apply_gamma = false);

}  // namespace braw
